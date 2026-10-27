"""Admin upload, the ingestion job queue and the worker process (LISTEN/NOTIFY, SKIP LOCKED)."""
import asyncio
from datetime import timedelta

import psycopg
import pytest
from sqlalchemy import select

from campusgpt import documents, worker
from campusgpt.api import admin
from campusgpt.db import make_async_engine
from campusgpt.models import IngestionJob, User
from campusgpt.retrieval import search
from tests.conftest import ADMIN, POLICIES, REGULAR, in_session, login

LIBRARY = b"""# Library Rules

Category: other

## 1. Borrowing

Students may borrow four books at a time for fourteen days. Reference books cannot be
taken out of the reading room.

## 2. Fines

A fine of Rs 5 per day is charged for each book returned after its due date.
"""


@pytest.fixture
def uploads(indexed, seeded):
    """Removes every document uploaded during the test and restores the versions it
    superseded, so the other tests see the six bundled policies only."""
    with psycopg.connect(seeded, autocommit=True) as c:
        before = c.execute("SELECT coalesce(max(id), 0) FROM documents").fetchone()[0]
        yield
        c.execute("UPDATE documents SET status = 'active', superseded_by = NULL "
                  "WHERE superseded_by > %s", (before,))
        c.execute("DELETE FROM documents WHERE id > %s", (before,))


def upload(client, data=LIBRARY, name="library.md", title="Library Rules", category="other"):
    return client.post("/api/admin/documents", files={"file": (name, data)},
                       data={"title": title, "category": category})


def run(test_url, fn):
    """Run fn(engine) against the test database with an engine of its own."""
    async def go():
        engine = make_async_engine(test_url)
        try:
            return await fn(engine)
        finally:
            await engine.dispose()
    return asyncio.run(go())


def work_once(test_url):
    """What one turn of the worker loop does: claim a job and process it."""
    async def go(engine):
        job = await worker.claim(engine)
        return job, job and await worker.process(engine, job)
    return run(test_url, go)


def searchable(test_url, question):
    hits = asyncio.run(in_session(test_url, lambda db: search(db, question, k=3)))
    return [h.content for h in hits]


# -- the upload ------------------------------------------------------------------------------
def test_upload_is_stored_and_queued_but_not_yet_searchable(client, uploads, test_url):
    login(client, ADMIN)
    r = upload(client)
    assert r.status_code == 202
    doc = r.json()
    assert (doc["status"], doc["version"], doc["chunks"]) == ("processing", 1, 0)
    assert doc["job"]["state"] == "queued" and doc["job"]["attempts"] == 0

    assert client.get(f"/api/admin/documents/{doc['id']}").json()["job"]["state"] == "queued"
    assert doc["id"] in [d["id"] for d in client.get("/api/admin/documents").json()]
    assert not any("Rs 5 per day" in c for c in searchable(test_url, "library fine per day"))


def test_upload_notifies_the_worker_on_commit(client, uploads, seeded):
    with psycopg.connect(seeded, autocommit=True) as listener:
        listener.execute(f"LISTEN {worker.CHANNEL}")
        login(client, ADMIN)
        doc_id = upload(client).json()["id"]
        [note] = list(listener.notifies(timeout=5, stop_after=1))
        job_id = listener.execute("SELECT id FROM ingestion_jobs WHERE document_id = %s",
                                  (doc_id,)).fetchone()[0]
    assert (note.channel, note.payload) == ("ingest_jobs", str(job_id))


def test_only_admins_can_upload_or_list(client, uploads):
    assert client.get("/api/admin/documents").status_code == 401
    assert upload(client).status_code == 401
    login(client, REGULAR)
    assert client.get("/api/admin/documents").status_code == 403
    assert upload(client).status_code == 403


@pytest.mark.parametrize("kwargs, code", [
    ({"name": "rules.docx"}, 422),
    ({"data": b""}, 422),
    ({"category": "gossip"}, 422),
    ({"title": "x"}, 422),
    ({"data": (POLICIES / "hostel-rules.md").read_bytes(), "name": "hostel-rules.md"}, 409),
])
def test_invalid_uploads_are_rejected(client, uploads, kwargs, code):
    login(client, ADMIN)
    assert upload(client, **kwargs).status_code == code


def test_oversized_uploads_are_rejected(client, uploads, monkeypatch):
    monkeypatch.setattr(admin, "MAX_UPLOAD_BYTES", 100)
    login(client, ADMIN)
    assert upload(client).status_code == 413


# -- the worker ------------------------------------------------------------------------------
def test_worker_indexes_the_upload(client, uploads, test_url):
    login(client, ADMIN)
    doc_id = upload(client).json()["id"]
    job, state = work_once(test_url)
    assert job.document_id == doc_id and job.attempts == 1 and state == "done"

    doc = client.get(f"/api/admin/documents/{doc_id}").json()
    assert doc["status"] == "active" and doc["chunks"] == 2
    assert doc["job"]["state"] == "done" and doc["job"]["progress"] == "2 chunks indexed"
    assert any("Rs 5 per day" in c for c in searchable(test_url, "library fine per day"))
    assert work_once(test_url) == (None, None)        # the queue is empty


