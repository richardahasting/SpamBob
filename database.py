"""SQLite persistence for scambaiter conversations."""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "scambaiter.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                persona_key             TEXT NOT NULL DEFAULT 'bob',
                scammer_email           TEXT NOT NULL,
                scammer_name            TEXT,
                subject                 TEXT,
                original_message_id     TEXT,
                last_inbound_message_id TEXT,
                status                  TEXT DEFAULT 'active',
                turn_count              INTEGER DEFAULT 0,
                created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                next_reply_at           TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                direction       TEXT NOT NULL,
                subject         TEXT,
                content         TEXT NOT NULL,
                message_id      TEXT,
                timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            -- Queued intro emails from referred personas (sent after a delay)
            CREATE TABLE IF NOT EXISTS pending_intros (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                persona_key     TEXT NOT NULL,
                scammer_email   TEXT NOT NULL,
                subject         TEXT NOT NULL,
                body            TEXT NOT NULL,
                send_after      TIMESTAMP NOT NULL,
                sent            INTEGER DEFAULT 0,
                sent_message_id TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_conv_email
                ON conversations(scammer_email);
            CREATE INDEX IF NOT EXISTS idx_conv_persona
                ON conversations(persona_key, scammer_email);
            CREATE INDEX IF NOT EXISTS idx_msg_message_id
                ON messages(message_id);
        """)


# ── Conversation queries ──────────────────────────────────────────────────────

def find_conversation_by_thread(message_ids: list[str]) -> dict | None:
    with get_conn() as conn:
        for mid in message_ids:
            mid = mid.strip().strip("<>")
            row = conn.execute(
                """SELECT c.* FROM conversations c
                   JOIN messages m ON m.conversation_id = c.id
                   WHERE m.message_id = ? AND c.status = 'active'
                   LIMIT 1""",
                (mid,),
            ).fetchone()
            if row:
                return dict(row)
    return None


def find_conversation_by_sender(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM conversations
               WHERE scammer_email = ? AND status = 'active'
               ORDER BY created_at DESC LIMIT 1""",
            (email.lower(),),
        ).fetchone()
        return dict(row) if row else None


def find_conversation_by_sender_and_persona(email: str, persona_key: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM conversations
               WHERE scammer_email = ? AND persona_key = ? AND status = 'active'
               LIMIT 1""",
            (email.lower(), persona_key),
        ).fetchone()
        return dict(row) if row else None


def create_conversation(
    scammer_email: str,
    scammer_name: str,
    subject: str,
    message_id: str,
    next_reply_at: datetime,
    persona_key: str = "bob",
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO conversations
               (persona_key, scammer_email, scammer_name, subject, original_message_id, next_reply_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (persona_key, scammer_email.lower(), scammer_name, subject, message_id, next_reply_at),
        )
        return cur.lastrowid


def add_message(
    conversation_id: int,
    direction: str,
    subject: str,
    content: str,
    message_id: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO messages (conversation_id, direction, subject, content, message_id)
               VALUES (?, ?, ?, ?, ?)""",
            (conversation_id, direction, subject, content, message_id),
        )
        conn.execute(
            """UPDATE conversations
               SET last_activity_at = CURRENT_TIMESTAMP,
                   turn_count = turn_count + 1
               WHERE id = ?""",
            (conversation_id,),
        )


def schedule_next_reply(
    conversation_id: int,
    next_reply_at: datetime | None,
    last_inbound_id: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE conversations
               SET next_reply_at = ?,
                   last_inbound_message_id = COALESCE(?, last_inbound_message_id)
               WHERE id = ?""",
            (next_reply_at, last_inbound_id, conversation_id),
        )


def get_messages(conversation_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_replies() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM conversations
               WHERE status = 'active'
               AND next_reply_at IS NOT NULL
               AND next_reply_at <= datetime('now')""",
        ).fetchall()
        return [dict(r) for r in rows]


def mark_complete(conversation_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET status = 'completed' WHERE id = ?",
            (conversation_id,),
        )


def abandon_stale_conversations(days: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE conversations SET status = 'abandoned'
               WHERE status = 'active'
               AND last_activity_at < datetime('now', ? || ' days')""",
            (f"-{days}",),
        )
        return cur.rowcount


# ── Pending intros (referral spawn queue) ─────────────────────────────────────

def set_pending_intro(
    conversation_id: int,
    body: str,
    scammer_email: str,
    persona_key: str,
    subject: str,
    send_after: datetime,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pending_intros
               (conversation_id, persona_key, scammer_email, subject, body, send_after)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (conversation_id, persona_key, scammer_email, subject, body, send_after),
        )


def get_pending_intros() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM pending_intros
               WHERE sent = 0 AND send_after <= datetime('now')""",
        ).fetchall()
        return [dict(r) for r in rows]


def clear_pending_intro(intro_id: int, sent_message_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_intros SET sent = 1, sent_message_id = ? WHERE id = ?",
            (sent_message_id, intro_id),
        )


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE status='active'"
        ).fetchone()[0]
        total_turns = (
            conn.execute("SELECT SUM(turn_count) FROM conversations").fetchone()[0] or 0
        )
        avg_turns = (
            conn.execute(
                "SELECT AVG(turn_count) FROM conversations WHERE status != 'active'"
            ).fetchone()[0] or 0
        )
        by_persona = conn.execute(
            """SELECT persona_key, COUNT(*) as cnt, SUM(turn_count) as turns
               FROM conversations GROUP BY persona_key ORDER BY turns DESC"""
        ).fetchall()
        return {
            "total_conversations": total,
            "active": active,
            "total_turns_wasted": total_turns,
            "avg_turns_per_scammer": round(avg_turns, 1),
            "by_persona": [dict(r) for r in by_persona],
        }
