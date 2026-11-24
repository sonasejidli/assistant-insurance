import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from fastapi import HTTPException
from fastapi.testclient import TestClient

from App import main, observability, query_resolution, text_search, vector_store
from App.azerbaijani import LEMMATIZER, normalize_az
from App.insurance_terminology import InsuranceTerminology, TERMINOLOGY
from App.settings import RetrievalSettings

TEST_CONFIGURATION = {"model_repository": "test-model", "dimensions": 2}


def make_chunk(doc, article, clause, text, insurance_type, law, title=""):
    return {"doc": doc, "text": text, "metadata": {
        "article": article, "clause": clause, "insurance_type": insurance_type,
        "law_name": law, "law_number": "999-IIIQ" if doc == "medical.pdf" else "111-IQ",
        "article_title": title,
    }}


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            make_chunk("medical.pdf", "20", "20.0.2", "Sığorta ödənişi istisna edilir.", "medical", "Tibbi sığorta", "İstisnalar"),
            make_chunk("medical.pdf", "20", "20.0.20", "Başqa müddəa.", "medical", "Tibbi sığorta"),
            make_chunk("other.pdf", "20", "20.0.2", "Sığorta haqqı və tarif.", "compulsory", "İcbari sığorta", "Tarif"),
        ]
        vectors = np.array([[0.2, 0.98], [0.1, 0.99], [1.0, 0.0]], dtype="float32")
        self.embed = Mock(side_effect=lambda texts, kind: vectors if kind == "passage" else np.array([[1.0, 0.0]], dtype="float32"))
        self.load_patch = patch.object(text_search, "load_chunks", return_value=self.chunks)
        self.embed_patch = patch.object(text_search, "embed", self.embed)
        self.load_patch.start()
        self.embed_patch.start()
        planner = patch.object(text_search, "plan_passages", return_value=None)
        planner.start()
        self.addCleanup(planner.stop)
        configuration = patch.object(text_search, "embedding_configuration", return_value=TEST_CONFIGURATION)
        configuration.start()
        self.addCleanup(configuration.stop)
        self.addCleanup(self.load_patch.stop)
        self.addCleanup(self.embed_patch.stop)
        self.retriever = text_search.TextRetriever()

    def test_expands_roles_without_conflating_them(self):
        for term, expected, unrelated in (
            ("policyholder", "sığortalı", "sığortaçı"),
            ("insurer", "sığortaçı", "faydalanan şəxs"),
            ("insured person", "sığorta olunan", "sığortalı"),
            ("beneficiary", "faydalanan şəxs", "sığortaçı"),
        ):
            expanded = text_search.expand_query(term)
            self.assertIn(expected, expanded)
            self.assertNotIn(unrelated, expanded)

    def test_colloquial_azerbaijani_queries_connect_to_formal_concepts(self):
        cases = (
            ("Maşınla başqasının malına ziyan vursam, ən çox nə qədər qarşılanır?",
             "üçüncü şəxslərin əmlakına dəyən zərər üzrə 5000 manat", "third_party_property_damage"),
            ("Masinla basqasinin malina ziyan vursam, en cox ne qeder qarsilanir?",
             "üçüncü şəxslərin əmlakına dəyən zərər üzrə 5000 manat", "third_party_property_damage"),
            ("Sığortaçıya qəzanı nə vaxt xəbər eləməliyəm?",
             "Sığorta hadisəsi barədə məlumat vermək", "event_notice"),
            ("Həkimə getməyin xərcini kim qarşılayır?",
             "Tibbi xidmətlərin dəyəri", "medical_services"),
        )
        for question, passage, concept in cases:
            with self.subTest(question=question):
                token = text_search.concept_token(concept)
                self.assertIn(token, text_search.lexical_query(question)[0])
                self.assertIn(token, text_search.lexical_tokens(passage))
                self.assertEqual(main.classify_intent_rule(question), "insurance_question")

    def test_article_in_history_does_not_switch_followup_to_exact_lookup(self):
        query = query_resolution.resolve_query("Bəs ödəniş nə vaxt edilir?", ["Maddə 20.0.2 nə deyir?"])
        self.assertIsNotNone(query.standalone)
        state = self.retriever._preprocess({
            "question": query.standalone,
            "original_question": query.original,
        })
        self.assertEqual(state["articles"], [])
        self.assertTrue(state["query_tokens"])

    def test_azerbaijani_followups_share_one_standalone_query_across_retrieval(self):
        cases = (
            ("Bəs bu halda?", "İcbari sığortada sığorta ödənişi hansı hallarda həyata keçirilir?",
             "İcbari sığortada sığorta ödənişi üçün hansı şərtlər tətbiq olunur?"),
            ("Bəs istisnalar necə?", "İcbari sığortada sığorta ödənişi necə hesablanır?",
             "İcbari sığortada sığorta ödənişi ilə bağlı hansı istisnalar var?"),
            ("Bu müddət neçə ildir?", "Tibbi sığorta müqaviləsinin qüvvədə olma müddəti nə qədərdir?",
             "Tibbi sığorta müqaviləsinin qüvvədə olma müddəti neçə ildir?"),
            ("Bu qayda KASKO-ya da aiddir?", "İcbari avtomobil sığortasında sığorta ödənişi necə hesablanır?",
             "İcbari avtomobil sığortasında sığorta ödənişi ilə bağlı qayda KASKO-ya da aiddir?"),
        )
        with patch.object(main.app.state, "retriever", self.retriever, create=True):
            client = TestClient(main.app)
            for question, prior, standalone in cases:
                for endpoint in ("/ask", "/search"):
                    with (
                        self.subTest(question=question, endpoint=endpoint),
                        patch.object(text_search, "lexical_query", wraps=text_search.lexical_query) as lexical,
                        patch.object(text_search, "rerank_documents", side_effect=lambda q, docs: docs) as rerank,
                        patch.object(main, "answer_question", return_value="Cavab [S1].") as generate,
                    ):
                        response = client.post(endpoint, json={
                            "question": question, "language": "az",
                            "history": ["Sosial sığorta nədir?", prior, "Salam"],
                        })
                        self.assertEqual(response.status_code, 200)
                        lexical.assert_called_once_with(standalone)
                        self.embed.assert_called_with([standalone], kind="query")
                        self.assertEqual(rerank.call_args.args[0], standalone)
                        if endpoint == "/ask":
                            self.assertEqual(generate.call_args.args[0], question)
                            self.assertEqual(generate.call_args.kwargs["history"], [prior])

    def test_unresolved_followups_ask_for_clarification_without_searching(self):
        search = Mock()
        with patch.object(main.app.state, "retriever", SimpleNamespace(search=search), create=True):
            client = TestClient(main.app)
            for endpoint in ("/ask", "/search"):
                for history in ([], ["İcbari sığortada avtomobil yanıb və ya oğurlanıbsa ödəniş edilirmi?"],
                                ["İcbari sığortada ödəniş hansı hallarda verilir?", "Bu gün hava necədir?"]):
                    response = client.post(endpoint, json={"question": "Bəs bu halda?", "history": history})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["intent"], "clarification")
                    self.assertIn("halı", response.json()["answer"])
            search.assert_not_called()

    def test_rerank_shortlist_includes_leading_single_branch_hits(self):
        self.retriever.settings = RetrievalSettings(rerank_top_k=4)
        chunk = self.chunks[0]
        self.retriever.chunks = [dict(chunk, doc=f"doc-{index}") for index in range(6)]
        candidates = [text_search.Document(page_content=str(index), metadata={"index": index}) for index in range(6)]
        state = {"candidates": candidates, "lexical_rank": [5], "vector_rank": [4], "question": "Q", "k": 2}
        with patch.object(text_search, "rerank_documents", side_effect=lambda question, docs: docs[::-1]) as rank:
            result = self.retriever._rerank(state)
        self.assertEqual(rank.call_args.args[1], [candidates[index] for index in (0, 1, 4, 5)])
        self.assertEqual(result["candidates"], [candidates[index] for index in (5, 4, 1, 0, 2, 3)])
        self.assertIn("policyholder", text_search.expand_query("sığortalı"))
        self.assertIn("policyholder", text_search.expand_query("sığortalının"))
        self.assertIn("beneficiary", text_search.expand_query("faydalananın"))
        self.assertIn("insurer", text_search.expand_query("страховщик"))
        self.assertNotIn("policyholder", text_search.expand_query("страховщик"))

    def test_expansion_does_not_replace_natural_language_embedding(self):
        self.embed.reset_mock()
        with patch.object(text_search, "rerank_documents", side_effect=lambda question, docs: docs):
            self.retriever.search("What are the insurer's obligations?")
        self.embed.assert_called_once_with(["What are the insurer's obligations?"], kind="query")

    def test_exact_article_lookup_does_not_use_embedding_or_prefix_match(self):
        self.embed.reset_mock()
        hits, score = self.retriever.search("What does Article 20.0.2 say?", filters={"insurance_type": "medical"})
        self.assertEqual(hits, [self.chunks[0]])
        self.assertEqual(score, 1.0)
        self.embed.assert_not_called()
        self.assertEqual(self.retriever.lookup_article("20", {"law": "999-IIIQ"}), self.chunks[:2])
        self.assertEqual(self.retriever.search("Article 99.1"), ([], 0.0))

    def test_multiple_articles_are_retrieved_fairly_and_missing_is_not_silently_ignored(self):
        hits, score = self.retriever.search("Compare Article 20.0.2 and Article 20.0.20")
        self.assertEqual([hit["metadata"]["clause"] for hit in hits[:2]], ["20.0.2", "20.0.20"])
        self.assertEqual(score, 1.0)
        self.assertEqual(self.retriever.search("Compare Article 20.0.2 and Article 99.1"), ([], 0.0))
        self.assertEqual(text_search.article_numbers("Compare articles 20.0.2 and 20.0.20"), ["20.0.2", "20.0.20"])
        self.assertEqual(text_search.article_numbers("Article 20.0.2 and 20.0.20"), ["20.0.2", "20.0.20"])

    def test_russian_article_query_uses_exact_lookup(self):
        self.embed.reset_mock()
        hits, score = self.retriever.search("Что означает статья 20.0.20?")
        self.assertEqual(hits, [self.chunks[1]])
        self.assertEqual(score, 1.0)
        self.embed.assert_not_called()

    def test_reranker_failure_falls_back_to_hybrid_order(self):
        with patch.object(text_search, "get_reranker", side_effect=RuntimeError("unavailable")):
            hits, score = self.retriever.search("insurance claim")
        self.assertEqual(len(hits), 3)
        self.assertGreater(score, 0)

    def test_search_limit_above_thirty_is_honored(self):
        chunks = [make_chunk(f"{index}.txt", str(index), None, f"document {index}", "medical", "Law")
                  for index in range(45)]
        vectors = np.tile(np.array([[1.0, 0.0]], dtype="float32"), (45, 1))
        with patch.object(text_search, "load_chunks", return_value=chunks), patch.object(
            text_search, "embed", side_effect=lambda texts, kind: vectors if kind == "passage" else vectors[:1]
        ), patch.object(text_search, "rerank_documents", side_effect=lambda question, docs: docs):
            retriever = text_search.TextRetriever()
            hits, _ = retriever.search("document", k=40)
        self.assertEqual(len(hits), 40)

    def test_hybrid_filters_before_ranking_and_score_uses_only_filtered_hits(self):
        with patch.object(text_search, "rerank_documents", side_effect=lambda question, docs: list(reversed(docs))) as rerank:
            hits, score = self.retriever.search("insurance claim", filters={"insurance_type": "medical", "law": "999-IIIQ"})
        self.assertEqual({hit["doc"] for hit in hits}, {"medical.pdf"})
        self.assertLess(score, 0.3)
        self.assertEqual(len(rerank.call_args.args[1]), 2)

    def test_bm25_can_add_candidate_outside_top_vector_results(self):
        chunks = [make_chunk(f"{index}.txt", str(index), None, f"document {index}", "medical", "Law")
                  for index in range(40)]
        vectors = np.tile(np.array([[1.0, 0.0]], dtype="float32"), (40, 1))
        with patch.object(text_search, "load_chunks", return_value=chunks), patch.object(
            text_search, "embed", side_effect=lambda texts, kind: vectors if kind == "passage" else vectors[:1]
        ), patch.object(text_search, "rerank_documents", side_effect=lambda question, docs: docs):
            retriever = text_search.TextRetriever(RetrievalSettings(vector_top_k=30))
            lexical = np.zeros(40)
            lexical[39] = 2.0
            retriever.bm25.get_scores = Mock(return_value=lexical)
            hits, _ = retriever.search("lexical match", k=30)
        self.assertIn(chunks[39], hits)

    def test_hybrid_branches_honor_independent_limits_and_similarity_threshold(self):
        self.retriever.settings = RetrievalSettings(bm25_top_k=1, vector_top_k=2, similarity_threshold=0.5)
        question = "insurance payout"
        with patch.object(text_search, "rerank_documents", side_effect=lambda question, docs: docs):
            result = self.retriever.graph.invoke({"question": question, "k": 3})
        self.assertEqual(result["lexical_rank"], [0])
        self.assertEqual(result["vector_rank"], [2])
        self.assertEqual(result["hits"], [self.chunks[0], self.chunks[2]])

    def test_vector_branch_finds_a_candidate_without_lexical_overlap(self):
        self.retriever.settings = RetrievalSettings(bm25_top_k=1, vector_top_k=1)
        question = "Mənə nə vaxt kömək edəcəklər?"
        result = self.retriever.graph.invoke({"question": question, "k": 1})
        self.assertEqual(result["lexical_rank"], [])
        self.assertEqual(result["vector_rank"], [2])
        self.assertEqual(result["hits"], [self.chunks[2]])
        self.embed.assert_called_with([question], kind="query")

    def test_retrieval_weights_change_fusion_order(self):
        self.retriever.settings = RetrievalSettings(bm25_weight=0.5, vector_weight=2)
        result = self.retriever._fuse({"lexical_rank": [0], "vector_rank": [2]})
        self.assertEqual([candidate.metadata["index"] for candidate in result["candidates"]], [2, 0])

    def test_rrf_uses_stable_ids_and_one_contribution_per_branch(self):
        self.retriever.chunks = [
            {"doc": "law.pdf", "text": "Provision", "metadata": {
                "document_id": "doc-a", "chunk_id": "chunk-1", "page_number": 7, "article": "20",
            }},
            {"doc": "law.pdf", "text": "Duplicate provision", "metadata": {
                "document_id": "doc-a", "chunk_id": "chunk-1", "page_number": 7,
            }},
            {"doc": "other.pdf", "text": "Independent provision", "metadata": {
                "document_id": "doc-b", "chunk_id": "chunk-1",
            }},
        ]
        with patch.dict(os.environ, {"RRF_K": "3"}):
            self.retriever.settings = RetrievalSettings.from_env()
        candidates = self.retriever._fuse({"lexical_rank": [0, 1, 2], "vector_rank": [2, 1]})["candidates"]
        self.assertEqual([candidate.metadata["index"] for candidate in candidates], [0, 2])
        self.assertAlmostEqual(candidates[0].metadata["rrf_score"], 1 / 4 + 1 / 5)
        self.assertAlmostEqual(candidates[1].metadata["rrf_score"], 1 / 6 + 1 / 4)
        self.assertEqual(candidates[0].metadata["page_number"], 7)
        self.assertEqual(candidates[0].metadata["article"], "20")
        self.assertEqual(candidates[0].metadata["document_id"], "doc-a")
        self.assertEqual(candidates[0].metadata["chunk_id"], "chunk-1")

    def test_bm25_recognizes_transliterated_inflected_and_translated_terms(self):
        for question in ("SIGORTA ODENISININ vaxtı", "sığorta ödənişinin vaxtı", "insurance payout"):
            with self.subTest(question=question):
                state = self.retriever._preprocess({"question": question})
                self.assertEqual(self.retriever._bm25({**state, "k": 5})["lexical_rank"][0], 0)

    def test_bm25_preserves_exact_legal_numbers_and_typed_amounts(self):
        chunks = [
            {"doc": "exact", "text": "Məsuliyyət limiti 5 000 manatdır. Tarif 2,50 faizdir.",
             "metadata": {"clause": "20.0.2", "law_number": "321-IIIQ"}},
            {"doc": "other", "text": "Məsuliyyət limiti 50 000 manatdır. Tarif 25 faizdir.",
             "metadata": {"clause": "20.0.20", "law_number": "322-IIIQ"}},
        ]
        index = text_search.RetrievalBM25.from_chunks(chunks)
        for question in ("limit 5000 AZN", "tarif 2.5%", "321–IIIQ", "20.0.2 şərti"):
            with self.subTest(question=question):
                tokens, _ = text_search.lexical_query(question)
                correct, other = index.get_scores(tokens)
                self.assertGreater(correct, other)
        self.assertNotIn("azn:50", index.doc_freqs[1])
        self.assertNotIn("article:20.0.2", index.doc_freqs[1])

    def test_qdrant_stores_source_payload_and_filters_semantic_candidates(self):
        from App.document_processing import process_document

        chunks = process_document("", "law.pdf", pages=[
            "Maddə 1. Müddəalar\n1.1. Birinci hissə.",
            "1.2. Article 1.1 applies.\nİkinci hissə.",
        ])["chunks"]
        vectors = np.array([[0.0, 1.0], [0.0, 1.0], [1.0, 0.0]], dtype="float32")
        with patch.object(text_search, "load_chunks", return_value=chunks), patch.object(
            text_search, "embed", return_value=vectors
        ):
            retriever = text_search.TextRetriever()
        self.addCleanup(retriever.close)
        index = retriever.vector_index
        self.assertEqual(index.search([1.0, 0.0], [0, 1, 2], 1), [(2, 1.0)])
        self.assertEqual(index.search([1.0, 0.0], [1], 1), [(1, 0.0)])
        payload = index.client.retrieve(index.collection, [index.point_ids[2]], with_payload=True)[0].payload
        self.assertEqual(payload["document_name"], "law.pdf")
        self.assertEqual(payload["document_id"], chunks[0]["metadata"]["document_id"])
        self.assertEqual(payload["document_type"], "pdf")
        self.assertEqual(payload["page_number"], 2)
        self.assertEqual(payload["article_number"], "1")
        self.assertEqual(payload["section_title"], "Müddəalar")
        self.assertEqual(payload["chunk_id"], index.point_ids[2])
        self.assertEqual(payload["original_text"], "1.2. Article 1.1 applies.\nİkinci hissə.")
        self.assertEqual(payload["references"][0]["target_chunk_id"], index.point_ids[1])
        self.assertEqual(payload["source_url"], "/documents/law.pdf/pdf#page=2")

    def test_qdrant_reuses_complete_persistent_collection(self):
        chunks = [{"doc": "law.txt", "text": "Qanun"}]
        encoder = Mock(return_value=np.array([[1.0, 0.0]], dtype="float32"))
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            vector_store, QDRANT_PATH=directory, QDRANT_URL=""
        ):
            first = vector_store.QdrantIndex(chunks, ["Qanun"], encoder, configuration=TEST_CONFIGURATION)
            first.close()
            reopened = vector_store.QdrantIndex(chunks, ["Qanun"], encoder, configuration=TEST_CONFIGURATION)
            try:
                self.assertEqual(reopened.collection, first.collection)
                self.assertEqual(reopened.search([1.0, 0.0], [0], 1), [(0, 1.0)])
            finally:
                reopened.close()
        encoder.assert_called_once_with(["Qanun"], kind="passage")

    def test_qdrant_reuses_passages_across_revisions_without_reusing_another_model(self):
        first = [{"doc": "a.txt", "text": "A"}, {"doc": "b.txt", "text": "B"}]
        revised = [{"doc": "b.txt", "text": "B"}, {"doc": "c.txt", "text": "C"},
                   {"doc": "copied.txt", "text": "C"}]
        encoder = Mock(side_effect=lambda texts, kind: np.tile([[1.0, 0.0]], (len(texts), 1)).astype("float32"))
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            vector_store, QDRANT_PATH=directory, QDRANT_URL=""
        ):
            original = vector_store.QdrantIndex(first, ["A", "B"], encoder, configuration=TEST_CONFIGURATION)
            original.close()
            index = vector_store.QdrantIndex(revised, ["B", "C", "C"], encoder, configuration=TEST_CONFIGURATION)
            try:
                self.assertNotEqual(index.collection, original.collection)
                self.assertEqual(index.client.count(index.collection).count, 3)
                self.assertEqual(len(index.search([1.0, 0.0], [0, 1, 2], 3)), 3)
            finally:
                index.close()
            other = vector_store.QdrantIndex(revised, ["B", "C", "C"], encoder,
                                             configuration=dict(TEST_CONFIGURATION, model_repository="second-model"))
            other.close()
        self.assertEqual([call.args[0] for call in encoder.call_args_list], [["A", "B"], ["C"], ["B", "C"]])

    def test_qdrant_resumes_partial_collection_after_interrupted_upload(self):
        chunks = [{"doc": "a.txt", "text": "A"}, {"doc": "b.txt", "text": "B"}]
        encoder = Mock(side_effect=lambda texts, kind: np.tile([[1.0, 0.0]], (len(texts), 1)).astype("float32"))
        original_upsert = vector_store.QdrantClient.upsert
        writes = []

        def interrupt_second_upload(client, collection, points, **kwargs):
            writes.append(points[0].id)
            if len(writes) == 2:
                raise RuntimeError("interrupted upload")
            return original_upsert(client, collection, points, **kwargs)

        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            vector_store, QDRANT_PATH=directory, QDRANT_URL="", BATCH_SIZE=1
        ):
            with patch.object(vector_store.QdrantClient, "upsert", interrupt_second_upload):
                with self.assertRaisesRegex(RuntimeError, "interrupted upload"):
                    vector_store.QdrantIndex(chunks, ["A", "B"], encoder, configuration=TEST_CONFIGURATION)
            resumed = vector_store.QdrantIndex(chunks, ["A", "B"], encoder, configuration=TEST_CONFIGURATION)
            try:
                self.assertEqual(resumed.client.count(resumed.collection).count, 2)
            finally:
                resumed.close()
        self.assertEqual([call.args[0] for call in encoder.call_args_list], [["A", "B"], ["B"]])

    def test_qdrant_fingerprints_configuration_and_keeps_previous_collections(self):
        chunks = [{"doc": "law.txt", "text": "A"}]
        config = {**TEST_CONFIGURATION, "model_revision": "model-a", "tokenizer_revision": "tokenizer-a",
                  "max_input_tokens": 512, "prefixes": {"query": "query: ", "passage": "passage: "},
                  "encoding": {"normalize": True, "precision": "float32"}}
        variants = (
            dict(config, model_revision="model-b"),
            dict(config, tokenizer_revision="tokenizer-b"),
            dict(config, dimensions=3),
            dict(config, encoding={"normalize": False, "precision": "float32"}),
            dict(config, max_input_tokens=480),
            dict(config, prefixes={"query": "query: ", "passage": "document: "}),
        )
        encoder = Mock(return_value=np.array([[1.0, 0.0]], dtype="float32"))
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            vector_store, QDRANT_PATH=directory, QDRANT_URL=""
        ):
            initial = vector_store.QdrantIndex(chunks, ["A"], encoder, configuration=config)
            initial.close()
            reordered = dict(reversed(list(config.items())))
            same = vector_store.QdrantIndex(chunks, ["A"], encoder, configuration=reordered)
            self.assertEqual(same.collection, initial.collection)
            same.close()
            for variant in variants:
                with self.subTest(variant=variant):
                    encoder.return_value = np.asarray([[1.0] + [0.0] * (variant["dimensions"] - 1)], dtype="float32")
                    new = vector_store.QdrantIndex(chunks, ["A"], encoder, configuration=variant)
                    try:
                        self.assertNotEqual(new.collection, initial.collection)
                        self.assertNotEqual(new.embedding_fingerprint, initial.embedding_fingerprint)
                        self.assertTrue(new.client.collection_exists(initial.collection))
                        meta = new.client.get_collection(new.collection).config.metadata
                        self.assertEqual(meta["embedding_fingerprint"], new.embedding_fingerprint)
                        self.assertEqual(meta["embedding_configuration"], variant)
                    finally:
                        new.close()
            with self.assertRaisesRegex(ValueError, "invalid vectors"):
                vector_store.QdrantIndex(chunks, ["A"], Mock(return_value=[[1.0]]),
                                         configuration=dict(config, model_revision="invalid-model"))
            old = vector_store.QdrantIndex(chunks, ["A"], encoder, configuration=config)
            try:
                self.assertEqual(old.search([1.0, 0.0], [0], 1), [(0, 1.0)])
            finally:
                old.close()
        self.assertEqual(encoder.call_count, 1 + len(variants))

    def test_contextual_terminology_keeps_legal_concepts_distinct(self):
        cases = {
            "Sığorta pulu nə qədərdir?": set(),
            "Sığorta pulunu nə qədər ödəməliyəm?": {"premium"},
            "Sığorta pulunu nə vaxt alacağam?": {"payout"},
            "Sığorta pulunu əvvəl ödəyəcəyəm, sonra nə vaxt alacağam?": set(),
            "Ödəyəcəyim pul sığorta üçün nə qədərdir?": {"premium"},
            "Zərərimin ödənilməsi üçün sığortaya müraciət etməliyəm?": {"payout"},
            "Ödəniş limiti nədir?": set(),
            "Ödəniş limiti əmlakın dəyərinə bağlıdır?": {"sum_insured"},
            "Üçüncü şəxs üçün ödəniş limiti nədir?": {"liability_limit"},
            "Maşının sığortası": {"motor_insurance"},
            "Maaş və əmək müqaviləsi": {"wages"},
            "Maaş və digər gəlirlər": {"income"},
            "Maaş": set(),
            "Daşınmaz əmlakın sığortası": {"real_estate"},
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(TERMINOLOGY.query_concepts(question), expected)
        self.assertEqual(TERMINOLOGY.direct_concepts("Sığorta pulunu nə vaxt alacağam?"), set())

    def test_contextual_candidate_reaches_bm25_without_rewriting_semantic_query(self):
        question = "Sığorta pulunu nə vaxt alacağam?"
        with patch.object(text_search, "rerank_documents", side_effect=lambda question, documents: documents):
            hits, _ = self.retriever.search(question, k=1)
        self.assertEqual(hits, self.chunks[:1])
        self.embed.assert_called_with([question], kind="query")

    def test_salary_calculation_expansion_preserves_conditions_and_amounts(self):
        question = "2026-cı ildə maaşım 8 500,50 manatdırsa, haqq hesablanmasında həddin təsiri nədir?"
        expanded = text_search.expand_query(question)
        self.assertTrue(expanded.startswith(question + " "))
        for term in ("əməkhaqqı", "sığorta haqqı", "hesablanma qaydası", "tarif", "hədd", "sığorta məbləği"):
            self.assertIn(term, expanded)
        self.assertNotIn("tibbi sığorta", expanded)
        self.assertNotIn("sığorta ödənişi", expanded)
        self.assertEqual(main.classify_intent_rule(question), "insurance_question")

    def test_ambiguous_query_keeps_both_interpretations_after_reranking(self):
        question = "Sığorta pulu nə qədərdir?"
        chunks = [{"doc": f"premium-{index}", "text": "Sığorta haqqı."} for index in range(32)]
        chunks.append({"doc": "payout", "text": "Sığorta ödənişi."})
        vectors = np.tile(np.array([[1.0, 0.0]], dtype="float32"), (len(chunks), 1))
        with patch.object(text_search, "load_chunks", return_value=chunks), patch.object(
            text_search, "embed", side_effect=lambda texts, kind: vectors[:len(texts)]
        ), patch.object(
            text_search, "rerank_documents",
            side_effect=lambda question, docs: sorted(docs, key=lambda doc: doc.metadata["index"]),
        ):
            hits, _ = text_search.TextRetriever().search(question, k=2)
        self.assertEqual([hit["doc"] for hit in hits], ["premium-0", "payout"])

    def test_terminology_can_load_a_new_concept_from_configuration(self):
        path = Mock()
        path.read_text.return_value = """{
          "concepts": {"renewal": {"aliases": ["müqavilənin yenilənməsi"]}},
          "expressions": [{"phrases": ["müqaviləni uzatmaq"], "candidates": {"renewal": []}}]
        }"""
        dictionary = InsuranceTerminology(path)
        self.assertEqual(dictionary.query_concepts("Müqaviləni uzatmaq"), {"renewal"})
        self.assertEqual(dictionary.direct_concepts("Müqaviləni uzatmaq"), set())
        self.assertEqual(dictionary.direct_concepts("Müqavilənin yenilənməsi"), {"renewal"})

    def test_azerbaijani_nominal_lemmas_preserve_case_distinctions_and_unknown_words(self):
        self.assertEqual(normalize_az("Ə I İ Ö Ü Ğ Ş Ç I\u0307"), "ə ı i ö ü ğ ş ç i")
        for word, expected in {
            "hesablanmasında": "hesablanma", "hesablanması": "hesablanma",
            "SIĞORTANIN": "sığorta", "ödənişlərdən": "ödəniş", "həddin": "hədd",
            "tariflərə": "tarif", "sığortalarımızdan": "sığorta", "öhdəliyimizə": "öhdəlik",
            "sığortalının": "sığortalı", "sığortaçının": "sığortaçı",
            "qaranlıqdan": "qaranlıqdan", "kitaplardan": "kitaplardan",
        }.items():
            with self.subTest(word=word):
                self.assertEqual(LEMMATIZER.lemmatize(word), expected)

    def test_bm25_matches_nominal_forms_in_both_directions_and_preserves_semantic_query(self):
        for surface, lemma in (
            ("hesablanmasında", "hesablama"), ("hesablanması", "hesablama"),
            ("sığortanın", "sığorta"), ("ödənişlərdən", "ödəniş"),
            ("həddin", "hədd"), ("tariflərə", "tarif"),
        ):
            for question, passage in ((surface, lemma), (lemma, surface)):
                with self.subTest(question=question, passage=passage):
                    chunks = [{"doc": "match", "text": passage}, {"doc": "other", "text": "başqa mövzu"}]
                    vectors = np.array([[0.0, 1.0], [1.0, 0.0]], dtype="float32")
                    with patch.object(text_search, "load_chunks", return_value=chunks), patch.object(
                        text_search, "embed", side_effect=[vectors, vectors[1:]]
                    ) as embed_mock, patch.object(text_search, "rerank_documents", side_effect=lambda question, docs: docs):
                        hits, _ = text_search.TextRetriever().search(question, k=1)
                    self.assertEqual(hits, chunks[:1])
                    self.assertEqual(embed_mock.call_args.args, ([question],))

    def test_ask_passes_lexical_evidence_to_generation_below_cosine_threshold(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(retriever=self.retriever)))
        with patch.object(text_search, "rerank_documents", side_effect=lambda question, docs: docs), patch.object(
            main, "answer_question", return_value="Cavab [S1]"
        ) as generate:
            response = main.ask(main.Question(question="sığorta ödənişinin vaxtı",
                                              filters=main.SearchFilters(insurance_type="medical")), request)
        self.assertEqual(response["sources"][0]["doc"], "medical.pdf")
        self.assertEqual(generate.call_args.args[1][0], self.chunks[0])

    def test_filter_applies_before_candidate_cutoff(self):
        chunks = [make_chunk(f"{index}.txt", str(index), None, f"document {index}",
                             "medical" if index == 39 else "social", "Law") for index in range(40)]
        vectors = np.array([[1.0, 0.0]] * 39 + [[0.1, 0.0]], dtype="float32")
        with patch.object(text_search, "load_chunks", return_value=chunks), patch.object(
            text_search, "embed", side_effect=lambda texts, kind: vectors if kind == "passage" else vectors[:1]
        ):
            retriever = text_search.TextRetriever()
            hits, score = retriever.search("document", filters={"insurance_type": "medical"})
        self.assertEqual(hits, [chunks[39]])
        self.assertAlmostEqual(score, 0.1)

    def test_topic_and_law_filters(self):
        filters = {"insurance_type": "medical", "law": "TİBBİ", "topic": "exclusion"}
        hits, _ = self.retriever.search("Article 20.0.2", filters=filters)
        self.assertEqual(hits, [self.chunks[0]])
        self.assertEqual(self.retriever.search("Article 20.0.2", filters={"topic": "tariff"})[0], [self.chunks[2]])
        self.assertEqual(self.retriever.search("Article 20.0.2", filters={"topic": "deadline"})[0], [])

    def test_reranker_controls_final_order(self):
        question = "What are the exclusions?"
        with patch.object(text_search, "get_reranker") as get_reranker:
            get_reranker.return_value.predict.return_value = [0.1, 0.9, 0.3]
            hits, _ = self.retriever.search(f"insurance claim {question}", original_question=question)
        pairs = get_reranker.return_value.predict.call_args.args[0]
        self.assertTrue(pairs[1][1].endswith(hits[0]["text"]))
        self.assertTrue(all(used == f"insurance claim {question}" for used, _ in pairs))
        self.assertIn(f"Bənd: {hits[0]['metadata']['clause']}", pairs[1][1])
        self.assertIn(f"Hüquqi sənəd: {hits[0]['metadata']['law_name']}", pairs[1][1])
        self.assertIs(hits[0], next(chunk for chunk in self.chunks if chunk["text"] == hits[0]["text"]))

    def test_lookup_and_search_endpoints(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(retriever=self.retriever)))
        result = main.search_documents(main.SearchRequest(question="Article 20.0.2", filters=main.SearchFilters(law="999-IIIQ")), request)
        self.assertEqual(result["match_type"], "article")
        self.assertIsNone(result["score"])
        self.assertEqual(result["hits"], [self.chunks[0]])
        self.assertEqual(main.get_article("20.0.2", request, law="999-IIIQ")["hits"], [self.chunks[0]])
        with self.assertRaises(HTTPException) as error:
            main.get_article("bad", request)
        self.assertEqual(error.exception.status_code, 422)

    def test_http_search_and_article_routes(self):
        with patch.object(main.app.state, "retriever", self.retriever, create=True):
            client = TestClient(main.app)
            response = client.post("/search", json={"question": "Article 20.0.2", "filters": {"law": "999-IIIQ"}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["hits"], [self.chunks[0]])
            self.assertEqual(client.get("/articles/99.1").status_code, 404)
            self.assertEqual(client.get("/articles/bad").status_code, 422)
            self.assertEqual(client.post("/search", json={"question": "insurance", "filters": {"topic": "unknown"}}).status_code, 422)

    def test_graph_receives_optional_trace_configuration(self):
        with patch.object(text_search, "tracing_config", return_value={"tags": ["test"]}):
            with patch.object(self.retriever.graph, "invoke", wraps=self.retriever.graph.invoke) as invoke:
                self.retriever.search("Article 20.0.2")
        self.assertEqual(invoke.call_args.kwargs["config"], {"tags": ["test"]})

    def test_tracing_is_disabled_by_default_and_without_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(observability.tracing_config(), {})
        with patch.dict(os.environ, {"LANGFUSE_TRACING_ENABLED": "true"}, clear=True):
            self.assertEqual(observability.tracing_config(), {})

    def test_langfuse_exports_metadata_without_raw_callbacks(self):
        client = Mock()
        fake_module = SimpleNamespace(get_client=Mock(return_value=client))
        environment = {"LANGFUSE_TRACING_ENABLED": "true", "LANGFUSE_PUBLIC_KEY": "public", "LANGFUSE_SECRET_KEY": "secret"}
        with patch.dict(os.environ, environment, clear=True), patch.dict(sys.modules, {"langfuse": fake_module}):
            self.assertEqual(observability.tracing_config(), {})
            observability.export_trace({"route": "ask", "request_id": "test", "stages": [{"stage": "bm25", "latency_ms": 2}]})
        client.start_observation.assert_called_once_with(name="ask", metadata={"route": "ask", "request_id": "test"})


if __name__ == "__main__":
    unittest.main()
