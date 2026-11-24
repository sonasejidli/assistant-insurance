"""Exercise the actual request path with offline, deterministic model boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree

from App.evaluation_capture import model_attempt, record, recording


def capture_case(case, documents, aliases, *, transport=None, provider=None):
    import numpy as np
    from starlette.requests import Request

    from App import legal_answers, main, observability, query_plan, settings, system, text_search

    chunks = [hit for doc in documents for hit in doc["chunks"]]
    fixture_order = [aliases[key] for key in case["dense_fixture"]]
    priorities = {pid: rank for rank, pid in enumerate(fixture_order)}
    retriever = text_search.TextRetriever.__new__(text_search.TextRetriever)
    retriever.chunks, retriever.documents = chunks, documents
    retriever.settings = settings.RetrievalSettings()
    retriever.bm25 = text_search.RetrievalBM25.from_chunks(chunks)

    def dense(_vector, eligible, limit, *, exact=False, **_):
        results = sorted((priorities[chunks[index]["metadata"]["chunk_id"]], index) for index in eligible
                         if chunks[index]["metadata"]["chunk_id"] in priorities)
        return [(index, 1.0 / (rank + 1)) for rank, index in results[:limit]]

    retriever.vector_index = SimpleNamespace(search=dense)
    retriever.graph = retriever._build_graph()
    request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(retriever=retriever))})
    actual_generator = legal_answers.generate_legal_answer
    actual_resolver = main.resolve_request

    def resolver(*args, **kwargs):
        resolved = actual_resolver(*args, **kwargs)
        record(resolved_context=list(resolved.context))
        return resolved

    def generator(*args, **kwargs):
        rendered, structured = actual_generator(*args, **kwargs)
        record(rendered=rendered, structured=structured.model_dump(mode="json"))
        return rendered, structured

    def scripted_provider(prompt, payload, **_):
        attempt = model_attempt("fixture-script", "structured-legal-1", prompt, payload)
        attempt["provider"] = "deterministic_fixture"
        if case.get("provider_failure"):
            attempt["status"] = "failed"
            attempt["error_type"] = "TimeoutError"
            raise TimeoutError("Synthetic fixture timeout")
        tags = ElementTree.fromstring("<packed>" + attempt["evidence_context"] + "</packed>")
        markers = {tag.get("chunk_id"): tag.get("id") for tag in tags}
        claims = [
            {"text": claim["text"], "source_ids": [markers.get(aliases[source], "S999") for source in claim["sources"]],
             **({"part": claim["part"]} if claim.get("part") else {})}
            for claim in case["scripted_claims"]
        ]
        output = json.dumps({"claims": claims, "evidence_status": case.get("scripted_status", "sufficient")},
                            ensure_ascii=False)
        if transform := case.get("_transform"):
            output = transform(output, payload)
        attempt.update(status="returned", output=output)
        return output

    experiments = {name: False for name in ("routing", "alternatives", "hyde", "reliability", "provision")}
    experiments["decompose_parts"] = case.get("decompose", False)
    config = {"model": "fixture-script", "model_boundary": "scripted", "dense_boundary": "scripted_candidates",
              "reranker_boundary": "scripted_scores", "judge_boundary": "scripted",
              "authority": True, "structured": True, "retrieval_settings": vars(retriever.settings),
              "top_k": 5, "experiments": experiments}
    with (
        recording() as capture,
        patch.dict("os.environ", {"LEGAL_SOURCE_AUTHORITY": "1", "RAG_METRICS_LOG_ENABLED": "0"}),
        patch.object(main, "TOP_K", 5),
        patch.object(main, "STRUCTURED_ANSWERS", True),
        patch.object(main, "LEGAL_MULTIPART_COVERAGE", False),
        patch.object(observability, "STRUCTURED_ANSWERS", True),
        patch.object(query_plan, "classify_intent_llm", return_value="insurance_question"),
        patch.object(main, "resolve_request", resolver),
        patch.object(main, "generate_legal_answer", generator),
        patch.object(main, "query_experiments", return_value=experiments),
        patch.object(text_search, "embed", return_value=np.ones((1, 1))),
        patch.object(text_search, "cross_encoder_scores", side_effect=lambda _query, docs: np.asarray([
            float(-priorities.get(doc.metadata.get("chunk_id"), 999)) for doc in docs])),
        patch.object(legal_answers, "API_KEY", legal_answers.API_KEY if provider else "offline-fixture"),
        patch.object(legal_answers, "LLM_MODEL", legal_answers.LLM_MODEL if provider else "fixture-script"),
        patch.object(legal_answers, "LEGAL_MIN_SUPPORTING_STAGES",
                     legal_answers.LEGAL_MIN_SUPPORTING_STAGES if provider else 1),
        patch.object(legal_answers, "LEGAL_CLAIM_GUARDS", legal_answers.LEGAL_CLAIM_GUARDS if provider else False),
        patch.object(system, "LLM_CONTEXT_WINDOW", system.LLM_CONTEXT_WINDOW if provider else 16384),
        patch.object(system, "LLM_MAX_OUTPUT_TOKENS", system.LLM_MAX_OUTPUT_TOKENS if provider else 1536),
        patch.object(legal_answers, "LLM_MAX_OUTPUT_TOKENS", legal_answers.LLM_MAX_OUTPUT_TOKENS if provider else 1536),
        patch.object(legal_answers, "invoke", provider or scripted_provider),
        patch.object(legal_answers, "judge_claims", legal_answers.judge_claims if provider else
                     lambda claims, _evidence: [case.get("judge", True)] * len(claims)),
    ):
        capture["configuration"] = config
        capture["history_input"] = case.get("history", [])
        capture["date_input"] = case.get("dates", {})
        question = main.Question(question=case["query"], language="az", history=capture["history_input"],
                                 case_dates=capture["date_input"])
        capture["response"] = transport(question, retriever) if transport else main.ask(question, request)
    return capture
