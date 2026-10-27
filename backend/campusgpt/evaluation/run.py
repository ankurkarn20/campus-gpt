"""Running the benchmark: retrieval quality per search mode, and the chat end to end under
each configuration.

Chat runs go through chat.run(), the same code the API serves, as the demo students. Each
run deletes the conversations it created, so the demo accounts' history stays clean (and
two runs can go on at once); the tool calls stay in the audit log like any other.
"""
import asyncio
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt import chat, retrieval, tools
from campusgpt.auth import CurrentUser
from campusgpt.evaluation.questions import QUESTIONS, STUDENTS, Question, Records, records
from campusgpt.evaluation.scoring import check, cites_expected
from campusgpt.llm import Provider, ProviderUnavailable
from campusgpt.models import Conversation
from campusgpt.security import account

CONFIGS = {"plain": chat.Pipeline(documents=False, records=False),
           "rag": chat.Pipeline(records=False),
           "db": chat.Pipeline(documents=False),
           "full": chat.FULL}
TITLE = "[benchmark]"


# -- retrieval -----------------------------------------------------------------------------
@dataclass
class RetrievalResult:
    id: str
    lang: str
    mode: str
    rank: int | None          # 1-based rank of the first passage from an expected section
    ms: float


async def retrieval_eval(db: AsyncSession, modes=("hybrid", "semantic", "lexical"),
                         k: int = 10) -> list[RetrievalResult]:
    out = []
    for q in QUESTIONS:
        if q.category != "policy":
            continue
        for mode in modes:
            started = time.perf_counter()
            passages = await retrieval.search(db, q.text(None), k=k, mode=mode)
            ms = (time.perf_counter() - started) * 1000
            rank = next((i for i, p in enumerate(passages, 1)
                         if cites_expected([tools.citation(p.document, p.section)], q.cites)),
                        None)
            out.append(RetrievalResult(q.id, q.lang, mode, rank, round(ms, 1)))
    return out


def retrieval_summary(results: list[RetrievalResult]) -> list[dict]:
    rows = []
    for mode in dict.fromkeys(r.mode for r in results):
        for lang in ("all", "en", "hinglish"):
            rs = [r for r in results if r.mode == mode and lang in ("all", r.lang)]
            ms = sorted(r.ms for r in rs)
            rows.append({"mode": mode, "lang": lang, "n": len(rs),
                         "hit@1": share(r.rank == 1 for r in rs),
                         "hit@4": share(r.rank is not None and r.rank <= 4 for r in rs),
                         "mrr@10": round(sum(1 / r.rank for r in rs if r.rank) / len(rs), 3),
                         "p95_ms": ms[int(0.95 * (len(ms) - 1))]})
    return rows


def share(flags) -> float:
    flags = list(flags)
    return round(sum(flags) / len(flags), 3) if flags else 0.0


# -- the chat ------------------------------------------------------------------------------
class DailyLimit(Exception):
    """The hosted model's quota is used up for longer than it is worth waiting."""


class Patient:
    """Wraps a provider and waits out rate limits (HTTP 429) instead of failing, up to
    `max_wait` seconds at a time. Free hosted tiers limit tokens per minute."""

    def __init__(self, inner: Provider, max_wait: float = 120):
        self.inner, self.max_wait, self.waited = inner, max_wait, 0.0

    async def stream(self, messages, tools_):
        for attempt in range(8):
            started = False
            try:
                async for event in self.inner.stream(messages, tools_):
                    started = True
                    yield event
                return
            except ProviderUnavailable as e:
                if started or "HTTP 429" not in str(e) or attempt == 7:
                    raise
                wait = retry_after(str(e))
                if wait > self.max_wait:
                    raise DailyLimit(str(e)) from e
                self.waited += wait
                await asyncio.sleep(wait)


def retry_after(message: str) -> float:
    """Seconds from "Please try again in 1m2.5s" or "in 75ms" (Groq), plus a margin; 20 s
    if absent."""
    if m := re.search(r"try again in ([\d.]+)ms", message):
        return float(m.group(1)) / 1000 + 1
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?", message)
    if not m or not any(m.groups()):
        return 20.0
    h, mins, s = (float(g or 0) for g in m.groups())
    return h * 3600 + mins * 60 + s + 1


