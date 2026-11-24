import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from App import embedding, text_search, vector_store
from App.settings import RetrievalSettings


class WordTokenizer:
    model_max_length = 32
    truncation_side = "right"

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(self, texts, *, add_special_tokens, return_offsets_mapping=False, **kwargs):
        if return_offsets_mapping:
            return {"offset_mapping": [match.span() for match in re.finditer(r"\S+", texts)]}
        return {"length": [len(text.split()) + (2 if add_special_tokens else 0) for text in texts]}


class EmbeddingChunkTests(unittest.TestCase):
    def setUp(self):
        self.model = SimpleNamespace(max_seq_length=36, tokenizer=WordTokenizer(), encode=Mock())
        for patcher in (
            patch.object(embedding, "get_model", return_value=self.model),
            patch.object(embedding, "EMBED_MODEL", "intfloat/multilingual-e5-large"),
            patch.object(embedding, "EMBED_TARGET_TOKENS", 0),
            patch.object(embedding, "EMBED_OVERLAP_TOKENS", 5),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.exception = "İstisna: ödəniş 5000 manat həddini keçmir."
        self.parent = {
            "doc": "law.pdf",
            "text": " ".join(["Sığorta müqaviləsi qüvvədə qalır."] * 9 + [self.exception]),
            "metadata": {"article": "13", "article_title": "Sığorta ödənişi", "page_number": 7},
        }
        self.text = text_search.searchable_text(self.parent)

    def test_planner_covers_complete_parent_and_logs_omitted_exception(self):
        with self.assertLogs(embedding.log, "WARNING") as messages:
            parts, = embedding.plan_passages([self.parent], [self.text])
        self.assertIn("exception", messages.output[0])
        self.assertIn("legacy_embedded_tokens=32", messages.output[0])
        event, = messages.records
        self.assertEqual(event.event, "oversized_passage")
        self.assertEqual(event.source_page, 7)
        self.assertGreater(event.original_tokens, event.legacy_embedded_tokens)
        self.assertIn("exception", event.omitted_legal_signals)
        self.assertGreater(len(parts), 1)
        self.assertEqual(parts[0].start, 0)
        self.assertEqual(parts[-1].end, len(self.parent["text"]))
        self.assertTrue(any(b.start < a.end for a, b in zip(parts, parts[1:])))
        for left, right in zip(parts, parts[1:]):
            self.assertLessEqual(right.start, left.end)
            self.assertGreater(right.end, left.end)
        self.assertTrue(all(part.embedded_tokens <= 32 for part in parts))
        self.assertTrue(all(part.text.startswith("Sığorta ödənişi\n") for part in parts))
        self.assertIn(self.exception, parts[-1].text)

    def test_encoder_refuses_unplanned_truncation(self):
        with self.assertRaisesRegex(ValueError, "exceeds the model token limit"):
            embedding.embed([self.text])
        self.model.encode.assert_not_called()
        parts, = embedding.plan_passages([self.parent], [self.text])
        self.model.encode.return_value = np.ones((len(parts), 2))
        embedding.embed([part.text for part in parts])
        inputs, = self.model.encode.call_args.args
        self.assertTrue(all(text.startswith("passage: ") for text in inputs))
        self.assertTrue(all(count <= 32 for count in embedding.token_counts(self.model, inputs)))
        self.assertIn(self.exception, inputs[-1])

    def test_child_hit_returns_complete_parent_and_preserves_source_metadata(self):
        other = {"doc": "other.txt", "text": "Başqa qayda."}
        chunks = [other, self.parent]

        def encode(texts, kind):
            return np.asarray([[1, 0] if "5000" in text else [0.1, 0.99] for text in texts], dtype=np.float32)

        settings = RetrievalSettings(bm25_weight=0)
        with patch.multiple(vector_store, QDRANT_URL="", QDRANT_PATH=""), patch.multiple(
            text_search, load_chunks=Mock(return_value=chunks), embed=encode,
            embedding_configuration=Mock(return_value={"model_repository": "test", "dimensions": 2}),
        ), patch.object(text_search, "get_reranker") as get_reranker:
            get_reranker.return_value.predict.side_effect = lambda pairs: [
                float(self.exception in passage) for _, passage in pairs
            ]
            retriever = text_search.TextRetriever(settings)
            self.addCleanup(retriever.close)
            hits, score = retriever.search("5000 manat istisnası", k=2)
        self.assertEqual(len(hits), 2)
        self.assertIs(hits[0], self.parent)
        self.assertEqual(score, 1.0)
        pairs, = get_reranker.return_value.predict.call_args.args
        self.assertTrue(any(self.parent["text"] in passage for _, passage in pairs))
        index = retriever.vector_index
        records = index.client.retrieve(index.collection, index.ids_by_parent[1], with_payload=True)
        self.assertTrue(any(record.id == index.point_ids[1] and record.payload["text"] == self.parent["text"]
                            for record in records))
        tail = max((record.payload for record in records), key=lambda item: item["child_ordinal"])
        self.assertEqual(tail["parent_chunk_id"], index.point_ids[1])
        self.assertEqual(tail["text"], self.parent["text"])
        self.assertEqual(tail["article_number"], "13")
        self.assertEqual(tail["section_title"], "Sığorta ödənişi")
        self.assertEqual(tail["page_number"], 7)
        self.assertIn(self.exception, tail["text"][tail["child_start"]:tail["child_end"]])
        self.assertIn(self.exception, tail["embedding_text"])
        self.assertEqual(index.search([1, 0], [1], 2, exact=True), [(1, 1.0)])
