# Job Scraper - Project Context

## What this project does
Scrapes career pages of ~400 companies for backend SWE internships and new grad roles. Filters by US-only locations, excludes PhD-required, senior, and frontend roles, and categorizes into:
- Fall 2026 Intern
- Spring 2027 Intern
- Summer 2027 Intern
- Summer 2027 New Grad

Results display in a local Flask web UI at `localhost:5000` with a single-user login so you can mark jobs as **Applied** or **Trashed**. Both states persist across re-scrapes.

## Architecture
- **Scrapers** (`scraper/`): One per ATS platform — Greenhouse, Lever, Ashby, SmartRecruiters, Workday, iCIMS, generic HTML, and a Playwright-based browser scraper for JS-rendered SPAs. Each fetches job listings and (where cheap) descriptions.
- **Filters** (`filters.py`): Whole-word keyword matching for backend SWE roles; seniority exclusion (senior/staff/principal/lead/II/III/IV/L3+); US location filter; PhD exclusion; and season/year categorization where the **title is authoritative** and description is only a tiebreaker.
- **Database** (`db.py`): SQLite (`jobs.db`), single `jobs` table with deduplication by URL. Per-row state for `active`, `applied`, `trashed` — the scraper's `upsert_job` only touches scraper-owned columns, so applied/trashed flags survive re-scrapes.
- **Company config** (`companies.yaml`): ~400 entries. Each has `name`, `ats`, and either `board_id` or `url`.
- **Web UI** (`web/`): Flask app with dark-themed single-page table, Open/Applied/Trash tabs, login modal, per-row action buttons. Session auth via `APP_PASSWORD` from `.env`.
- **Entry point** (`run.py`): `python run.py` scrapes then launches UI. `--scrape` or `--web` for just one.
- **One-shot scripts** (`scripts/`): `classify_companies.py` parses the speedyapply markdown tables and diffs them against `companies.yaml`. `cleanup_db.py` removes rows that no longer pass the current filter.

