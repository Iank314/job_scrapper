import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import COMPANIES_FILE, MAX_WORKERS
from db import pending_notifications, mark_notified, discard_stale_notifications
from notify import send_new_jobs
from scraper.greenhouse import GreenhouseScraper
from scraper.lever import LeverScraper
from scraper.ashby import AshbyScraper
from scraper.smartrecruiters import SmartRecruitersScraper
from scraper.workday import WorkdayScraper
from scraper.icims import ICIMSScraper
from scraper.generic import GenericScraper
from scraper.radancy import RadancyScraper
from scraper.microsoft import MicrosoftScraper
from scraper.oracle import OracleScraper
from scraper.workable import WorkableScraper
from scraper.playwright_scraper import PlaywrightScraper, close_browser

SCRAPERS = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "ashby": AshbyScraper,
    "smartrecruiters": SmartRecruitersScraper,
    "workday": WorkdayScraper,
    "icims": ICIMSScraper,
    "generic": GenericScraper,
    "radancy": RadancyScraper,
    "microsoft": MicrosoftScraper,
    "oracle": OracleScraper,
    "workable": WorkableScraper,
    "playwright": PlaywrightScraper,
}


def load_companies():
    with open(COMPANIES_FILE, "r") as f:
        data = yaml.safe_load(f)
    return data.get("companies", [])


def scrape_one(company_cfg):
    ats = company_cfg.get("ats", "generic")
    scraper_cls = SCRAPERS.get(ats, GenericScraper)
    scraper = scraper_cls()
    return scraper.scrape_company(company_cfg)


def run_all():
    companies = load_companies()
    print(f"Scraping {len(companies)} companies...\n")

    pw_companies = [c for c in companies if c.get("ats") == "playwright"]
    api_companies = [c for c in companies if c.get("ats") != "playwright"]

    all_new_jobs = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(scrape_one, c): c["name"] for c in api_companies}
        for future in as_completed(futures):
            name = futures[future]
            try:
                new_jobs = future.result()
                if new_jobs:
                    all_new_jobs.extend(new_jobs)
            except Exception as e:
                print(f"  [!] {name}: {e}")

    if pw_companies:
        print(f"\nScraping {len(pw_companies)} browser-rendered companies...")
        pw_scraper = PlaywrightScraper()
        for c in pw_companies:
            try:
                new_jobs = pw_scraper.scrape_company(c)
                if new_jobs:
                    all_new_jobs.extend(new_jobs)
            except Exception as e:
                print(f"  [!] {c['name']}: {e}")
        close_browser()

    if all_new_jobs:
        print(f"\n{len(all_new_jobs)} new jobs found this run.")
    else:
        print("\nNo new jobs this run.")

    # Alerts are driven off the DB rather than `all_new_jobs` so that anything a
    # previous run failed to deliver is picked up here, and so a failure now
    # stays pending instead of vanishing with this process.
    discard_stale_notifications()
    pending = pending_notifications()
    if pending:
        backlog = len(pending) - len(all_new_jobs)
        if backlog > 0:
            print(f"Retrying {backlog} alert(s) undelivered from an earlier run.")
        delivered = send_new_jobs(pending)
        mark_notified([job["url"] for job in delivered])
        undelivered = len(pending) - len(delivered)
        if undelivered:
            print(f"  [!] {undelivered} alert(s) undelivered - will retry next run.")

    print("Scraping complete.")
