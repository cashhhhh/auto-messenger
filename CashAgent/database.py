"""
database.py — All data storage for Cash's AI Agent
Tracks leads, messages, responses, conversions, and scrape logs
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "agent_data.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tekion_id        TEXT UNIQUE,
            name             TEXT NOT NULL,
            phone            TEXT,
            email            TEXT,
            vehicle_interest TEXT,
            source           TEXT,
            lead_date        TEXT,
            last_activity    TEXT,
            status           TEXT DEFAULT 'new',
            notes            TEXT,
            raw_data         TEXT,
            quality_score    INTEGER DEFAULT 0,
            skip_reason      TEXT,
            created_at       TEXT DEFAULT (datetime('now')),
            updated_at       TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id       INTEGER REFERENCES leads(id),
            draft         TEXT NOT NULL,
            sent_text     TEXT,
            sent_at       TEXT,
            approved      INTEGER DEFAULT 0,
            got_response  INTEGER DEFAULT 0,
            response_text TEXT,
            response_at   TEXT,
            converted     INTEGER DEFAULT 0,
            follow_up_num INTEGER DEFAULT 1,
            tone_used     TEXT,
            input_tokens  INTEGER,
            output_tokens INTEGER,
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS lead_scores (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id        INTEGER REFERENCES leads(id),
            score          REAL,
            score_breakdown TEXT,
            scored_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS learning_patterns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type    TEXT,
            key             TEXT,
            attempts        INTEGER DEFAULT 0,
            responses       INTEGER DEFAULT 0,
            conversions     INTEGER DEFAULT 0,
            response_rate   REAL DEFAULT 0.0,
            conversion_rate REAL DEFAULT 0.0,
            updated_at      TEXT DEFAULT (datetime('now'))
        )
    """)

    # Scrape audit log — every sync run is recorded
    c.execute("""
        CREATE TABLE IF NOT EXISTS scrape_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at          TEXT DEFAULT (datetime('now')),
            leads_found     INTEGER DEFAULT 0,
            leads_imported  INTEGER DEFAULT 0,
            leads_skipped   INTEGER DEFAULT 0,
            tekion_count    INTEGER DEFAULT 0,
            count_match     INTEGER DEFAULT 0,
            status          TEXT,
            notes           TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    defaults = [
        ("salesperson_name",  "Cash"),
        ("dealership",        "Grubbs Infiniti"),
        ("phone",             "5127346462"),
        ("tekion_url",        "https://app.tekioncloud.com"),
        ("tekion_username",   ""),
        ("tekion_password",   ""),
        ("auto_send",         "0"),
        ("daily_limit",       "150"),
        ("api_key",           ""),
        ("cost_gate",         "1"),      # 1 = always confirm cost before batch
        ("min_quality_score", "2"),      # skip leads below this quality (0-4)
    ]
    for key, val in defaults:
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))

    conn.commit()
    conn.close()


def get_setting(key):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def upsert_lead(data: dict) -> int:
    conn = get_conn()
    now = datetime.now().isoformat()
    existing = conn.execute(
        "SELECT id FROM leads WHERE tekion_id=?", (data.get("tekion_id"),)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE leads SET name=?, phone=?, email=?, vehicle_interest=?,
                source=?, last_activity=?, status=?, notes=?,
                raw_data=?, quality_score=?, skip_reason=?, updated_at=?
            WHERE tekion_id=?
        """, (
            data.get("name"), data.get("phone"), data.get("email"),
            data.get("vehicle_interest"), data.get("source"),
            data.get("last_activity"), data.get("status", "new"),
            data.get("notes"), json.dumps(data.get("raw_data", {})),
            data.get("quality_score", 0), data.get("skip_reason"),
            now, data.get("tekion_id")
        ))
        lead_id = existing["id"]
    else:
        cur = conn.execute("""
            INSERT INTO leads
                (tekion_id, name, phone, email, vehicle_interest, source,
                 lead_date, last_activity, status, notes, raw_data,
                 quality_score, skip_reason, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get("tekion_id"), data.get("name"), data.get("phone"),
            data.get("email"), data.get("vehicle_interest"), data.get("source"),
            data.get("lead_date", now), data.get("last_activity", now),
            data.get("status", "new"), data.get("notes"),
            json.dumps(data.get("raw_data", {})),
            data.get("quality_score", 0), data.get("skip_reason"),
            now, now
        ))
        lead_id = cur.lastrowid

    conn.commit()
    conn.close()
    return lead_id


def log_scrape_run(leads_found, leads_imported, leads_skipped, tekion_count, count_match, status, notes=""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO scrape_log
            (leads_found, leads_imported, leads_skipped, tekion_count, count_match, status, notes)
        VALUES (?,?,?,?,?,?,?)
    """, (leads_found, leads_imported, leads_skipped, tekion_count, count_match, status, notes))
    conn.commit()
    conn.close()


