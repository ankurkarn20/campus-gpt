"""Ingestion worker: a separate process that indexes documents uploaded by an administrator.

The API and the worker share no memory; they communicate only through PostgreSQL:

  * the `ingestion_jobs` table is the durable queue. The upload transaction inserts the
    document, its file and a `queued` job together;
  * `NOTIFY ingest_jobs` (sent in the same transaction, delivered on commit) wakes the
    worker at once. PostgreSQL does not keep notifications for a worker that is not
    listening, so the worker also checks the table every 30 seconds;
  * the worker claims a job with `FOR UPDATE SKIP LOCKED`, so with several workers running
    each job is still taken by exactly one of them.

Indexing runs in one transaction that also marks the job done, so a failure never leaves a
half-indexed document visible to search. A job whose worker died (no progress for ten
minutes) is claimed again, up to three attempts.

    python -m campusgpt.worker        # or: make worker
"""
import argparse
import asyncio
import logging
import signal
import sys
from dataclasses import dataclass
from datetime import timedelta

import psycopg
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from campusgpt import documents
from campusgpt.db import make_async_engine
from campusgpt.documents import UnsupportedDocument
from campusgpt.models import Document, DocumentFile, IngestionJob

log = logging.getLogger("campusgpt.worker")

CHANNEL = "ingest_jobs"
POLL_SECONDS = 30
STALE_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    document_id: int
    attempts: int


# -- API side --------------------------------------------------------------------------------
async def enqueue(db: AsyncSession, doc: Document, data: bytes,
                  content_type: str) -> IngestionJob:
    """Store the uploaded file and queue its ingestion, in the caller's transaction. The
    worker is notified when that transaction commits (never before, so it cannot look for
    a job it cannot see yet)."""
    db.add(DocumentFile(document_id=doc.id, content_type=content_type,
                        size_bytes=len(data), data=data))
    job = IngestionJob(document_id=doc.id, state="queued", progress="Waiting for the worker")
    db.add(job)
    await db.flush()
    await db.execute(select(func.pg_notify(CHANNEL, str(job.id))))
    return job


# -- worker side -----------------------------------------------------------------------------
GIVE_UP_STALE = text("""
WITH given_up AS (
    UPDATE ingestion_jobs
       SET state = 'failed', progress = NULL, updated_at = now(),
           error = 'The worker stopped while processing this file ' || attempts || ' times'
     WHERE state = 'processing' AND updated_at < now() - :stale AND attempts >= :max
    RETURNING document_id)
UPDATE documents SET status = 'failed' WHERE id IN (SELECT document_id FROM given_up)
""")

# The oldest queued job, or one whose worker stopped reporting progress (crashed).
CLAIM = text("""
UPDATE ingestion_jobs
   SET state = 'processing', attempts = attempts + 1, updated_at = now(), progress = 'Starting'
 WHERE id = (SELECT id FROM ingestion_jobs
              WHERE state = 'queued'
                 OR (state = 'processing' AND updated_at < now() - :stale
                     AND attempts < :max)
              ORDER BY created_at
              LIMIT 1
              FOR UPDATE SKIP LOCKED)
RETURNING id, document_id, attempts
""")


async def claim(engine: AsyncEngine) -> ClaimedJob | None:
    """Take the next job and commit it as 'processing', so the admin console sees it."""
    async with AsyncSession(engine) as db:
        params = {"stale": STALE_AFTER, "max": MAX_ATTEMPTS}
        await db.execute(GIVE_UP_STALE, params)
        row = (await db.execute(CLAIM, params)).first()
        await db.commit()
    return ClaimedJob(*row) if row else None


async def _set_job(engine: AsyncEngine, job_id: int, **values) -> None:
    async with AsyncSession(engine) as db:
        await db.execute(update(IngestionJob).where(IngestionJob.id == job_id)
                         .values(updated_at=func.now(), **values))
        await db.commit()


async def process(engine: AsyncEngine, job: ClaimedJob) -> str:
    """Index the job's document. Returns the job's new state: 'done', 'failed', or
    'queued' (to be retried after an unexpected error)."""
    async def report(progress: str) -> None:
        # Its own short transaction, so the console sees it while indexing is still running.
        await _set_job(engine, job.id, progress=progress)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            doc = await db.get(Document, job.document_id)
            file = await db.get(DocumentFile, job.document_id)
            n = await documents.index(db, doc, file.data, report)
            await db.execute(update(IngestionJob).where(IngestionJob.id == job.id).values(
                state="done", progress=f"{n} chunks indexed", error=None,
                updated_at=func.now()))
            await db.commit()
        log.info("job %s: document %s indexed, %s chunks", job.id, job.document_id, n)
        return "done"
    except Exception as e:
        # A file that cannot be read will not improve on a retry; anything else might.
        permanent = isinstance(e, UnsupportedDocument) or job.attempts >= MAX_ATTEMPTS
        state = "failed" if permanent else "queued"
        log.warning("job %s: %s (%s)", job.id, e, state, exc_info=not permanent)
        await _set_job(engine, job.id, state=state, progress=None,
                       error=str(e)[:500] or type(e).__name__)
        if permanent:
            async with AsyncSession(engine) as db:
                await db.execute(update(Document).where(Document.id == job.document_id)
                                 .values(status="failed"))
                await db.commit()
        return state


async def _wait_for_notification(conn: psycopg.AsyncConnection, shutdown: asyncio.Event,
                                 timeout: float) -> None:
    """Sleep until a job is announced, `timeout` seconds pass, or shutdown is requested."""
    async def one_notification():
        async for _ in conn.notifies(timeout=timeout, stop_after=1):
            pass

    waiters = {asyncio.create_task(one_notification()), asyncio.create_task(shutdown.wait())}
    _, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def run_worker(database_url: str | None, shutdown: asyncio.Event,
                     poll_seconds: float = POLL_SECONDS) -> None:
    """Process jobs until `shutdown` is set. The current job is always finished first."""
    engine = make_async_engine(database_url)
    dsn = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    try:
        await conn.execute(f"LISTEN {CHANNEL}")
        log.info("listening on %s (checking the queue every %ss)", CHANNEL, poll_seconds)
        while not shutdown.is_set():
            while not shutdown.is_set() and (job := await claim(engine)) is not None:
                log.info("job %s: claimed (attempt %s)", job.id, job.attempts)
                await process(engine, job)
            if not shutdown.is_set():
                await _wait_for_notification(conn, shutdown, poll_seconds)
    finally:
        await conn.close()
        await engine.dispose()
        log.info("stopped")


async def _main(database_url: str | None, poll_seconds: float) -> None:
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)
    await run_worker(database_url, shutdown, poll_seconds)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", help="defaults to DATABASE_URL from .env")
    parser.add_argument("--poll-seconds", type=float, default=POLL_SECONDS)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_main(args.database_url, args.poll_seconds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
