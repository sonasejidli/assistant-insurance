import hashlib
import json
import logging
import re
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

import numpy as np
from huggingface_hub import hf_hub_download
from sentence_transformers import SentenceTransformer
from App.legal_documents import contextual_header
from App.settings import EMBED_MODEL, EMBED_MODEL_REVISION, EMBED_OVERLAP_TOKENS, EMBED_TARGET_TOKENS, INDEX_CHUNK_CHARS

_model: SentenceTransformer | None = None
_model_revision: str | None = None
NORMALIZE_EMBEDDINGS = True
ENCODE_PRECISION = "float32"
CHUNKING_VERSION = 1
log = logging.getLogger(__name__)
LEGAL_BOUNDARY = re.compile(r"(?:(?<!\d)\.|[!?;])\s+|\s+(?=\d+(?:[.-]\d+)+[.)]\s)")
LEGAL_SIGNALS = {
    "exception": r"istisna|tətbiq (?:edilmir|olunmur)|şamil edilmir|aid edilmir|nəzərə alınmır|истисна|исключени",
    "condition": r"şərt|olduqda|halda|təqdirdə|müddət|gec olmayaraq|шярт|мцддят|олдугда|асылы",
    "threshold": r"\d|faiz|manat|məbləğ|hədd|limit|фаиз|манат|мябляь|лимит|мящдудлаш",
    "reference": r"maddə|bənd|hissə|qanun|qayda|маддя|бянд|ганун|гайда",
    "definition": r"dedikdə|başa düşülür|nəzərdə tutulur|anlayış|дедикдя|баша дцшцлцр|нязярдя тутулур",
}


@dataclass(frozen=True)
class PassageInput:
    text: str
    start: int
    end: int
    original_tokens: int
    embedded_tokens: int
 
 
def get_model() -> SentenceTransformer:
    global _model, _model_revision
    if _model is None:  # lazy: nothing is loaded at import time
        directory = Path(EMBED_MODEL)
        if directory.is_dir():
            digest = hashlib.sha256()
            for file in sorted(path for path in directory.rglob("*") if path.is_file()):
                with file.open("rb") as stream:
                    digest.update(json.dumps([file.relative_to(directory).as_posix(),
                                              hashlib.file_digest(stream, "sha256").hexdigest()]).encode("utf-8"))
            revision = "sha256:" + digest.hexdigest()
            model = SentenceTransformer(EMBED_MODEL)
        else:
            config = Path(hf_hub_download(EMBED_MODEL, "config.json", revision=EMBED_MODEL_REVISION))
            revision = config.parent.name
            if config.parent.parent.name != "snapshots" or not re.fullmatch(r"[a-f0-9]{40}", revision):
                raise RuntimeError("Could not resolve the embedding model to an immutable Hub snapshot")
            model = SentenceTransformer(EMBED_MODEL, revision=revision)
        _model_revision = revision
        _model = model
    return _model


def input_prefix(model, kind: str) -> str:
    if "e5" in EMBED_MODEL.lower():
        return f"{kind}: "
    return model.prompts.get(model.default_prompt_name, "")


def model_input(text: str, kind: str) -> str:
    return input_prefix(get_model(), kind) + text