## Key decisions
- JSON API scrapers (Greenhouse, Lever, Ashby) use clean `Accept: application/json` headers. HTML scrapers use browser-like headers with Sec-Fetch headers.
- iCIMS uses `/jobs/search?pr=0&in_iframe=1&...` since the normal `/jobs/search` is POST-only and returns 405 on GET.
- Playwright companies run **sequentially** sharing one browser (sync API isn't thread-safe). Timeouts capped: 20s goto / 8s networkidle / 1s settle / 3 scroll passes → ~30s max per company.
- Location filter is strict: must have a positive US signal to be included. Unknown locations without any US signal are rejected.
- Summer 2026 / Spring 2026 postings are explicitly excluded as past cycle — title-only so we don't drop a 2027 role that happens to mention a past program in its description.
- `.env` loads via python-dotenv; `APP_PASSWORD` and `APP_SECRET_KEY` never get committed.

## How to run
```bash
pip install -r requirements.txt
playwright install chromium    # one-time, for the playwright scraper
cp .env.example .env           # then edit APP_PASSWORD and APP_SECRET_KEY

python run.py              # scrape + web UI
python run.py --scrape     # scrape only
python run.py --web        # UI only
```

## Adding companies
Edit `companies.yaml`. Verify board IDs before adding:
- Greenhouse: `curl https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
- Lever: `curl https://api.lever.co/v0/postings/{slug}`
- Ashby: `curl https://api.ashbyhq.com/posting-api/job-board/{slug}`

## Known limitations
- The playwright generic extractor catches `<a>` tags with job-title text OR job-detail-URL patterns, but sites that render listings as clickable divs/buttons without anchor tags may return 0 results.
- Some FAANG cycles aren't posted yet (see "FAANG timing" note below) — empty playwright results for Google/Meta/Microsoft/Apple/Netflix during April–July are mostly timing, not broken code.
- Running on localhost means nothing scrapes when the laptop is closed.

## FAANG timing note
Many big-tech companies open their Summer 2027 intern cycle in **late July through September 2026**. Currently (April 2026):
- **Banking** (Goldman, JPMorgan, Morgan Stanley): Summer 2027 intern postings typically open March–May, so *some* should be live now.
- **Quant / Trading** (Citadel, Two Sigma, HRT, Jane Street, Jump): cycle opens March–April, should be live now.
- **Big Tech** (Google, Meta, Microsoft, Apple, Netflix, TikTok): Summer 2027 interns mostly **not posted yet**. Don't treat empty results from these as a scraper bug until August+.
- **Continuous hiring** (Amazon, Tesla, Anthropic, OpenAI, most startups): should have results year-round.

---

## Next steps (prioritized)

### 1. Continuous polling + push notifications *(biggest ROI)*
The tool is currently a batch job that only runs when manually invoked. The real edge in "apply before others" requires continuous polling.

**Build:**
- Windows Task Scheduler XML that runs `python run.py --scrape` every 15–30 minutes (or cron if on Linux/WSL/VPS).
- A Discord webhook poster that fires when a *new* URL is inserted into `jobs.db`. Read `DISCORD_WEBHOOK_URL` from `.env`.
- Webhook payload: company, title, category, location, direct URL. One message per new job so you can star/react on your phone.
- Mark jobs that already existed (and just got re-upserted) as "not new" — only alert on true first-sight inserts.

**Where to hook in:** `db.upsert_job()` returns whether the row was INSERT vs UPDATE (currently doesn't — needs a small change to return the `lastrowid` + `changes()` diff). Collect new-job tuples during `run_all()` and flush a batch webhook at the end.

**Estimated effort:** 2–3 hours. This is the single biggest competitive edge and should be built before anything else on this list.

### 2. "New since last check" filter in the UI *(tiny effort, big QoL)*
Add a `last_seen_at` per-user timestamp (stored in the session or a tiny file), and a toggle on the Open tab that filters jobs to only those scraped after `last_seen_at`. On page load, update `last_seen_at` to now. Turns the tool from "show me 90 things to sift through" into "show me what's new since I last looked."

**Estimated effort:** 30 minutes.

### 3. Per-site JSON API handlers for high-value SPAs *(do when FAANG cycles open)*
When the big-tech Summer 2027 cycle actually opens (Aug–Sep 2026), the playwright generic extractor will likely miss a lot because those sites don't render listings as plain anchors. The fix is per-site handlers that hit the internal JSON endpoints directly:

- **Amazon** — `https://www.amazon.jobs/en/search.json` (public JSON; just add query params)
- **Microsoft** — `https://gcsservices.careers.microsoft.com/search/api/v1/search`
- **Apple** — POST to `https://jobs.apple.com/api/role/search` with a JSON body
- **Meta** — internal GraphQL; harder, requires reverse-engineering the request
- **Google** — no public API; stay on playwright
- **TikTok** — has a JSON endpoint on `careers.tiktok.com/api/`

Add each as a `site:` handler in `scraper/playwright_scraper.py`'s `SITE_HANDLERS` dict (or split into a separate module once there are 3+). Each handler is ~30 lines.

**Estimated effort:** 4–6 hours for the top six. **Don't do this now** — wait until FAANG cycles open so you can actually verify handlers work against real data.

### 4. Expand the Applied tracker into a real personal ATS
The Applied tab currently just hides jobs. Extend it with:
- `applied_date` (manual override; defaults to `applied_at`)
- `status` enum: applied / OA received / phone screen / onsite / offer / rejected / ghosted
- `notes` free text
- `next_action_date` with a soft "overdue" badge if past

Turns the tool into a full application tracker so you stop juggling a separate spreadsheet.

**Estimated effort:** half a day. High daily value once #1 and #2 are live.

### 5. Dedupe across companies
Some roles appear twice — e.g., Hudson River Trading on their own site and on Greenhouse, or a parent company and subsidiary listing the same req. Add a soft-dedup key `(company_normalized, title_normalized, location_normalized)` and hide/collapse duplicates in the UI.

**Estimated effort:** 1–2 hours.

### 6. Description-based categorization pass
"Intern (Uncategorized)" is currently ~50% of rows. Most of those could be resolved by fetching and scanning the job description for season/year clues — but not all scrapers fetch descriptions today. Audit which scrapers skip descriptions and add them where cheap (Greenhouse / Ashby / Lever already provide them in the listing JSON; Workday needs an extra request per job; iCIMS same).

**Estimated effort:** 2–3 hours.

---

## Honest calibration on the "apply first" edge
**FAANG**: being applicant #1 vs #5000 barely moves the needle — they hire by recruiter queue and referral. Don't over-optimize speed for these; optimize for referrals instead.

**Quant / trading** (Jane Street, HRT, Citadel, Two Sigma, Jump): first ~50 applicants usually get manual resume review; rest auto-reject. Speed matters a lot here.

**Startups** (<500 people): hiring managers read the first batch of apps directly. First-mover advantage is real.

**Niche roles** (kernel, embedded, security, distributed systems): low volume, early movers win.

So: **item #1 above (polling + notifications) pays off mostly for the Quant and Startup buckets, not FAANG.** Calibrate where to invest effort accordingly.