@dataclass
class ChatResult:
    id: str
    category: str
    lang: str
    config: str
    model: str
    question: str
    answer: str
    facts: list[str]
    found: list[bool]
    correct: bool
    tools: list[str]                     # called, in order (prefetches included)
    tools_ok: bool | None                # the expected tools were called (None: none expected)
    citations: list[dict]
    cite_expected: bool | None           # an expected section was cited (None: none expected)
    citations_verified: bool             # every citation is backed by a retrieved passage
    seconds: float                       # excluding time spent waiting out rate limits
    error: str | None = None
    tags: list[str] = field(default_factory=list)


async def ask(db: AsyncSession, provider: Provider, user: CurrentUser, question: str,
              now: datetime, pipeline: chat.Pipeline,
              created: list[int]) -> tuple[str, list[dict], list[dict], str | None]:
    conv = Conversation(user_id=user.id, title=f"{TITLE} {question[:150]}")
    db.add(conv)
    await db.commit()
    created.append(conv.id)
    answer, sources, citations, error = "", [], [], None
    async for event in chat.run(db, provider, user, question, conv.id, now, pipeline=pipeline):
        if event.kind == "token":
            answer += event.data["text"]
        elif event.kind == "tool":
            sources.append(event.data)
        elif event.kind == "done":
            citations = event.data["citations"]
        elif event.kind == "error":
            error = event.data["message"]
    return answer.strip(), sources, citations, error


def score(q: Question, r: Records, config: str, model: str, question: str, answer: str,
          sources: list[dict], citations: list[dict], seconds: float,
          error: str | None) -> ChatResult:
    facts = q.expected(r)
    found = check(answer, facts)
    called = [s["tool"] for s in sources]
    tools_ok = (all(any(t in group for t in called) for group in q.tools)
                if q.tools and config != "plain" else None)
    cited = [c["cite"] for c in citations]
    return ChatResult(
        q.id, q.category, q.lang, config, model, question, answer, [f.label for f in facts],
        found, bool(facts) and all(found) and not error, called, tools_ok, citations,
        cites_expected(cited, q.cites) if q.cites else None,
        all(c["verified"] for c in citations), round(seconds, 2), error, list(q.tags))


async def chat_eval(db: AsyncSession, provider: Provider, model: str, configs: list[str],
                    now: datetime, only: Callable[[str, str], bool] | None = None
                    ) -> AsyncIterator[ChatResult]:
    """Results of the questions (those for which only(config, id) holds, if given)."""
    patient = provider if isinstance(provider, Patient) else Patient(provider)
    users, truth, created = {}, {}, []
    for who, email in STUDENTS.items():
        users[who], st = await account(db, email)
        truth[who] = await records(db, st.id, now)
    try:
        for config in configs:
            for q in QUESTIONS:
                if only and not only(config, q.id):
                    continue
                text = q.text(truth[q.who])
                started, waited = time.monotonic(), patient.waited
                # A model error (e.g. a request too large) comes back as `error`.
                answer, sources, citations, error = await ask(
                    db, patient, users[q.who], text, now, CONFIGS[config], created)
                seconds = time.monotonic() - started - (patient.waited - waited)
                yield score(q, truth[q.who], config, model, text, answer, sources, citations,
                            seconds, error)
    finally:
        await db.rollback()
        await db.execute(delete(Conversation).where(Conversation.id.in_(created)))
        await db.commit()


def chat_summary(results: list[ChatResult]) -> list[dict]:
    """Per model and configuration: overall and per-category correctness, tool selection,
    citations, and latency."""
    rows = []
    for key in dict.fromkeys((r.model, r.config) for r in results):
        rs = [r for r in results if (r.model, r.config) == key]
        secs = sorted(r.seconds for r in rs if not r.error)
        with_tools = [r for r in rs if r.tools_ok is not None]
        with_cites = [r for r in rs if r.cite_expected is not None]
        cited = [r for r in rs if r.citations]
        rows.append({
            "model": key[0], "config": key[1], "n": len(rs),
            "correct": share(r.correct for r in rs),
            **{f"correct_{c}": share(r.correct for r in rs if r.category == c)
               for c in ("policy", "records", "combined")},
            **{f"correct_{lang}": share(r.correct for r in rs if r.lang == lang)
               for lang in ("en", "hinglish")},
            "regressions": share(r.correct for r in rs if "regression" in r.tags),
            "tools_ok": share(r.tools_ok for r in with_tools) if with_tools else None,
            "cites_expected": share(r.cite_expected for r in with_cites),
            "answers_with_unverified_citations": sum(not r.citations_verified for r in cited),
            "errors": sum(bool(r.error) for r in rs),
            "median_s": secs[len(secs) // 2] if secs else None,
        })
    return rows


def as_dicts(items) -> list[dict]:
    return [asdict(i) for i in items]
