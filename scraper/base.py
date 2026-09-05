import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import REQUEST_TIMEOUT, RATE_LIMIT_DELAY
from filters import matches_backend_swe, categorize, is_us_location, requires_phd
from db import sync_company_jobs

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


# With MAX_WORKERS threads negotiating TLS at once, hosts intermittently drop
# the handshake and requests raises SSLError(SSLEOFError: UNEXPECTED_EOF...).
# Every host that failed this way (Nvidia, Dell, Intel, Salesforce, Adobe,
# Cisco, Broadcom, HP, Cohere, OpenAI, DeepMind, Hugging Face) answers fine on
# a retry, so one flaky handshake shouldn't cost the company for the whole run.
#
# urllib3 classifies SSLError as neither a connect nor a read error, so it is
# the `total` budget that absorbs these — connect/read alone would not retry.
# allowed_methods=None is required because Workday's cxs job search is a POST,
# and the default allowlist is idempotent-methods-only: it would skip retrying
# exactly the requests that fail most. raise_on_status=False keeps the final
# response so raise_for_status() can still produce our 403/404 messages.
RETRY_POLICY = Retry(
    total=3,
    backoff_factor=0.7,  # ~0s, 0.7s, 1.4s between attempts
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=None,
    raise_on_status=False,
    respect_retry_after_header=True,
)


class BaseScraper:
    ats_name = "base"
    use_browser_headers = False  # Subclasses set True for HTML scraping
    retry_policy = RETRY_POLICY  # Subclasses override when a host needs its own

    def __init__(self):
        self.session = requests.Session()
        headers = BROWSER_HEADERS if self.use_browser_headers else API_HEADERS
        self.session.headers.update(headers)
        adapter = HTTPAdapter(max_retries=self.retry_policy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

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
            elif status == 405:
                print(f"  [!] {self.ats_name}/{name}: HTTP 405 — endpoint rejects GET "
                      f"(often an AWS WAF challenge); needs the playwright scraper")
            else:
                print(f"  [!] {self.ats_name}/{name}: HTTP {status} — {e}")
            return set()
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            # Retries already exhausted by RETRY_POLICY — the full urllib3 chain
            # is noise, so report the host and the underlying reason only.
            reason = "TLS handshake dropped" if isinstance(e, requests.exceptions.SSLError) else "connection failed"
            host = getattr(e.request, "url", "?") if e.request is not None else "?"
            print(f"  [!] {self.ats_name}/{name}: {reason} after retries — {host}")
            return set()
        except requests.exceptions.Timeout:
            print(f"  [!] {self.ats_name}/{name}: timed out after {REQUEST_TIMEOUT}s")
            return set()
        except Exception as e:
            print(f"  [!] {self.ats_name}/{name}: {e}")
            return set()

        jobs_to_save = []
        active_urls = set()
        seen_urls = set()
        for job in raw_jobs:
            title = job["title"]
            url = job["url"]
            location = job.get("location", "")
            date_posted = job.get("date_posted")
            description = job.get("description", "")

            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)

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
            jobs_to_save.append({
                "title": title,
                "url": url,
                "category": category,
                "location": location,
                "date_posted": date_posted,
            })

        new_urls = sync_company_jobs(name, self.ats_name, jobs_to_save, active_urls)
        new_jobs = [
            {
                "company": name,
                "title": job["title"],
                "url": job["url"],
                "category": job["category"],
                "location": job.get("location") or "",
            }
            for job in jobs_to_save
            if job["url"] in new_urls
        ]

        saved = len(jobs_to_save)
        if saved:
            new_tag = f" ({len(new_jobs)} new)" if new_jobs else ""
            print(f"  [+] {self.ats_name}/{name}: {saved} relevant jobs found{new_tag}")
        return new_jobs

    def _fetch_jobs(self, company_cfg):
        raise NotImplementedError

    def throttle(self):
        time.sleep(RATE_LIMIT_DELAY)
