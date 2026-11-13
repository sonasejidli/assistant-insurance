import numpy as np
from sentence_transformers import SentenceTransformer
from App.settings import EMBED_MODEL

_model: SentenceTransformer | None = None
 
 
def get_model() -> SentenceTransformer:
    global _model
    if _model is None:  # lazy: nothing is loaded at import time
        _model = SentenceTransformer(EMBED_MODEL)
    return _model
 
 
def embed(texts: list[str], kind: str = "passage", batch_size: int = 16,
          show_progress: bool = False) -> np.ndarray:
    """Return an L2-normalized float32 matrix (inner product == cosine similarity).
 
    kind: "passage" for document chunks, "query" for user questions.
    """
    if kind not in ("passage", "query"):
        raise ValueError("kind must be 'passage' or 'query'")
    if "e5" in EMBED_MODEL.lower():
        texts = [f"{kind}: {t}" for t in texts]
    vectors = get_model().encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
        show_progress_bar=show_progress,
    )
    return np.asarray(vectors, dtype="float32")
