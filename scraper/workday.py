import re
from urllib.parse import urlparse

from scraper.base import BaseScraper
from filters import is_senior_role


# Workday's `searchText` ANDs its tokens together — it is not a phrase match and
# not an OR. Multi-word cycle phrases therefore require every token to appear in
# the posting, which almost never happens because the year lives in the title but
# "new"/"grad" live elsewhere (or vice versa). Measured against live tenants, the
# old phrase list was returning nothing at all:
#
#     tenant     "grad"   "new grad"   "2027 new grad"
#     Adobe        808        694            1
#     Salesforce   209        174           14
#     Nvidia       246        128            6
#     Snap          44         31            0
#     PayPal         3          1            0
#
# 36 of 91 Workday companies returned zero rows for that reason. Single tokens
# stem-match ("grad" is a superset of graduate/graduates/new grad/undergrad), so
# they enumerate a broad candidate set and let filters.py do the real gating.
DEFAULT_SEARCH_TERMS = (
    "grad",
    "intern",
    "campus",
    "university",
    "entry level",
    # "Early Career" is how aerospace and defense employers label campus hiring
    # and it shares no token with any of the above — Blue Origin's whole campus
    # ladder ("Software Development Engineer I - Early Career") is invisible
    # without it.
    "early career",
    "college",
    "co-op",
    "2027",
)

# Workday tags every posting with a `workerSubType` ("Regular", "Intern (Fixed
# Term)", "New College Graduate", ...) and exposes it as a filterable facet.
# Where a tenant defines an early-career subtype this is far better than text
# search: it is exact, and it catches roles whose *title* carries no signal at
# all — Nvidia files "Software Architect, AI Networking" and "Physical Design
# Engineer" under New College Graduate, and a title-driven categorize() would
# drop both. Matching values get their descriptor appended to the title, the
# same trick the Greenhouse scraper uses for its custom metadata.
_EARLY_CAREER_SUBTYPE = re.compile(
    r'\b(new\s*college\s*grad(uate)?s?|new\s*grad(uate)?s?|graduate|'
    r'intern(ship)?s?|co[-\s]?ops?|apprentice|trainee|student|campus)\b',
    re.IGNORECASE,
)

# Facet ids are per-tenant GUIDs, so they have to be discovered at run time.
_FACET_PARAM = "workerSubType"

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

    def _post_search(self, search_url, search_text="", facets=None, limit=20, offset=0):
        return self.fetch_json(
            search_url,
            method="POST",
            json={
                "appliedFacets": facets or {},
                "limit": limit,
                "offset": offset,
                "searchText": search_text,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def _early_career_facets(self, data):
        """[(facet_id, descriptor)] for early-career `workerSubType` values.

        Reads the facet block Workday returns alongside any search response, so
        discovery costs no extra request.
        """
        found = []
        for facet in data.get("facets") or []:
            if facet.get("facetParameter") != _FACET_PARAM:
                continue
            for value in facet.get("values") or []:
                descriptor = (value.get("descriptor") or "").strip()
                facet_id = value.get("id")
                if not descriptor or not facet_id:
                    continue
                if not value.get("count"):
                    continue
                if _EARLY_CAREER_SUBTYPE.search(descriptor) and not is_senior_role(descriptor):
                    found.append((facet_id, descriptor))
        return found

    def _fetch_from_search_url(self, search_url, base_url, company_cfg):
        results = []
        seen_urls = set()
        limit = int(company_cfg.get("limit", 20))
        max_pages = int(company_cfg.get("max_pages", 8))
        search_terms = company_cfg.get("search_terms") or DEFAULT_SEARCH_TERMS
        if isinstance(search_terms, str):
            search_terms = (search_terms,)

        def collect(job_postings, tag=""):
            """Append postings, returning how many were new. `tag` is the facet
            descriptor, appended to the title so a title-driven categorize()
            can see an early-career signal the title itself never carried."""
            added = 0
            for job in job_postings:
                title = (job.get("title") or "").strip()
                job_url = self._job_url(base_url, job.get("externalPath", ""))
                if not job_url or job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                if tag and tag.lower() not in title.lower():
                    title = f"{title} ({tag})"
                results.append({
                    "title": title,
                    "url": job_url,
                    "location": self._location_text(job),
                    "date_posted": job.get("postedOn", ""),
                })
                added += 1
            return added

        # First request doubles as facet discovery — its response carries the
        # tenant's whole facet block regardless of what was searched.
        first = self._post_search(search_url, search_terms[0], limit=limit)
        collect(first.get("jobPostings", []))

        queries = [(term, None, "") for term in search_terms[1:]]
        queries += [("", {_FACET_PARAM: [fid]}, desc)
                    for fid, desc in self._early_career_facets(first)]

        # Page 2+ of the first term, then everything else.
        if len(first.get("jobPostings", [])) >= limit:
            queries.insert(0, (search_terms[0], None, ""))

        for search_text, facets, tag in queries:
            # A facet query starts at page 0; the re-queued first term resumes
            # where its opening page left off.
            offset = limit if (search_text == search_terms[0] and not facets) else 0
            pages = 0
            while pages < max_pages:
                try:
                    data = self._post_search(search_url, search_text, facets, limit, offset)
                except Exception:
                    # The opening request already proved the endpoint works, so
                    # a later failure is a flaky page, not a bad config.
                    break

                job_postings = data.get("jobPostings", [])
                if not job_postings:
                    break
                collect(job_postings, tag)

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

        if tenant and site:
            # The cxs endpoint is the only one that returns JSON. If it errors
            # (404 wrong site / 422 wrong tenant / 410 migrated pod), let that
            # HTTP error propagate so the real cause is visible — don't fall
            # back to the visible career URL, which serves HTML and would mask
            # the failure as a misleading "Expecting value" JSON-parse error.
            return [f"{origin}/wday/cxs/{tenant}/{site}/jobs"]

        # Couldn't derive a cxs path (no tenant/site); try the legacy form.
        return [base_url.rstrip("/") + "/jobs"]

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
