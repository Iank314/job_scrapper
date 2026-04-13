import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import init_db
from scraper.runner import run_all


def main():
    parser = argparse.ArgumentParser(description="Backend SWE Job Scraper")
    parser.add_argument("--scrape", action="store_true", help="Only scrape, don't start web UI")
    parser.add_argument("--web", action="store_true", help="Only start web UI, skip scraping")
    parser.add_argument("--port", type=int, default=5000, help="Port for web UI (default: 5000)")
    args = parser.parse_args()

    init_db()

    if not args.web:
        print("=" * 60)
        print("  Backend SWE Job Scraper")
        print("=" * 60)
        run_all()
        print()

    if not args.scrape:
        from web.app import app
        print(f"Starting web UI at http://localhost:{args.port}")
        app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
