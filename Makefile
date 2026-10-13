# Common development commands. Run `make help` for the list.
PY      := .venv/bin/python
ALEMBIC := .venv/bin/alembic -c backend/alembic.ini

.PHONY: help db-start db-stop db-status migrate seed seed-small test lint psql

help:
	@echo "make db-start     start the local PostgreSQL server"
	@echo "make db-stop      stop it"
	@echo "make migrate      apply database migrations"
	@echo "make seed         rebuild the synthetic university (5,000 students, as of today)"
	@echo "make seed-small   same with 300 students (faster)"
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

seed: migrate
	cd backend && ../$(PY) -m campusgpt.seed --students 5000

seed-small: migrate
	cd backend && ../$(PY) -m campusgpt.seed --students 300

test:
	cd backend && ../.venv/bin/pytest -q

lint:
	.venv/bin/ruff check backend/campusgpt backend/tests backend/migrations

psql:
	scripts/db.sh psql
