"""Consistency checks that foreign keys alone cannot express.

Each check is a query that counts violating rows; a correct dataset returns 0 for all.
"""
import psycopg

CHECKS: dict[str, str] = {
    "enrollment matches the student's department, semester and section": """
        SELECT count(*) FROM enrollments e
        JOIN students s ON s.id = e.student_id
        JOIN programs p ON p.id = s.program_id
        JOIN course_offerings o ON o.id = e.offering_id
        JOIN courses c ON c.id = o.course_id
        WHERE c.department_id <> p.department_id
           OR c.semester <> s.current_semester
           OR o.section <> s.section""",
    "every student takes every course of their semester": """
        SELECT count(*) FROM students s
        JOIN programs p ON p.id = s.program_id
        WHERE (SELECT count(*) FROM enrollments e WHERE e.student_id = s.id)
           <> (SELECT count(*) FROM courses c
               WHERE c.department_id = p.department_id AND c.semester = s.current_semester)""",
    "attendance session and enrollment belong to the same offering": """
        SELECT count(*) FROM attendance a
        JOIN class_sessions cs ON cs.id = a.session_id
        JOIN enrollments e ON e.id = a.enrollment_id
        WHERE cs.offering_id <> e.offering_id""",
    "attendance recorded for every enrolled student at every session": """
        SELECT abs((SELECT count(*) FROM attendance)
                 - (SELECT count(*) FROM enrollments e
                    JOIN class_sessions cs ON cs.offering_id = e.offering_id))""",
    "submission assignment and enrollment belong to the same offering": """
        SELECT count(*) FROM submissions sb
        JOIN assignments a ON a.id = sb.assignment_id
        JOIN enrollments e ON e.id = sb.enrollment_id
        WHERE a.offering_id <> e.offering_id""",
    "submission marks within the assignment maximum": """
        SELECT count(*) FROM submissions sb JOIN assignments a ON a.id = sb.assignment_id
        WHERE sb.marks > a.max_marks""",
    "payments never exceed the invoice amount": """
        SELECT count(*) FROM invoice_balances WHERE paid > amount""",
    "waived or cancelled invoices have no payments": """
        SELECT count(*) FROM invoices i JOIN payments p ON p.invoice_id = i.id
        WHERE i.status <> 'issued'""",
    "every student user has a student record and vice versa": """
        SELECT (SELECT count(*) FROM users u WHERE u.role = 'student'
                AND NOT EXISTS (SELECT 1 FROM students s WHERE s.user_id = u.id))
             + (SELECT count(*) FROM students s JOIN users u ON u.id = s.user_id
                WHERE u.role <> 'student')""",
    "only demo accounts can log in": """
        SELECT count(*) FROM users
        WHERE (password_hash IS NOT NULL) <> (email LIKE '%@demo.campusgpt.example')""",
    "all records are labelled synthetic": """
        SELECT (SELECT count(*) FROM students WHERE NOT is_synthetic)
             + (SELECT count(*) FROM notices WHERE NOT is_synthetic)""",
    "class sessions fall on weekdays": """
        SELECT count(*) FROM class_sessions WHERE extract(isodow FROM held_on) > 5""",
}


def validate(conninfo: str) -> dict[str, int]:
    """Return {check description: number of violating rows}."""
    with psycopg.connect(conninfo) as conn:
        return {name: conn.execute(query).fetchone()[0] for name, query in CHECKS.items()}
