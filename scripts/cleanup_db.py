"""Re-apply current filters to existing jobs.db rows and delete anything
that no longer passes. Run this after tightening filters in filters.py to
clear stale rows that were scraped under the old rules.

Deletes a row if its title fails matches_backend_swe() — that check is
title-only, so it's safe to apply retroactively without descriptions.
Rows that only fail categorization (which needs description) are left alone.
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import DB_PATH
from filters import matches_backend_swe, is_senior_role


def main(dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, company, title, category FROM jobs")
    rows = c.fetchall()

    to_delete = []
    reasons = {"senior": 0, "not_backend": 0}
    for row_id, company, title, category in rows:
        if is_senior_role(title):
            to_delete.append((row_id, company, title, category, "senior"))
            reasons["senior"] += 1
            continue
        if not matches_backend_swe(title):
            to_delete.append((row_id, company, title, category, "not_backend"))
            reasons["not_backend"] += 1

    print(f"Total rows:    {len(rows)}")
    print(f"Would delete:  {len(to_delete)}")
    print(f"  senior:      {reasons['senior']}")
    print(f"  not_backend: {reasons['not_backend']}")
    print(f"Remaining:     {len(rows) - len(to_delete)}")
    print()

    if to_delete:
        print("Sample of rows to delete:")
        for row_id, company, title, category, reason in to_delete[:15]:
            print(f"  [{reason:11s}] {company} | {title}")
        if len(to_delete) > 15:
            print(f"  ... and {len(to_delete) - 15} more")

    if dry_run:
        print("\nDRY RUN — no changes made. Pass --apply to delete.")
        return

    if to_delete:
        ids = [row[0] for row in to_delete]
        placeholders = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
        conn.commit()
        print(f"\nDeleted {len(to_delete)} rows.")
    conn.close()


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    main(dry_run=dry)
