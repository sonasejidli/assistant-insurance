"""Bounded query-passage scoring for the experimental BGE path."""

from bisect import bisect_right
import logging
import re

import numpy as np

from App.embedding import LEGAL_BOUNDARY


log = logging.getLogger(__name__)


def pair_lengths(tokenizer, pairs):
    if not pairs:
        return []
    return tokenizer([pair[0] for pair in pairs], [pair[1] for pair in pairs],
                     return_length=True, truncation=False, verbose=False)["length"]


def bounded_passages(tokenizer, question, body, render, limit):
    def fits(start, end):
        excerpt = render(body[start:end].strip())
        return pair_lengths(tokenizer, [(question, excerpt)])[0] <= limit

    stops = sorted({m.end() for m in LEGAL_BOUNDARY.finditer(body)} | {len(body)})
    words = [m.end() for m in re.finditer(r"\S+\s*", body)]
    result = []
    start = covered = 0
    while covered < len(body):
        def furthest(boundaries):
            lower = bisect_right(boundaries, covered)
            lo, hi = lower, len(boundaries)
            while lo < hi:
                mid = (lo + hi) // 2
                if fits(start, boundaries[mid]):
                    lo = mid + 1
                else:
                    hi = mid
            return boundaries[lo - 1] if lo > lower else covered

        end = furthest(stops)
        if end == covered:
            end = furthest(words)
        if end == covered and start != covered:
            start = covered
            end = furthest(stops)
            if end == covered:
                end = furthest(words)
        if end == covered:
            raise ValueError("Reranker budget cannot fit the full query and any passage word")
        result.append(render(body[start:end].strip()))
        if end == len(body):
            break
        # Keep some preceding words when another full unit can still fit.
        position = max(0, bisect_right(words, end) - 1)
        start = max(start, words[position - 12]) if position >= 12 else end
        covered = end
    return result


def bge_scores(model, question, documents, render, *, max_tokens, batch_size):
    limit = min(value for value in (max_tokens, model.max_seq_length, model.tokenizer.model_max_length)
                if value is not None)
    pairs = [(question, render(document)) for document in documents]
    lengths = pair_lengths(model.tokenizer, pairs)
    windows, owners = [], []
    for i, (document, pair, length) in enumerate(zip(documents, pairs, lengths, strict=True)):
        if length <= limit:
            passages = [pair[1]]
        else:
            passages = bounded_passages(model.tokenizer, question, document.page_content,
                                        lambda content: render(document, content), limit)
            log.info("Reranker split %d tokens into %d windows at limit %d", length, len(passages), limit,
                     extra={"event": "reranker_windows", "original_tokens": length, "window_count": len(passages),
                            "token_limit": limit, "parent_passage_id": document.metadata.get("chunk_id")})
        windows.extend((question, passage) for passage in passages)
        owners.extend([i] * len(passages))
    if any(length > limit for length in pair_lengths(model.tokenizer, windows)):
        raise ValueError("Reranker attempted an over-limit pair")
    scores = np.asarray(model.predict(windows, batch_size=batch_size, show_progress_bar=False))
    if scores.shape != (len(windows),) or not np.isfinite(scores).all():
        raise ValueError("Invalid BGE window scores")
    parent_scores = np.full(len(documents), -np.inf)
    np.maximum.at(parent_scores, owners, scores)
    return parent_scores
