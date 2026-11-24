"""Qdrant-backed semantic index for a versioned corpus of legal passages."""

import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from qdrant_client import QdrantClient, models
from App.legal_documents import APP_METADATA
from App.observability import startup_stage
from qdrant_client.http.exceptions import UnexpectedResponse

from App.settings import QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_PATH, QDRANT_URL

log = logging.getLogger(__name__)
BATCH_SIZE = 128


def fingerprint(value) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class QdrantIndex:
    def __init__(self, chunks, texts, embed, *, configuration, passages=None):
        self.embedding_fingerprint = fingerprint(configuration)
        self.collection_metadata = {"embedding_fingerprint": self.embedding_fingerprint,
                                    "embedding_configuration": configuration}
        self.dimensions = configuration["dimensions"]
        with startup_stage("qdrant_client"):
            if QDRANT_URL:
                self.client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
            elif QDRANT_PATH:
                self.client = QdrantClient(path=QDRANT_PATH)
            else:
                self.client = QdrantClient(":memory:")
        try:
            self._initialize(chunks, texts, embed, passages)
        except Exception:
            self.client.close()
            raise

    def _initialize(self, chunks, texts, embed, passages):
        if not chunks or len(chunks) != len(texts):
            raise ValueError("Qdrant indexing requires one embedding input per chunk")
        ids_by_doc = defaultdict(list)
        payloads = []
        for index, chunk in enumerate(chunks):
            info = {key: value for key, value in (chunk.get("metadata") or {}).items() if key not in APP_METADATA}
            name = chunk["doc"]
            document_id = info.get("document_id") or str(uuid5(NAMESPACE_URL, f"insurance-document:{name}"))
            chunk_id = info.get("chunk_id") or str(uuid5(NAMESPACE_URL, f"{document_id}:{len(ids_by_doc[name])}"))
            ids_by_doc[name].append(chunk_id)
            payloads.append({
                **info, "document_id": document_id, "document_name": name,
                "document_type": info.get("document_type") or name.rpartition(".")[2].lower() or None,
                "page_number": info.get("page_number"),
                "section_title": info.get("section_title") or info.get("article_title"),
                "article_number": info.get("article_number") or info.get("article"),
                "chunk_id": chunk_id, "original_text": info.get("original_text", chunk["text"]),
                "index": index, "text": chunk["text"], "note_ids": chunk.get("note_ids", []),
            })
        for chunk, payload in zip(chunks, payloads):
            point_ids = ids_by_doc[chunk["doc"]]
            payload["references"] = [
                {**reference, "source_chunk_id": payload["chunk_id"],
                 "target_chunk_id": point_ids[target] if (target := reference["target_chunk"]) is not None else None}
                for reference in chunk.get("references", [])
            ]
            if payload["document_type"] == "pdf":
                payload["source_url"] = f"/documents/{quote(chunk['doc'], safe='')}/pdf"
                if page := payload["page_number"]:
                    payload["source_url"] += f"#page={page}"
        self.point_ids = [payload["chunk_id"] for payload in payloads]
        if len(set(self.point_ids)) != len(self.point_ids):
            raise ValueError("Qdrant indexing requires unique parent chunk IDs")
        self.ids_by_parent = [[point_id] for point_id in self.point_ids]
        if passages is not None:
            child_payloads, child_texts = [], []
            for parent, parts in zip(payloads, passages, strict=True):
                parent_id = parent["chunk_id"]
                ids = []
                for ordinal, part in enumerate(parts):
                    point_id = parent_id if ordinal == 0 else str(
                        uuid5(NAMESPACE_URL, f"{parent_id}:embedding:{part.start}:{part.end}")
                    )
                    ids.append(point_id)
                    child_payloads.append({
                        **parent, "chunk_id": point_id, "parent_chunk_id": parent_id,
                        "child_ordinal": ordinal, "child_count": len(parts),
                        "child_start": part.start, "child_end": part.end,
                        "embedding_text": part.text, "original_embedding_tokens": part.original_tokens,
                        "embedded_tokens": part.embedded_tokens,
                    })
                    child_texts.append(part.text)
                self.ids_by_parent[parent["index"]] = ids
            payloads, texts = child_payloads, child_texts
        self.index_by_id = {point_id: index for index, ids in enumerate(self.ids_by_parent) for point_id in ids}
        if len(self.index_by_id) != len(payloads):
            raise ValueError("Qdrant indexing requires unique chunk IDs")
        version = fingerprint(["v2", self.embedding_fingerprint, texts, payloads])[:24]
        self.collection = f"{QDRANT_COLLECTION}_{version}"
        with startup_stage("qdrant_collection_lookup"):
            exists = self.client.collection_exists(self.collection)
        expected_keys = {}
        for payload, text in zip(payloads, texts, strict=True):
            key = fingerprint([self.embedding_fingerprint, text])
            payload.update(embedding_key=key, embedding_fingerprint=self.embedding_fingerprint,
                           embedding_model=self.collection_metadata["embedding_configuration"]["model_repository"])
            expected_keys[payload["chunk_id"]] = key
        with startup_stage("qdrant_collection_validation", existing=exists):
            present = self._validate_collection(expected_keys) if exists else set()
        if present == expected_keys.keys():
            log.info("Reusing complete Qdrant collection %s (%d vector points)", self.collection, len(payloads),
                     extra={"event": "vector_index_reused", "collection_name": self.collection,
                            "embedding_fingerprint": self.embedding_fingerprint, "point_count": len(payloads)})
            return
        if os.getenv("RAG_REQUIRE_PREPARED_INDEX") == "1":
            raise RuntimeError(
                f"Prepared Qdrant index is incomplete: {len(present)}/{len(expected_keys)} validated points. "
                "Prepare the matching corpus index before starting the API."
            )

        pending = [(payload, text) for payload, text in zip(payloads, texts, strict=True)
                   if payload["chunk_id"] not in present]
        text_by_key = {payload["embedding_key"]: text for payload, text in pending}

        with startup_stage("qdrant_embedding_reuse", requested=len(text_by_key)):
            vectors = self._reuse_embeddings(set(text_by_key), exists)
        reused = len(vectors)
        missing = [key for key in text_by_key if key not in vectors]
        if missing:
            with startup_stage("embedding_generation", inputs=len(missing)):
                embedded = np.asarray(embed([text_by_key[key] for key in missing], kind="passage"))
            if embedded.shape != (len(missing), self.dimensions) or not np.isfinite(embedded).all():
                raise ValueError("Passage encoder returned invalid vectors")
            vectors.update(zip(missing, embedded, strict=True))
        with startup_stage("qdrant_population", points=len(pending)):
            if not exists:
                try:
                    # The encoder L2-normalizes embeddings, so dot product is cosine similarity.
                    self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                        size=self.dimensions, distance=models.Distance.DOT,
                    ), metadata=self.collection_metadata)
                except UnexpectedResponse:
                    if not self.client.collection_exists(self.collection) or not self._compatible(self.collection):
                        raise
            for start in range(0, len(pending), BATCH_SIZE):
                points = [models.PointStruct(id=payload["chunk_id"],
                                              vector=vectors[payload["embedding_key"]].tolist(), payload=payload)
                          for payload, _ in pending[start:start + BATCH_SIZE]]
                self.client.upsert(self.collection, points, wait=True)
        with startup_stage("qdrant_final_validation", points=len(expected_keys)):
            if self._validate_collection(expected_keys) != expected_keys.keys():
                raise RuntimeError(f"Incomplete vector index {self.collection}")
        log.info("Indexed Qdrant collection %s: %d uploaded, %d present, %d distinct embeddings reused, %d encoded",
                 self.collection, len(pending), len(present), reused, len(missing),
                 extra={"event": "vector_index_validated", "collection_name": self.collection,
                        "embedding_fingerprint": self.embedding_fingerprint, "point_count": len(payloads),
                        "uploaded_points": len(pending), "resumed_points": len(present),
                        "reused_vectors": reused, "encoded_vectors": len(missing)})

    def _records(self, collection, fields, *, scroll_filter=None):
        offset = None
        while True:
            records, offset = self.client.scroll(collection, limit=BATCH_SIZE, offset=offset,
                                                 with_payload=fields, scroll_filter=scroll_filter)
            yield from records
            if offset is None:
                break

    def _compatible(self, collection: str) -> bool:
        config = self.client.get_collection(collection).config
        vectors = config.params.vectors
        metadata = config.metadata or {}
        return (isinstance(vectors, models.VectorParams) and vectors.size == self.dimensions
                and vectors.distance == models.Distance.DOT
                and all(metadata.get(key) == value for key, value in self.collection_metadata.items()))

    def _validate_collection(self, expected_keys: dict[str, str]) -> set[str]:
        if not self._compatible(self.collection):
            raise RuntimeError(f"Incompatible configuration for vector index {self.collection}")
        present = set()
        for record in self._records(self.collection, ["embedding_key", "embedding_fingerprint"]):
            payload = record.payload or {}
            if (record.id not in expected_keys or payload.get("embedding_key") != expected_keys[record.id]
                    or payload.get("embedding_fingerprint") != self.embedding_fingerprint):
                raise RuntimeError(f"Incompatible point in vector index {self.collection}: {record.id}")
            present.add(record.id)
        return present

    def _reuse_embeddings(self, wanted: set[str], current_exists: bool) -> dict[str, np.ndarray]:
        collections = [self.collection] if current_exists else []
        pattern = re.compile(re.escape(QDRANT_COLLECTION) + r"_[0-9a-f]{24}")
        collections.extend(item.name for item in self.client.get_collections().collections
                           if item.name != self.collection and pattern.fullmatch(item.name))
        model_filter = models.Filter(must=[models.FieldCondition(
            key="embedding_fingerprint", match=models.MatchValue(value=self.embedding_fingerprint),
        )])
        vectors = {}
        for collection in collections:
            if not self._compatible(collection):
                continue
            matching = {}
            for record in self._records(collection, ["embedding_key"], scroll_filter=model_filter):
                key = (record.payload or {}).get("embedding_key")
                if key in wanted:
                    matching.setdefault(key, record.id)
                if len(matching) == len(wanted):
                    break
            ids = list(matching.values())
            keys_by_id = {point_id: key for key, point_id in matching.items()}
            for start in range(0, len(ids), BATCH_SIZE):
                records = self.client.retrieve(collection, ids[start:start + BATCH_SIZE],
                                               with_payload=False, with_vectors=True)
                for record in records:
                    if (isinstance(record.vector, list) and len(record.vector) == self.dimensions
                            and np.isfinite(record.vector).all()):
                        key = keys_by_id[record.id]
                        vectors[key] = np.asarray(record.vector, dtype="float32")
                        wanted.discard(key)
            if not wanted:
                break
        return vectors

    def search(self, vector: list[float], eligible: list[int], limit: int, *, exact: bool = False,
               score_threshold: float | None = None):
        if not eligible or limit < 1:
            return []
        query_filter = None
        point_count = len(self.index_by_id)
        if len(eligible) < len(self.point_ids):
            ids = [point_id for index in eligible for point_id in self.ids_by_parent[index]]
            point_count = len(ids)
            query_filter = models.Filter(must=[models.HasIdCondition(has_id=ids)])
        # Extra child matches must not crowd distinct parents out of the requested rank.
        point_limit = min(point_count, limit + point_count - len(eligible))
        points = self.client.query_points(
            self.collection, query=vector, query_filter=query_filter, limit=point_limit,
            search_params=models.SearchParams(exact=exact), with_payload=False, score_threshold=score_threshold,
        ).points
        best = {}
        for point in points:
            index = self.index_by_id[str(point.id)]
            best[index] = max(best.get(index, float("-inf")), point.score)
        return sorted(best.items(), key=lambda item: (-item[1], item[0]))[:limit]

    def close(self):
        self.client.close()
