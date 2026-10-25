"""Sentence embeddings for document search (BGE-small, 384 dimensions, run locally).

One model instance per process, loaded on first use. BGE is asymmetric: questions are
embedded with a query instruction, document chunks without one. Vectors are normalised, so
cosine distance (pgvector's <=> with vector_cosine_ops) ranks them.
"""
import asyncio
from functools import lru_cache

import numpy as np

from campusgpt.config import get_settings
from campusgpt.models.documents import EMBEDDING_DIM


@lru_cache
def _model():
    from fastembed import TextEmbedding  # slow import; only processes that search pay for it
    settings = get_settings()
    return TextEmbedding(settings.embedding_model,
                         cache_dir=str(settings.model_cache_dir.expanduser()))


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    vectors = list(_model().embed(texts, batch_size=32))
    assert all(v.shape == (EMBEDDING_DIM,) for v in vectors)
    return vectors


def embed_query(text: str) -> np.ndarray:
    return next(iter(_model().query_embed([text])))


async def embed_query_async(text: str) -> np.ndarray:
    """embed_query without blocking the event loop (the model runs in a worker thread)."""
    return await asyncio.to_thread(embed_query, text)
