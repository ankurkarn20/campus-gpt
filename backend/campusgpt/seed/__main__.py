"""Generate, load and validate the synthetic university.

    python -m campusgpt.seed [--students 5000] [--seed 42] [--as-of YYYY-MM-DD]

Loading replaces all existing data in the target database.
"""
import argparse
import sys
import time
from datetime import date

from campusgpt.config import get_settings
from campusgpt.seed.generate import generate
from campusgpt.seed.load import load
from campusgpt.seed.validate import validate


def libpq_url(sqlalchemy_url: str) -> str:
    """psycopg wants postgresql://..., SQLAlchemy uses postgresql+psycopg://..."""
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--students", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                        help="the 'current' date of the dataset (default: today)")
    parser.add_argument("--database-url", help="defaults to DATABASE_URL from .env")
    args = parser.parse_args(argv)

    settings = get_settings()
    url = libpq_url(args.database_url or settings.database_url)

    started = time.perf_counter()
    try:
        ds = generate(args.students, args.seed, args.as_of, settings.demo_password)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    generated = time.perf_counter()
    load(url, ds)
    loaded = time.perf_counter()

    print(f"Synthetic university for term {ds.term.code}, as of {ds.as_of} (seed {args.seed})")
    for table, n in ds.counts().items():
        print(f"  {table:<18} {n:>10,}")
    print(f"Generated in {generated - started:.1f} s, loaded in {loaded - generated:.1f} s")

    failures = {name: n for name, n in validate(url).items() if n}
    if failures:
        print("\nVALIDATION FAILED:")
        for name, n in failures.items():
            print(f"  {n:>8,}  {name}")
        return 1
    print("All validation checks passed.")

    print(f"\nDemo accounts (password: value of DEMO_PASSWORD, default '{settings.demo_password}'):")
    for account in ds.demo_accounts:
        print(f"  {account.email:<42} {account.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