def get_leads_for_queue(limit=150):
    conn = get_conn()
    min_q = int(get_setting("min_quality_score") or 2)
    rows = conn.execute("""
        SELECT l.*, ls.score
        FROM leads l
        LEFT JOIN (
            SELECT lead_id, MAX(scored_at) as mx, score
            FROM lead_scores GROUP BY lead_id
        ) ls ON ls.lead_id = l.id
        WHERE l.status NOT IN ('sold', 'dead')
          AND l.quality_score >= ?
          AND l.phone IS NOT NULL
          AND l.phone != ''
        ORDER BY ls.score DESC, l.lead_date DESC
        LIMIT ?
    """, (min_q, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_message_draft(lead_id, draft, tone, follow_up_num, input_tokens=None, output_tokens=None):
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO messages (lead_id, draft, tone_used, follow_up_num, input_tokens, output_tokens)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (lead_id, draft, tone, follow_up_num, input_tokens, output_tokens))
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def mark_message_sent(msg_id, sent_text):
    conn = get_conn()
    conn.execute("""
        UPDATE messages SET approved=1, sent_text=?, sent_at=datetime('now') WHERE id=?
    """, (sent_text, msg_id))
    conn.commit()
    conn.close()


def mark_response(msg_id, response_text):
    conn = get_conn()
    conn.execute("""
        UPDATE messages SET got_response=1, response_text=?, response_at=datetime('now') WHERE id=?
    """, (response_text, msg_id))
    conn.commit()
    conn.close()


def mark_converted(lead_id):
    conn = get_conn()
    conn.execute("UPDATE leads SET status='sold' WHERE id=?", (lead_id,))
    conn.execute("UPDATE messages SET converted=1 WHERE lead_id=? AND sent_at IS NOT NULL", (lead_id,))
    conn.commit()
    conn.close()


def get_learning_stats():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM learning_patterns").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_learning_patterns():
    conn = get_conn()
    conn.execute("DELETE FROM learning_patterns WHERE pattern_type='source_response_rate'")
    conn.execute("""
        INSERT INTO learning_patterns (pattern_type, key, attempts, responses, conversions, response_rate, conversion_rate, updated_at)
        SELECT 'source_response_rate', l.source, COUNT(m.id),
               SUM(m.got_response), SUM(m.converted),
               CAST(SUM(m.got_response) AS REAL) / MAX(COUNT(m.id), 1),
               CAST(SUM(m.converted) AS REAL) / MAX(COUNT(m.id), 1),
               datetime('now')
        FROM messages m JOIN leads l ON l.id = m.lead_id
        WHERE m.sent_at IS NOT NULL GROUP BY l.source
    """)
    conn.execute("DELETE FROM learning_patterns WHERE pattern_type='tone_response_rate'")
    conn.execute("""
        INSERT INTO learning_patterns (pattern_type, key, attempts, responses, conversions, response_rate, conversion_rate, updated_at)
        SELECT 'tone_response_rate', tone_used, COUNT(id),
               SUM(got_response), SUM(converted),
               CAST(SUM(got_response) AS REAL) / MAX(COUNT(id), 1),
               CAST(SUM(converted) AS REAL) / MAX(COUNT(id), 1),
               datetime('now')
        FROM messages WHERE sent_at IS NOT NULL AND tone_used IS NOT NULL GROUP BY tone_used
    """)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
