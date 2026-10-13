# CampusGPT

**AI-Powered University Intelligence and Student Assistance Platform** — a major CSE project.

CampusGPT is a chat assistant for university students. A logged-in student asks questions in plain language and gets answers grounded in two sources:

- **Their own records** — attendance, exams, assignments, fees — fetched from a PostgreSQL database through predefined, permission-checked backend tools.
- **University policy documents** — searched with retrieval-augmented generation (RAG) and cited in the answer.

Example questions:

- "What is my attendance in DBMS?"
- "How many more classes must I attend to reach 75%?"
- "Can I sit for my exam based on my attendance and the regulations?"
- "What do I need to take care of this week?"

> **All data is synthetic.** We have no access to any real university system. Every student, record and policy document in this project is generated and labelled as fictional demo data.

## Core design principles

1. **The AI never touches the database directly.** It can only call a fixed set of backend tools (e.g. `get_my_attendance`). The backend decides whose data is returned from the login session — never from the AI's request.
2. **Facts and calculations come from code, not the model.** Numbers come from the database; calculations such as attendance requirements are deterministic Python. The LLM selects tools and phrases the answer.
3. **Every answer shows its sources** — database record or a specific document chunk — and policy citations are traceable to the retrieved text.
4. **The AI provider is swappable.** One adapter, one config line. The non-chat parts of the app keep working if the AI service is down.
5. **Measured, not claimed.** An evaluation benchmark compares CampusGPT against simpler baselines.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI |
| Database | PostgreSQL + pgvector (records and document vectors in one DB) |
| Frontend | Next.js (TypeScript) |
| LLM | Free hosted API (Groq or Google Gemini) behind an adapter; optional local model via Ollama for comparison |
| Embeddings | Small local open-source embedding model (CPU) |
| Local infra | PostgreSQL installed natively (saves memory on an 8 GB laptop) |

## Getting started

Requirements: Python 3.12, PostgreSQL 16 with the pgvector extension.

```bash
cp .env.example .env              # then set the database passwords
python3 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
make db-start                     # if you use the local cluster in ~/.local/share/campus-gpt
make seed                         # migrate + generate 5,000 synthetic students (about 20 s)
make test                         # 20 tests against the separate test database
```

`make seed` prints the demo accounts. All share the password in `DEMO_PASSWORD`
(default `campusgpt-demo`); no other synthetic user can log in.

| Account | Profile |
|---|---|
| `admin@demo.campusgpt.example` | Academic office administrator |
| `student.regular@demo.campusgpt.example` | Cyber Security, semester 5: good attendance, all fees paid |
| `student.shortage@demo.campusgpt.example` | CSE, semester 3: below 75% in Database Management Systems |
| `student.fees@demo.campusgpt.example` | ECE, semester 7: tuition fee overdue |

The dataset is generated relative to `--as-of` (default: today), so there is always work due
"this week". The same seed and date always produce the same data.

## Status

Week 1 in progress: database schema, migrations and synthetic data generator done.

| Document | |
|---|---|
| [Project plan](docs/PLAN.md) | Scope, timeline, decisions |
| [Software Requirements Specification](docs/srs/campus-gpt-srs.pdf) | Requirements (v1.1) |
| [Technical Design Document](docs/design/campus-gpt-technical-design.pdf) | Diagrams, IPC, programming concepts, libraries |
| [Presentation](docs/slides/CampusGPT_Major_Project.pptx) | 18-slide major-project deck (UPES template) |
