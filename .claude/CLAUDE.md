# Job Scraper - Project Context

## What this project does
Scrapes career pages of ~400 companies for backend SWE internships and new grad roles, targeting the **~May 2027 graduating class**. Filters by US-only locations, excludes PhD-required, senior, and frontend roles, and categorizes into:
- Spring 2027 Intern
- Summer 2027 Intern
- 2027 New Grad (season-less: campus / class-of-2027 / University Grad 2027 / "graduating Dec 2026 – June 2027")
- Summer 2027 New Grad
- Fall 2027 New Grad
- Spring 2027 New Grad
- Fall 2026 New Grad

Fall 2026 Intern was dropped (that recruiting season is over).

Results display in a local Flask web UI at `localhost:5000` with a single-user login so you can mark jobs as **Applied**, **Accepted**, or **Trashed**. All states persist across re-scrapes.

## Architecture
- **Scrapers** (`scraper/`): One per ATS platform — Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday, iCIMS, Radancy (branded sites like capitalonecareers.com), Oracle HCM Cloud, generic HTML, and a Playwright-based browser scraper for JS-rendered SPAs. Each fetches job listings and (where cheap) descriptions.
- **Filters** (`filters.py`): Whole-word keyword matching for backend SWE roles (incl. software developer / SDE / architect titles); seniority exclusion (senior/staff/principal/lead/II/III/IV/L3+); US location filter; PhD exclusion; and season/year categorization where the **title is authoritative** and description is only a tiebreaker. **Tuned recall-first** — see Key decisions: a year-less new-grad/intern role defaults to the 2027 target class rather than being dropped, and only clearly non-US locations are rejected.
- **Database** (`db.py`): SQLite (`jobs.db`), single `jobs` table with deduplication by URL. Per-row state for `active`, `applied`, `trashed` — the scraper's `upsert_job` only touches scraper-owned columns, so applied/trashed flags survive re-scrapes.
- **Company config** (`companies.yaml`): ~400 entries. Each has `name`, `ats`, and either `board_id` or `url`.
- **Web UI** (`web/`): Flask app with dark-themed single-page table, Open/Applied/Trash tabs, login modal, per-row action buttons. Session auth via `APP_PASSWORD` from `.env`.
- **Entry point** (`run.py`): `python run.py` scrapes then launches UI. `--scrape` or `--web` for just one.
- **One-shot scripts** (`scripts/`): `classify_companies.py` parses the speedyapply markdown tables and diffs them against `companies.yaml`. `cleanup_db.py` removes rows that no longer pass the current filter. `audit_scrape.py` health-checks every entry without writing to the DB — see Key decisions.

