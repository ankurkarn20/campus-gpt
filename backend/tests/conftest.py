"""Shared fixtures. Tests run against TEST_DATABASE_URL, never the development database."""
import argparse
from datetime import date
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from campusgpt.config import get_settings
from campusgpt.seed.__main__ import libpq_url
from campusgpt.seed.generate import generate
from campusgpt.seed.load import load

AS_OF = date(2026, 10, 13)
STUDENTS = 300
SEED = 7
DEMO_PASSWORD = "test-demo-password"


@pytest.fixture(scope="session")
def test_url() -> str:
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    return url


@pytest.fixture(scope="session")
def migrated(test_url) -> str:
    """Rebuild the test schema from scratch, exercising downgrade and upgrade."""
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.cmd_opts = argparse.Namespace(x=[f"url={test_url}"])
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return libpq_url(test_url)


@pytest.fixture(scope="session")
def dataset():
    return generate(STUDENTS, SEED, AS_OF, DEMO_PASSWORD)


@pytest.fixture(scope="session")
def seeded(migrated, dataset) -> str:
    load(migrated, dataset)
    return migrated


@pytest.fixture
def conn(seeded):
    """A connection whose changes are rolled back after the test."""
    with psycopg.connect(seeded) as connection:
        yield connection
        connection.rollback()
