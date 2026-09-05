# Job Scraper

Scrapes career pages of 250+ companies for backend SWE internships and new grad roles, targeting the **~May 2027 graduating class**. Filters out non-engineering positions and categorizes results into:

Internships (while still enrolled):
- **Spring 2027 Intern**
- **Summer 2027 Intern**

New grad / early career (starting on/after May 2027):
- **2027 New Grad** — season-less (campus / class-of-2027 / University Grad 2027 / "graduating Dec 2026 – June 2027")
- **Summer 2027 New Grad**
- **Fall 2027 New Grad**
- **Spring 2027 New Grad**

Results are displayed in a local web UI with search, filtering, and sorting.

## How it works

Most companies use one of a few Applicant Tracking Systems (Greenhouse, Lever, Workday, Ashby, etc.). This scraper hits their public APIs to pull job listings, then filters by backend SWE keywords (backend, infrastructure, distributed systems, SRE, embedded, etc.) and excludes irrelevant roles (frontend, marketing, HR, etc.).

Companies are configured in `companies.yaml` — add or remove entries anytime.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Scrape all companies then launch the web UI
python run.py

# Just scrape, no UI
python run.py --scrape

# Just launch the UI with existing data
python run.py --web

# Use a custom port
python run.py --port 8080
```

Then open **http://localhost:5000** in your browser.

## Automatic scraping (Windows)

To scrape automatically three times a day — **12:00 PM, 6:00 PM, and 12:30 AM** — register a Task Scheduler job:

```bash
python scripts/setup_scheduler.py
```

Each run uses `run.py --if-due`, which only scrapes if a scheduled time has
passed since the last run. So if the laptop was asleep and missed one or more
slots, it runs a **single** catch-up scrape on wake-up instead of one per
missed slot. (It skips when offline and only runs one instance at a time.)

```bash
# What Task Scheduler runs under the hood — safe to run manually too
python run.py --if-due

schtasks /Query /TN "JobScraper" /V /FO LIST   # verify
schtasks /Run   /TN "JobScraper"               # trigger a run now
schtasks /Delete /TN "JobScraper" /F           # remove
```

On Linux/macOS the script prints equivalent `crontab` lines instead.

## Adding companies

Edit `companies.yaml`. Each entry needs a name, ATS type, and either a `board_id` or `url`:

```yaml
- name: Stripe
  ats: greenhouse
  board_id: stripe

- name: Intel
  ats: workday
  url: https://intel.wd1.myworkdayjobs.com/en-US/External
```

Supported ATS types: `greenhouse`, `lever`, `ashby`, `smartrecruiters`, `workday`, `icims`, `generic`.