def test_new_version_replaces_the_old_one_in_search(client, uploads, test_url):
    login(client, ADMIN)
    new = (POLICIES / "hostel-rules.md").read_bytes().replace(b"10:30 pm", b"11:15 pm")
    doc = upload(client, data=new, name="hostel-rules.md", title="Hostel Rules",
                 category="hostel").json()
    assert doc["version"] == 2
    assert any("10:30 pm" in c for c in searchable(test_url, "when does the hostel gate close"))

    work_once(test_url)
    old = [d for d in client.get("/api/admin/documents").json()
           if d["title"] == "Hostel Rules" and d["version"] == 1]
    assert old[0]["status"] == "superseded"
    hits = searchable(test_url, "when does the hostel gate close")
    assert any("11:15 pm" in c for c in hits) and not any("10:30 pm" in c for c in hits)


def test_unreadable_file_fails_and_nothing_becomes_searchable(client, uploads, test_url):
    login(client, ADMIN)
    doc_id = upload(client, data=b"not really a pdf", name="broken.pdf").json()["id"]
    _, state = work_once(test_url)
    doc = client.get(f"/api/admin/documents/{doc_id}").json()
    assert state == "failed" and doc["status"] == "failed" and doc["chunks"] == 0
    assert "could not read the PDF" in doc["job"]["error"]


def test_unexpected_errors_are_retried_then_given_up(client, uploads, test_url, monkeypatch):
    async def index_then_crash(db, doc, data, on_progress):
        await real_index(db, doc, data, on_progress)   # chunks written, then...
        raise RuntimeError("disk full")
    real_index = documents.index
    monkeypatch.setattr(documents, "index", index_then_crash)

    login(client, ADMIN)
    doc_id = upload(client).json()["id"]
    states = [work_once(test_url)[1] for _ in range(worker.MAX_ATTEMPTS)]
    doc = client.get(f"/api/admin/documents/{doc_id}").json()
    assert states == ["queued"] * (worker.MAX_ATTEMPTS - 1) + ["failed"]
    assert doc["status"] == "failed" and doc["chunks"] == 0       # rolled back every time
    assert doc["job"]["attempts"] == worker.MAX_ATTEMPTS and doc["job"]["error"] == "disk full"


def test_a_locked_job_is_skipped_by_other_workers(client, uploads, test_url, seeded):
    login(client, ADMIN)
    first = upload(client).json()["job"]
    second = upload(client, data=LIBRARY + b"\nRenewals are allowed once.\n").json()
    with psycopg.connect(seeded) as other_worker:       # holds the first job's row lock
        locked = other_worker.execute(
            "SELECT id FROM ingestion_jobs WHERE state = 'queued' ORDER BY created_at "
            "LIMIT 1 FOR UPDATE").fetchone()[0]
        job = run(test_url, worker.claim)
        other_worker.rollback()
    assert first["state"] == "queued" and job.id != locked
    assert job.document_id == second["id"]


def test_concurrent_claims_never_take_the_same_job(client, uploads, test_url):
    login(client, ADMIN)
    for i in range(3):
        upload(client, data=LIBRARY + f"\nRule {i}.\n".encode(), title=f"Library Rules {i}")

    async def five_workers(engine):
        return await asyncio.gather(*(worker.claim(engine) for _ in range(5)))
    claims = run(test_url, five_workers)
    taken = [c.id for c in claims if c is not None]
    assert len(taken) == len(set(taken)) == 3


def test_stale_jobs_are_reclaimed_then_given_up(client, uploads, test_url, seeded):
    login(client, ADMIN)
    doc_id = upload(client).json()["id"]
    run(test_url, worker.claim)                         # this worker then "crashes"

    def age_job(attempts):
        with psycopg.connect(seeded) as c:
            c.execute("UPDATE ingestion_jobs SET updated_at = now() - %s, attempts = %s "
                      "WHERE document_id = %s",
                      (worker.STALE_AFTER + timedelta(minutes=1), attempts, doc_id))

    age_job(1)
    job = run(test_url, worker.claim)
    assert job.document_id == doc_id and job.attempts == 2

    age_job(worker.MAX_ATTEMPTS)
    assert run(test_url, worker.claim) is None
    doc = client.get(f"/api/admin/documents/{doc_id}").json()
    assert doc["status"] == "failed" and doc["job"]["state"] == "failed"


def test_running_worker_wakes_on_notify_and_stops_cleanly(uploads, test_url):
    """A long poll interval, so only the notification can explain a prompt pick-up."""
    async def scenario():
        shutdown = asyncio.Event()
        task = asyncio.create_task(worker.run_worker(test_url, shutdown, poll_seconds=600))
        await asyncio.sleep(1)                          # let it LISTEN and go idle

        async def upload_directly(db):
            admin_id = await db.scalar(select(User.id).where(User.email == ADMIN))
            doc = await documents.register(db, title="Library Rules", category="other",
                                           file_name="library.md", data=LIBRARY,
                                           uploaded_by=admin_id)
            await worker.enqueue(db, doc, LIBRARY, "text/markdown")
            return doc.id
        doc_id = await in_session(test_url, upload_directly, commit=True)

        async def state(db):
            return await db.scalar(select(IngestionJob.state)
                                   .where(IngestionJob.document_id == doc_id))
        for _ in range(60):
            if await in_session(test_url, state) == "done":
                break
            await asyncio.sleep(0.5)
        shutdown.set()
        await asyncio.wait_for(task, timeout=5)
        return await in_session(test_url, state)

    assert asyncio.run(scenario()) == "done"
