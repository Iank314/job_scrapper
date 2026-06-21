import re
import sqlite3
from datetime import datetime
from config import DB_PATH
from filters import ALLOWED_CATEGORIES, categorize, cycle_compatible, is_us_location

# Title-only guard for stale rows. Excludes any season tied to an out-of-range
# year (2010-2025, 2028+) and the past spring/winter/summer 2026 cycles. Note
# Fall 2026 (new grad) and all of 2027 stay valid and are intentionally absent.
NON_TARGET_TITLE_CYCLE_RE = re.compile(
    r'\b(?:fall|autumn|spring|winter|summer)\s*20(?:1\d|2[0-5]|2[89]|3\d)\b|'
    r'\b(?:spring|winter|summer)\s*2026\b',
    re.IGNORECASE,
)


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
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
            trashed_at TEXT,
            accepted INTEGER DEFAULT 0,
            accepted_at TEXT
        )
    """)
    # Handle upgrade from older schemas: add columns if they're missing.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for col, ddl in [
        ("applied", "INTEGER DEFAULT 0"),
        ("applied_at", "TEXT"),
        ("trashed", "INTEGER DEFAULT 0"),
        ("trashed_at", "TEXT"),
        ("accepted", "INTEGER DEFAULT 0"),
        ("accepted_at", "TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs(active)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(applied)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_trashed ON jobs(trashed)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_accepted ON jobs(accepted)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_open_sort "
        "ON jobs(active, applied, trashed, date_scraped)"
    )
    conn.commit()
    conn.close()


def _passes_current_display_filters(job):
    category = job.get("category")
    title = job.get("title") or ""
    if category not in ALLOWED_CATEGORIES:
        return False
    if not is_us_location(job.get("location") or ""):
        return False
    if NON_TARGET_TITLE_CYCLE_RE.search(title):
        return False

    title_category = categorize(title)
    if title_category is not None and not cycle_compatible(title_category, category):
        return False
    return True


def sync_company_jobs(company, source_ats, jobs, active_urls):
    """Persist one company's filtered jobs in a single transaction.

    Returns the set of URLs that were not already present before this sync.
    """
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    urls = [job["url"] for job in jobs if job.get("url")]
    active_urls = {url for url in active_urls if url}

    try:
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS scrape_urls (url TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM scrape_urls")
        if urls:
            conn.executemany(
                "INSERT OR IGNORE INTO scrape_urls (url) VALUES (?)",
                [(url,) for url in urls],
            )

        existing_urls = {
            row[0]
            for row in conn.execute(
                "SELECT jobs.url FROM jobs JOIN scrape_urls ON scrape_urls.url = jobs.url"
            ).fetchall()
        }

        rows = [
            (
                company,
                job["title"],
                job["url"],
                job["category"],
                source_ats,
                job.get("location"),
                job.get("date_posted"),
                now,
            )
            for job in jobs
            if job.get("url")
        ]
        if rows:
            conn.executemany("""
                INSERT INTO jobs (company, title, url, category, source_ats, location, date_posted, date_scraped, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    category = excluded.category,
                    location = excluded.location,
                    date_posted = excluded.date_posted,
                    date_scraped = excluded.date_scraped,
                    active = 1
            """, rows)

        # Because this is only called after a successful fetch, an empty
        # active set means the company currently has no matching jobs.
        if active_urls:
            conn.execute("""
                UPDATE jobs SET active = 0
                WHERE source_ats = ?
                  AND company = ?
                  AND active = 1
                  AND NOT EXISTS (
                      SELECT 1 FROM scrape_urls WHERE scrape_urls.url = jobs.url
                  )
            """, (source_ats, company))
        else:
            conn.execute("""
                UPDATE jobs SET active = 0
                WHERE source_ats = ? AND company = ? AND active = 1
            """, (source_ats, company))

        conn.commit()
        return set(urls) - existing_urls
    finally:
        conn.close()


def upsert_job(company, title, url, category, source_ats, location=None, date_posted=None):
    """Insert or update a job. Returns True if this was a brand-new insert
    (URL never seen before), False if it was an update to an existing row."""
    conn = get_conn()
    now = datetime.utcnow().isoformat()
    try:
        exists = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone() is not None
        conn.execute("""
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
        return not exists
    finally:
        conn.close()


def mark_inactive(source_ats, company, active_urls):
    """Mark jobs as inactive if they no longer appear on the career page."""
    conn = get_conn()
    try:
        active_urls = {url for url in active_urls if url}
        if active_urls:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS scrape_urls (url TEXT PRIMARY KEY)")
            conn.execute("DELETE FROM scrape_urls")
            conn.executemany(
                "INSERT OR IGNORE INTO scrape_urls (url) VALUES (?)",
                [(url,) for url in active_urls],
            )
            conn.execute("""
                UPDATE jobs SET active = 0
                WHERE source_ats = ?
                  AND company = ?
                  AND active = 1
                  AND NOT EXISTS (
                      SELECT 1 FROM scrape_urls WHERE scrape_urls.url = jobs.url
                  )
            """, (source_ats, company))
        else:
            conn.execute("""
                UPDATE jobs SET active = 0
                WHERE source_ats = ? AND company = ? AND active = 1
            """, (source_ats, company))
        conn.commit()
    finally:
        conn.close()


def get_all_jobs(category=None, search=None, active_only=True, include_applied=False, since=None):
    conn = get_conn()
    query = "SELECT * FROM jobs WHERE 1=1"
    params = []

    if active_only:
        query += " AND active = 1"
    if not include_applied:
        query += " AND applied = 0"
    # Trashed and accepted jobs never show in the main Open list.
    query += " AND trashed = 0 AND accepted = 0"
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
    jobs = [dict(r) for r in rows]
    return [job for job in jobs if _passes_current_display_filters(job)]


def get_applied_jobs(search=None):
    conn = get_conn()
    # Once a job is accepted it moves to the Accepted tab and leaves Applied.
    query = "SELECT * FROM jobs WHERE applied = 1 AND accepted = 0 AND trashed = 0"
    params = []
    if search:
        query += " AND (company LIKE ? OR title LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY applied_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_accepted_jobs(search=None):
    conn = get_conn()
    query = "SELECT * FROM jobs WHERE accepted = 1 AND trashed = 0"
    params = []
    if search:
        query += " AND (company LIKE ? OR title LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY accepted_at DESC"
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


def mark_accepted(job_id, accepted=True):
    """Mark a job as accepted (offer accepted). Accepting also clears any
    trashed flag and keeps the row out of the Open/Applied lists; un-accepting
    returns it to Applied (its applied flag is left untouched)."""
    conn = get_conn()
    now = datetime.utcnow().isoformat() if accepted else None
    if accepted:
        cur = conn.execute(
            "UPDATE jobs SET accepted = 1, accepted_at = ?, applied = 1, trashed = 0 WHERE id = ?",
            (now, job_id),
        )
    else:
        cur = conn.execute(
            "UPDATE jobs SET accepted = 0, accepted_at = NULL WHERE id = ?",
            (job_id,),
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
    open_rows = conn.execute(
        "SELECT * FROM jobs WHERE active = 1 AND applied = 0 AND trashed = 0"
    ).fetchall()
    open_jobs = [
        dict(row) for row in open_rows
        if _passes_current_display_filters(dict(row))
    ]
    total = len(open_jobs)
    applied = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE applied = 1 AND accepted = 0 AND trashed = 0"
    ).fetchone()[0]
    accepted = conn.execute("SELECT COUNT(*) FROM jobs WHERE accepted = 1 AND trashed = 0").fetchone()[0]
    trashed = conn.execute("SELECT COUNT(*) FROM jobs WHERE trashed = 1").fetchone()[0]
    categories = {}
    for job in open_jobs:
        categories[job["category"]] = categories.get(job["category"], 0) + 1
    conn.close()
    return {
        "total": total,
        "applied": applied,
        "accepted": accepted,
        "trashed": trashed,
        "categories": categories,
    }
