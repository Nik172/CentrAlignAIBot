import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "tickets.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer TEXT NOT NULL,
            subject TEXT,
            refund_amount REAL,
            status TEXT DEFAULT 'open',
            resolution_notes TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def seed_if_empty():
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) as c FROM tickets").fetchone()["c"]
    if count == 0:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO tickets (customer, subject, refund_amount, status, created_at) VALUES (?,?,?,?,?)",
                     ("Jane Doe", "Damaged item received", 1500, "open", now))
        conn.execute("INSERT INTO tickets (customer, subject, refund_amount, status, created_at) VALUES (?,?,?,?,?)",
                     ("John Smith", "Wrong item shipped", 5000, "open", now))
        conn.commit()
    conn.close()


def get_tickets(status: str | None = None, customer: str | None = None) -> list[dict]:
    conn = get_connection()
    query = "SELECT * FROM tickets WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if customer:
        query += " AND LOWER(customer) LIKE ?"
        params.append(f"%{customer.lower()}%")
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_ticket(ticket_id: int, resolution_notes: str, approved: bool):
    conn = get_connection()
    status = "resolved" if approved else "escalated"
    conn.execute("UPDATE tickets SET status=?, resolution_notes=? WHERE id=?",
                 (status, resolution_notes, ticket_id))
    conn.commit()
    conn.close()


def reset_db():
    conn = get_connection()
    conn.execute("DELETE FROM tickets")
    conn.commit()
    conn.close()