"""Per-company scrape audit — does every companies.yaml entry actually reach a
job board, and does the filter chain keep the new-grad roles it should?

Runs each company's `_fetch_jobs` without touching the database, then replays
the filter chain job-by-job recording *which gate* dropped each posting. Two
things come out of that:

  * config health   — entries that error, or return zero raw postings
  * filter recall   — postings whose title carries an early-career signal but
                      that got dropped anyway ("near misses")

Usage:
    python scripts/audit_scrape.py --out audit.json            # everything
    python scripts/audit_scrape.py --ats greenhouse,lever      # subset
    python scripts/audit_scrape.py --skip-playwright           # fast pass
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MAX_WORKERS  # noqa: E402
from filters import (  # noqa: E402
    matches_backend_swe, categorize, is_us_location, requires_phd,
    is_senior_role, _INCLUDE_RE, _EXCLUDE_RE, FIRMWARE_EMBEDDED_RE,
)
from scraper.runner import SCRAPERS, load_companies  # noqa: E402

# A raw posting is "early-career-ish" if its title mentions any of these. Used
# only to decide which drops are worth reporting — a dropped "Senior Staff
# Engineer" is uninteresting, a dropped "2027 University Graduate" is a bug.
EARLY_CAREER_HINT = re.compile(
    r'\b(intern(ship)?s?|co[-\s]?ops?|new\s*grad\w*|grad(uate)?s?|campus|'
    r'university|entry[-\s]?level|early[-\s]?career|student|apprentice|'
    r'rotation\w*|class\s+of|20(26|27|28))\b',
    re.IGNORECASE,
)

# Buckets that matter most to a May-2027 graduate looking for full-time work.
NEWGRAD_CATEGORIES = {
    "2027 New Grad", "Summer 2027 New Grad",
    "Fall 2027 New Grad", "Spring 2027 New Grad",
}


def _drop_reason(title, location, description):
    """Replay base.BaseScraper's filter chain, returning the gate that dropped
    the job (or None if it survives) plus the category when it survives."""
    if is_senior_role(title):
        return "seniority", None
    if _EXCLUDE_RE.search(title):
        return "exclude-keyword", None
    # Its own gate rather than part of exclude-keyword: firmware/embedded needs
    # to out-rank the include keywords ("Embedded Software Engineer" matches
    # "software engineer"), and keeping it separate keeps the drop breakdown
    # readable.
    if FIRMWARE_EMBEDDED_RE.search(title):
        return "firmware-embedded", None
    if not _INCLUDE_RE.search(title):
        return "no-swe-keyword", None
    if not is_us_location(location):
        return "non-us-location", None
    if requires_phd(title, description):
        return "phd-required", None
    category = categorize(title, description)
    if category is None:
        return "no-category", None
    return None, category


def audit_company(cfg, pw_scraper=None):
    name = cfg["name"]
    ats = cfg.get("ats", "generic")
    result = {
        "name": name, "ats": ats,
        "board": cfg.get("board_id") or cfg.get("url", ""),
        "error": None, "raw": 0, "elapsed": 0.0,
        "kept": [], "drops": {}, "near_misses": [],
    }

    scraper = pw_scraper if ats == "playwright" else SCRAPERS.get(ats, SCRAPERS["generic"])()
    started = time.time()
    try:
        raw_jobs = scraper._fetch_jobs(cfg) or []
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"[:300]
        result["elapsed"] = round(time.time() - started, 1)
        return result
    result["elapsed"] = round(time.time() - started, 1)
    result["raw"] = len(raw_jobs)

    seen = set()
    for job in raw_jobs:
        title = (job.get("title") or "").strip()
        url = job.get("url") or ""
        if not title or not url or url in seen:
            continue
        seen.add(url)
        location = job.get("location", "") or ""
        description = job.get("description", "") or ""

        reason, category = _drop_reason(title, location, description)
        if reason is None:
            result["kept"].append({
                "title": title, "category": category,
                "location": location[:80], "url": url,
            })
            continue

        result["drops"][reason] = result["drops"].get(reason, 0) + 1
        # Only surface drops that look early-career — everything else is the
        # filter doing its job on experienced roles.
        if EARLY_CAREER_HINT.search(title):
            result["near_misses"].append({
                "title": title, "reason": reason,
                "location": location[:80],
                "has_desc": bool(description),
            })
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="audit.json")
    ap.add_argument("--ats", help="comma-separated ATS filter")
    ap.add_argument("--name", help="substring match on company name")
    ap.add_argument("--skip-playwright", action="store_true")
    args = ap.parse_args()

    companies = load_companies()
    if args.ats:
        wanted = {a.strip() for a in args.ats.split(",")}
        companies = [c for c in companies if c.get("ats", "generic") in wanted]
    if args.name:
        needle = args.name.lower()
        companies = [c for c in companies if needle in c["name"].lower()]
    if args.skip_playwright:
        companies = [c for c in companies if c.get("ats") != "playwright"]

    pw = [c for c in companies if c.get("ats") == "playwright"]
    api = [c for c in companies if c.get("ats") != "playwright"]
    print(f"Auditing {len(api)} API + {len(pw)} browser companies...", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(audit_company, c): c["name"] for c in api}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            results.append(r)
            flag = "ERR " if r["error"] else ("ZERO" if r["raw"] == 0 else "    ")
            print(f"[{i}/{len(api)}] {flag} {r['ats']}/{r['name']}: "
                  f"raw={r['raw']} kept={len(r['kept'])} near_miss={len(r['near_misses'])}"
                  + (f" :: {r['error']}" if r["error"] else ""), flush=True)

    if pw:
        from scraper.playwright_scraper import PlaywrightScraper, close_browser
        pw_scraper = PlaywrightScraper()
        try:
            for i, c in enumerate(pw, 1):
                r = audit_company(c, pw_scraper=pw_scraper)
                results.append(r)
                flag = "ERR " if r["error"] else ("ZERO" if r["raw"] == 0 else "    ")
                print(f"[pw {i}/{len(pw)}] {flag} {r['name']}: raw={r['raw']} "
                      f"kept={len(r['kept'])} ({r['elapsed']}s)"
                      + (f" :: {r['error']}" if r["error"] else ""), flush=True)
        finally:
            close_browser()

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)

    errors = [r for r in results if r["error"]]
    zeros = [r for r in results if not r["error"] and r["raw"] == 0]
    kept_total = sum(len(r["kept"]) for r in results)
    ng = sum(1 for r in results for k in r["kept"] if k["category"] in NEWGRAD_CATEGORIES)
    print(f"\n=== {len(results)} companies | {len(errors)} errored | {len(zeros)} returned 0 raw")
    print(f"=== {kept_total} jobs kept, {ng} of them new-grad")
    print(f"=== wrote {args.out}")


if __name__ == "__main__":
    main()
