import re
from bs4 import BeautifulSoup
from scraper.base import BaseScraper


class GenericScraper(BaseScraper):
    ats_name = "generic"
    use_browser_headers = True

    def _fetch_jobs(self, company_cfg):
        url = company_cfg.get("url", "")
        if not url:
            return []

        html = self.fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        job_pattern = re.compile(
            r'intern|new\s*grad|entry\s*level|software|engineer|swe|backend|platform',
            re.IGNORECASE
        )

        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            href = link["href"]

            if not text or len(text) < 5 or len(text) > 200:
                continue

            if job_pattern.search(text):
                if not href.startswith("http"):
                    href = url.rstrip("/") + "/" + href.lstrip("/")
                results.append({
                    "title": text,
                    "url": href,
                    "location": "",
                    "date_posted": "",
                })

        return results
