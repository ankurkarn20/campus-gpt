# Evaluation method

The results are in [RESULTS.md](RESULTS.md), generated from the raw data in `results/`.
The code is `backend/campusgpt/evaluation/`.

## Question set

50 questions (`questions.py`), asked as the three demo students:

| Category | n | What it tests |
|---|---|---|
| Policy | 26 (20 English, 6 Hinglish) | Rules from the synthetic policy documents; one paraphrase ("rechecked" for "re-evaluation") |
| Records | 17 (12 English, 5 Hinglish) | The student's own attendance, exams, assignments, fees and timetable, and attendance arithmetic |
| Combined | 7 | Records and rules together: end-term eligibility, admit card, condonation, late fees |

Expected answers to policy questions come from the documents. Expected answers about a
student's records are **computed from the database when the benchmark runs**, with the same
functions as the dashboard, because the synthetic data is generated relative to the day it
is seeded. Four questions (tagged `regression`) are the failures found when the system was
tested by hand on 27 Oct 2026: "how many holidays can i take in computer network", "next
class when", "where is my compiler design class", and the Hinglish holidays question.

## Scoring (by code, no model judge)

- **Correct**: every expected fact appears in the answer. A fact is a number (within 0.05,
  so 68.4 matches 68.42; digit grouping ignored, so ₹1,60,000 matches 160000; "seven"
  matches 7), a date or time in any common format, or one of several phrases.
- **Tools**: the expected tools were called. Each expectation is a set of alternatives, and
  tools the chat runs itself (the policy and attendance prefetches) count.
- **Cited**: the answer cites an expected section, e.g. [Attendance Policy §4] or a clause
  of it.
- **Unverified citations**: answers citing a section that no retrieved passage backs
  (`chat.check_citations`).
- **Latency**: wall-clock time per answer, excluding time spent waiting out the hosted
  model's rate limits.

Fact matching can be too lenient (a number that appears in the answer for another reason).
It cannot be too strict about wording, because it never matches wording.

## Configurations

`chat.Pipeline` switches parts of the production chat off; everything else is the same code.

| Configuration | Documents (search tool, policy prefetch) | Records (record tools, attendance prefetch, course resolution) | Prompt |
|---|---|---|---|
| Plain LLM | – | – | a generic helpdesk prompt with the student's name and programme |
| RAG only | ✓ | – | CampusGPT's |
| DB tools only | – | ✓ (the eligibility check returns no policy passages) | CampusGPT's |
| Full CampusGPT | ✓ | ✓ | CampusGPT's |

Models: the local `qwen3:4b-instruct-2507-q4_K_M` (Ollama, laptop GPU) for all four
configurations, and the hosted `openai/gpt-oss-120b` (Groq free tier) for the full system.

## Retrieval

The 26 policy questions are searched in each mode (`hybrid`, `semantic`, `lexical`;
`retrieval.search`). The measure is the rank of the first passage from an expected
section among the top 10: Hit@1, Hit@4 (the chat gives the model 4 passages) and MRR@10,
with 95th-percentile latency (NFR-P3: under 500 ms).

## Security baseline

`text_to_sql.py` implements the design CampusGPT avoids: the model is shown the schema,
told the logged-in student's id and told to return only that student's data, and writes
SQL that is executed. The nine attacks of the security demonstration (`campusgpt.security`)
are run against both designs and judged by the same code. The baseline's SQL runs in a
`READ ONLY` transaction with a 5 s timeout that is always rolled back, so it can read the
development database but never change it. Besides the victim's identifiers, the judge
counts any other student's roll number, name or student id in the returned rows.

## Reproducing

```sh
make db-start && make seed      # data as of today
make llm                        # in another terminal
make bench-retrieval
make bench                      # ~25 min on the laptop GPU
make bench-groq                 # needs GROQ_API_KEY; waits out the free tier's limits
make bench-security MODEL=local
make bench-security MODEL=groq
```

Chat results are merged by (configuration, question), so a run cut short can be continued:
`cd backend && ../.venv/bin/python -m campusgpt.evaluation chat --model groq --configs full --only r04,r09`.
