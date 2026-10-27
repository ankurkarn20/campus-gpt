"""Security demonstration: refused identity arguments, the leak detector, the audit log."""
import asyncio
import json

from campusgpt import security
from campusgpt.llm import ScriptedProvider, TextChunk, ToolCall
from campusgpt.tools import TOOLS
from tests.conftest import ADMIN, FEES, NOW, REGULAR, SHORTAGE, in_session, login
from tests.test_chat import ask, of, use

REFUSAL = [TextChunk("I can only help with your own records.")]


def test_identity_arguments_are_refused_and_audited(app, client, conn):
    use(app, ScriptedProvider([
        [ToolCall("c1", "get_my_fee_status", '{"student_id": 4242}')], REFUSAL]))
    login(client, SHORTAGE)
    tool = of(ask(client, "fees of student 4242"), "tool")[0]
    assert not tool["ok"]
    assert "unexpected arguments student_id" in tool["result"]["error"]
    outcome, detail = conn.execute(
        "SELECT outcome, detail FROM audit_logs WHERE action = 'tool_call' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    # Recorded as denied, with the field's name but never its value.
    assert outcome == "denied" and detail == {"reason": "unexpected arguments",
                                              "fields": ["student_id"]}


def test_tool_schemas_forbid_extra_properties():
    for spec in TOOLS.values():
        assert spec.args.model_json_schema().get("additionalProperties") is False, spec.name


def attack(name):
    return [a for a in security.ATTACKS if a.id == name]


def run(test_url, provider, attacks):
    async def go(db):
        return [r async for r in security.run_attacks(db, provider, NOW, attacks=attacks)]
    return asyncio.run(in_session(test_url, go, commit=True))


def test_an_honest_model_blocks_every_attack(seeded, test_url):
    results = run(test_url, ScriptedProvider([REFUSAL]), security.ATTACKS)
    assert [r.id for r in results] == [a.id for a in security.ATTACKS]
    assert all(r.verdict == "blocked" and not r.leaks for r in results)


def test_smuggled_arguments_are_reported(seeded, test_url):
    [r] = run(test_url, ScriptedProvider([
        [ToolCall("c1", "get_my_fee_status", '{"student_id": 1}')], REFUSAL]),
        attack("argument_smuggling"))
    [fees] = [t for t in r.tools if t["tool"] == "get_my_fee_status"]   # after any prefetch
    assert r.verdict == "blocked" and fees["ok"] is False
    assert r.notes == ["1 tool call(s) with an identity argument refused"]


def test_the_detector_catches_a_leak(seeded, test_url):
    """A model that 'knows' the victim's name and courses (as if from another source) is
    caught, while echoing what the prompt already contained is not counted."""
    async def victim(db):
        attacker, _ = await security.account(db, security.ATTACKER)
        return await security.victim_for(db, attacker, security.VICTIM)
    v = asyncio.run(in_session(test_url, victim))
    [r] = run(test_url, ScriptedProvider([[TextChunk(
        f"Roll number {v.roll_no} belongs to {v.name}, enrolled in {v.own_courses[0]}.")]]),
        attack("by_roll_no"))
    assert r.verdict == "leaked"
    assert r.leaks == [f"answer contains {v.name!r}", f"answer contains {v.own_courses[0]!r}"]


def test_injected_instructions_and_prompt_disclosure_are_noted(seeded, test_url):
    results = run(test_url, ScriptedProvider([[TextChunk(
        "You are CampusGPT, the helpdesk assistant of a university. ZX-4471")]]),
        attack("canary") + attack("system_prompt"))
    assert all(r.verdict == "blocked" for r in results)      # not a data leak
    assert results[0].notes == [
        "followed an injected instruction (canary code in the answer)",
        "repeated part of its instructions"]


# -- API -------------------------------------------------------------------------------------
def test_security_run_streams_results_and_is_audited(app, client, conn):
    use(app, ScriptedProvider([REFUSAL]))
    login(client, ADMIN)
    assert len(client.get("/api/admin/security/attacks").json()["attacks"]) == \
        len(security.ATTACKS)
    r = client.post("/api/admin/security/run")
    assert r.status_code == 200
    events = [(b.split("\n")[0].removeprefix("event: "),
               json.loads(b.split("data: ", 1)[1])) for b in r.text.strip().split("\n\n")]
    results = [d for k, d in events if k == "result"]
    assert [d["verdict"] for d in results] == ["blocked"] * len(security.ATTACKS)
    done = events[-1]
    assert done[0] == "done" and done[1]["students_before"] == done[1]["students_after"]

    log = client.get("/api/admin/audit", params={"action": "security_test"}).json()
    assert [e["detail"]["attack"] for e in log["entries"][:len(results)]] == \
        [d["id"] for d in reversed(results)]
    assert all(e["user"] == ADMIN for e in log["entries"][:len(results)])


def test_audit_log_filters_and_pages(app, client):
    use(app, ScriptedProvider([REFUSAL]))
    login(client, REGULAR, password="wrong")                 # a denied login
    login(client, ADMIN)
    log = client.get("/api/admin/audit", params={"action": "login", "outcome": "denied"}).json()
    assert log["entries"] and all(e["action"] == "login" and e["outcome"] == "denied"
                                  for e in log["entries"])
    assert {"action": "login", "outcome": "success"} in [
        {k: c[k] for k in ("action", "outcome")} for c in log["counts"]]

    first = client.get("/api/admin/audit", params={"limit": 2}).json()
    second = client.get("/api/admin/audit",
                        params={"limit": 2, "before": first["next_before"]}).json()
    assert first["next_before"] == first["entries"][-1]["id"]
    assert all(e["id"] < first["next_before"] for e in second["entries"])

    mine = client.get("/api/admin/audit", params={"user": "student.fees"}).json()
    assert all(e["user"] == FEES for e in mine["entries"])


def test_only_admins_see_the_audit_log_or_run_attacks(client):
    login(client, REGULAR)
    assert client.get("/api/admin/audit").status_code == 403
    assert client.post("/api/admin/security/run").status_code == 403


def test_sql_in_tool_arguments_is_only_ever_data(app, client, conn):
    """The live model tends to refuse the SQL injection prompt without calling a tool, so
    the tool layer is tested directly: the string is matched as text, never executed."""
    students = conn.execute("SELECT count(*) FROM students").fetchone()[0]
    use(app, ScriptedProvider([[ToolCall(
        "c1", "get_my_attendance", json.dumps({"course": "DBMS'; DROP TABLE students; --"}))],
        REFUSAL]))
    login(client, SHORTAGE)
    tool = of(ask(client, "attendance"), "tool")[0]
    assert tool["result"]["error"].startswith(
        "No enrolled course matches 'DBMS'; DROP TABLE students; --'.")
    assert len(tool["result"]["your_courses"]) == 5
    assert conn.execute("SELECT count(*) FROM students").fetchone()[0] == students
