"""Bulk-load a generated Dataset into PostgreSQL with COPY, in a single transaction."""
import psycopg
from psycopg import sql

from campusgpt.seed.generate import ATTENDANCE_COLUMNS, COLUMNS, Dataset

# Every table the seed owns, emptied before loading. Chat history, audit logs and documents
# reference users, so they are cleared too; a reseed always starts from a clean state.
RESET_TABLES = [
    "attendance", "submissions", "payments", "class_sessions", "exams", "assignments",
    "enrollments", "invoices", "course_offerings", "students", "courses", "faculty",
    "programs", "departments", "notices", "messages", "conversations", "audit_logs",
    "ingestion_jobs", "document_chunks", "documents", "sessions", "users",
]
LOAD_ORDER = list(COLUMNS)  # parents before children


def _copy(cur: psycopg.Cursor, table: str, columns, rows) -> None:
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)))
    with cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def load(conninfo: str, ds: Dataset) -> None:
    """Replace all seed-owned data with ds. Either everything loads or nothing changes."""
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
            sql.SQL(", ").join(map(sql.Identifier, RESET_TABLES))))
        for table in LOAD_ORDER:
            _copy(cur, table, COLUMNS[table], ds.rows[table])
            if table == "class_sessions":
                # attendance depends on class_sessions and enrollments, both loaded by now
                _copy(cur, "attendance", ATTENDANCE_COLUMNS, ds.attendance_rows())
        # Ids were supplied explicitly, so move each identity sequence past them.
        for table in LOAD_ORDER:
            cur.execute(sql.SQL(
                "SELECT setval(pg_get_serial_sequence({}, 'id'), "
                "coalesce((SELECT max(id) FROM {}), 0) + 1, false)"
            ).format(sql.Literal(table), sql.Identifier(table)))
        conn.commit()
    # Refresh planner statistics so queries are planned for the new row counts.
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("ANALYZE")
