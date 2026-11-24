import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from App import main, query_plan, query_resolution, system


MULTI = ("İş qəzası zamanı sığorta ödənişi necə hesablanır, hansı sənədlər tələb olunur "
         "və hansı hallarda ödənişdən imtina edilə bilər?")


def make_plan(text, history=()):
    return query_plan.plan_query(query_resolution.resolve_query(text, list(history)), "az")


def hit(identifier):
    return {"doc": "source.pdf", "text": f"Evidence {identifier}", "metadata": {"chunk_id": identifier}}


class QueryPlanTests(unittest.TestCase):
    def test_unscoped_compulsory_coverage_requests_clarification(self):
        question = "İcbari sığorta nəyi əhatə edir?"
        retriever = Mock(spec=["search"])
        with patch.object(main.app.state, "retriever", retriever, create=True):
            response = TestClient(main.app).post("/ask", json={"question": question})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "clarification")
        self.assertEqual(response.json()["sources"], [])
        retriever.search.assert_not_called()
        self.assertEqual(make_plan("İcbari tibbi sığorta nəyi əhatə edir?").intent, "insurance_question")

    def test_intent_routes(self):
        cases = {
            "salam": "greeting", "Necəsən?": "general_conversation", "Sığorta ödənişi necə hesablanır?": "insurance_question",
            "Sığorta qanunu nə deyir?": "legal_question", MULTI: "multi_part_question", "Bəs bu halda?": "ambiguous_question",
            "Sabah hava necə olacaq?": "out_of_scope",
        }
        for question, intent in cases.items():
            with self.subTest(question=question):
                self.assertEqual(make_plan(question).intent, intent)

    def test_followups_share_resolution(self):
        previous = "İcbari sığortada gecikmə olduqda ödəniş müddəti hansı hallarda dəyişir?"
        cases = {"Bəs bu halda?": "şərtlər", "Bəs istisnalar necə?": "istisnalar", "Bu müddət nə qədərdir?": "müddət",
                 "Digər hallarda necə olur?": "digər hallarda", "Bes istisnalar nece?": "istisnalar"}
        for text, word in cases.items():
            with self.subTest(text=text):
                plan = make_plan(text, (previous,))
                resolved = plan.resolution
                self.assertEqual(plan.intent, "follow_up_question")
                self.assertIn(word, resolved.standalone)
                self.assertEqual((resolved.bm25_query, resolved.dense_query, resolved.rerank_query), (resolved.standalone,) * 3)
                self.assertEqual(resolved.history, (previous,))
                self.assertEqual(resolved.original, text)
        plan = make_plan("Bəs sağlamlıq məlumatları?", ("Şəxsi məlumatlarım sığorta şirkətində necə qorunur?",))
        self.assertIn("sağlamlıq məlumatları", plan.resolution.normalized)
        switched = make_plan("Bəs təkrarsığorta necə işləyir?", (previous,))
        self.assertEqual(switched.resolution.context, ())
        self.assertNotIn("İcbari", switched.resolution.standalone)

    def test_decomposition_keeps_dependent_request_intact(self):
        plan = make_plan(MULTI)
        self.assertEqual(len(plan.parts), 3)
        self.assertTrue(all(part.question.startswith("İş qəzası") for part in plan.parts))
        coupled = "Ödəniş necə hesablanır və hansı sənədlər tələb olunur, əgər hadisə iş yerində olubsa?"
        self.assertEqual(query_plan.decompose(coupled), (coupled,))

    def test_short_second_question_reaches_retrieval(self):
        prior = "What does compulsory medical insurance cover?"
        question = "What are the exceptions?"
        retriever = Mock(spec=["search", "documents"])
        retriever.search.return_value = ([], 0.0)
        with patch.object(main.app.state, "retriever", retriever, create=True):
            response = TestClient(main.app).post("/ask", json={"question": question, "history": [prior]})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json().get("intent"), "out_of_scope")
        resolution = retriever.search.call_args.args[0]
        self.assertEqual(resolution.context, (prior,))
        self.assertIn("medical insurance", resolution.standalone)

    def test_short_followups_require_an_insurance_anchor(self):
        prior = "İcbari tibbi sığorta nəyi əhatə edir?"
        question = "İstisnalar hansılardır?"
        plan = make_plan(question, (prior, "Hansı sənədlər lazımdır?"))
        self.assertEqual(plan.intent, "follow_up_question")
        self.assertEqual(plan.resolution.context, (prior,))
        self.assertEqual(make_plan(question).intent, "ambiguous_question")
        self.assertEqual(make_plan(question, (prior, "Sabah hava necə olacaq?")).intent, "ambiguous_question")
        self.assertEqual(make_plan("Sabah hava necə olacaq?", (prior,)).intent, "out_of_scope")

    def test_merge_deduplicates_and_keeps_subquestion_attribution(self):
        shared = hit("shared")
        retriever = Mock(spec=["search"])
        retriever.search.side_effect = [([hit(str(i)), shared], 0.8) for i in range(3)]
        hits, _, associations, parts = query_plan.retrieve_plan(retriever, make_plan(MULTI), k=5, filters={},
                                                               decompose_parts=True, routing=False)
        self.assertEqual(len(hits), 4)
        self.assertEqual(associations[query_plan.passage_key(shared)], {"Q1", "Q2", "Q3"})
        self.assertEqual([call.args[0].standalone for call in retriever.search.call_args_list], [part.question for part in parts])

    def test_route_keeps_broad_candidate_and_respects_explicit_filter(self):
        broad = hit("broad")
        routed = hit("routed")
        retriever = Mock(spec=["search"])
        retriever.search.side_effect = [([broad], 0.8), ([routed], 0.7)]
        plan = make_plan("İş qəzası zamanı sığorta ödənişi necə hesablanır?")
        hits, _, _, _ = query_plan.retrieve_plan(retriever, plan, k=2, filters={"law": "rule"}, routing=True)
        self.assertEqual(hits, [broad, routed])
        self.assertEqual(retriever.search.call_args_list[0].kwargs["filters"], {"law": "rule"})
        self.assertEqual(retriever.search.call_args_list[1].kwargs["filters"], {"law": "rule", "insurance_type": "occupational"})
        self.assertGreater(query_plan.route_query(plan.resolution.standalone).confidence, 0.8)

    def test_generated_variants_are_bounded_and_do_not_change_topics_or_numbers(self):
        question = "Sığorta ödənişi 5 günə verilir?"
        response = SimpleNamespace(text='{"alternatives":["SIĞORTA ÖDƏNİŞİ 5 GÜNƏ VERİLİR?", '
                                        '"Sığorta ödənişi 6 günə verilir?", "Sığorta ödənişi üçün 5 günlük müddət"], '
                                        '"hypothetical":"KASKO ödəniş müddəti 5 gün"}')
        with patch.object(query_plan, "API_KEY", "test"), patch.object(query_plan, "ChatOpenRouter") as model:
            model.return_value.invoke.return_value = response
            self.assertEqual(query_plan.generated_queries(question, alternatives=True, hyde=True),
                             query_plan.GeneratedQueries(("Sığorta ödənişi üçün 5 günlük müddət",)))
            model.return_value.invoke.assert_called_once()

    def test_hypothesis_only_changes_dense_input_and_never_becomes_evidence(self):
        retriever = Mock(spec=["search"])
        source = hit("actual")
        retriever.search.return_value = ([source], 0.8)
        question = "Sığorta ödənişi nə vaxt edilir?"
        hypothesis = "Sığorta ödənişinin müddətini göstərən hüquqi bənd."
        with patch.object(query_plan, "generated_queries", return_value=query_plan.GeneratedQueries(hypothesis=hypothesis)):
            hits, _, _, _ = query_plan.retrieve_plan(retriever, make_plan(question), k=2, filters={}, hyde=True)
        self.assertEqual(hits, [source])
        original, expanded = [call.args[0] for call in retriever.search.call_args_list]
        self.assertEqual(original.dense_query, question)
        self.assertEqual(expanded.dense_query, hypothesis)
        self.assertEqual(expanded.bm25_query, question)
        self.assertEqual(expanded.rerank_query, question)

    def test_multipart_generation_requires_citation_for_each_part(self):
        hits = [hit("1"), hit("2")]
        options = {"required_parts": {"Q1", "Q2"}, "source_parts": [{"Q1"}, {"Q2"}]}
        self.assertIsNone(system.validate_generated_answer("Q1. Cavab [S1]", hits, {0, 1}, **options))
        self.assertIsNone(system.validate_generated_answer("Q1. Cavab [S1]\nQ2. Cavab [S1]", hits, {0, 1}, **options))
        self.assertEqual(system.validate_generated_answer("Q1. Cavab [S1]\nQ2. Cavab [S2]", hits, {0, 1}, **options),
                         "1. Cavab [S1]\n2. Cavab [S2]")

    def test_ask_multipart_retains_api_shape_and_original_question(self):
        retriever = Mock(spec=["search", "documents"])
        chunks = [hit(str(i)) for i in range(3)]
        retriever.documents = [{"doc": "source.pdf", "chunks": chunks}]
        retriever.search.side_effect = [([chunk], 0.7) for chunk in chunks]
        with patch.object(main.app.state, "retriever", retriever, create=True), patch.object(main, "QUERY_DECOMPOSITION", True), \
                patch.object(main, "answer_question", return_value="1. Cavab [S1]\n2. Cavab [S2]\n3. Cavab [S3]") as answer:
            response = TestClient(main.app).post("/ask", json={"question": MULTI})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([source["url"] for source in response.json()["sources"]],
                         [f"/documents/source.pdf/preview/{i}" for i in range(3)])
        self.assertEqual(answer.call_args.args[0], MULTI)
        self.assertEqual(answer.call_args.kwargs["source_parts"], [{"Q1"}, {"Q2"}, {"Q3"}])

    def test_conversation_needs_no_retriever(self):
        response = TestClient(main.app).post("/ask", json={"question": "Necəsən?"})
        self.assertEqual(response.json()["intent"], "general_conversation")
        self.assertEqual(response.json()["sources"], [])
