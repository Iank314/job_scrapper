import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from scraper.base import BaseScraper
from filters import extract_us_location


# Link text that plausibly names a role. Deliberately broad: this only decides
# what is worth handing to the filter chain, and base.scrape_company() then
# applies the real title/location/seniority/cycle gates.
#
# It used to also require an explicit cycle token ("Spring 2027", "class of
# 2027", ...) in the same link text, which is stricter than anything else in the
# pipeline: filters.categorize() is recall-first and defaults a year-less
# new-grad or intern posting to the 2027 class. Boards that render plain
# "Software Engineer Intern" links — most of them — matched nothing at all, and
# 18 of the 18 `generic` companies were returning zero rows because of it.
ROLE_TEXT_RE = re.compile(
    r'\b(?:intern(ship)?s?|co[-\s]?ops?|new\s*grad\w*|grad(uate)?s?|campus|'
    r'university|entry[-\s]?level|early[-\s]?career|'
    r'software|engineer(ing)?|developer|swe|sde|backend|back[-\s]?end|'
    r'platform|infrastructure|architect|programmer)\b',
    re.IGNORECASE,
)

# Hrefs that look like a link to one specific posting rather than a nav target.
JOB_HREF_RE = re.compile(
    r'/(?:job|jobs|apply|career|careers|opening|openings|position|positions|'
    r'vacancy|vacancies|posting|postings|req)s?[/-][A-Za-z0-9]',
    re.IGNORECASE,
)

# Obvious non-postings.
SKIP_HREF_RE = re.compile(
    r'(^#|^javascript:|^mailto:|^tel:|/privacy|/terms|/cookie|/accessibility|'
    r'/login|/signin|/register|/faq|/help|/rss|\.pdf$|\.zip$)',
    re.IGNORECASE,
)


class GenericScraper(BaseScraper):
    ats_name = "generic"
    use_browser_headers = True

    def _fetch_jobs(self, company_cfg):
        """`url:` may be a single string or a list — a keyword-search career
        page only returns what the query asks for, so covering both the intern
        and the new-grad cycle takes two URLs."""
        urls = company_cfg.get("url", "")
        if isinstance(urls, str):
            urls = [urls] if urls else []
        if not urls:
            return []

        merged, seen = [], set()
        for url in urls:
            for job in self._fetch_one(url):
                if job["url"] not in seen:
                    seen.add(job["url"])
                    merged.append(job)
        return merged

    def _fetch_one(self, url):
        html = self.fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(url).netloc

        results = []
        seen = set()

        for link in soup.find_all("a", href=True):
            text = link.get_text(" ", strip=True)
            href = link["href"].strip()

            if not href or SKIP_HREF_RE.search(href):
                continue
            if not text or len(text) < 5 or len(text) > 200:
                continue

            # Either the text names a role, or the URL points at a posting.
            if not (ROLE_TEXT_RE.search(text) or JOB_HREF_RE.search(href)):
                continue

            full = urljoin(url, href)
            # Stay on the career host — boards link out to LinkedIn, press, etc.
            if urlparse(full).netloc != host:
                continue
            if full in seen:
                continue
            seen.add(full)

            parent = link.find_parent(["li", "tr", "article", "section", "div"])
            context = parent.get_text(" | ", strip=True) if parent else ""
            results.append({
                "title": text,
                "url": full,
                "location": extract_us_location(context),
                "date_posted": "",
            })

        return results
