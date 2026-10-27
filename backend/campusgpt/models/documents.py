"""Policy documents, their uploaded files, searchable chunks, the ingestion job queue, and
notices."""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from campusgpt.models.base import Base, created_at_column, id_column

EMBEDDING_DIM = 384  # BGE-small
DOCUMENT_STATUSES = ("processing", "active", "superseded", "failed")
JOB_STATES = ("queued", "processing", "done", "failed")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"status IN {DOCUMENT_STATUSES}", name="status"),
        CheckConstraint("version >= 1", name="version"),
    )

    id: Mapped[int] = id_column()
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    status: Mapped[str] = mapped_column(String(16), server_default="processing")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, server_default=true())
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()


class DocumentFile(Base):
    """The uploaded file itself. Stored in the database so that the upload, its file and its
    ingestion job are committed together; the worker reads the bytes from here."""

    __tablename__ = "document_files"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        Index(
            "ix_document_chunks_embedding_hnsw", "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_document_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(200))
    page: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    content_tsv = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )


class IngestionJob(Base):
    """Durable job queue shared by the API and the ingestion worker (claimed with
    SELECT ... FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(f"state IN {JOB_STATES}", name="state"),
        CheckConstraint("attempts >= 0", name="attempts"),
        # Small partial index that serves the worker's claim query.
        Index("ix_ingestion_jobs_queued", "created_at", postgresql_where=text("state = 'queued'")),
    )

    id: Mapped[int] = id_column()
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(16), server_default="queued")
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    # What the worker is doing right now, shown in the admin console ("Embedding 12 chunks").
    progress: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Notice(Base):
    __tablename__ = "notices"

    id: Mapped[int] = id_column()
    published_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    # 'all' or a department code such as 'CSE'
    audience: Mapped[str] = mapped_column(String(20))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, server_default=true())
