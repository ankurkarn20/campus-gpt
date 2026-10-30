"""Answer verification: figures must come from what the model was given."""
import pytest

from campusgpt.verify import claims, feedback, unsupported

RECORDS = [{"tool": "get_my_exams", "result": [
    {"course": "CSE301", "date": "2026-11-02", "start": "14:00:00", "room": "A-101",
     "attendance": 68.42, "balance": "160000.00"}]}]


@pytest.mark.parametrize("answer", [
    "Your attendance is 68.4%, or about 68%.",
    "The CSE301 exam is on 2nd November 2026 at 2 PM in A-101.",
    "It starts at 14:00 on 02/11/2026.",
    "You owe ₹1,60,000 (1.6 lakh).",
    "Minimum is 75% [Attendance Policy §3.1]. Today is 13 October.",
])
def test_figures_from_the_records_prompt_or_question_are_supported(answer):
    messages = [{"role": "system", "content": "Today is Tuesday 13 October 2026."},
                {"role": "user", "content": "Do I need 75%?"}]
    assert unsupported(answer, messages, RECORDS) == []


def test_invented_figures_are_reported_once():
    answer = "Your exam is on 9 November in A-205, and 9 November is a Monday. You owe ₹3 lakh."
    assert unsupported(answer, [], RECORDS) == ["9", "205", "3 lakh"]


def test_totals_and_differences_of_records_are_supported():
    fees = [{"tool": "get_my_fee_status", "result": [
        {"amount": 195000.0, "balance": 160000.0}, {"amount": 3500.0, "balance": "3500.00"}]}]
    attendance = [{"tool": "get_my_attendance", "result": [{"held": 38, "attended": 26}]}]
    assert unsupported("Total due: ₹1,63,500.", [], fees) == []
    assert unsupported("You missed 12 classes.", [], attendance) == []
    passages = [{"tool": "search_university_documents", "result": [{"text": "7 days, 30 days"}]}]
    assert unsupported("within 37 days", [], passages) == ["37"]


def test_times_inside_timestamps_count_in_12_hour_form():
    exams = [{"tool": "get_my_exams", "result": [{"starts_at": "2026-11-06T14:00:00+05:30"}]}]
    assert unsupported("Quiz on 6 November at 2:00 PM.", [], exams) == []


def test_rounding_is_only_as_loose_as_the_digits_written():
    assert unsupported("68.5%", [], RECORDS) == ["68.5"]
    assert unsupported("68%", [], RECORDS) == []


def test_list_markers_section_numbers_and_codes_are_not_figures():
    answer = "1. Attend CSE301 [Attendance Policy §4.2]\n2. Pay fees"
    assert [c.text for c in claims(answer)] == []


def test_the_assistants_own_earlier_answers_are_not_a_source():
    messages = [{"role": "assistant", "content": "You can miss 9 classes."}]
    assert unsupported("You can miss 9 classes.", messages, []) == ["9"]


def test_feedback_names_what_failed():
    text = feedback(["9"], ["Exam Rules §12"])
    assert "9" in text and "Exam Rules §12" in text and "student" in text


def test_numbers_spelled_out_in_passages_are_supported():
    passages = [{"tool": "search_university_documents", "result": [
        {"text": "Apply within seven days; hostel leave needs Forty-eight hours' notice."}]}]
    assert unsupported("Apply within 7 days, 48 hours ahead.", [], passages) == []
    assert unsupported("Apply within 8 days.", [], passages) == ["8"]
