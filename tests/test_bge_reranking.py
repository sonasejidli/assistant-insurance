import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from App import rerank, text_search
from evaluation.evaluate_bge_reranking import split_cases


class PairTokenizer:
    model_max_length = 36

    def __call__(self, queries, passages, **kwargs):
        self.options = kwargs
        return {"length": [len(q.split()) + len(p.split()) + 4 for q, p in zip(queries, passages, strict=True)]}


class BGERerankingTests(unittest.TestCase):
    def test_validation_and_heldout_do_not_share_labeled_parents(self):
        groups = (["p1"], ["p1", "p2"], ["p2"], ["p3"], ["p4"], [])
        cases = [{"id": str(i), "relevant_parent_passage_ids": parents} for i, parents in enumerate(groups)]
        validation, heldout = split_cases(cases)
        left = {parent for case in validation for parent in case["relevant_parent_passage_ids"]}
        right = {parent for case in heldout for parent in case["relevant_parent_passage_ids"]}
        self.assertFalse(left & right)
        self.assertEqual(sorted(case["id"] for case in validation + heldout), [str(i) for i in range(6)])

    def test_explicit_model_and_device_reach_cross_encoder(self):
        text_search.get_reranker.cache_clear()
        self.addCleanup(text_search.get_reranker.cache_clear)
        with patch.multiple(text_search, RERANK_MODEL="test/revision", RERANK_DEVICE="cuda:0"), patch.object(
            text_search, "CrossEncoder",
        ) as loader:
            self.assertIs(text_search.get_reranker(), loader.return_value)
            self.assertIs(text_search.get_reranker(), loader.return_value)
        loader.assert_called_once_with("test/revision", device="cuda:0")

    def test_bounded_bge_scores_late_exception_and_returns_original_parent(self):
        exception = "İstisna: ödəniş 5000 manat həddinədək verilir."
        parent = text_search.Document(page_content="Sığorta müqaviləsi qüvvədə qalır. " * 20 + exception,
                                      metadata={"chunk_id": "complete-parent", "clause": "20.3", "doc": "law.pdf"})
        other = text_search.Document(page_content="Ümumi sığorta qaydası.", metadata={"chunk_id": "other"})
        tokenizer = PairTokenizer()
        model = SimpleNamespace(tokenizer=tokenizer, max_seq_length=34, predict=Mock(
            side_effect=lambda pairs, **kwargs: [1 if exception in passage else 0 for _, passage in pairs],
        ))
        question = "Sığorta ödənişinin istisnası nədir?"
        with patch.object(text_search, "get_reranker", return_value=model), patch.multiple(
            text_search, RERANK_MODE="bge_safe", RERANK_BATCH_SIZE=3, RERANK_MAX_TOKENS=40,
        ):
            ranked = text_search.rank_with_cross_encoder(question, [other, parent])
        self.assertIs(ranked[0], parent)
        self.assertEqual(ranked[0].metadata["chunk_id"], "complete-parent")
        self.assertTrue(ranked[0].page_content.endswith(exception))
        (pairs,), options = model.predict.call_args
        self.assertEqual(options, {"batch_size": 3, "show_progress_bar": False})
        self.assertTrue(all(query == question for query, _ in pairs))
        self.assertTrue(any(exception in passage and "Bənd: 20.3" in passage for _, passage in pairs))
        self.assertTrue(all(length <= 34 for length in rerank.pair_lengths(tokenizer, pairs)))
        self.assertFalse(tokenizer.options["truncation"])

    def test_bge_refuses_impossible_pair_instead_of_truncating_query(self):
        model = SimpleNamespace(tokenizer=PairTokenizer(), max_seq_length=34, predict=Mock())
        document = text_search.Document(page_content="Sığorta qaydası")
        with self.assertRaisesRegex(ValueError, "full query"):
            rerank.bge_scores(model, "sığorta " * 40, [document], text_search.reranker_passage,
                              max_tokens=32, batch_size=8)
        model.predict.assert_not_called()
