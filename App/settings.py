import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("EMBED_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "liquid/lfm-3-1.7b:free")
LLM_GENERATION_PROVIDER = os.getenv("LLM_GENERATION_PROVIDER", "openrouter").strip().lower()
if LLM_GENERATION_PROVIDER not in {"openrouter", "gemini"}:
    raise ValueError("LLM_GENERATION_PROVIDER must be openrouter or gemini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
LLM_CONTEXT_WINDOW = int(os.getenv("LLM_CONTEXT_WINDOW", "16384"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1536"))
if not 0 < LLM_MAX_OUTPUT_TOKENS < LLM_CONTEXT_WINDOW:
    raise ValueError("LLM_MAX_OUTPUT_TOKENS must be positive and smaller than LLM_CONTEXT_WINDOW")
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-large")
EMBED_MODEL_REVISION = os.getenv("EMBED_MODEL_REVISION", "main")
EMBED_TARGET_TOKENS = int(os.getenv("EMBED_TARGET_TOKENS", "0"))
EMBED_OVERLAP_TOKENS = int(os.getenv("EMBED_OVERLAP_TOKENS", "24"))
if EMBED_TARGET_TOKENS and EMBED_TARGET_TOKENS < 32:
    raise ValueError("EMBED_TARGET_TOKENS must be zero or at least 32")
if EMBED_OVERLAP_TOKENS < 0:
    raise ValueError("EMBED_OVERLAP_TOKENS must be nonnegative")
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_PATH = os.getenv("QDRANT_PATH", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "insurance_chunks")
INDEX_CHUNK_CHARS = int(os.getenv("INDEX_CHUNK_CHARS", "1200"))
CONTEXTUAL_HEADERS, LEGAL_EVIDENCE, STRUCTURED_ANSWERS, LEGAL_FAITHFULNESS = (
    os.getenv(name, "").casefold() in {"1", "true", "yes"}
    for name in ("CONTEXTUAL_HEADERS", "LEGAL_EVIDENCE", "STRUCTURED_ANSWERS", "LEGAL_FAITHFULNESS")
)
LEGAL_MIN_SUPPORTING_STAGES = int(os.getenv("LEGAL_MIN_SUPPORTING_STAGES", "1"))
LEGAL_RETRIEVAL_V2 = os.getenv("LEGAL_RETRIEVAL_V2", "").casefold() in {"1", "true", "yes"}
LEGAL_PROVISION_RETRIEVAL = os.getenv("LEGAL_PROVISION_RETRIEVAL", "").casefold() in {"1", "true", "yes"}
LEGAL_MULTIPART_COVERAGE = os.getenv("LEGAL_MULTIPART_COVERAGE", "").casefold() in {"1", "true", "yes"}
LEGAL_CLAIM_GUARDS = os.getenv("LEGAL_CLAIM_GUARDS", "").casefold() in {"1", "true", "yes"}
STAGED_LEGAL_SOURCES = os.getenv("STAGED_LEGAL_SOURCES", "").casefold() in {"1", "true", "yes"}
if not 1 <= LEGAL_MIN_SUPPORTING_STAGES <= 4:
    raise ValueError("LEGAL_MIN_SUPPORTING_STAGES must be between 1 and 4")
if INDEX_CHUNK_CHARS < 1:
    raise ValueError("INDEX_CHUNK_CHARS must be positive")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
QUERY_DECOMPOSITION, QUERY_ROUTING, QUERY_EXPANSION, QUERY_HYDE = (
    os.getenv(name, "").casefold() in {"1", "true", "yes"}
    for name in ("QUERY_DECOMPOSITION", "QUERY_ROUTING", "QUERY_EXPANSION", "QUERY_HYDE")
)
RERANK_MODE = os.getenv("RERANK_MODE", "baseline")
RERANK_DEVICE = os.getenv("RERANK_DEVICE") or None
RERANK_BATCH_SIZE = int(os.getenv("RERANK_BATCH_SIZE", "8"))
RERANK_MAX_TOKENS = int(os.getenv("RERANK_MAX_TOKENS", "512"))
if RERANK_MODE not in {"baseline", "bge_safe"} or RERANK_BATCH_SIZE < 1 or RERANK_MAX_TOKENS < 32:
    raise ValueError("Invalid reranking mode, batch size, or token budget")
# Selected on the tuning split by evaluation/tune_bm25.py.
BM25_K1 = 0.3
BM25_B = 0.0
TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
if not 1 <= TOP_K <= 50:
    raise ValueError("RETRIEVAL_TOP_K must be between 1 and 50")


@dataclass(frozen=True)
class RetrievalSettings:
    bm25_top_k: int = 50
    vector_top_k: int = 50
    similarity_threshold: float = 0.0
    bm25_weight: float = 1.0
    vector_weight: float = 1.0
    rrf_k: int = 60
    rerank_top_k: int = 24

    def __post_init__(self):
        if min(self.bm25_top_k, self.vector_top_k, self.rerank_top_k) < 1:
            raise ValueError("BM25_TOP_K, VECTOR_TOP_K and RERANK_TOP_K must be positive")
        if self.rrf_k < 0:
            raise ValueError("RRF_K must be nonnegative")
        if not -1 <= self.similarity_threshold <= 1:
            raise ValueError("VECTOR_SIMILARITY_THRESHOLD must be between -1 and 1")
        weights = (self.bm25_weight, self.vector_weight)
        if any(not isfinite(weight) or weight < 0 for weight in weights) or not any(weights):
            raise ValueError("Retrieval weights must be finite, nonnegative and include a positive weight")

    @classmethod
    def from_env(cls):
        defaults = cls()
        return cls(
            bm25_top_k=int(os.getenv("BM25_TOP_K", defaults.bm25_top_k)),
            vector_top_k=int(os.getenv("VECTOR_TOP_K", defaults.vector_top_k)),
            similarity_threshold=float(os.getenv("VECTOR_SIMILARITY_THRESHOLD", defaults.similarity_threshold)),
            bm25_weight=float(os.getenv("BM25_WEIGHT", defaults.bm25_weight)),
            vector_weight=float(os.getenv("VECTOR_WEIGHT", defaults.vector_weight)),
            rrf_k=int(os.getenv("RRF_K", defaults.rrf_k)),
            rerank_top_k=int(os.getenv("RERANK_TOP_K", defaults.rerank_top_k)),
        )
