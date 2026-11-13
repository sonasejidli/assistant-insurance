import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from fastapi import HTTPException

from App import main, system, text_search


class TextApplicationTests(unittest.TestCase):
    def test_loads_text_files_without_inventing_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "policy.txt").write_text("First paragraph.\n\nSecond paragraph.", encoding="utf-8")
            chunks = text_search.load_chunks(Path(directory))
        self.assertEqual(chunks, [
            {"text": "First paragraph.", "doc": "policy.txt"},
            {"text": "Second paragraph.", "doc": "policy.txt"},
        ])

    def test_search_returns_text_document(self):
        chunks = [{"text": "Subrogation is a right of recovery.", "doc": "policy.txt"}]
        with patch.object(text_search, "load_chunks", return_value=chunks), patch.object(
            text_search, "embed", return_value=np.array([[1.0, 0.0]], dtype="float32")
        ):
            retriever = text_search.TextRetriever()
            hits, score = retriever.search("What is subrogation?")
        self.assertEqual(hits, chunks)
        self.assertEqual(score, 1.0)

    def test_english_prompt_uses_document_context(self):
        model = Mock()
        model.invoke.return_value = SimpleNamespace(text="Answer in English")
        with patch.object(system, "API_KEY", "test-key"), patch.object(system, "LLM_MODEL", "test-model"), patch.object(
            system, "ChatOpenRouter", return_value=model
        ):
            answer = system.answer_question("Question?", [{"text": "Evidence", "doc": "policy.txt"}])
        self.assertEqual(answer, "Answer in English")
        messages = model.invoke.call_args.args[0]
        self.assertIn("Answer in English", messages[0].content)
        self.assertIn("[policy.txt]", messages[1].content)

    def test_api_returns_distinct_text_sources(self):
        hits = [{"text": "one", "doc": "policy.txt"}, {"text": "two", "doc": "policy.txt"}]
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            retriever=SimpleNamespace(search=lambda question: (hits, 0.9))
        )))
        with patch.object(main, "answer_question", return_value="Answer"):
            response = main.ask(main.Question(question="Question?"), request)
        self.assertEqual(response, {"answer": "Answer", "sources": [{"doc": "policy.txt"}]})

    def test_api_rejects_whitespace_question(self):
        with self.assertRaises(HTTPException):
            main.ask(main.Question(question="   "), None)


if __name__ == "__main__":
    unittest.main()
