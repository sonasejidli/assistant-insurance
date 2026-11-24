import logging
import re
import unicodedata
from functools import lru_cache
from itertools import zip_longest
from math import log1p
from pathlib import Path
from typing import TypedDict

import numpy as np
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from App.azerbaijani import LEMMATIZER, RETRIEVAL_EQUIVALENTS, surface_tokens
from App.document_processing import load_documents
from App.embedding import embed, embedding_configuration, plan_passages
from App.legal_documents import applies_on, contextual_header, link_references
from App.settings import CONTEXTUAL_HEADERS, LEGAL_MULTIPART_COVERAGE, LEGAL_PROVISION_RETRIEVAL, STAGED_LEGAL_SOURCES
from App.insurance_terminology import TERMINOLOGY
from App.observability import event, retrieval_trace, stage_timing, startup_stage, tracing_config
from App.evaluation_capture import current, passage_id
from App.query_resolution import QueryResolution
from App.rerank import bge_scores
from App.settings import (
    BM25_B, BM25_K1, INDEX_CHUNK_CHARS, RERANK_BATCH_SIZE, RERANK_DEVICE, RERANK_MAX_TOKENS,
    RERANK_MODE, RERANK_MODEL, TOP_K, RetrievalSettings,
)
from App.vector_store import QdrantIndex

TEXT_DIR = Path("data/index")
MAX_CHARS = INDEX_CHUNK_CHARS
NUMBER = r"\d+(?:-\d+)?(?:\.\d+(?:-\d+)?)*"
ARTICLE_QUERY = re.compile(rf"\b(?:articles?|maddə|стать\w*)\s+({NUMBER})\b|\b({NUMBER})(?:-c[ıiuü])?\s+maddə\w*", re.IGNORECASE)
ARTICLE_LIST = re.compile(rf"\b(?:articles?|maddə(?:lər)?|стать\w*)\s+({NUMBER}(?:\s*(?:,|and\b|və\b|и\b|&)\s*{NUMBER})+)", re.IGNORECASE)
ARTICLE_NUMBER = re.compile(rf"^{NUMBER}$")
EXACT_VALUE = re.compile(
    r"(?<!\w)(?<!\d[.,])(?:"
    r"(?P<law>\d+[ \t]*[-–][ \t]*[ivxlcdm]+q\w*)"
    r"|(?P<clause>\d+(?:-\d+)?(?:\.\d+(?:-\d+)?){2,}|\d+-\d+\.\d+(?:-\d+)?)"
    r"|(?P<number>(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?)"
    r"(?P<unit>[ \t]*(?:%|₼|faiz\w*\b|manat\w*\b|(?:azn|usd|eur|dollar|avro)\b))?"
    r")(?!\w|[.,]\d)",
    re.IGNORECASE,
)
TOPIC_TERMS = {
    "tariff": ("tarif", "sığorta haqq", "premium", "tariff"),
    "exclusion": ("istisna", "exclusion", "excluded"),
    "deadline": ("müddət", "vaxt", "gün ərzində", "deadline", "time limit"),
}
log = logging.getLogger(__name__)


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace("\u0307", "")


def tokenize(text: str) -> list[str]:
    return surface_tokens(text)


def concept_token(key: str) -> str:
    return f"insurance_concept_{key}"


def exact_value_tokens(text: str, metadata: dict | None = None) -> tuple[str, list[str]]:
    tokens = []

    def add_value(match: re.Match) -> str:
        if law := match["law"]:
            tokens.append("law:" + re.sub(r"\s+", "", law).replace("–", "-").lower())
        elif clause := match["clause"]:
            tokens.append(f"article:{clause}")
        else:
            value = re.sub(r"\s+", "", match["number"]).replace(",", ".")
            whole, _, fraction = value.partition(".")
            value = (whole.lstrip("0") or "0") + ("." + fraction.rstrip("0") if fraction.rstrip("0") else "")
            unit = (match["unit"] or "").strip().lower()
            tokens.append(f"number:{value}")
            if unit:
                if unit == "%" or unit.startswith("faiz"):
                    unit = "percent"
                elif unit in {"azn", "₼"} or unit.startswith("manat"):
                    unit = "azn"
                else:
                    unit = {"dollar": "usd", "avro": "eur"}.get(unit, unit)
                tokens.append(f"{unit}:{value}")
        # Keep the currency/percentage word available for ordinary lexical matching.
        return " " + (match["unit"] or "") + " "

    surface = EXACT_VALUE.sub(add_value, unicodedata.normalize("NFKC", text))
    for number in article_numbers(text):
        tokens.append(f"article:{number}")
    if metadata:
        for field in ("article", "clause"):
            if number := metadata.get(field):
                tokens.append(f"article:{number}")
        if law_number := metadata.get("law_number"):
            tokens.append("law:" + re.sub(r"\s+", "", law_number).replace("–", "-").lower())
    return surface, list(dict.fromkeys(tokens))


