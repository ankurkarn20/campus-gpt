"""Rate limits (NFR-S5): login per IP and per account, chat per user and per IP."""
import pytest

from campusgpt.config import get_settings
from campusgpt.llm import ScriptedProvider, TextChunk
from tests.conftest import FEES, REGULAR, SHORTAGE, login
from tests.test_chat import use


@pytest.fixture
def limits(monkeypatch):
    def set_(**values):
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), name, value)
    return set_


def test_login_is_limited_per_ip(client, limits):
    limits(login_rate_per_ip="3/minute")
    codes = [login(client, f"nobody{i}@example.com").status_code for i in range(3)]
    r = login(client, REGULAR)
    assert codes == [401, 401, 401] and r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert r.json()["detail"].startswith("Too many requests")


def test_an_account_is_throttled_after_repeated_failures(client, conn, limits):
    limits(login_max_failures=3)
    assert [login(client, FEES, "wrong").status_code for _ in range(3)] == [401] * 3
    # Even the right password is refused now, so guessing cannot continue...
    r = login(client, FEES)
    assert r.status_code == 429 and "for this account" in r.json()["detail"]
    assert int(r.headers["retry-after"]) > 14 * 60
    # ...while other accounts are unaffected.
    assert login(client, SHORTAGE).status_code == 200

    # Throttled attempts are audited but do not extend the lock: once the real failures
    # leave the window, the account opens again.
    reasons = conn.execute(
        "SELECT detail->>'reason' FROM audit_logs a JOIN users u ON u.id = a.user_id "
        "WHERE u.email = %s AND action = 'login' ORDER BY a.id DESC LIMIT 1",
        (FEES,)).fetchone()
    assert reasons == ("too many failed attempts",)
    conn.execute("UPDATE audit_logs SET created_at = now() - interval '16 minutes' "
                 "WHERE detail IS NULL AND outcome = 'denied' AND action = 'login' "
                 "AND user_id = (SELECT id FROM users WHERE email = %s)", (FEES,))
    conn.commit()
    assert login(client, FEES).status_code == 200


def test_a_successful_login_clears_earlier_failures(client, limits):
    limits(login_max_failures=3)
    for _ in range(2):
        login(client, REGULAR, "wrong")
    assert login(client, REGULAR).status_code == 200
    for _ in range(2):
        login(client, REGULAR, "wrong")
    assert login(client, REGULAR).status_code == 200      # 2 failures since the success


def chat(client):
    return client.post("/api/chat", json={"message": "hello"})


def test_chat_is_limited_per_user(app, client, limits):
    use(app, ScriptedProvider([[TextChunk("Hi.")]]))
    limits(chat_rate_per_user="2/minute")
    login(client, SHORTAGE)
    assert [chat(client).status_code for _ in range(3)] == [200, 200, 429]
    login(client, REGULAR)                                 # another student, same IP
    assert chat(client).status_code == 200


def test_chat_is_limited_per_ip(app, client, limits):
    use(app, ScriptedProvider([[TextChunk("Hi.")]]))
    limits(chat_rate_per_ip="2/minute")
    login(client, SHORTAGE)
    chat(client)
    login(client, REGULAR)
    assert [chat(client).status_code for _ in range(2)] == [200, 429]
