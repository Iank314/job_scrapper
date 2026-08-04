"""Microsoft careers scraper (apply.careers.microsoft.com JSON API).

Microsoft retired careers.microsoft.com/v2/global/en/search — it now 302s to a
404 page, which is why the playwright entry silently returned nothing. The
replacement portal is a JSON-backed SPA, so this talks to its API directly
instead of driving a browser: faster, paginated, and it runs in the concurrent
HTTP pool rather than the sequential playwright pass.

Two quirks worth knowing:

* `num` is not honoured — the search endpoint always returns ~10 positions per
  call, so paging must advance by however many came back, not by a page size.
  Assuming a page size skips half the results.
* The portal's own `filter_seniority` facet is unreliable: `Intern` returns 0
  even while "Software Engineer: Intern Opportunities for University Students"
  is live, and `Entry` surfaces principal-level roles. We therefore run plain
  keyword queries and let filters.py decide, which is also how every other
  scraper here behaves.
"""

import html
import re
import time

from scraper.base import BaseScraper
from filters import matches_backend_swe, is_us_location

SEARCH_URL = "https://apply.careers.microsoft.com/api/pcsx/search"
DETAIL_URL = "https://apply.careers.microsoft.com/api/pcsx/position_details"
JOB_URL = "https://apply.careers.microsoft.com/careers/job/{job_id}"
DOMAIN = "microsoft.com"

# Broad enough to cover both cycles the target class cares about: the summer
# internship and the full-time new-grad/university openings.
DEFAULT_QUERIES = (
    "software engineer intern",
    "software engineer university",
    "software engineer new grad",
    "software engineer",
)

MAX_PAGES_PER_QUERY = 15
MAX_DETAIL_FETCHES = 40
TAG_RE = re.compile(r"<[^>]+>")


class MicrosoftScraper(BaseScraper):
    ats_name = "microsoft"

    def _fetch_jobs(self, company_cfg):
        queries = company_cfg.get("queries") or DEFAULT_QUERIES
        if isinstance(queries, str):
            queries = (queries,)
        location = company_cfg.get("location", "United States")

        by_id = {}
        for query in queries:
            for pos in self._search(query, location):
                by_id[pos["id"]] = pos

        results = [self._to_job(p) for p in by_id.values()]
        self._attach_descriptions(results)
        for job in results:
            job.pop("_id", None)
        return results

    def _search(self, query, location):
        start = 0
        for _ in range(MAX_PAGES_PER_QUERY):
            data = self.fetch_json(SEARCH_URL, params={
                "domain": DOMAIN,
                "query": query,
                "location": location,
                "start": start,
            })
            positions = (data.get("data") or {}).get("positions") or []
            if not positions:
                return
            for pos in positions:
                if pos.get("id"):
                    yield pos
            # `num` is ignored by the API — advance by the actual page length.
            start += len(positions)
            count = (data.get("data") or {}).get("count")
            if isinstance(count, int) and start >= count:
                return
            self.throttle()

    def _to_job(self, pos):
        locations = pos.get("standardizedLocations") or pos.get("locations") or []
        posted = pos.get("postedTs") or pos.get("creationTs")
        try:
            date_posted = time.strftime("%Y-%m-%d", time.gmtime(int(posted))) if posted else ""
        except (TypeError, ValueError, OSError):
            date_posted = ""

        return {
            "title": pos.get("name", ""),
            "url": JOB_URL.format(job_id=pos["id"]),
            "location": ", ".join(str(x) for x in locations if x),
            "date_posted": date_posted,
            "description": "",
            "_id": pos["id"],
        }

    def _attach_descriptions(self, jobs):
        """Fetch descriptions only for jobs past the title/location gate.

        The search response has no description, and categorize() leans on it to
        tell a Summer 2027 posting from an evergreen one — but one request per
        job across four queries is far more than the handful that can actually
        be saved.
        """
        candidates = [
            job for job in jobs
            if matches_backend_swe(job["title"]) and is_us_location(job["location"])
        ]
        for job in candidates[:MAX_DETAIL_FETCHES]:
            try:
                data = self.fetch_json(DETAIL_URL, params={
                    "position_id": job["_id"],
                    "domain": DOMAIN,
                    "hl": "en",
                })
            except Exception:
                continue
            raw = (data.get("data") or {}).get("jobDescription") or ""
            if raw:
                job["description"] = html.unescape(TAG_RE.sub(" ", raw))
            self.throttle()
