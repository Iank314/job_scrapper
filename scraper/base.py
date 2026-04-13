import time
import requests
from config import REQUEST_TIMEOUT, RATE_LIMIT_DELAY
from filters import matches_backend_swe, categorize, is_us_location, requires_phd
from db import upsert_job, mark_inactive

# Clean headers for JSON APIs (Greenhouse, Lever, Ashby, SmartRecruiters)
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# Browser-like headers for HTML scraping (generic, iCIMS)
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class BaseScraper:
    ats_name = "base"
    use_browser_headers = False  # Subclasses set True for HTML scraping

    def __init__(self):
        self.session = requests.Session()
        headers = BROWSER_HEADERS if self.use_browser_headers else API_HEADERS
        self.session.headers.update(headers)

    def fetch_json(self, url, method="GET", **kwargs):
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def fetch_html(self, url, **kwargs):
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        resp = self.session.get(url, **kwargs)
        resp.raise_for_status()
        return resp.text

    def scrape_company(self, company_cfg):
        """Scrape a single company. Returns set of saved URLs."""
        name = company_cfg["name"]
        try:
            raw_jobs = self._fetch_jobs(company_cfg)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status == 403:
                print(f"  [!] {self.ats_name}/{name}: BLOCKED (403 Forbidden) — site requires browser/JS")
            elif status == 404:
                print(f"  [!] {self.ats_name}/{name}: URL not found (404) — check companies.yaml")
            else:
                print(f"  [!] {self.ats_name}/{name}: HTTP {status} — {e}")
            return set()
        except Exception as e:
            print(f"  [!] {self.ats_name}/{name}: {e}")
            return set()

        saved = 0
        new_jobs = []
        active_urls = set()
        for job in raw_jobs:
            title = job["title"]
            url = job["url"]
            location = job.get("location", "")
            date_posted = job.get("date_posted")
            description = job.get("description", "")

            if not matches_backend_swe(title):
                continue

            if not is_us_location(location):
                continue

            if requires_phd(title, description):
                continue

            category = categorize(title, description)
            if category is None:
                continue

            active_urls.add(url)
            is_new = upsert_job(name, title, url, category, self.ats_name, location, date_posted)
            saved += 1
            if is_new:
                new_jobs.append({
                    "company": name,
                    "title": title,
                    "url": url,
                    "category": category,
                    "location": location or "",
                })

        mark_inactive(self.ats_name, name, active_urls)

        if saved:
            new_tag = f" ({len(new_jobs)} new)" if new_jobs else ""
            print(f"  [+] {self.ats_name}/{name}: {saved} relevant jobs found{new_tag}")
        return new_jobs

    def _fetch_jobs(self, company_cfg):
        raise NotImplementedError

    def throttle(self):
        time.sleep(RATE_LIMIT_DELAY)
