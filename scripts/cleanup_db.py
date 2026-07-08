"""Re-apply current filters to existing jobs.db rows.

Run this after tightening filters in filters.py to clear stale rows that were
scraped under older, looser rules. The cleanup is intentionally title/location
based because historical rows do not store full descriptions.
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import DB_PATH
from filters import (
    ALLOWED_CATEGORIES,
    categorize,
    cycle_compatible,
    is_senior_role,
    is_us_location,
    matches_backend_swe,
    requires_phd,
)


def main(dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, company, title, category, location, applied, accepted FROM jobs")
    rows = c.fetchall()

    to_delete = []
    to_update = []
    protected = 0
    reasons = {
        "senior": 0,
        "not_backend": 0,
        "phd": 0,
        "non_us": 0,
        "wrong_cycle": 0,
    }

    for row_id, company, title, category, location, applied, accepted in rows:
        # Never delete application history: rows the user applied to (or got
        # an offer from) stay even if they no longer pass current filters.
        if applied or accepted:
            protected += 1
            continue
        if is_senior_role(title):
            to_delete.append((row_id, company, title, category, "senior"))
            reasons["senior"] += 1
            continue
        if not matches_backend_swe(title):
            to_delete.append((row_id, company, title, category, "not_backend"))
            reasons["not_backend"] += 1
            continue
        if requires_phd(title):
            to_delete.append((row_id, company, title, category, "phd"))
            reasons["phd"] += 1
            continue
        if not is_us_location(location or ""):
            to_delete.append((row_id, company, title, category, "non_us"))
            reasons["non_us"] += 1
            continue

        # Cleanup is title-only (historical rows don't store descriptions), so a
        # title that yields no cycle is NOT proof the row is stale — the cycle
        # may have come from the description. Only delete when the title can't
        # reclassify it AND the stored category is no longer a valid target.
        current_category = categorize(title)
        if current_category is None:
            if category in ALLOWED_CATEGORIES:
                continue
            to_delete.append((row_id, company, title, category, "wrong_cycle"))
            reasons["wrong_cycle"] += 1
            continue
        if not cycle_compatible(current_category, category) or category not in ALLOWED_CATEGORIES:
            to_update.append((row_id, company, title, category, current_category))

    print(f"Total rows:    {len(rows)}")
    print(f"Protected (applied/accepted): {protected}")
    print(f"Would delete:  {len(to_delete)}")
    print(f"  senior:      {reasons['senior']}")
    print(f"  not_backend: {reasons['not_backend']}")
    print(f"  phd:         {reasons['phd']}")
    print(f"  non_us:      {reasons['non_us']}")
    print(f"  wrong_cycle: {reasons['wrong_cycle']}")
    print(f"Would update:  {len(to_update)}")
    print(f"Remaining:     {len(rows) - len(to_delete)}")
    print()

    if to_delete:
        print("Sample of rows to delete:")
        for row_id, company, title, category, reason in to_delete[:15]:
            print(f"  [{reason:11s}] {company} | {title}")
        if len(to_delete) > 15:
            print(f"  ... and {len(to_delete) - 15} more")

    if to_update:
        print("\nSample of rows to update:")
        for row_id, company, title, old_category, new_category in to_update[:15]:
            print(f"  [{old_category} -> {new_category}] {company} | {title}")
        if len(to_update) > 15:
            print(f"  ... and {len(to_update) - 15} more")

    if dry_run:
        print("\nDRY RUN - no changes made. Pass --apply to delete/update.")
        conn.close()
        return

    if to_delete:
        ids = [row[0] for row in to_delete]
        placeholders = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
        print(f"\nDeleted {len(to_delete)} rows.")
    if to_update:
        c.executemany(
            "UPDATE jobs SET category = ? WHERE id = ?",
            [(row[4], row[0]) for row in to_update],
        )
        print(f"Updated {len(to_update)} rows.")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    main(dry_run=dry)
