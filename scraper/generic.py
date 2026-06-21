import re
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from filters import extract_us_location


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
        target_cycle = (
            r'\b(?:fall|autumn)\s*2026\b|'
            r'\b(?:spring|winter|summer)\s*2027\b|'
            r'\bclass\s*of\s*2027\b|'
            r'\b2027\b.{0,50}\b(?:new\s*grad|university\s*grad|graduate)\b|'
            r'\b(?:new\s*grad|university\s*grad|graduate)\b.{0,50}\b2027\b'
        )
        target_role = (
            r'\b(?:intern(ship)?s?|co[-\s]?ops?|new\s*grad|university\s*grad|'
            r'software|engineer|swe|backend|platform)\b'
        )
        job_pattern = re.compile(
            r'(?=.*(?:' + target_cycle + r'))(?=.*(?:' + target_role + r'))',
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
                context = ""
                parent = link.find_parent(["li", "tr", "article", "section", "div"])
                if parent:
                    context = parent.get_text(" | ", strip=True)
                results.append({
                    "title": text,
                    "url": href,
                    "location": extract_us_location(context),
                    "date_posted": "",
                })

        return results
