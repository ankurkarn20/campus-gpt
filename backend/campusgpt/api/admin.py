"""Administrator endpoints: upload policy documents and follow their ingestion.

An upload is only stored and queued here; the ingestion worker (a separate process, see
campusgpt.worker) does the slow part, so the request returns 202 straight away.
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import documents, worker
from campusgpt.auth import CurrentUser, require_role
from campusgpt.db import get_db
from campusgpt.models import AuditLog, Document, DocumentChunk, IngestionJob

router = APIRouter(prefix="/api/admin", tags=["admin"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
CONTENT_TYPES = {".md": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf"}


def _summary(doc: Document, job: IngestionJob | None, chunks: int) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "category": doc.category,
        "version": doc.version,
        "status": doc.status,
        "file_name": doc.file_name,
        "created_at": datetime.isoformat(doc.created_at),
        "chunks": chunks,
        "job": job and {
            "state": job.state,
            "progress": job.progress,
            "attempts": job.attempts,
            "error": job.error,
            "updated_at": datetime.isoformat(job.updated_at),
        },
    }


def _with_latest_job():
    """Documents, each with its most recent ingestion job and its number of chunks."""
    latest_job = (select(IngestionJob.id).where(IngestionJob.document_id == Document.id)
                  .order_by(IngestionJob.id.desc()).limit(1)
                  .correlate(Document).scalar_subquery())
    chunks = (select(func.count()).select_from(DocumentChunk)
              .where(DocumentChunk.document_id == Document.id)
              .scalar_subquery())
    return (select(Document, IngestionJob, chunks)
            .outerjoin(IngestionJob, IngestionJob.id == latest_job))


@router.get("/documents")
async def list_documents(_: CurrentUser = Depends(require_role("admin")),
                         db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = await db.execute(_with_latest_job().order_by(Document.created_at.desc(),
                                                        Document.id.desc()))
    return [_summary(*row) for row in rows]


@router.get("/documents/{document_id}")
async def get_document(document_id: int, _: CurrentUser = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)) -> dict:
    row = (await db.execute(_with_latest_job().where(Document.id == document_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such document")
    return _summary(*row)


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(file: UploadFile = File(...),
                          title: str = Form(..., min_length=3, max_length=200),
                          category: str = Form(...),
                          user: CurrentUser = Depends(require_role("admin")),
                          db: AsyncSession = Depends(get_db)) -> dict:
    file_name = Path(file.filename or "").name
    suffix = Path(file_name).suffix.lower()
    if suffix not in CONTENT_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Upload a {', '.join(documents.FILE_TYPES)} file")
    if category not in documents.CATEGORIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Category must be one of {', '.join(documents.CATEGORIES)}")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                            f"Files may be at most {MAX_UPLOAD_BYTES // 2**20} MB")
    same = await db.scalar(select(Document.title).where(
        Document.content_sha256 == documents.sha256(data), Document.status == "active"))
    if same:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This file is already active as “{same}”")

    # One transaction: the document, its file, its job and the notification.
    doc = await documents.register(db, title=title.strip(), category=category,
                                   file_name=file_name, data=data, uploaded_by=user.id)
    job = await worker.enqueue(db, doc, data, CONTENT_TYPES[suffix])
    db.add(AuditLog(user_id=user.id, action="document_upload", outcome="success",
                    detail={"document_id": doc.id, "version": doc.version,
                            "bytes": len(data)}))
    await db.commit()
    await db.refresh(job)
    return _summary(doc, job, 0)
