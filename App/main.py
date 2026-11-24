import logging
import json
import re
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, field_validator

from App.settings import TOP_K, QUERY_DECOMPOSITION, QUERY_ROUTING, QUERY_EXPANSION, QUERY_HYDE
from App.answer_recovery import answer_recovery, provider_failure
from App.settings import LEGAL_EVIDENCE, LEGAL_MULTIPART_COVERAGE, LEGAL_PROVISION_RETRIEVAL, LEGAL_RETRIEVAL_V2, STAGED_LEGAL_SOURCES, STRUCTURED_ANSWERS
from App.legal_answers import LegalAnswer, abstention, canonical_references, generate_legal_answer
from App.legal_evidence import assemble_evidence
from App.observability import capture_retrieval, client_request_id, event, stage_timing, startup_stage
from App.evaluation_capture import current, decision, passage_id, record
from App.intent import classify_intent, classify_intent_rule
from App.query_plan import passage_key, plan_query, retrieve_plan
from App.query_resolution import follow_up_clarification, resolve_query
from App import accounts
from App import bot_templates, gemini_generation, source_authority, verified_release
from App.document_processing import ARTICLE, CLAUSE, clean_text, join_lines
from App.system import (
    AnswerFormatError, NOT_FOUND, PARTIAL_PREFIX, answer_question, citation_for, citation_matches, cited_indexes,
    detect_language, format_answer, limited_answer, surrounding_evidence, usable_hits,
)
from App.text_search import TEXT_DIR, TextRetriever, article_number, article_numbers
from App.topic_modules import HEALTH_SALARY_CLAUSE, extract_limits, salary_health_answer, salary_insurance_request

def disclaimer_footer(lang: str) -> str:
    return bot_templates.get_disclaimer_footer(lang)


logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def clarification(language: str, answer: str | None = None) -> dict:
    answer = answer or bot_templates.get_clarification(language)
    structured = abstention(language).model_copy(update={"answer": answer}).model_dump(exclude={"answer"}) if STRUCTURED_ANSWERS else {}
    return {"answer": answer, "sources": [], "warnings": [], "disclaimer": "", **structured,
            "limits": [], "previews": [], "related_articles": [], "quick_replies": [],
            "intent": "clarification", "language": language}


@stage_timing("query_resolution_timing", capture_only=True)
def resolve_request(text: str, history: list[str], *, direct_article: bool):
    resolution = resolve_query(text, history, direct_article=direct_article)
    details = {"original_chars": len(text), "resolved_chars": len(resolution.standalone or ""),
               "context_turns": len(resolution.context), "clarification_required": resolution.standalone is None}
    log.debug("Query resolution recorded", extra={"event": "query_resolution", **details})
    event("query_resolution", **details)
    return resolution


def query_experiments() -> dict[str, bool]:
    provision = LEGAL_PROVISION_RETRIEVAL or LEGAL_MULTIPART_COVERAGE
    planned = LEGAL_RETRIEVAL_V2 or provision
    return {"decompose_parts": QUERY_DECOMPOSITION or planned, "routing": QUERY_ROUTING or planned,
            "alternatives": QUERY_EXPANSION, "hyde": QUERY_HYDE, "reliability": planned, "provision": provision}


@asynccontextmanager
async def lifespan(app: FastAPI):
    with startup_stage("application_readiness"):
        if verified_release.enabled():
            with startup_stage("verified_release_dependencies"):
                from evaluation.verify_legal_scope_v2 import verify_case

                profiles, policy = verified_release.configuration()
                if not profiles or not policy.get("witnesses") or not callable(verify_case):
                    raise RuntimeError("Verified release configuration is incomplete")
                source_authority.load_catalog()
        app.state.retriever = TextRetriever()
    try:
        yield
    finally:
        app.state.retriever.close()


app = FastAPI(title="Insurance Assistant", lifespan=lifespan)
app.include_router(accounts.router)


