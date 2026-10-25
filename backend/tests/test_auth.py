"""Login, sessions, logout and role checks over the real HTTP API."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from campusgpt.auth import COOKIE_NAME, CurrentUser, require_role, token_digest
from tests.conftest import ADMIN, DEMO_PASSWORD, REGULAR, SHORTAGE, login


@pytest.fixture
def app(app):
    # A route that exists only in tests, to exercise the admin role check.
    @app.get("/api/test/admin-only")
    async def admin_only(user: CurrentUser = Depends(require_role("admin"))):
        return {"email": user.email}

    return app


def audit(conn, action):
    return conn.execute("SELECT u.email, a.outcome FROM audit_logs a "
                        "LEFT JOIN users u ON u.id = a.user_id "
                        "WHERE a.action = %s ORDER BY a.id DESC LIMIT 1", (action,)).fetchone()


# -- login ---------------------------------------------------------------------------------
def test_login_sets_an_http_only_cookie_and_returns_the_profile(client):
    r = login(client, REGULAR)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "student"
    assert body["student"]["program"] and body["student"]["roll_no"]
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()


def test_email_is_case_and_whitespace_insensitive(client):
    assert login(client, f"  {ADMIN.upper()} ").status_code == 200


@pytest.mark.parametrize("email,password", [
    (REGULAR, "wrong-password"),
    ("nobody@demo.campusgpt.example", DEMO_PASSWORD),
])
def test_bad_credentials_are_rejected_with_one_message(client, email, password):
    r = login(client, email, password)
    assert r.status_code == 401
    assert r.json()["detail"] == "Incorrect email or password"
    assert COOKIE_NAME not in client.cookies


def test_synthetic_students_without_a_password_cannot_log_in(client, conn):
    email = conn.execute("SELECT email FROM users WHERE password_hash IS NULL LIMIT 1").fetchone()[0]
    assert login(client, email, "").status_code == 401


def test_logins_are_audited_without_secrets(client, conn):
    login(client, REGULAR, "wrong-password")
    assert audit(conn, "login") == (REGULAR, "denied")
    login(client, REGULAR)
    assert audit(conn, "login") == (REGULAR, "success")
    detail = conn.execute("SELECT detail::text FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert detail is None or DEMO_PASSWORD not in detail


# -- sessions ------------------------------------------------------------------------------
def test_me_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401


def test_database_stores_only_the_token_digest(client, conn):
    login(client, REGULAR)
    token = client.cookies[COOKIE_NAME]
    assert conn.execute("SELECT count(*) FROM sessions WHERE id = %s", (token,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM sessions WHERE id = %s",
                        (token_digest(token),)).fetchone()[0] == 1


def test_forged_and_expired_tokens_are_rejected(client, seeded):
    import psycopg
    login(client, REGULAR)
    token = client.cookies[COOKIE_NAME]
    with psycopg.connect(seeded) as c:
        c.execute("UPDATE sessions SET expires_at = %s WHERE id = %s",
                  (datetime.now(UTC) - timedelta(seconds=1), token_digest(token)))
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(COOKIE_NAME, "forged-token")
    assert client.get("/api/auth/me").status_code == 401


def test_logout_invalidates_the_token_even_if_replayed(client, conn):
    login(client, REGULAR)
    token = client.cookies[COOKIE_NAME]
    assert client.post("/api/auth/logout").status_code == 204
    assert audit(conn, "logout") == (REGULAR, "success")
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/auth/me").status_code == 401


# -- isolation and roles -------------------------------------------------------------------
def test_each_student_sees_only_their_own_identity(app):
    with TestClient(app) as a, TestClient(app) as b:
        login(a, REGULAR)
        login(b, SHORTAGE)
        me_a, me_b = a.get("/api/auth/me").json(), b.get("/api/auth/me").json()
    assert me_a["email"] == REGULAR and me_b["email"] == SHORTAGE
    assert me_a["student"]["roll_no"] != me_b["student"]["roll_no"]


def test_admin_has_no_student_profile(client):
    login(client, ADMIN)
    assert client.get("/api/auth/me").json() == {"email": ADMIN, "role": "admin", "student": None}


def test_role_check(client):
    assert client.get("/api/test/admin-only").status_code == 401
    login(client, REGULAR)
    assert client.get("/api/test/admin-only").status_code == 403
    login(client, ADMIN)
    assert client.get("/api/test/admin-only").json() == {"email": ADMIN}