## Key decisions
- JSON API scrapers (Greenhouse, Lever, Ashby) use clean `Accept: application/json` headers. HTML scrapers use browser-like headers with Sec-Fetch headers.
- iCIMS uses `/jobs/search?pr=0&in_iframe=1&...` since the normal `/jobs/search` is POST-only and returns 405 on GET.
- **Greenhouse metadata → title**: some boards put the intern/new-grad signal only in Greenhouse's custom metadata (Jane Street titles every campus role plain "Software Engineer" with `Employment Type: Full-Time: New Grad / Summer Internship / Winter Co-Op`). The Greenhouse scraper appends early-career metadata values to the title so `categorize()` sees them; values carrying seniority markers are never appended.
- **SmartRecruiters' postings list is a summary view — three traps.** (1) The `ref` field is the *API* URL (`api.smartrecruiters.com/v1/companies/{co}/postings/{id}`), so storing it put raw JSON in the UI's job links; the human-facing URL is `https://jobs.smartrecruiters.com/{company.identifier}/{id}` (bare id resolves 200, no slug needed). (2) `jobAd` is absent from the list response and only exists on the per-posting detail endpoint, so descriptions were always empty — the scraper now fetches details *only* for postings already past the title+location gate (ServiceNow has 445 postings but 20 candidates). (3) `location.country` is a lowercase ISO-2 code (`my`, `th`), which `is_us_location` can't recognize, so every foreign role leaked through; use `location.fullLocation` ("Petaling Jaya, Selangor, Malaysia") instead — present on 100% of records.
- **The playwright generic extractor had two silent job-killers** (found Aug 2026 when Google/Microsoft came back empty). (1) `HREF_SKIP_PATTERN` matched `/about` *anywhere* in a href, and every Google posting lives at `google.com/**about**/careers/applications/jobs/results/<id>` — so 100% of Google's jobs were dropped. A href matching `JOB_HREF_PATTERN` now outranks that boilerplate skip list. (2) Google's job link is a **text-less** "Learn more" button whose title lives only in `aria-label` ("Learn more about Software Engineer III, Cloud Networking"); the title chain now falls back to the accessible name (lead-ins like "Learn more about" / "View details for" are stripped) and finally to plain ancestor text. Ancestor lookup also requires a meaningfully longer ancestor, else a wrapper reading just "Learn more" wins over the real job card.
- **`url:` in companies.yaml may be a list** for playwright entries. Search-driven career SPAs return only what the query asks for, so an intern-keyword URL structurally *cannot* surface new-grad roles. Google needs `target_level=EARLY&employment_type=FULL_TIME` for new grad — a bare keyword search returns 800+ mostly-senior hits and only page 1 is ever read.
- **Microsoft is its own scraper (`ats: microsoft`), not playwright.** `careers.microsoft.com/v2/global/en/search` now 302s to a 404 page, and the `gcsservices.careers.microsoft.com` API in the old notes is dead (TLS cert hostname mismatch). The live portal is `apply.careers.microsoft.com/api/pcsx/search`. Two traps: `num` is ignored — the endpoint always returns ~10 positions, so paging must advance by the actual page length or you skip half the results; and its own `filter_seniority` facet is unreliable (`Intern` returns 0 while a live intern posting exists, `Entry` surfaces principal roles), so we run plain keyword queries and let filters.py decide.
- **Radancy sites ignore search keywords server-side** — the `/search-jobs/{keyword}/{location}` page renders a default job list; real results come from the `/search-jobs/results` AJAX endpoint (JSON with an HTML fragment). The radancy scraper queries that endpoint with a per-company `keywords:` list from companies.yaml. Campus program titles without SWE words ("Technology Development Program - 2027") are caught via INCLUDE_KEYWORDS additions plus a title-only development/rotation-program new-grad pattern in filters.py.
- **A retried `page.goto` on the *same* page is what wedges chromium — retry on a fresh page.** careers.honeywell.com answers with `ERR_HTTP2_PROTOCOL_ERROR`; a single attempt fails in 0.1s and the page closes instantly, but a *second* goto into that same failed renderer leaves chromium wedged, and the eventual `page.close()` then blocks for **~172 seconds** before the driver connection finally drops. That is what "stuck at Honeywell" was: the run stopped with three companies left to scrape and never reached the notification flush. `_goto_with_retry` now takes the *context* and hands back the page it succeeded (or failed) on.
- **The shared browser must be disposable, because one site can kill it.** Three separate guards, all verified against the live Honeywell URL: `_ensure_browser()` health-checks `is_connected()` plus a `_poisoned` flag and relaunches; a `_watchdog` kills the node driver if any company exceeds `HARD_DEADLINE_S` (90s), which is the *only* way to interrupt a blocked sync-API call — there is no timeout parameter on `close()`; and `_discard_browser()` never calls `browser.close()` on a poisoned driver. Two traps: `is_connected()` returns **True** for a wedged driver, so it cannot be the only check; and after a hard kill you must still call `playwright.stop()` (it returns instantly against a dead driver) or the next `sync_playwright().start()` refuses with *"It looks like you are using Playwright Sync API inside the asyncio loop"*.
- **Oracle HCM Cloud (`ats: oracle`) is a JSON API, not a browser job.** Sites shaped `{host}/hcmUI/CandidateExperience/en/sites/{site}` (Dell) or a vanity domain over the same app (Honeywell) are SPAs, but `/hcmRestApi/resources/latest/recruitingCEJobRequisitions` is public. Three quirks: `siteNumber` is **not validated** (CX_1/CX_2/CX_1001 all return the same board, so CX_1 works everywhere); the `keyword` filter is fuzzy, not a word match (`intern` returns 690 of Honeywell's 1350 because it also matches "Internal Audit Manager"), so we skip keywords entirely and enumerate the board — these are small (Dell 441, Honeywell 1350) and gating belongs in filters.py; and a vanity domain may **not proxy `/hcmRestApi`** (careers.honeywell.com 302s every REST call to an Oracle error page), which is what `api_host:` in companies.yaml overrides while `url:` stays the base for job links.
- **A 422 from every Workday site path means the *tenant* is gone, not the site.** Dell, Alight and IDEXX all 422'd on `/wday/cxs/{tenant}/{site}/jobs` for every plausible site name and 500'd on the human page: all three had left Workday (Dell → Oracle HCM, Alight and IDEXX → Phenom). Probing site names is wasted effort — fetch the company's public careers URL and see where it redirects.
- Playwright companies run **sequentially** sharing one browser (sync API isn't thread-safe). Timeouts capped: 20s goto / 8s networkidle / 1s settle / 3 scroll passes → ~30s max per company.
- **Connection errors are retried, because they're concurrency flakiness — not broken config.** 20 concurrent TLS handshakes make hosts intermittently drop the connection (`SSLEOFError: UNEXPECTED_EOF_WHILE_READING`); every host that failed this way answered fine on a sequential retry. `RETRY_POLICY` in `scraper/base.py` handles it. Two traps: urllib3 counts `SSLError` as neither a connect nor a read error, so only `total=` retries it; and `allowed_methods=None` is required because Workday's `cxs` search is a **POST** and the default allowlist is idempotent-only. Playwright gets the same treatment via `_goto_with_retry` for connection-level `ERR_*` codes only — **timeouts are not retried**, as that would blow the ~30s per-company budget.
- **Diagnose before editing `companies.yaml`**: only a *reproducible* 404/405/422 means the entry is actually wrong. Re-request sequentially first.
- **ATS keyword search is AND-across-tokens, never a phrase match.** This silently zeroed out whole platforms. Workday's `searchText: "2027 new grad"` requires *all three* tokens in one posting, which essentially never happens — measured on live tenants, `"grad"` returned 808/209/246 rows where `"2027 new grad"` returned 1/14/6, and **36 of 91 Workday companies were scraping nothing at all**. iCIMS behaves identically (`searchRelation=keyword_all`). Always search single tokens (`grad`, `intern`, `campus`, `early career`, `college`) and let `filters.py` do the gating. A term list must cover *disjoint vocabularies*: "Early Career" shares no token with grad/intern/campus, and omitting it silently dropped Blue Origin's entire campus ladder.
- **iCIMS 405s are triggered by the browser User-Agent, not by the URL.** The WAF in front of most iCIMS tenants answers a Chrome-like UA with 405 on every GET; the identical request with a plain `python-requests` UA returns 200 and a full listing (verified across 11 tenants). `ICIMSScraper` therefore overrides the session UA — do not "fix" it back to browser headers. Schwab and State Farm stay unreachable for unrelated reasons (tenant 404-gone / 302-away).
- **iCIMS anchors embed a hidden field label**, so link text arrives as `TitleSoftware Engineer` / `Job TitleDriver - Abilene`. That kills the `\b` in `\bsoftware engineer\b` and drops the role — strip the label before the title reaches the filters.
- **Workday's `workerSubType` facet is a first-class early-career signal** and catches roles whose title says nothing: Nvidia files "Software Architect, AI Networking" under *New College Graduate*. Facet ids are per-tenant GUIDs, so they are discovered from the facet block that rides along with any search response (no extra request) and the descriptor is appended to the title — the same trick the Greenhouse scraper uses for its metadata.
- **A search URL that names a cycle can only ever return that cycle.** 21 `companies.yaml` entries queried their site for the literal word "intern", so no new-grad posting could come back regardless of filter quality. `url:` accepts a **list** (playwright and generic both merge and dedupe), so intern-only entries carry a new-grad query alongside.
- **The generic scraper must not out-filter `filters.py`.** It used to require an explicit cycle token ("Spring 2027", "class of 2027") in the link text, which is stricter than `categorize()` — that is recall-first and defaults a year-less posting to the 2027 class. Every board rendering plain "Software Engineer Intern" links matched nothing, and all 18 `generic` companies returned zero. Candidate extraction should be broad; gating belongs in one place.
- **Titles put the year on either side of the grad word.** `"graduating ... 2027"` and `"2027 Grads"` are both common ("Software Engineer (C++ or Python) - 2027 Grads" at HRT, "Software Engineer (2027 Graduates) (Campus)" at Appian) — match both, or half the postings read as ordinary experienced roles.
- **A season-less title carrying a year names a graduating class, not a start date.** "Software Engineer - New Grad 2026" is the *2026* class; it used to fall through to the season-less 2027 bucket, so last cycle's postings diluted the one that matters. Only the title's year is trusted for this — description prose is full of unrelated years.
- **Underscores suppress `\b`.** GE Appliances posts "Software Engineering Co-op_Spring 2027", where `\bco[-\s]?ops?\b` cannot match across `op_S` and the cycle token is invisible. `categorize()` normalizes `_` to a space first.
- **`scripts/audit_scrape.py` is the tool for all of the above.** It runs every company's `_fetch_jobs` without touching the DB and records *which gate* dropped each posting, so config breakage (errors / zero raw) and filter recall gaps (early-career titles that got dropped) are separable. Run it before and after any filter change and diff — that is what caught the Blue Origin regression.
- **Recall-first filtering** (better to over-include than miss a crucial role): the location filter rejects a role *only* when it has an explicit non-US signal and no US signal — blank / remote / ambiguous locations are kept. Likewise `categorize()` no longer requires an explicit year: a new-grad/early-career role (or a title-level intern) with no cycle in the text defaults to the ~2027 target class instead of being dropped. The strong gate that keeps volume bounded is the intern/new-grad **category** requirement — plain experienced "Software Engineer" roles still get no category and are excluded.
- `architect`-style titles (software / system / systems / solutions / cloud / data architect) are **included**, not treated as senior. Bare seniority markers (senior/staff/principal/lead/…) still exclude, so "Senior Software Architect" is still dropped. "Experienced" (and French "chevronné" on bilingual boards) also counts as a seniority marker.
- **Location matching is accent-folded** — "Montréal"/"Zürich" fold to "montreal"/"zurich" before the non-US check, otherwise accented spellings slip past the filter (bit us on Tower Research's bilingual Montréal posting).
- **Description signals are negation-checked within their own sentence.** Postings routinely name an early-career cycle in order to *exclude* it, and reading those naively was the biggest polluter of the "2027 New Grad" bucket: Airtable's "Please note this is **not** a new grad position" (on a role titled *4-8 YOE*), Stripe's "if you are an intern, new grad, staff… please **do not apply** using this posting", SpaceX's "positions **ranging from** entry-level to very experienced". `_description_signal()` scopes negation to the sentence containing the match, so a cue in a *neighbouring* sentence ("This is a new grad role. Experienced candidates should not apply.") does not disqualify, and a bare "not" isn't enough — it must be a copular/prepositional denial ("is not a/an/for") or a seniority-spanning range, so "do **not** hesitate to apply" stays safe. Titles are never routed through this check: a title that says new grad means it.
- **A title-level intern never falls through to the new-grad path**, and `_intern_category` trusts only the *title's* year. Descriptions state the candidate's **graduation** date ("graduating in December 2026 or later", "expected graduation date between 2026 - 2028"), which is not the internship's cycle — letting it win pushed Nuro's and Ramp's clearly-titled interns into "2027 New Grad". Net effect of both fixes across the audited set: 2027 New Grad 86 → 77, Summer 2027 Intern 72 → 80.
- **Workday's `DEFAULT_SEARCH_TERMS` are deliberately year-specific — do not "broaden" them.** Measured Aug 2026: adding year-less early-career terms took Salesforce 14→230 raw, Adobe 8→188, Blue Origin 16→148 and yielded **zero** extra kept jobs in every case. Companies returning 0 (PayPal, Snap, Zillow) do so because they have no early-career SWE roles open, not because the query is too narrow.
- **Campus/university *recruiting* phrases are title-only signals**: in description prose they usually describe an experienced hire's duties ("occasional campus recruiting trips"), not eligibility — matching them in descriptions mislabeled an experienced Tower role as new grad. Eligibility phrasings (new grad, recent graduate, class of 20XX, entry level, graduate program…) still match title+description.
- **Quant-shop developer titles** (quantitative developer, quant developer, python/c++/java developer, low latency developer) are include keywords — quant firms title SWE roles without "software engineer" (e.g. Tower's "Quantitative Developer Intern - Summer 2027").
- `scripts/cleanup_db.py` never deletes rows with `applied`/`accepted` state — application history survives filter tightening.
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
- **Bank of America is commented out — `careers.bankofamerica.com` does not respond at all.** curl gets zero bytes in 40s and headless Chromium times out at 60s, on both the campus page and the job search; `campus.bankofamerica.com` only 302s onto that same dead host. Check it by hand, like Schwab and State Farm.
- **Jahnel Group is commented out.** They left Greenhouse, and their own `/positions` page renders every role as a card whose only anchors are `href="#"` — the "clickable divs without anchor tags" limitation above. All 12 current roles are senior/lead anyway.
- **Charles Schwab and State Farm are commented out in `companies.yaml`, not fixable.** Their iCIMS tenants sit behind an AWS WAF challenge that returns 405 to *every* GET (including `/`) and serves an interactive "confirm you are human" CAPTCHA that real headless Chromium can't clear either. Check those two by hand.

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
