"""Shared fixtures. Tests run against TEST_DATABASE_URL, never the development database."""
import argparse
from datetime import date, datetime, time
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from campusgpt.api.app import create_app
from campusgpt.api.student import IST, get_now
from campusgpt.config import get_settings
from campusgpt.seed.__main__ import libpq_url
from campusgpt.seed.generate import generate
from campusgpt.seed.load import load

AS_OF = date(2026, 10, 13)
STUDENTS = 300
SEED = 7
DEMO_PASSWORD = "test-demo-password"
# The API sees this as the current time, matching the dataset generated for AS_OF.
NOW = datetime.combine(AS_OF, time(12, 0), tzinfo=IST)

REGULAR = "student.regular@demo.campusgpt.example"
SHORTAGE = "student.shortage@demo.campusgpt.example"
FEES = "student.fees@demo.campusgpt.example"
ADMIN = "admin@demo.campusgpt.example"


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


@pytest.fixture
def app(seeded, test_url):
    app = create_app(test_url)
    app.dependency_overrides[get_now] = lambda: NOW
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def login(client, email, password=DEMO_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})