@lru_cache(maxsize=1)
def embedding_configuration() -> dict:
    model = get_model()
    if _model_revision is None:
        raise RuntimeError("Embedding model revision is unknown")
    tokenizer = model.tokenizer
    # The backend describes the vocabulary, added tokens, normalizer, and post-processor.
    backend = json.loads(tokenizer.backend_tokenizer.to_str())
    # Fast tokenizers change these transient fields after each batch.
    backend.pop("padding", None)
    backend.pop("truncation", None)
    tokenizer_digest = hashlib.sha256(
        json.dumps(backend, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    get_dimensions = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    dimensions = get_dimensions()
    if not dimensions:
        raise RuntimeError("Embedding model has no fixed sentence vector dimension")
    return {
        "model_repository": EMBED_MODEL,
        "model_revision": _model_revision,
        # Both artifacts are loaded from the same pinned snapshot or local bundle.
        "tokenizer_revision": _model_revision,
        "tokenizer": {
            "class": type(tokenizer).__name__, "backend_sha256": tokenizer_digest,
            "max_length": tokenizer.model_max_length, "truncation_side": tokenizer.truncation_side,
            "padding_side": tokenizer.padding_side, "special_tokens": tokenizer.special_tokens_map,
        },
        "dimensions": dimensions,
        "pooling": [{"class": type(module).__name__, "configuration": module.get_config_dict()}
                    for module in model.children() if hasattr(module, "pooling_output_dimension")],
        "max_input_tokens": input_limit(model),
        "prefixes": {kind: input_prefix(model, kind) for kind in ("query", "passage")},
        "encoding": {
            "normalize": NORMALIZE_EMBEDDINGS, "precision": ENCODE_PRECISION, "output": "sentence_embedding",
            "backend": model.backend, "weights_dtype": str(model.dtype), "truncate_dimension": model.truncate_dim,
            "libraries": {name: version(name) for name in ("sentence-transformers", "transformers", "tokenizers", "torch")},
        },
        "chunking": {"version": CHUNKING_VERSION, "parent_characters": INDEX_CHUNK_CHARS,
                     "target_tokens": EMBED_TARGET_TOKENS, "overlap_tokens": EMBED_OVERLAP_TOKENS},
    }


def input_limit(model) -> int:
    return min(length for length in (model.max_seq_length, model.tokenizer.model_max_length) if length is not None)


def token_counts(model, texts: list[str]) -> list[int]:
    lengths = []
    for offset in range(0, len(texts), 128):
        batch = texts[offset:offset + 128]
        lengths.extend(model.tokenizer(batch, add_special_tokens=True, truncation=False,
                                       return_length=True, verbose=False)["length"])
    return lengths


def plan_passages(chunks: list[dict], texts: list[str], *, contextual: bool = False) -> list[list[PassageInput]]:
    model = get_model()
    limit = input_limit(model)
    target = min(EMBED_TARGET_TOKENS or limit, limit)
    overlap = min(EMBED_OVERLAP_TOKENS, target // 4)
    original_inputs = [model_input(text, "passage") for text in texts]
    counts = token_counts(model, original_inputs)
    oversized = sum(count > limit for count in counts)
    log.info("Passage token audit model=%s model_limit=%s tokenizer_limit=%s truncation_side=%s "
             "target=%d overlap=%d parents=%d oversized=%d",
             EMBED_MODEL, model.max_seq_length, model.tokenizer.model_max_length,
             model.tokenizer.truncation_side, target, overlap, len(chunks),
             oversized, extra={"event": "passage_token_audit", "embedding_model": EMBED_MODEL,
                               "token_limit": limit, "target_tokens": target, "overlap_tokens": overlap,
                               "parent_count": len(chunks), "oversized_count": oversized})
    plans = []
    for chunk, text, original_input, count in zip(chunks, texts, original_inputs, counts, strict=True):
        body = chunk["text"]
        if count <= target:
            plans.append([PassageInput(text, 0, len(body), count, count)])
            continue
        metadata = chunk.get("metadata") or {}
        header = contextual_header(chunk) if contextual else metadata.get("article_title") or ""
        parts = split_passage(body, header, model, target, overlap, count)
        plans.append(parts)
        if count > limit:
            encoded = model.tokenizer(original_input, truncation=False, return_offsets_mapping=True,
                                      add_special_tokens=False, verbose=False)
            # Account for the special tokens added to the actual encoder input.
            keep = limit - model.tokenizer.num_special_tokens_to_add(pair=False)
            offsets = encoded["offset_mapping"]
            omitted = (original_input[:offsets[-keep][0]] if model.tokenizer.truncation_side == "left"
                       else original_input[offsets[keep - 1][1]:])
            signals = [name for name, pattern in LEGAL_SIGNALS.items() if re.search(pattern, omitted, re.IGNORECASE)]
            child_counts = [part.embedded_tokens for part in parts]
            log.warning("Oversized passage doc=%s article=%s clause=%s page=%s original_tokens=%d "
                        "legacy_embedded_tokens=%d child_embedded_tokens=%s omitted_legal_signals=%s",
                        chunk["doc"], metadata.get("article"), metadata.get("clause"),
                        metadata.get("page_number"), count, limit,
                        child_counts, signals, extra={
                            "event": "oversized_passage", "source_document": chunk["doc"],
                            "source_article": metadata.get("article"), "source_clause": metadata.get("clause"),
                            "source_page": metadata.get("page_number"), "original_tokens": count,
                            "legacy_embedded_tokens": limit, "child_embedded_tokens": child_counts,
                            "omitted_legal_signals": signals,
                        })
    return plans


def split_passage(body: str, title: str, model, target: int, overlap: int, original: int) -> list[PassageInput]:
    def render(start: int, end: int) -> str:
        excerpt = body[start:end].strip()
        return f"{title}\n{excerpt}" if title and title not in excerpt else excerpt

    def size(text: str) -> int:
        return token_counts(model, [model_input(text, "passage")])[0]

    if title and size(title) + 8 >= target:
        # The complete heading stays in the parent and in the child metadata.
        title = ""
    stops = sorted({match.end() for match in LEGAL_BOUNDARY.finditer(body)} | {len(body)})
    words = [match.end() for match in re.finditer(r"\S+\s*", body)]
    parts = []
    covered = start = 0
    while covered < len(body):
        def furthest(boundaries) -> int:
            low = bisect_right(boundaries, covered)
            high = len(boundaries)
            while low < high:
                mid = (low + high) // 2
                if size(render(start, boundaries[mid])) <= target:
                    low = mid + 1
                else:
                    high = mid
            return boundaries[low - 1] if low > bisect_right(boundaries, covered) else covered

        end = furthest(stops)
        if end == covered and start < covered:
            overlapping_start = start
            start = covered
            end = furthest(stops)
            if end == covered:
                start = overlapping_start
        if end == covered:
            end = furthest(words)
        if end == covered and start < covered:
            start = covered
            end = furthest(words)
        if end == covered:
            # An uninterrupted extracted string can exceed the budget on its own.
            end = furthest(range(covered + 1, len(body) + 1))
        if end == covered:
            raise ValueError("Embedding target leaves no room for passage text")
        text = render(start, end)
        parts.append(PassageInput(text, start, end, original, size(text)))
        if end == len(body):
            break
        if end in stops:
            candidates = stops[max(0, bisect_right(stops, end) - 2):bisect_right(stops, end) - 1]
        else:
            candidates = words[max(0, bisect_right(words, end) - 1 - overlap):bisect_right(words, end) - 1]
        start = next((offset for offset in candidates if offset > start and
                      size(body[offset:end].strip()) - size("") <= overlap), end)
        covered = end
    return parts
 
 
def embed(texts: list[str], kind: str = "passage", batch_size: int = 16,
          show_progress: bool = False) -> np.ndarray:
    """Return an L2-normalized float32 matrix (inner product == cosine similarity).
 
    kind: "passage" for document chunks, "query" for user questions.
    """
    if kind not in ("passage", "query"):
        raise ValueError("kind must be 'passage' or 'query'")
    model = get_model()
    texts = [model_input(text, kind) for text in texts]
    if kind == "passage" and any(count > input_limit(model) for count in token_counts(model, texts)):
        raise ValueError("Passage embedding input exceeds the model token limit")
    vectors = model.encode(
        texts,
        prompt="",
        normalize_embeddings=NORMALIZE_EMBEDDINGS,
        precision=ENCODE_PRECISION,
        output_value="sentence_embedding",
        batch_size=batch_size,
        show_progress_bar=show_progress,
    )
    return np.asarray(vectors, dtype="float32")
