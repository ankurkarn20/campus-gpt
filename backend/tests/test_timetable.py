"""The class timetable: upcoming classes on teaching days, the chat tool, the dashboard."""
from datetime import date, datetime, time, timedelta

from campusgpt.llm import ScriptedProvider, TextChunk, ToolCall
from campusgpt.student import IST, ClassSlot, upcoming_classes
from tests.conftest import NOW, SHORTAGE, login
from tests.test_chat import ask, of, use
from tests.test_student import dashboard

FRIDAY_CLASS = ClassSlot("Friday", 4, time(9), time(9, 50), "CSE301", "DBMS", "A-101", "X")
MONDAY_CLASS = ClassSlot("Monday", 0, time(14), time(14, 50), "CSE302", "OOP", "A-102", "Y")


def at(d, hour=17):
    return datetime.combine(d, time(hour), tzinfo=IST)


def test_upcoming_classes_skip_weekends_mid_terms_holidays_and_term_end():
    slots = [FRIDAY_CLASS, MONDAY_CLASS]
    # Friday evening before the mid-term week (7-12 Sep): next class is Monday the 14th.
    [first] = upcoming_classes(slots, at(date(2026, 9, 4)), limit=1)
    assert (first.date, first.code) == (date(2026, 9, 14), "CSE302")
    # Friday 2 Oct is Gandhi Jayanti: from Thursday 1 Oct the next Friday class is the 9th.
    fridays = [m.date for m in upcoming_classes([FRIDAY_CLASS], at(date(2026, 10, 1)), 2)]
    assert fridays == [date(2026, 10, 9), date(2026, 10, 16)]
    # A class later today is included, one already started is not.
    assert upcoming_classes([MONDAY_CLASS], at(date(2026, 10, 26), 13), 1)[0].date == \
        date(2026, 10, 26)
    assert upcoming_classes([MONDAY_CLASS], at(date(2026, 10, 26), 15), 1)[0].date == \
        date(2026, 11, 2)
    # Nothing after the last teaching day (22 Nov).
    assert upcoming_classes(slots, at(date(2026, 11, 20)), 10) == []


def test_dashboard_has_the_timetable_and_next_classes(client):
    data = dashboard(client, SHORTAGE)
    assert len(data["timetable"]) == 3 * len(data["attendance"])    # 3 classes a week each
    starts = [datetime.fromisoformat(m["starts_at"]) for m in data["next_classes"]]
    assert len(starts) == 5 and starts == sorted(starts) and starts[0] > NOW
    assert all(c["can_miss"] <= c["classes_left"] for c in data["attendance"])


def test_classes_tool_answers_for_a_day(app, client):
    use(app, ScriptedProvider([[ToolCall("c1", "get_my_classes", '{"day": "tomorrow"}')],
                               [TextChunk("…")]]))
    login(client, SHORTAGE)
    result = of(ask(client, "kal kaunsi classes hain?"), "tool")[0]["result"]
    tomorrow = (NOW.date() + timedelta(days=1)).isoformat()
    assert result["day"]["date"] == tomorrow and result["day"]["weekday"] == "Wednesday"
    assert result["day"]["classes"] and {m["date"] for m in result["day"]["classes"]} == \
        {tomorrow}
    assert len(result["next_classes"]) == 3 and len(result["weekly_timetable"]) == 15


def test_a_day_without_classes_says_why_and_still_gives_the_next_ones(app, client):
    """Late on a Friday: no more classes today, none tomorrow (Saturday), next on Monday."""
    from campusgpt.api.student import get_now
    app.dependency_overrides[get_now] = lambda: datetime(2026, 10, 16, 18, tzinfo=IST)
    use(app, ScriptedProvider([
        [ToolCall("c1", "get_my_classes", '{"day": "today"}')], [TextChunk("…")],
        [ToolCall("c2", "get_my_classes", '{"day": "tomorrow"}')], [TextChunk("…")]]))
    login(client, SHORTAGE)
    today, tomorrow = (of(ask(client, q), "tool")[0]["result"]
                       for q in ("next class when", "classes tomorrow?"))
    assert today["day"]["classes"] == "None: no more classes today."
    assert tomorrow["day"] == {"date": "2026-10-17", "weekday": "Saturday",
                               "classes": "None: weekend."}
    assert today["next_classes"][0]["date"] == "2026-10-19"          # Monday
