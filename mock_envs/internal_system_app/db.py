import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "invoices.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            invoice_number TEXT,
            amount REAL NOT NULL,
            due_date TEXT NOT NULL,
            status TEXT DEFAULT 'entered',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def insert_invoice(company: str, invoice_number: str, amount: float, due_date: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO invoices (company, invoice_number, amount, due_date, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (company, invoice_number, amount, due_date, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    invoice_id = cur.lastrowid
    conn.close()
    return invoice_id


def get_invoices(company: str | None = None) -> list[dict]:
    conn = get_connection()
    if company:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE LOWER(company) LIKE ? ORDER BY id DESC",
            (f"%{company.lower()}%",),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def reset_db():
    """Used by tests to start from a clean slate."""
    conn = get_connection()
    conn.execute("DELETE FROM invoices")
    conn.commit()
    conn.close()