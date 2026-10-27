# Common development commands. Run `make help` for the list.
PY      := .venv/bin/python
ALEMBIC := .venv/bin/alembic -c backend/alembic.ini

.PHONY: help db-start db-stop db-status migrate seed seed-small policies llm api worker web security test lint psql

help:
	@echo "make db-start     start the local PostgreSQL server"
	@echo "make db-stop      stop it"
	@echo "make migrate      apply database migrations"
	@echo "make seed         rebuild the synthetic university (5,000 students, as of today)"
	@echo "make seed-small   same with 300 students (faster)"
	@echo "make policies     index the synthetic policy documents in docs/policies"
	@echo "make llm          run the local model server (Ollama, http://localhost:11434)"
	@echo "make api          run the API server on http://localhost:8000 (docs at /docs)"
	@echo "make worker       run the ingestion worker (indexes uploaded documents)"
	@echo "make web          run the frontend on http://localhost:3000 (needs make api too)"
	@echo "make security     run the attack prompts against the chat (needs make llm)"
	@echo "make test         run the test suite"
	@echo "make lint         run the linter"
	@echo "make psql         open a SQL shell on the development database"

db-start:
	scripts/db.sh start

db-stop:
	scripts/db.sh stop

db-status:
	scripts/db.sh status

migrate:
	$(ALEMBIC) upgrade head

# Reseeding empties the documents table, so both re-index the policies afterwards.
seed: migrate
	cd backend && ../$(PY) -m campusgpt.seed --students 5000
	$(MAKE) policies

seed-small: migrate
	cd backend && ../$(PY) -m campusgpt.seed --students 300
	$(MAKE) policies

policies:
	cd backend && ../$(PY) -m campusgpt.documents load ../docs/policies

# Local chat model. 8k context: instructions + tool results + history exceed Ollama's 4k default.
LLM_MODEL_LOCAL := qwen3:4b-instruct-2507-q4_K_M
llm:
	@# `ollama list`/`pull` need a running server, so check the model files directly.
	@test -e ~/.ollama/models/manifests/registry.ollama.ai/library/$(subst :,/,$(LLM_MODEL_LOCAL)) \
		|| { echo "Model missing: start 'ollama serve', then run 'ollama pull $(LLM_MODEL_LOCAL)'"; exit 1; }
	OLLAMA_HOST=127.0.0.1:11434 OLLAMA_CONTEXT_LENGTH=8192 OLLAMA_KEEP_ALIVE=30m ollama serve

api:
	cd backend && ../.venv/bin/uvicorn campusgpt.api.app:app --reload --port 8000

worker:
	cd backend && ../$(PY) -m campusgpt.worker

web:
	cd frontend && npm run dev

security:
	cd backend && ../$(PY) -m campusgpt.security

test:
	cd backend && ../.venv/bin/pytest -q

lint:
	.venv/bin/ruff check backend/campusgpt backend/tests backend/migrations

psql:
	scripts/db.sh psql
