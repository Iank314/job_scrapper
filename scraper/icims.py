import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from filters import extract_us_location


# iCIMS's own search is keyword-AND (`searchRelation=keyword_all`), exactly like
# Workday's: "new grad" requires both tokens in the posting and returns nothing,
# while "grad" alone returns 14 on the same tenant. Single tokens only.
DEFAULT_SEARCH_TERMS = (
    # An empty keyword lists the whole board. Some tenants index nothing for a
    # keyword search at all — Canon returns 0 for "software engineer" but 20 for
    # no keyword — so without this the company silently scrapes zero.
    "",
    "software engineer",
    "software developer",
    "grad",
    "intern",
    "campus",
    "university",
    "early career",
)

# Anchors to iCIMS posting pages: /jobs/<id>/<slug>/job
JOB_HREF_RE = re.compile(r"/jobs/\d+/[^/]+/job")

# Each posting link wraps a visually-hidden field label ("Title" on most
# tenants, "Job Title" on others), so the anchor's text comes out as
# "TitleSoftware Engineer" / "Job TitleSoftware Engineer". Left in place it
# destroys the word boundary the include-keyword regex needs — \bsoftware
# engineer\b cannot match "TitleSoftware Engineer" — so every such role was
# silently dropped.
TITLE_LABEL_RE = re.compile(r"^\s*(?:job\s*)?title(?=[A-Z0-9])", re.IGNORECASE)

# Some tenants have migrated off the iframe view and answer with nothing but a
# redirect script. Detect it so the entry gets reported as misconfigured rather
# than silently scraping zero jobs.
REDIRECT_RE = re.compile(r"window\.top\.location\.href\s*=\s*'([^']+)'")


class ICIMSScraper(BaseScraper):
    """Scrape iCIMS career portals.

    iCIMS's /jobs/search endpoint is POST-only and returns 405 on GET, but their
    embedded-iframe view at /jobs/search?in_iframe=1&pr=0 serves a GET-friendly
    HTML listing. We pull that, then extract posting links.

    Two things make or break this scraper:

    * **Do not send a browser User-Agent.** The AWS WAF in front of most iCIMS
      tenants answers a Chrome-like UA with 405 on *every* GET, which is what
      made these look permanently blocked. The same URL with a plain
      `python-requests` UA returns 200 and a full listing — verified across
      Aerotek, Berkley, Bio-Rad, CalAmp, Canon, Enterprise, EverWatch, GDMS,
      Iridium, ISYS and Joby. (Schwab and State Farm stay unreachable for a
      different reason: their tenants are 404-gone and 302-away respectively.)
    * **Page through.** One request returns 20-30 rows; `pr=N` is the page.
    """

    ats_name = "icims"
    use_browser_headers = False

    def __init__(self):
        super().__init__()
        # Deliberately unbranded — see the class docstring. Anything resembling
        # a real browser trips the WAF.
        self.session.headers.update({
            "User-Agent": "python-requests/2.31",
            "Accept": "text/html,application/xhtml+xml",
        })

    def _fetch_jobs(self, company_cfg):
        url = company_cfg.get("url", "")
        if not url:
            return []

        parsed = urlparse(url)
        tenant = f"{parsed.scheme}://{parsed.netloc}"
        max_pages = int(company_cfg.get("max_pages", 4))
        search_terms = company_cfg.get("search_terms") or DEFAULT_SEARCH_TERMS
        if isinstance(search_terms, str):
            search_terms = (search_terms,)

        results = []
        seen = set()
        fetched_any = False
        moved_to = None

        for term in search_terms:
            for page in range(max_pages):
                search_url = (
                    f"{tenant}/jobs/search?pr={page}&in_iframe=1"
                    f"&searchRelation=keyword_all&searchKeyword={term.replace(' ', '+')}"
                    "&mobile=false&widget=0&rmpdu=0"
                )
                try:
                    html = self.fetch_html(search_url)
                except Exception:
                    if not fetched_any:
                        raise
                    break
                fetched_any = True

                redirect = REDIRECT_RE.search(html)
                if redirect and "icims.com" not in redirect.group(1):
                    # Not fatal on its own: several tenants serve this bounce
                    # script on some views while still listing jobs on others.
                    # Only report it if nothing at all came back.
                    moved_to = redirect.group(1).replace("\\/", "/")
                    break

                added = self._extract(html, tenant, results, seen)
                if not added:
                    break
                self.throttle()

        if not results and moved_to:
            raise RuntimeError(f"tenant has moved to {moved_to} — update companies.yaml")

        return results

    def _extract(self, html, tenant, results, seen):
        soup = BeautifulSoup(html, "html.parser")
        added = 0
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not JOB_HREF_RE.search(href):
                continue
            title = TITLE_LABEL_RE.sub("", link.get_text(strip=True)).strip()
            if not title or len(title) < 5:
                continue
            full = urljoin(tenant, href)
            if full in seen:
                continue
            seen.add(full)
            parent = link.find_parent(["li", "tr", "article", "section", "div"])
            context = parent.get_text(" | ", strip=True) if parent else ""
            results.append({
                "title": title,
                "url": full,
                "location": extract_us_location(context),
                "date_posted": "",
            })
            added += 1
        return added
