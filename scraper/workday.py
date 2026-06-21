import re
from urllib.parse import urlparse

from scraper.base import BaseScraper


DEFAULT_SEARCH_TERMS = (
    "fall 2026",
    "spring 2027",
    "summer 2027",
    "2027 new grad",
    "2027 university graduate",
    "class of 2027",
)

LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


class WorkdayScraper(BaseScraper):
    ats_name = "workday"
    use_browser_headers = True

    def _fetch_jobs(self, company_cfg):
        base_url = company_cfg.get("url", "")
        if not base_url:
            return []

        search_urls = self._search_urls(base_url, company_cfg)
        last_error = None
        for search_url in search_urls:
            try:
                return self._fetch_from_search_url(search_url, base_url, company_cfg)
            except Exception as e:
                last_error = e

        if last_error:
            raise last_error
        return []

    def _fetch_from_search_url(self, search_url, base_url, company_cfg):
        results = []
        seen_urls = set()
        limit = int(company_cfg.get("limit", 20))
        max_pages = int(company_cfg.get("max_pages", 5))
        search_terms = company_cfg.get("search_terms") or DEFAULT_SEARCH_TERMS
        if isinstance(search_terms, str):
            search_terms = (search_terms,)
        had_response = False

        for search_text in search_terms:
            offset = 0
            pages = 0

            while pages < max_pages:
                payload = {
                    "appliedFacets": {},
                    "limit": limit,
                    "offset": offset,
                    "searchText": search_text,
                }

                try:
                    data = self.fetch_json(
                        search_url,
                        method="POST",
                        json=payload,
                        headers={
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                    )
                    had_response = True
                except Exception:
                    if not had_response and not results:
                        raise
                    break

                job_postings = data.get("jobPostings", [])
                if not job_postings:
                    break

                for job in job_postings:
                    title = job.get("title", "")
                    external_path = job.get("externalPath", "")
                    job_url = self._job_url(base_url, external_path)
                    if not job_url or job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    results.append({
                        "title": title,
                        "url": job_url,
                        "location": self._location_text(job),
                        "date_posted": job.get("postedOn", ""),
                    })

                if len(job_postings) < limit:
                    break
                offset += limit
                pages += 1
                self.throttle()

        return results

    def _search_urls(self, base_url, company_cfg):
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        tenant = company_cfg.get("tenant") or parsed.netloc.split(".")[0]
        site = company_cfg.get("site") or self._site_from_path(parsed.path)

        urls = []
        if tenant and site:
            urls.append(f"{origin}/wday/cxs/{tenant}/{site}/jobs")

        # Older Workday links in this repo used the visible career URL plus
        # /jobs. Keep it as a fallback for any tenant that still accepts it.
        urls.append(base_url.rstrip("/") + "/jobs")
        return urls

    def _site_from_path(self, path):
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            return ""
        if LOCALE_RE.match(parts[0]) and len(parts) > 1:
            return parts[1]
        return parts[0]

    def _job_url(self, base_url, external_path):
        if not external_path:
            return ""
        if external_path.startswith(("http://", "https://")):
            return external_path
        return base_url.rstrip("/") + "/" + external_path.lstrip("/")

    def _location_text(self, job):
        locations_text = job.get("locationsText") or ""
        if locations_text:
            return locations_text

        locations = job.get("locations") or []
        if isinstance(locations, list):
            names = []
            for loc in locations:
                if isinstance(loc, dict):
                    name = loc.get("descriptor") or loc.get("name")
                else:
                    name = str(loc)
                if name:
                    names.append(name)
            if names:
                return ", ".join(names)

        primary = job.get("primaryLocation") or job.get("location") or ""
        if isinstance(primary, dict):
            return primary.get("descriptor") or primary.get("name") or ""
        return primary
