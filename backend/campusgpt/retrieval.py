"""Hybrid search over the active policy documents.

Two rankings of the chunks are computed in PostgreSQL and fused with Reciprocal Rank Fusion
(Cormack et al., 2009): score = sum over rankings of 1 / (RRF_K + rank).

- semantic: cosine distance between the question's BGE embedding and each chunk's
  (pgvector HNSW index), which finds paraphrases ("rechecking" ~ "re-evaluation");
- lexical: PostgreSQL full-text search (GIN index on content_tsv), which finds exact terms,
  numbers and names the embedding may blur ("Rs 1,500", "DB grade").

`mode` selects one ranking alone, so the evaluation can measure what each contributes.
"""
from dataclasses import dataclass
from typing import Literal

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt.embedding import embed_query_async
from campusgpt.models.documents import EMBEDDING_DIM

RRF_K = 60            # the constant from the RRF paper; dampens the weight of the top ranks
CANDIDATES = 20       # taken from each ranking before fusion
Mode = Literal["hybrid", "semantic", "lexical"]


@dataclass
class Passage:
    chunk_id: int
    document_id: int
    document: str
    version: int
    section: str | None
    page: int | None
    content: str
    score: float
    semantic_rank: int | None
    lexical_rank: int | None
    similarity: float | None       # cosine similarity to the question (semantic hits only)


# Words are OR-ed (any may match, ts_rank_cd rewards those matching more), unlike
# plainto_tsquery's AND, which would require every word of a natural question to appear.
SEARCH = text("""
WITH semantic AS (
    SELECT id, distance, row_number() OVER (ORDER BY distance, id) AS rank
    FROM (SELECT c.id, c.embedding <=> :embedding AS distance
          FROM document_chunks c JOIN documents d ON d.id = c.document_id
          WHERE d.status = 'active' AND :use_semantic
          ORDER BY distance LIMIT :candidates) s
), query AS (
    SELECT nullif(replace(plainto_tsquery('english', :question)::text, '&', '|'), '')::tsquery
           AS q
), lexical AS (
    SELECT id, row_number() OVER (ORDER BY score DESC, id) AS rank
    FROM (SELECT c.id, ts_rank_cd(c.content_tsv, query.q) AS score
          FROM document_chunks c JOIN documents d ON d.id = c.document_id, query
          WHERE d.status = 'active' AND :use_lexical AND c.content_tsv @@ query.q
          ORDER BY score DESC LIMIT :candidates) l
)
SELECT c.id, c.document_id, d.title, d.version, c.section, c.page, c.content,
       coalesce(1.0 / (:rrf_k + s.rank), 0) + coalesce(1.0 / (:rrf_k + l.rank), 0) AS score,
       s.rank AS semantic_rank, l.rank AS lexical_rank, 1 - s.distance AS similarity
FROM semantic s FULL JOIN lexical l ON l.id = s.id
JOIN document_chunks c ON c.id = coalesce(s.id, l.id)
JOIN documents d ON d.id = c.document_id
ORDER BY score DESC, c.id
LIMIT :k
""").bindparams(bindparam("embedding", type_=Vector(EMBEDDING_DIM)))


async def search(db: AsyncSession, question: str, k: int = 4,
                 mode: Mode = "hybrid") -> list[Passage]:
    """The k passages most relevant to `question`, best first."""
    question = question.strip()
    if not question:
        return []
    embedding = await embed_query_async(question) if mode != "lexical" else [0.0] * EMBEDDING_DIM
    rows = await db.execute(SEARCH, {
        "embedding": embedding, "question": question, "k": k, "candidates": CANDIDATES,
        "rrf_k": RRF_K, "use_semantic": mode != "lexical", "use_lexical": mode != "semantic"})
    return [Passage(*row[:7], float(row[7]), row[8], row[9],
                    None if row[10] is None else float(row[10])) for row in rows]


SECTIONS = text("""
SELECT c.id, c.document_id, d.title, d.version, c.section, c.page, c.content
FROM document_chunks c JOIN documents d ON d.id = c.document_id
WHERE d.status = 'active' AND lower(d.title) = lower(:document)
  AND (c.section LIKE :number || '.%' OR c.section = :number)
ORDER BY c.chunk_index
""")


async def section(db: AsyncSession, document: str, number: str) -> list[Passage]:
    """Every passage of one numbered section ("4" gives §4 and its clauses) of the active
    version of a document, in document order: for tools that rely on a known rule rather
    than on searching for one. Empty if the document is not indexed."""
    rows = await db.execute(SECTIONS, {"document": document, "number": number})
    return [Passage(*row, score=0.0, semantic_rank=None, lexical_rank=None, similarity=None)
            for row in rows]
