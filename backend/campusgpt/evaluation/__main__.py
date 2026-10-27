"""Command line for the evaluation. Results go to docs/evaluation/results/*.json and the
report, docs/evaluation/RESULTS.md, is rebuilt from them after every run.

    python -m campusgpt.evaluation retrieval                 # no model needed
    python -m campusgpt.evaluation chat --model local --configs full,rag,db,plain
    python -m campusgpt.evaluation chat --model groq --configs full --only r04,r09
    python -m campusgpt.evaluation security --model local    # text-to-SQL vs CampusGPT
    python -m campusgpt.evaluation report

Chat results are merged into the model's file by (config, question), so a run cut short
(e.g. by the hosted model's daily quota) can be continued with --only, and answers lost to
a model error re-asked with --redo-errors.
"""
import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from campusgpt.config import REPO_ROOT, get_settings
from campusgpt.evaluation import report, run, text_to_sql
from campusgpt.llm import OpenAICompatible, make_provider
from campusgpt.student import IST

RESULTS = REPO_ROOT / "docs" / "evaluation" / "results"
GROQ_URL = "https://api.groq.com/openai/v1"


def provider_for(name: str) -> tuple[OpenAICompatible, str]:
    s = get_settings()
    if name == "groq":
        if not s.groq_api_key:
            sys.exit("GROQ_API_KEY is not set (add it to .env)")
        return OpenAICompatible(GROQ_URL, s.groq_api_key, s.groq_model, 120), s.groq_model
    return make_provider(s), s.llm_model


def load(path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save(path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")


async def main(args) -> int:
    from campusgpt.db import make_async_engine

    now = datetime.now(IST)
    engine = make_async_engine()
    provider = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            if args.command == "retrieval":
                results = await run.retrieval_eval(db)
                save(RESULTS / "retrieval.json", {"run_at": now.isoformat(),
                                                   "results": run.as_dicts(results)})
                for row in run.retrieval_summary(results):
                    print(row)
            elif args.command == "chat":
                provider, model = provider_for(args.model)
                path = RESULTS / f"chat-{args.model}.json"
                data = load(path)
                kept = {(r["config"], r["id"]): r for r in data.get("results", [])}
                ids = set(args.only.split(",")) if args.only else None
                failed = {k for k, r in kept.items() if r["error"]}

                def only(config, qid):
                    return ((ids is None or qid in ids)
                            and (not args.redo_errors or (config, qid) in failed))
                try:
                    async for r in run.chat_eval(db, provider, model, args.configs.split(","),
                                                 now, only):
                        kept[(r.config, r.id)] = asdict(r)
                        mark = "ok  " if r.correct else "FAIL"
                        print(f"{mark} {r.config:<5} {r.id} {r.seconds:>5}s "
                              f"{','.join(r.tools) or '-'}"
                              + (f"  error: {r.error}" if r.error else ""), flush=True)
                        save(path, {"model": model, "run_at": now.isoformat(),
                                    "results": list(kept.values())})
                except run.DailyLimit as e:
                    print(f"Stopped: the model's quota is used up ({e}). Continue later "
                          "with --only for the questions not yet answered.")
            elif args.command == "security":
                provider, model = provider_for(args.model)
                from campusgpt import security
                attacks = security.ATTACKS + text_to_sql.INDIRECT
                baseline = await text_to_sql.run_attacks(db, run.Patient(provider), now, attacks)
                campus = [r async for r in security.run_attacks(db, run.Patient(provider), now,
                                                                attacks=attacks)]
                save(RESULTS / f"security-{args.model}.json", {
                    "model": model, "run_at": now.isoformat(),
                    "text_to_sql": run.as_dicts(baseline), "campusgpt": run.as_dicts(campus)})
                for b, c in zip(baseline, campus, strict=True):
                    print(f"{b.id:<20} text-to-SQL: {b.verdict:<8} CampusGPT: {c.verdict}")
    finally:
        if provider:
            await provider.aclose()
        await engine.dispose()
    report.write(RESULTS, REPO_ROOT / "docs" / "evaluation" / "RESULTS.md")
    print("Report: docs/evaluation/RESULTS.md")
    return 0


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m campusgpt.evaluation", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("retrieval", help="search quality per mode (no model needed)")
    c = sub.add_parser("chat", help="the question set through the chat")
    c.add_argument("--model", choices=("local", "groq"), default="local")
    c.add_argument("--configs", default="full,rag,db,plain")
    c.add_argument("--only", help="comma-separated question ids")
    c.add_argument("--redo-errors", action="store_true",
                   help="only the questions whose saved result is an error")
    s = sub.add_parser("security", help="attacks on the text-to-SQL baseline and CampusGPT")
    s.add_argument("--model", choices=("local", "groq"), default="local")
    sub.add_parser("report", help="rebuild RESULTS.md from the saved results")
    args = parser.parse_args(argv)
    if args.command == "report":
        report.write(RESULTS, REPO_ROOT / "docs" / "evaluation" / "RESULTS.md")
        return 0
    return asyncio.run(main(args))


if __name__ == "__main__":
    sys.exit(cli())
