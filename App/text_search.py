import re
from pathlib import Path

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from App.settings import TOP_K
from App.embedding import embed

TEXT_DIR = Path("data/index")
MAX_CHARS = 1200
TOKEN = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def load_chunks(directory: Path = TEXT_DIR) -> list[dict]:
    chunks = []
    for path in sorted(directory.glob("*.txt")):
        text = path.read_text(encoding="utf-8-sig").strip()
        if not text:
            continue
        paragraphs = re.split(r"\n\s*\n", text)
        for paragraph in paragraphs:
            for start in range(0, len(paragraph), MAX_CHARS):
                part = paragraph[start:start + MAX_CHARS].strip()
                if part:
                    chunks.append({"text": part, "doc": path.name})
    if not chunks:
        raise RuntimeError(f"No text documents found in {directory}")
    return chunks


class TextRetriever:
    def __init__(self):
        self.chunks = load_chunks()
        vectors = embed([chunk["text"] for chunk in self.chunks], kind="passage")
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(np.ascontiguousarray(vectors))
        self.bm25 = BM25Okapi([tokenize(chunk["text"]) for chunk in self.chunks])

    def search(self, question: str, k: int = TOP_K) -> tuple[list[dict], float]:
        query = embed([question], kind="query")
        scores, indexes = self.index.search(query, min(20, len(self.chunks)))
        lexical = self.bm25.get_scores(tokenize(question))
        ranked = {}
        for rank, index in enumerate(indexes[0]):
            if index >= 0:
                ranked[int(index)] = 1 / (60 + rank)
        for rank, index in enumerate(np.argsort(lexical)[::-1][:20]):
            if lexical[index] > 0:
                ranked[int(index)] = ranked.get(int(index), 0) + 1 / (60 + rank)
        top = sorted(ranked, key=ranked.get, reverse=True)[:k]
        return [self.chunks[index] for index in top], float(scores[0][0])
