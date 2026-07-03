import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import init_db
from scraper.runner import run_all


def _scrape():
    print("=" * 60)
    print("  Backend SWE Job Scraper")
    print("=" * 60)
    run_all()
    print()


def main():
    parser = argparse.ArgumentParser(description="Backend SWE Job Scraper")
    parser.add_argument("--scrape", action="store_true", help="Only scrape, don't start web UI")
    parser.add_argument("--web", action="store_true", help="Only start web UI, skip scraping")
    parser.add_argument("--if-due", action="store_true",
                        help="Headless scrape for Task Scheduler: only runs if a scheduled slot "
                             "(00:30/12:00/18:00) has passed since the last scrape. Collapses missed "
                             "runs into a single catch-up.")
    parser.add_argument("--port", type=int, default=5000, help="Port for web UI (default: 5000)")
    args = parser.parse_args()

    init_db()

    # Self-gating scheduled scrape: skip unless a slot has elapsed since the
    # last run, then stamp the time so queued catch-up triggers don't re-run.
    if args.if_due:
        from datetime import datetime
        from schedule_gate import is_due, record_scrape, most_recent_slot
        now = datetime.now()
        if not is_due(now):
            print(f"[{now:%Y-%m-%d %H:%M}] Scrape not due — already ran since the "
                  f"{most_recent_slot(now):%H:%M} slot. Skipping.")
            return
        _scrape()
        record_scrape()
        return

    if not args.web:
        _scrape()

    if not args.scrape:
        from web.app import app
        print(f"Starting web UI at http://localhost:{args.port}")
        app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
