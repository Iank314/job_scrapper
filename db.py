import sqlite3
from datetime import datetime
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            category TEXT,
            source_ats TEXT,
            location TEXT,
            date_posted TEXT,
            date_scraped TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            applied INTEGER DEFAULT 0,
            applied_at TEXT,
            trashed INTEGER DEFAULT 0,
            trashed_at TEXT
        )
    """)
    # Handle upgrade from older schemas: add columns if they're missing.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for col, ddl in [
        ("applied", "INTEGER DEFAULT 0"),
        ("applied_at", "TEXT"),
        ("trashed", "INTEGER DEFAULT 0"),
        ("trashed_at", "TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs(active)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(applied)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_trashed ON jobs(trashed)")
    conn.commit()
    conn.close()


def upsert_job(company, title, url, category, source_ats, location=None, date_posted=None):
    """Insert or update a job. Returns True if this was a brand-new insert
    (URL never seen before), False if it was an update to an existing row."""
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    try:
        cur = conn.execute("""
            INSERT INTO jobs (company, title, url, category, source_ats, location, date_posted, date_scraped, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                category = excluded.category,
                location = excluded.location,
                date_posted = excluded.date_posted,
                date_scraped = excluded.date_scraped,
                active = 1
        """, (company, title, url, category, source_ats, location, date_posted, now))
        conn.commit()
        # SQLite: lastrowid is set on INSERT but not on ON CONFLICT UPDATE.
        # changes() returns 1 for both INSERT and UPDATE though.
        # Best heuristic: if lastrowid > 0 and the id matches the row we
        # just touched, it was a fresh insert.
        row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
        is_new = row is not None and cur.lastrowid == row[0]
        return is_new
    finally:
        conn.close()


def mark_inactive(source_ats, company, active_urls):
    """Mark jobs as inactive if they no longer appear on the career page."""
    if not active_urls:
        return
    conn = get_conn()
    placeholders = ",".join("?" * len(active_urls))
    conn.execute(f"""
        UPDATE jobs SET active = 0
        WHERE source_ats = ? AND company = ? AND url NOT IN ({placeholders}) AND active = 1
    """, [source_ats, company] + list(active_urls))
    conn.commit()
    conn.close()


def get_all_jobs(category=None, search=None, active_only=True, include_applied=False, since=None):
    conn = get_conn()
    query = "SELECT * FROM jobs WHERE 1=1"
    params = []

    if active_only:
        query += " AND active = 1"
    if not include_applied:
        query += " AND applied = 0"
    # Trashed jobs never show in the main list.
    query += " AND trashed = 0"
    if category and category != "All":
        query += " AND category = ?"
        params.append(category)
    if search:
        query += " AND (company LIKE ? OR title LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if since:
        query += " AND date_scraped > ?"
        params.append(since)

    query += " ORDER BY date_scraped DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_applied_jobs(search=None):
    conn = get_conn()
    query = "SELECT * FROM jobs WHERE applied = 1"
    params = []
    if search:
        query += " AND (company LIKE ? OR title LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY applied_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trashed_jobs(search=None):
    conn = get_conn()
    query = "SELECT * FROM jobs WHERE trashed = 1"
    params = []
    if search:
        query += " AND (company LIKE ? OR title LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY trashed_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_applied(job_id, applied=True):
    conn = get_conn()
    now = datetime.utcnow().isoformat() if applied else None
    cur = conn.execute(
        "UPDATE jobs SET applied = ?, applied_at = ? WHERE id = ?",
        (1 if applied else 0, now, job_id),
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return changed > 0


def mark_trashed(job_id, trashed=True):
    conn = get_conn()
    now = datetime.utcnow().isoformat() if trashed else None
    cur = conn.execute(
        "UPDATE jobs SET trashed = ?, trashed_at = ? WHERE id = ?",
        (1 if trashed else 0, now, job_id),
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return changed > 0


def get_stats():
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE active = 1 AND applied = 0 AND trashed = 0"
    ).fetchone()[0]
    applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied = 1").fetchone()[0]
    trashed = conn.execute("SELECT COUNT(*) FROM jobs WHERE trashed = 1").fetchone()[0]
    categories = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM jobs "
        "WHERE active = 1 AND applied = 0 AND trashed = 0 GROUP BY category"
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "applied": applied,
        "trashed": trashed,
        "categories": {r[0]: r[1] for r in categories},
    }
