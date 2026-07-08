import html
import re
from urllib.parse import urlsplit
from scraper.base import BaseScraper

# Radancy (formerly TMP) hosts branded career sites like capitalonecareers.com.
# The server-rendered /search-jobs/{keyword}/{location} page IGNORES the
# keyword — results load client-side from the /search-jobs/results AJAX
# endpoint — so scraping the page HTML (or rendering it without running the
# search) returns an arbitrary default job list. Query the AJAX endpoint
# directly instead; it returns JSON whose "results" field is an HTML fragment.

_JOB_LINK_RE = re.compile(
    r'<a[^>]+href="(?P<href>[^"]*/job/[^"]+)"[^>]*data-job-id="(?P<id>\d+)"'
    r'[^>]*>(?P<body>.*?)</a>',
    re.S | re.I,
)
_TITLE_RE = re.compile(r'<h2[^>]*>(.*?)</h2>', re.S | re.I)
_LOCATION_RE = re.compile(r'class="job-location"[^>]*>(.*?)</span>', re.S | re.I)
_DATE_RE = re.compile(r'class="job-date-posted"[^>]*>(.*?)</span>', re.S | re.I)

# Companies title campus roles without SWE words ("Technology Development
# Program - 2027"), so the keyword sweep must cast wider than "software
# engineer"; the title filters downstream keep only backend SWE roles.
DEFAULT_KEYWORDS = [
    "software engineer",
    "intern",
    "new grad",
    "development program",
    "2027",
]

_MAX_PAGES = 10  # per keyword, 100 records each — safety cap


def _clean(fragment):
    return html.unescape(re.sub(r'<[^>]+>', ' ', fragment)).strip()


class RadancyScraper(BaseScraper):
    ats_name = "radancy"

    def _fetch_jobs(self, company_cfg):
        site = company_cfg.get("url", "")
        if not site:
            return []
        parts = urlsplit(site)
        base = f"{parts.scheme}://{parts.netloc}"
        keywords = company_cfg.get("keywords") or DEFAULT_KEYWORDS

        jobs_by_id = {}
        for kw in keywords:
            for page in range(1, _MAX_PAGES + 1):
                params = {
                    "ActiveFacetID": 0,
                    "CurrentPage": page,
                    "RecordsPerPage": 100,
                    "Distance": 50,
                    "RadiusUnitType": 0,
                    "Keywords": kw,
                    "Location": "",
                    "ShowRadius": "False",
                    "IsPagination": "False" if page == 1 else "True",
                    "SearchResultsModuleName": "Search Results",
                    "SearchFiltersModuleName": "Search Filters",
                    "SortCriteria": 0,
                    "SortDirection": 1,
                    "SearchType": 5,
                    "ResultsType": 0,
                }
                data = self.fetch_json(
                    f"{base}/search-jobs/results",
                    params=params,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                fragment = data.get("results", "") or ""
                matches = _JOB_LINK_RE.findall(fragment)
                new = 0
                for href, job_id, body in matches:
                    if job_id in jobs_by_id:
                        continue
                    title_m = _TITLE_RE.search(body)
                    if not title_m:
                        continue
                    loc_m = _LOCATION_RE.search(body)
                    date_m = _DATE_RE.search(body)
                    jobs_by_id[job_id] = {
                        "title": _clean(title_m.group(1)),
                        "url": base + href if href.startswith("/") else href,
                        "location": _clean(loc_m.group(1)) if loc_m else "",
                        "date_posted": _clean(date_m.group(1)) if date_m else "",
                        "description": "",
                    }
                    new += 1
                # Stop paging once a page adds nothing new or came back short.
                if new == 0 or len(matches) < 100:
                    break
                self.throttle()
        return list(jobs_by_id.values())