class SearchFilters(BaseModel):
    as_of: date | None = None
    insurance_type: str | None = Field(default=None, max_length=100)
    law: str | None = Field(default=None, max_length=300)
    topic: Literal["tariff", "exclusion", "deadline"] | None = None

    @field_validator("insurance_type", "law")
    @classmethod
    def clean_filter(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CaseDates(BaseModel):
    insured_event_date: date | None = None
    claim_notification_date: date | None = None
    claim_date: date | None = None
    contract_start: date | None = None
    contract_termination: date | None = None
    requested_reference_date: date | None = None


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    filters: SearchFilters | None = None
    article: str | None = Field(default=None, pattern=r"^\d+(?:-\d+)?(?:\.\d+(?:-\d+)?)*$")
    language: Literal["auto", "en", "az", "ru"] = "auto"
    mode: Literal["question", "exclusions", "tariff", "claims", "limits", "rights", "comparison", "scenario"] = "question"
    history: list[str] = Field(default_factory=list, max_length=5)
    compare_laws: list[str] = Field(default_factory=list, max_length=2)
    case_dates: CaseDates | None = None

    @field_validator("history", "compare_laws")
    @classmethod
    def clean_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("Items must be nonempty and at most 500 characters")
        return [value.strip() for value in values]


class SearchRequest(Question):
    question: str = Field(min_length=3, max_length=500)
    limit: int = Field(default=TOP_K, ge=1, le=50)


class Calculation(BaseModel):
    base_azn: Decimal = Field(ge=0, le=Decimal("1000000000000"), allow_inf_nan=False)
    rate_percent: Decimal = Field(ge=0, le=100, allow_inf_nan=False)
    language: Literal["en", "az", "ru"] = "en"


@app.post("/calculate")
def calculate_premium(calculation: Calculation):
    value = (calculation.base_azn * calculation.rate_percent / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"amount_azn": str(value), "base_azn": str(calculation.base_azn),
            "rate_percent": str(calculation.rate_percent), "disclaimer": disclaimer_footer(calculation.language),
            "warning": "Arithmetic only: the entered rate and base are not verified against any law, threshold, or eligibility condition."}


@app.get("/", include_in_schema=False)
def home():
    page = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    templates = json.dumps(bot_templates.load_templates()).replace("<", "\\u003c")
    return HTMLResponse(page.replace("<!-- bot-templates -->", templates))


@app.get("/health")
def health(request: Request):
    return {"status": "ok", "chunks": len(request.app.state.retriever.chunks)}


@app.get("/documents")
def documents(request: Request):
    return [{"doc": document["doc"], "metadata": document["metadata"]}
            for document in request.app.state.retriever.documents]


@app.get("/documents/{name}/versions")
def document_versions(name: str, request: Request):
    documents = request.app.state.retriever.documents
    versions = [document["doc"] for document in documents
                if Path(document["doc"]).stem.split("@", 1)[0] == name]
    if not versions:
        raise HTTPException(404, "Document not found")
    return {"name": name, "versions": versions}


@app.get("/documents/{name}/versions/{version}")
def document_version(name: str, version: str, request: Request):
    for document in request.app.state.retriever.documents:
        if document["doc"] == version and Path(version).stem.split("@", 1)[0] == name:
            return document
    raise HTTPException(404, "Document version not found")


def indexed_document(filename: str, request: Request):
    return next((document for document in request.app.state.retriever.documents
                 if document["doc"] == filename), None)


def passage_url(filename: str, index: int) -> str:
    return f"/documents/{quote(filename, safe='')}/preview/{index}"


def indexed_pdf_path(filename):
    roots = [TEXT_DIR]
    if STAGED_LEGAL_SOURCES:
        roots.append(TEXT_DIR.parent / "staged_legal")
    for root in roots:
        path = (root / filename).resolve()
        if path.suffix.lower() == ".pdf" and path.parent == root.resolve() and path.is_file():
            return path
    return None


def pdf_section_page(chunk: dict, pages: list[str]) -> int | None:
    cleaned_pages = [clean_text(text) for text in pages]
    flattened = [join_lines(text.splitlines()) for text in cleaned_pages]
    passage = join_lines(clean_text(chunk["text"]).splitlines())
    if not passage:
        return None

    matches = {i + 1 for i, text in enumerate(flattened) if passage in text}
    for i, (first, second) in enumerate(zip(flattened, flattened[1:])):
        if not first or not second:
            continue
        combined = f"{first} {second}"
        start = combined.find(passage, max(0, len(first) + 1 - len(passage)))
        if 0 <= start < len(first) and start + len(passage) > len(first) + 1:
            matches.add(i + 1)
    if matches:
        return next(iter(matches)) if len(matches) == 1 else None

    metadata = chunk.get("metadata") or {}
    heading = CLAUSE if metadata.get("clause") else ARTICLE
    identifier = metadata.get("clause") or metadata.get("article")
    if not identifier:
        return None
    for i, text in enumerate(cleaned_pages, start=1):
        if any(match[1] == identifier for line in text.splitlines() if (match := heading.match(line))):
            matches.add(i)
    return next(iter(matches)) if len(matches) == 1 else None


@app.get("/citations/resolve")
def resolve_citation(title: str, article: str, clause: str, request: Request):
    matches = [(document, index, chunk)
               for document in request.app.state.retriever.documents
               for index, chunk in enumerate(document["chunks"])
               if citation_matches(chunk, title, article, clause)]
    if not matches:
        raise HTTPException(404, "Passage not found")
    if len(matches) != 1:
        raise HTTPException(409, "Citation matches multiple indexed passages")
    document, index, chunk = matches[0]
    return {"source": citation_for(chunk), "url": passage_url(document["doc"], index)}


@app.get("/documents/{filename}/preview/{index}")
def preview_document(filename: str, index: int, request: Request):
    document = indexed_document(filename, request)
    if not document or index < 0 or index >= len(document["chunks"]):
        raise HTTPException(404, "Passage not found")
    chunk = document["chunks"][index]
    page = (chunk.get("metadata") or {}).get("page_number")
    original_url = None
    if Path(filename).suffix.lower() == ".pdf":
        if path := indexed_pdf_path(filename):
            if page is None:
                import pymupdf

                with pymupdf.open(path) as pdf:
                    page = pdf_section_page(chunk, [item.get_text(sort=True) for item in pdf])
            original_url = f"/documents/{quote(filename, safe='')}/pdf"
    pdf_url = f"{original_url}#page={page}" if original_url and page else None
    return {"text": chunk["text"], "source": citation_for(chunk), "page": page,
            "pdf_url": pdf_url, "original_url": original_url}


@app.get("/documents/{filename}/pdf")
def document_pdf(filename: str, request: Request):
    document = indexed_document(filename, request)
    path = indexed_pdf_path(filename)
    if not document or path is None:
        raise HTTPException(404, "PDF not found")
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")


@app.get("/articles/{number}")
def get_article(number: str, request: Request, insurance_type: str | None = None,
                law: str | None = None, topic: Literal["tariff", "exclusion", "deadline"] | None = None):
    filters = SearchFilters(insurance_type=insurance_type, law=law, topic=topic).model_dump(exclude_none=True)
    try:
        hits = request.app.state.retriever.lookup_article(number, filters)
    except ValueError:
        raise HTTPException(422, "Invalid article number")
    if not hits:
        raise HTTPException(404, "Article not found")
    return {"article": number, "hits": hits}


@app.post("/search")
@capture_retrieval
def search_documents(query: SearchRequest, request: Request):
    text = query.question.strip()
    if len(text) < 3:
        raise HTTPException(422, "Please enter a question of at least 3 characters.")
    filters = query.filters.model_dump(exclude_none=True, mode="json") if query.filters else {}
    direct = bool(query.article or article_number(text))
    resolution = resolve_request(text, query.history, direct_article=direct)
    if resolution.standalone is None:
        language = detect_language(text) if query.language == "auto" else query.language
        return {"hits": [], "match_type": "clarification", "score": None, "intent": "clarification",
                "answer": follow_up_clarification(resolution.original, language), "language": language}
    try:
        retriever = request.app.state.retriever
        experiments = query_experiments()
        plan = plan_query(resolution, query.language, forced=True) if not direct and any(experiments.values()) else None
        if plan and plan.parts:
            hits, score, _, _ = retrieve_plan(retriever, plan, k=query.limit, filters=filters, **experiments)
        else:
            hits, score = retriever.search(resolution if resolution.standalone != text else text, k=query.limit,
                                           filters=filters, article=query.article)
    except Exception as exc:
        event("retrieval_error", error_type=type(exc).__name__)
        raise HTTPException(503, "The search service is temporarily unavailable. Please try again.")
    return {"hits": hits, "match_type": "article" if direct else "hybrid", "score": None if direct else score}


@app.post("/ask", name="ask")
def ask_http(question: Question, request: Request, response: Response):
    result = ask(question, request)
    if request_id := client_request_id(request):
        response.headers["X-Request-ID"] = request_id
    return result


@verified_release.enforce
@capture_retrieval
def ask(question: Question, request: Request):
    record(query=question.question)
    text = question.question.strip()
    if not text:
        raise HTTPException(422, "Please enter a message.")
    response_language = detect_language(text) if question.language == "auto" else question.language
    filters = question.filters.model_dump(exclude_none=True, mode="json") if question.filters else {}
    release_enabled = verified_release.enabled()
    authority_enabled = source_authority.enabled() or release_enabled
    if release_enabled:
        record(release_language=response_language)
    authority = None
    if authority_enabled:
        dates = question.case_dates.model_dump(exclude_none=True, mode="json") if question.case_dates else {}
        reference_from_filter = bool(filters.get("as_of") and "requested_reference_date" not in dates)
        if filters.get("as_of") and dates.setdefault("requested_reference_date", filters["as_of"]) != filters["as_of"]:
            raise HTTPException(422, "The requested reference dates disagree.")
        timeline = source_authority.case_timeline(**dates, current_requested=source_authority.requests_current_law(text))
        if reference_from_filter:
            timeline["date_provenance"]["requested_reference_date"]["input_field"] = "filters.as_of"
    force_insurance = question.mode != "question" or bool(filters or question.article or question.compare_laws)
    requested_articles = [question.article] if question.article else article_numbers(text)
    resolution = resolve_request(text, question.history, direct_article=bool(requested_articles))
    plan = plan_query(resolution, response_language, forced=force_insurance, direct=bool(requested_articles),
                      **({"preserve_explicit_parts": True} if release_enabled else {}))
    if current.get() is not None:
        record(normalized_query=resolution.normalized, standalone_query=resolution.standalone,
               planned_parts={part.id: part.question for part in plan.parts}, route=plan.intent)
    log.debug("Query intent %s", plan.intent, extra={"event": "query_intent", "query_intent": plan.intent})
    event("intent", intent=plan.intent, part_count=len(plan.parts), filter_fields=sorted(filters))
    if plan.intent == "ambiguous_question":
        decision(None, "clarification")
        return clarification(response_language, follow_up_clarification(resolution.original, response_language))
    if intent := plan.social_response:
        decision(None, "social_response")
        opening = bot_templates.get_opening(response_language)
        answer = opening["greeting"] if intent == "greeting" else bot_templates.get_intent_template(response_language, intent)
        follow_up = [opening["follow_up"]] if intent == "greeting" else []
        return {"answer": answer, "sources": [], "warnings": [], "disclaimer": "",
                "limits": [], "previews": [], "related_articles": [], "quick_replies": [],
                "intent": "general_conversation" if intent == "conversation" else intent,
                "follow_up_messages": follow_up, "language": response_language}
    if plan.intent == "out_of_scope":
        decision(None, "out_of_scope")
        answer = bot_templates.get_intent_template(response_language, "out_of_scope")
        examples = bot_templates.get_examples(response_language)
        quick_replies = examples[:2]
        return {"answer": answer, "sources": [], "warnings": [], "disclaimer": "",
                "limits": [], "previews": [], "related_articles": [], "quick_replies": quick_replies,
                "intent": plan.intent, "language": response_language}
    if len(text) < 3:
        raise HTTPException(422, "Please enter a question of at least 3 characters.")
    options = {}
    if len(requested_articles) > 50:
        raise HTTPException(422, "Please ask about at most 50 articles at a time.")
    if len(requested_articles) > TOP_K:
        options["k"] = len(requested_articles)
    if filters:
        options["filters"] = filters
    if question.article:
        options["article"] = question.article
    retriever = request.app.state.retriever
    salary_request = salary_insurance_request(text) if response_language == "az" and not force_insurance and not requested_articles else None
    comparison_groups = []
    associations, parts = {}, ()
    experiments = query_experiments()
    if release_enabled and len(plan.parts) > 1:
        experiments = {**experiments, "decompose_parts": True}
    search_query = resolution if resolution.standalone != text else text
    capture = current.get()
    ranking_limit = options.get("k", TOP_K)
    try:
        if salary_request is not None:
            hits = retriever.lookup_article(HEALTH_SALARY_CLAUSE, {"insurance_type": "medical"})
            if len(hits) != 1:
                hits = []
        elif question.mode == "comparison":
            if len(question.compare_laws) != 2 or question.compare_laws[0].casefold() == question.compare_laws[1].casefold():
                raise HTTPException(422, "Comparison requires two different law names or numbers.")
            hits = []
            for law in question.compare_laws:
                filters = {**options.get("filters", {}), "law": law}
                extra = {"k": options["k"]} if "k" in options else {}
                law_hits, _ = retriever.search(search_query, filters=filters, article=question.article, **extra)
                law_hits = usable_hits(law_hits)
                if not law_hits:
                    comparison_groups.append([])
                    continue
                if any(hit["doc"] in {existing["doc"] for existing in hits} for hit in law_hits):
                    raise HTTPException(422, "Law filters overlap; use more specific names or numbers.")
                comparison_groups.append(law_hits)
                hits.extend(law_hits)
        elif not requested_articles and any(experiments.values()):
            ranking_limit = max(TOP_K, len(plan.parts))
            hits, _, associations, parts = retrieve_plan(retriever, plan, k=ranking_limit,
                                                          filters=options.get("filters", {}), **experiments)
        else:
            hits, _ = retriever.search(search_query, **options)
    except HTTPException:
        raise
    except Exception as exc:
        event("retrieval_error", error_type=type(exc).__name__)
        decision(None, "internal_error")
        return answer_recovery("internal_error", response_language)
    hits = usable_hits(hits)
    if capture is not None:
        record(ranked_passage_ids=[passage_id(hit) for hit in hits],
               retrieval_limit=None if salary_request is not None or comparison_groups else ranking_limit,
               executed_parts={part.id: part.question for part in parts},
               retrieved_assignments=[{"passage_id": passage_id(hit),
                                       "parts": sorted(associations.get(passage_key(hit), ()))} for hit in hits])
    if not hits:
        record(generation_path="no_evidence")
        decision("NOT_FOUND", "no_usable_retrieval")
        event("empty_retrieval")
        log.info("Answer evidence: retrieval returned no usable passages")
        return {"answer": limited_answer(response_language), "sources": [], "warnings": [],
                "answer_mode": "NOT_FOUND", "evidence_status": "insufficient",
                **(abstention(response_language).model_dump(exclude={"answer"}) if STRUCTURED_ANSWERS else {}),
                **({"source_authority": source_authority.annotate([], [], [], timeline)} if authority_enabled else {}),
                "disclaimer": disclaimer_footer(response_language), "limits": [], "previews": [], "related_articles": []}
    documents = getattr(retriever, "documents", [])
    comparison_docs = [{hit["doc"] for hit in group} for group in comparison_groups]
    if comparison_groups:
        # Give each law an early slot when the generation budget is tight.
        hits = [hit for group in comparison_groups for hit in group[:1]]
        hits.extend(hit for group in comparison_groups for hit in group[1:])
    package = None
    structured = None
    gemini_enabled = gemini_generation.enabled()
    structured_generation = STRUCTURED_ANSWERS or gemini_enabled
    if LEGAL_EVIDENCE or structured_generation or LEGAL_RETRIEVAL_V2 or experiments["provision"] or STAGED_LEGAL_SOURCES or authority_enabled:
        package = assemble_evidence(resolution.standalone, hits, documents, associations=associations,
                                    part_ids=[part.id for part in parts] if len(parts) > 1 else (),
                                    part_questions={part.id: part.question for part in parts} if (LEGAL_RETRIEVAL_V2 or experiments["provision"]) and len(parts) > 1 else None,
                                    critical_groups=experiments["provision"], multipart_coverage=LEGAL_MULTIPART_COVERAGE,
                                    filters=options.get("filters"),
                                    expand=salary_request is None)
        hits = package.hits
        if authority_enabled:
            authority = source_authority.annotate(hits, package.items, documents, timeline)
            record(source_authority=authority)
            from App import retrieved_sources
            if capture is not None and retrieved_sources.enabled():
                record(retrieved_sources=retrieved_sources.source_cards(package.items, authority))
    elif salary_request is None:
        hits = surrounding_evidence(hits, documents)
    if capture is not None:
        record(assembled_evidence=[
            {"passage_id": passage_id(hit), "text": hit["text"],
             "parts": sorted(package.items[i]["subquestions"] if package and (structured_generation or LEGAL_MULTIPART_COVERAGE)
                             else associations.get(passage_key(hit), ()))}
            for i, hit in enumerate(hits)
        ])
    try:
        if salary_request is not None:
            record(generation_path="deterministic_calculation")
            if authority is not None and not authority["sources"][0]["eligible_normative"]:
                answer = NOT_FOUND
            else:
                answer = salary_health_answer(*salary_request, hits[0]["text"]) or NOT_FOUND
            if STRUCTURED_ANSWERS:
                if answer != NOT_FOUND and package.items[0]["passage_id"] and package.items[0]["document_id"]:
                    explicit_health = salary_request[1]
                    structured = LegalAnswer(answer=answer, references=canonical_references(package.items[:1]),
                                             limitations=[] if explicit_health else ["Hesablama yalnız icbari tibbi sığortaya aiddir."],
                                             evidence_status="sufficient" if explicit_health else "partial",
                                             confidence="medium" if explicit_health else "low")
                else:
                    answer, structured = NOT_FOUND, abstention(response_language)
        elif authority is not None or structured_generation or (package and package.conflicts):
            record(generation_path="structured")
            answer, structured = generate_legal_answer(resolution.original, package, response_language,
                history=resolution.context, subquestions={part.id: part.question for part in parts} if len(parts) > 1 else None,
                required_articles=requested_articles, comparison_docs=comparison_docs,
                **({"authority": authority, "judge": True} if authority is not None or gemini_enabled else {}))
        else:
            record(generation_path="legacy")
            part_options = {}
            if len(parts) > 1:
                part_options["subquestions"] = {part.id: part.question for part in parts}
                part_options["source_parts"] = ([set(item["subquestions"]) for item in package.items]
                                                if package and LEGAL_MULTIPART_COVERAGE else
                                                [associations.get(passage_key(hit), set()) for hit in hits])
            answer = answer_question(resolution.original, hits, language=response_language, mode=question.mode,
                                     history=list(resolution.context), **part_options)
    except AnswerFormatError:
        decision(None, "verification_failed")
        return answer_recovery("verification_failed", response_language)
    except Exception as exc:
        status = provider_failure(exc, "generation")
        decision(None, status)
        return answer_recovery(status, response_language)
    if structured and structured.delivery_failure:
        decision("NOT_FOUND", structured.delivery_failure)
        return answer_recovery(structured.delivery_failure, response_language)
    result = format_answer(answer, hits, response_language,
                           max_sources=8 if package and package.required_part_passages else 6 if len(parts) > 1 else 3)
    if release_enabled:
        record(release_rendered=answer)
    if result.get("intent") == "clarification":
        decision(None, "clarification")
        reply = clarification(response_language, result["answer"])
        if authority is not None:
            reply["source_authority"] = authority
        return reply
    indexes = cited_indexes(answer, hits) or []
    if experiments["provision"] and package and len(parts) > 1 and structured is None and not answer.startswith(PARTIAL_PREFIX):
        cited_ids = {package.items[i]["passage_id"] for i in indexes}
        if package.missing_parts or any(not ids <= cited_ids for ids in package.required_part_passages.values()):
            result = {"answer": NOT_FOUND, "sources": [], "warnings": []}
            indexes = []
    cited_articles = all(any((hits[index].get("metadata") or {}).get("clause" if "." in number else "article") == number
                             for index in indexes) for number in requested_articles)
    cited_documents = {hits[index]["doc"] for index in indexes}
    missing_requested_evidence = not cited_articles or any(not group.intersection(cited_documents) for group in comparison_docs)
    if result["answer"] == NOT_FOUND or (missing_requested_evidence and not answer.startswith(PARTIAL_PREFIX)):
        result = {"answer": NOT_FOUND, "sources": [], "warnings": []}
        indexes = []
    cited_hits = [hits[index] for index in indexes]
    result["limits"] = extract_limits(cited_hits)
    result["disclaimer"] = disclaimer_footer(response_language)
    result["previews"] = []
    result["related_articles"] = []
    for cited_index, hit in zip(indexes, cited_hits):
        document = next((item for item in documents if item["doc"] == hit["doc"]), None)
        if not document:
            continue
        identity = [index for index, chunk in enumerate(document["chunks"]) if chunk is hit]
        equal = [index for index, chunk in enumerate(document["chunks"]) if chunk == hit] if not identity else identity
        if len(equal) == 1:
            index = equal[0]
            chunk = document["chunks"][index]
            url = passage_url(hit["doc"], index)
            next(source for source in result["sources"] if source["id"] == f"S{cited_index + 1}")["url"] = url
            preview = {"source": citation_for(hit), "url": url}
            if preview not in result["previews"]:
                result["previews"].append(preview)
            for reference in chunk.get("references", []) if not package else ():
                target = reference.get("target_chunk")
                if isinstance(target, int) and 0 <= target < len(document["chunks"]):
                    related = {"article": reference["target"], "doc": hit["doc"],
                               "url": passage_url(hit["doc"], target)}
                    if related not in result["related_articles"]:
                        result["related_articles"].append(related)
    if result["answer"] == NOT_FOUND:
        decision("NOT_FOUND", "insufficient_evidence")
        result["answer"] = limited_answer(response_language)
        result.update(answer_mode="NOT_FOUND", evidence_status="insufficient")
        event("insufficient_evidence")
    else:
        partial = answer.startswith(PARTIAL_PREFIX) or (structured and structured.evidence_status == "partial")
        decision("PARTIAL" if partial else "FULL", "accepted_answer")
    if package:
        for link in package.relationships:
            target = next(item for item in package.items if item["passage_id"] == link["included_target_passage_id"])
            related = {"article": link["referenced_article_id"], "doc": target["document_reference"], "url": target["source_url"]}
            if related not in result["related_articles"]:
                result["related_articles"].append(related)
        result["evidence"] = {"source_count": len({item["document_id"] for item in package.items}),
                              "relationships": package.relationships, "conflicts": package.conflicts,
                              "missing_parts": sorted(package.missing_parts)}
        if len(parts) > 1:
            result["evidence"]["part_coverage"] = {part.id: {
                "candidate_passage_ids": [item["passage_id"] for item in package.items if part.id in item["subquestions"]],
                "required_passage_ids": sorted(package.required_part_passages.get(part.id, ())),
                "missing_required_passage_ids": sorted(package.required_part_passages.get(part.id, set()) -
                    {item["passage_id"] for item in package.items}),
                "supported_claim": part.id in structured.answered_parts if structured else None,
            } for part in parts}
    if structured:
        result.update(structured.model_dump(exclude={"answer"}))
        document_count = len({item.document_id for item in structured.references})
        result["evidence"]["support_mode"] = (
            "conflicting" if structured.evidence_status == "conflicting" else
            "insufficient" if not document_count else "multiple_sources" if document_count > 1 else "single_source"
        )
        if structured.evidence_status == "conflicting":
            decision(None, "conflicting")
            result["answer"] = structured.answer
            record(conflicting_references=result["references"])
            result["references"] = []
    if capture is not None:
        record(citation_passages={source["id"]: passage_id(hits[source["document_number"] - 1])
                                  for source in result["sources"]})
    if authority is not None:
        result["source_authority"] = authority
    return result
