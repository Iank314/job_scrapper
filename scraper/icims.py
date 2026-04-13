import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from scraper.base import BaseScraper


class ICIMSScraper(BaseScraper):
    """Scrape iCIMS career portals.

    iCIMS's /jobs/search endpoint is POST-only and returns 405 on GET, but
    their embedded-iframe view at /jobs/search?in_iframe=1&pr=0 serves a
    GET-friendly HTML listing. We pull that, then extract posting links.
    """
    ats_name = "icims"
    use_browser_headers = True

    def _fetch_jobs(self, company_cfg):
        url = company_cfg.get("url", "")
        if not url:
            return []

        # If the yaml URL is the raw /jobs/search path, rewrite it to the
        # GET-able iframe variant that ignores the search POST requirement.
        parsed = urlparse(url)
        tenant = f"{parsed.scheme}://{parsed.netloc}"
        fetch_url = (
            f"{tenant}/jobs/search"
            "?pr=0&in_iframe=1&searchRelation=keyword_all"
            "&searchKeyword=software+engineer+intern"
            "&mobile=false&widget=0&rmpdu=0"
        )

        try:
            html = self.fetch_html(fetch_url)
        except Exception:
            # Fall back to the tenant root if the iframe URL is blocked.
            html = self.fetch_html(f"{tenant}/jobs/intro")

        soup = BeautifulSoup(html, "html.parser")
        results = []
        seen = set()

        # iCIMS job listings are anchor tags pointing at /jobs/<id>/<slug>/job
        job_href = re.compile(r"/jobs/\d+/[^/]+/job")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not job_href.search(href):
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            full = urljoin(tenant, href)
            if full in seen:
                continue
            seen.add(full)
            results.append({
                "title": title,
                "url": full,
                "location": "",
                "date_posted": "",
            })

        return results