def lexical_tokens(text: str, concepts: set[str] | None = None, *, metadata: dict | None = None) -> list[str]:
    surface, exact_tokens = exact_value_tokens(text, metadata)
    tokens = tokenize(surface)
    variants = []
    for token in tokens:
        lemma = LEMMATIZER.lemmatize(token)
        aliases = (lemma, RETRIEVAL_EQUIVALENTS.get(lemma, lemma))
        variants.extend(alias for alias in dict.fromkeys(aliases) if alias != token)
    if concepts is None:
        concepts = TERMINOLOGY.direct_concepts(text)
    return [*tokens, *variants, *exact_tokens, *(concept_token(key) for key in sorted(concepts))]


def lexical_query(question: str) -> tuple[list[str], list[str]]:
    concepts, groups = TERMINOLOGY.expand(question)
    alternatives = list(dict.fromkeys(key for group in groups for key in group))
    return list(dict.fromkeys(lexical_tokens(question, concepts.union(alternatives)))), alternatives


class RetrievalBM25(BM25Okapi):
    @classmethod
    def from_chunks(cls, chunks: list[dict], *, k1: float = BM25_K1, b: float = BM25_B):
        return cls([lexical_tokens(searchable_text(chunk), metadata=chunk.get("metadata")) or [""]
                    for chunk in chunks], k1=k1, b=b)

    def _calc_idf(self, nd):
        # Positive BM25 IDF keeps common terms searchable even in small corpora.
        self.idf = {
            term: log1p((self.corpus_size - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in nd.items()
        }


def searchable_text(chunk: dict) -> str:
    title = (chunk.get("metadata") or {}).get("article_title") or ""
    return f"{title}\n{chunk['text']}" if title and title not in chunk["text"] else chunk["text"]


def embedding_passage_text(chunk: dict, *, contextual: bool = False) -> str:
    return ("\n".join(filter(None, (contextual_header(chunk), chunk["text"]))) if contextual else searchable_text(chunk))


def provision_candidates(question, chunks, eligible):
    """Recognize directly stated provisions for narrowly named legal requests."""
    query = normalize(question).strip(" ?.!;")
    definition = re.fullmatch(r"(?:azərbaycan respublikasının )?mülki məcəllədə (.{5,90}?) nədir", query)
    motor_base = (re.search(r"\b(?:avtomobil|avtonəqliyyat)\w*\b", query)
                  and re.search(r"\bicbari\b", query) and re.search(r"\bbaza (?:sığorta )?haqq\w*\b", query))
    auditor_nonpayment = (re.search(r"\bauditor\w*\b", query) and re.search(r"\bimtina\w*\b", query)
                          and re.search(r"\bhaqq\w*\s+(?:ödənilmə|ödəmə)", query))
    if not (definition or motor_base or auditor_nonpayment):
        return []
    selected = []
    for index in eligible:
        chunk = chunks[index]
        info = chunk.get("metadata") or {}
        name = normalize(info.get("law_name") or "")
        if not info.get("clause"):
            continue
        text = re.sub(r"^\d+(?:[.\-–]\d+)+[.)]?\s+", "", normalize(chunk["text"]))
        if definition:
            matches = ("mülki məcəllə" in name and text.startswith(definition[1] + " ")
                       and re.search(r"\b(?:razılaşmadır|müqavilədir|başa düşülür|hesab edilir)\b", text))
        elif motor_base:
            matches = (info.get("legal_document_type") == "regulation" and "icbari sığorta haqqı" in name
                       and re.match(r"baza sığorta haqqı\s+\d+(?:[.,]\d+)?\s+manat\b", text))
        else:
            matches = ("auditor" in name and "peşə məsuliyyəti" in name
                       and re.match(r"sığortalı\s+sığorta haqqını\s+ödəmədikdə\b", text))
        if matches:
            selected.append(index)
    return selected if len(selected) == 1 else []


def scoped_obligations(question, chunks, eligible):
    """Locate independently stated rules by requested legal scope and operative text."""
    query = normalize(question)
    occupational = bool(re.search(r"\b(?:iş qəza|istehsalat)", query))
    compulsory = "icbari sığorta" in query and not occupational and "tibbi" not in query
    slots = ()
    if occupational and re.search(r"\b(?:işəgötürən|sığortalı)\w*", query) and re.search(r"(?:məlumat|xəbər) ver", query):
        slots = (r"hadisəsinin baş verməsi tarixindən.*?iş günü ərzində sığortaçıya.*?məlumat vermək",)
    elif occupational and re.search(r"gecik\w*.*müraciət|müraciət.*gecik", query):
        slots = (r"sığorta tələbini.*?hüququ yarandıqdan sonra.*?gec təqdim.*?əvvəlki.*?il",)
    elif occupational and "sığorta haqqı" in query and re.search(r"hesabla\w*", query):
        slots = (r"peşə riskinin.*?sığorta tarifləri.*?faizdən artıq olmamaq", r"əmək\s*haqqı fondunun sığorta tarifinə hasili")
    elif compulsory and re.search(r"gecik\w*.*müraciət|iddia müddəti", query):
        slots = (r"iddia müddəti.*?bildiyi və ya bilməli olduğu tarixdən.*?il müddətində",)
    elif compulsory and re.search(r"son(?:uncu)? sənəd\w*|sənədlərdən sonuncu", query) and re.search(r"müddət|nə vaxt|nə qədər", query):
        slots = (r"sənədlərdən sonuncusunun.*?iş günündən gec olmayaraq.*?ödəniş",)
    if not slots:
        return None
    scoped = []
    for i in eligible:
        meta = chunks[i].get("metadata") or {}
        if occupational and meta.get("insurance_type") == "occupational" or (
            compulsory and normalize(meta.get("law_name") or "") == "icbari sığortalar haqqında"
        ):
            scoped.append(i)
    matches = [[i for i in scoped if re.search(pattern, normalize(chunks[i]["text"]))] for pattern in slots]
    if any(len(group) != 1 for group in matches):
        return []
    selected = [group[0] for group in matches]
    return selected if len({chunks[i]["doc"] for i in selected}) == 1 else []


def expand_query(question: str) -> str:
    query = normalize(question)
    concepts, alternatives = TERMINOLOGY.expand(question)
    concepts.update(key for group in alternatives for key in group)
    additions = [term for key in sorted(concepts) for term in TERMINOLOGY.aliases[key] if normalize(term) not in query]
    return " ".join([question, *additions])


def article_number(question: str) -> str | None:
    numbers = article_numbers(question)
    return numbers[0] if numbers else None


def article_numbers(question: str) -> list[str]:
    stripped = unicodedata.normalize("NFKC", question).strip()
    if ARTICLE_NUMBER.fullmatch(stripped):
        return [stripped]
    matches = [(match.start(), match[1] or match[2]) for match in ARTICLE_QUERY.finditer(stripped)]
    for group in ARTICLE_LIST.finditer(stripped):
        matches.extend((group.start(1) + match.start(), match.group()) for match in re.finditer(NUMBER, group[1]))
    return list(dict.fromkeys(number for _, number in sorted(matches)))


def matches_filters(chunk: dict, filters: dict | None) -> bool:
    if not filters:
        return True
    metadata = chunk.get("metadata") or {}
    if filters.get("as_of") and not applies_on(metadata, filters["as_of"]):
        return False
    insurance_type = filters.get("insurance_type")
    if insurance_type and normalize(insurance_type.strip()) != normalize(metadata.get("insurance_type") or ""):
        return False
    law = filters.get("law")
    if law:
        law = normalize(law.strip())
        fields = (metadata.get("law_name") or "", metadata.get("law_number") or "", chunk["doc"])
        if not any(law in normalize(field) for field in fields):
            return False
    topic = filters.get("topic")
    if topic:
        text = normalize(" ".join((metadata.get("article_title") or "", chunk["text"])))
        if metadata.get("category") != topic and not any(normalize(term) in text for term in TOPIC_TERMS[topic]):
            return False
    return True


def load_chunks(directory: Path = TEXT_DIR) -> list[dict]:
    documents = load_documents(directory, MAX_CHARS)
    if STAGED_LEGAL_SOURCES and directory == TEXT_DIR:
        staged = load_documents(directory.parent / "staged_legal", MAX_CHARS, staged=True)
        if {document["doc"] for document in documents} & {document["doc"] for document in staged}:
            raise ValueError("Staged source names must be distinct from base sources")
        documents.extend(staged)
        link_references(documents)
    chunks = DocumentChunks(chunk for document in documents for chunk in document["chunks"])
    chunks.documents = documents
    if not chunks:
        raise RuntimeError(f"No readable documents found in {directory}")
    log.info("Loaded %d passages from %d indexed documents", len(chunks), len(documents))
    return chunks


class DocumentChunks(list):
    documents: list[dict]


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    return CrossEncoder(RERANK_MODEL, device=RERANK_DEVICE) if RERANK_DEVICE else CrossEncoder(RERANK_MODEL)


def reranker_passage(document: Document, content: str | None = None) -> str:
    content = document.page_content if content is None else content
    metadata = document.metadata
    chapter = metadata.get("chapter") or {}
    insurance_type = metadata.get("insurance_type")
    insurance_label = {
        "medical": "tibbi sığorta", "social": "sosial sığorta",
        "agricultural": "aqrar sığorta", "occupational": "istehsalat sığortası",
        "compulsory": "icbari sığorta",
    }.get(insurance_type, insurance_type)
    section = metadata.get("section_title") or metadata.get("article_title")
    fields = [
        ("Sığorta növü", insurance_label),
        ("Hüquqi sənəd", metadata.get("law_name")),
        ("Sənədin nömrəsi", metadata.get("law_number")),
        ("Fəsil", chapter.get("title")),
        ("Bölmə", section if section and section not in content else None),
        ("Maddə", metadata.get("article_number") or metadata.get("article")),
        ("Bənd", metadata.get("clause")),
    ]
    context = [f"{label}: {value}" for label, value in fields if value]
    return "\n".join([*context, content])


def cross_encoder_scores(question: str, documents: list[Document], *, mode: str | None = None) -> np.ndarray:
    if (mode or RERANK_MODE) == "bge_safe":
        return bge_scores(get_reranker(), question, documents, reranker_passage,
                          max_tokens=RERANK_MAX_TOKENS, batch_size=RERANK_BATCH_SIZE)
    return np.asarray(get_reranker().predict([(question, reranker_passage(doc)) for doc in documents]))


def rank_with_cross_encoder(question: str, documents: list[Document]) -> list[Document]:
    if len(documents) < 2:
        return documents
    scores = cross_encoder_scores(question, documents)
    if scores.shape != (len(documents),) or not np.isfinite(scores).all():
        raise ValueError("Invalid reranker scores")
    for score, document in zip(scores, documents, strict=True):
        document.metadata["reranker_score"] = float(score)
    return [document for _, document in sorted(zip(scores, documents), key=lambda item: float(item[0]), reverse=True)]


def rerank_documents(question: str, documents: list[Document]) -> list[Document]:
    try:
        return rank_with_cross_encoder(question, documents)
    except Exception as exc:
        event("reranker_error", error_type=type(exc).__name__)
        log.warning("Reranker unavailable; using hybrid ranking (%s)", type(exc).__name__)
        return documents


class SearchState(TypedDict, total=False):
    question: str
    original_question: str
    dense_query: str
    dense_input_kind: str
    bm25_query: str
    rerank_query: str
    query_tokens: list[str]
    alternative_concepts: list[str]
    interpretation_hits: list[list[int]]
    eligible: list[int]
    lexical_rank: list[int]
    vector_rank: list[int]
    filters: dict
    article: str | None
    articles: list[str]
    k: int
    candidates: list[Document]
    hits: list[dict]
    score: float
    match_type: str
    vector_scores: dict[int, float]
    lexical_scores: dict[int, float]
    direct_provisions: list[int]
    query_vector: list[float]


class TextRetriever:
    def __init__(self, settings: RetrievalSettings | None = None):
        with startup_stage("retrieval_configuration"):
            self.settings = settings if settings is not None else RetrievalSettings.from_env()
        with startup_stage("corpus_discovery_parsing_and_chunking"):
            self.chunks = load_chunks()
        self.documents = getattr(self.chunks, "documents", [])
        with startup_stage("embedding_model"):
            configuration = embedding_configuration()
        with startup_stage("embedding_input_preparation", chunks=len(self.chunks)):
            texts = [embedding_passage_text(chunk, contextual=CONTEXTUAL_HEADERS) for chunk in self.chunks]
            passages = (plan_passages(self.chunks, texts, contextual=True) if CONTEXTUAL_HEADERS
                        else plan_passages(self.chunks, texts))
        self.vector_index = QdrantIndex(self.chunks, texts, embed, configuration=configuration, passages=passages)
        with startup_stage("bm25_and_graph"):
            self.bm25 = RetrievalBM25.from_chunks(self.chunks)
            self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(SearchState)
        stages = {
            "preprocess": self._preprocess,
            "exact_lookup": self._exact_lookup,
            "bm25": self._bm25,
            "vector_search": self._vector_search,
            "rrf": self._fuse,
            "rerank": self._rerank,
            "select_context": self._select_context,
        }
        for name, node in stages.items():
            graph.add_node(name, RunnableLambda(node))
        graph.add_edge(START, "preprocess")
        graph.add_conditional_edges(
            "preprocess",
            lambda state: ["exact_lookup"] if state["articles"] else ["bm25", "vector_search"],
            ["exact_lookup", "bm25", "vector_search"],
        )
        graph.add_edge("exact_lookup", END)
        graph.add_edge(["bm25", "vector_search"], "rrf")
        graph.add_edge("rrf", "rerank")
        graph.add_edge("rerank", "select_context")
        graph.add_edge("select_context", END)
        return graph.compile()

    def close(self):
        self.vector_index.close()

    def lookup_article(self, number: str, filters: dict | None = None) -> list[dict]:
        if not ARTICLE_NUMBER.fullmatch(number):
            raise ValueError("Invalid article number")
        return [chunk for chunk in self.chunks if matches_filters(chunk, filters) and
                (chunk.get("metadata") or {}).get("clause" if "." in number else "article") == number]

    def _record_ranks(self, stage, order, scores):
        if (capture := current.get()) is not None and capture["branches"]:
            capture["branches"][-1][stage] = [
                {"passage_id": passage_id(self.chunks[index]), "rank": rank, "score": scores.get(index)}
                for rank, index in enumerate(order, 1)
            ]

    @stage_timing("retrieval_preprocess", capture_only=True)
    def _preprocess(self, state: SearchState) -> dict:
        articles = [state["article"]] if state.get("article") else article_numbers(state.get("original_question", state["question"]))
        if articles:
            return {"articles": articles}
        filters = state.get("filters") or {}
        eligible = [index for index, chunk in enumerate(self.chunks) if matches_filters(chunk, filters)]
        tokens, alternatives = lexical_query(state.get("bm25_query", state["question"]))
        if (capture := current.get()) is not None and capture["branches"]:
            capture["branches"][-1]["bm25_tokens"] = tokens
        return {"articles": [], "eligible": eligible,
                "query_tokens": tokens,
                "alternative_concepts": alternatives}

    @stage_timing("exact_lookup", capture_only=True)
    def _exact_lookup(self, state: SearchState) -> dict:
        groups = [self.lookup_article(number, state.get("filters")) for number in state["articles"]]
        hits = []
        if all(groups):
            for group in zip_longest(*groups):
                for hit in group:
                    if hit is not None and not any(existing is hit for existing in hits):
                        hits.append(hit)
        return {"hits": hits[:state["k"]], "score": 1.0 if hits else 0.0, "match_type": "article"}

    @stage_timing("bm25")
    def _bm25(self, state: SearchState) -> dict:
        if not state["eligible"] or not state["query_tokens"]:
            self._record_ranks("bm25", (), {})
            return {"lexical_rank": [], "interpretation_hits": []}
        scores = self.bm25.get_scores(state["query_tokens"])
        order = sorted((index for index in state["eligible"] if scores[index] > 0),
                       key=lambda index: -scores[index])[:self.settings.bm25_top_k]
        interpretation_hits = []
        for key in state.get("alternative_concepts", []):
            token = concept_token(key)
            matches = [index for index in order if token in self.bm25.doc_freqs[index]]
            if matches:
                interpretation_hits.append(matches[:state["k"]])
        scores = {index: float(scores[index]) for index in order}
        self._record_ranks("bm25", order, scores)
        return {"lexical_rank": order, "interpretation_hits": interpretation_hits, "lexical_scores": scores}

    @stage_timing("dense")
    def _vector_search(self, state: SearchState) -> dict:
        eligible = state["eligible"]
        if not eligible:
            self._record_ranks("dense", (), {})
            return {"vector_rank": [], "vector_scores": {}}
        query = embed([state.get("dense_query", state["question"])], kind=state.get("dense_input_kind", "query"))[0].tolist()
        ranked = self.vector_index.search(query, eligible, self.settings.vector_top_k,
                                          score_threshold=self.settings.similarity_threshold)
        self._record_ranks("dense", (index for index, _ in ranked), dict(ranked))
        return {"query_vector": query, "vector_rank": [index for index, _ in ranked],
                "vector_scores": dict(ranked)}

    def _chunk_key(self, index: int) -> tuple[str, str | int]:
        chunk = self.chunks[index]
        metadata = chunk.get("metadata") or {}
        return metadata.get("document_id") or chunk["doc"], metadata.get("chunk_id") or index

    @stage_timing("rrf")
    def _fuse(self, state: SearchState) -> dict:
        scores = {}
        representatives = {}
        for order, weight in ((state["lexical_rank"], self.settings.bm25_weight),
                              (state["vector_rank"], self.settings.vector_weight)):
            if not weight:
                continue
            seen = set()
            for rank, index in enumerate(order, start=1):
                key = self._chunk_key(index)
                if key in seen:
                    continue
                seen.add(key)
                representatives.setdefault(key, index)
                scores[key] = scores.get(key, 0.0) + weight / (self.settings.rrf_k + rank)
        candidates = []
        direct = (provision_candidates(state["question"], self.chunks, state["eligible"])
                  if getattr(self, "provision_retrieval", LEGAL_PROVISION_RETRIEVAL or LEGAL_MULTIPART_COVERAGE) else [])
        if getattr(self, "multipart_coverage", LEGAL_MULTIPART_COVERAGE):
            direct = list(dict.fromkeys([*direct, *(scoped_obligations(state["question"], self.chunks, state["eligible"]) or [])]))
        preferred = [self._chunk_key(index) for index in direct]
        for key, index in zip(preferred, direct, strict=True):
            representatives.setdefault(key, index)
        order = list(dict.fromkeys([*preferred, *sorted(scores, key=scores.__getitem__, reverse=True)]))
        for key in order:
            index = representatives[key]
            chunk = self.chunks[index]
            metadata = {
                **(chunk.get("metadata") or {}),
                **{field: chunk[field] for field in ("note_ids", "references") if field in chunk},
                "doc": chunk["doc"], "index": index, "rrf_score": scores.get(key),
            }
            candidates.append(Document(page_content=searchable_text(chunk), metadata=metadata))
        if current.get() is not None:
            self._record_ranks("fusion", [representatives[key] for key in order],
                               {representatives[key]: scores.get(key) for key in order})
        return {"candidates": candidates, "match_type": "hybrid", "direct_provisions": direct}

    @stage_timing("reranker")
    def _rerank(self, state: SearchState) -> dict:
        candidates = state["candidates"]
        depth = max(self.settings.rerank_top_k, state.get("k", TOP_K))
        # RRF can place a strong single-branch hit below candidates that appear in both branches.
        reserve = min(4, depth // 4)
        leading = set()
        if self.settings.bm25_weight:
            leading.update(self._chunk_key(index) for index in state["lexical_rank"][:reserve])
        if self.settings.vector_weight:
            leading.update(self._chunk_key(index) for index in state["vector_rank"][:reserve])
        keyed = [(self._chunk_key(doc.metadata["index"]), doc) for doc in candidates]
        shortlist = {key for key, _ in keyed if key in leading}
        for key, _ in keyed:
            if len(shortlist) >= depth:
                break
            shortlist.add(key)
        selected, tail = [], []
        for key, doc in keyed:
            (selected if key in shortlist else tail).append(doc)
        ranked = rerank_documents(state.get("rerank_query", state["question"]), selected)
        final = candidates if ranked is selected else [*ranked, *tail]
        if current.get() is not None:
            self._record_ranks("reranked", [doc.metadata["index"] for doc in final],
                               {doc.metadata["index"]: doc.metadata.get("reranker_score") for doc in final})
        return {"candidates": final}

    @stage_timing("retrieval_selection", capture_only=True)
    def _select_context(self, state: SearchState) -> dict:
        order = [document.metadata["index"] for document in state["candidates"]]
        positions = {index: rank for rank, index in enumerate(order)}
        representatives = {self._chunk_key(index): index for index in order}
        reserved = set()
        if state["k"] > 1 and self.settings.bm25_weight:
            for matches in state["interpretation_hits"]:
                present = [representatives[key] for index in matches if (key := self._chunk_key(index)) in representatives]
                if present:
                    reserved.add(min(present, key=positions.__getitem__))
        chosen = sorted(reserved, key=positions.__getitem__)[:state["k"]]
        chosen.extend(index for index in order if index not in reserved)
        direct = [representatives[self._chunk_key(i)] for i in state.get("direct_provisions", [])
                  if self._chunk_key(i) in representatives]
        if direct:
            indexes = list(dict.fromkeys([*direct, *chosen]))[:state["k"]]
        else:
            indexes = sorted(chosen[:state["k"]], key=positions.__getitem__)
        scores = {self._chunk_key(index): score for index, score in state["vector_scores"].items()}
        missing = [index for index in indexes if self._chunk_key(index) not in scores]
        if missing and "query_vector" in state:
            scores.update((self._chunk_key(index), score) for index, score in self.vector_index.search(
                state["query_vector"], missing, len(missing), exact=True, score_threshold=self.settings.similarity_threshold,
            ))
        return {"hits": [self.chunks[index] for index in indexes],
                "score": max((scores[key] for key in map(self._chunk_key, indexes) if key in scores), default=0.0)}

    @stage_timing("retrieval")
    def search(self, question: str | QueryResolution, k: int = TOP_K, filters: dict | None = None,
               article: str | None = None, *, original_question: str | None = None) -> tuple[list[dict], float]:
        query = question if isinstance(question, QueryResolution) else QueryResolution(original_question or question, question)
        if query.standalone is None:
            raise ValueError("A standalone search query is required")
        branch = None
        if (capture := current.get()) is not None:
            branch = {"query": query.standalone, "normalized_query": query.normalized,
                      "bm25_query": query.bm25_query, "dense_query": query.dense_query, "rerank_query": query.rerank_query,
                      "filters": filters or {}, "limit": k, "dense_input_kind": "passage" if query.dense_hypothesis else "query",
                      "status": "started"}
            capture["branches"].append(branch)
        try:
            result = self.graph.invoke({"question": query.standalone, "original_question": query.original,
                                        "dense_query": query.dense_query, "bm25_query": query.bm25_query,
                                        "rerank_query": query.rerank_query,
                                        "dense_input_kind": "passage" if query.dense_hypothesis else "query",
                                        "k": k, "filters": filters or {}, "article": article},
                                       config=tracing_config())
        except Exception as exc:
            if branch is not None:
                branch.update(status="failed", error_type=type(exc).__name__)
            raise
        if branch is not None:
            branch.update(status="returned", match_type=result.get("match_type"),
                          selected=[passage_id(hit) for hit in result["hits"]])
        event("retrieval_results", bm25=[(i, result.get("lexical_scores", {}).get(i)) for i in result.get("lexical_rank", [])[:50]],
              dense=list(result.get("vector_scores", {}).items())[:50],
              ranked=[(doc.metadata["index"], doc.metadata.get("rrf_score"), doc.metadata.get("reranker_score"))
                      for doc in result.get("candidates", [])[:50]],
              parents=[(hit.get("metadata") or {}).get("chunk_id") for hit in result["hits"]])
        if (trace := retrieval_trace.get()) is not None:
            stages = {name: {index: rank for rank, index in enumerate(result.get(field, []), 1)}
                      for name, field in (("bm25", "lexical_rank"), ("dense", "vector_rank"))}
            by_index = {doc.metadata["index"]: (position, doc.metadata)
                        for position, doc in enumerate(result.get("candidates", []), 1)}
            hits_by_id = {id(chunk): index for index, chunk in enumerate(self.chunks)}
            for rank, hit in enumerate(result["hits"], 1):
                index = hits_by_id[id(hit)]
                position, scores = by_index.get(index, (None, {}))
                trace.setdefault(self._chunk_key(index), []).append({
                    "query": query.standalone, "rank": rank, "match_type": result.get("match_type"),
                    "bm25_rank": stages["bm25"].get(index), "dense_parent_rank": stages["dense"].get(index),
                    "candidate_rank_after_rerank": position,
                    "bm25_score": result.get("lexical_scores", {}).get(index),
                    "dense_score": result.get("vector_scores", {}).get(index),
                    "rrf_score": scores.get("rrf_score"), "reranker_score": scores.get("reranker_score"),
                })
        return result["hits"], result["score"]
