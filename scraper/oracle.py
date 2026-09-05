"""Oracle HCM Cloud (Recruiting Cloud / "Candidate Experience") scraper.

Careers sites served out of Oracle Fusion look like
`{host}/hcmUI/CandidateExperience/en/sites/{site}` (Dell) or a vanity domain
rewritten onto the same app (`careers.honeywell.com/en/sites/Honeywell`). They
are SPAs, so the HTML is an empty shell — but the JSON the SPA itself calls is
public and unauthenticated:

    {api_host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&expand=requisitionList.secondaryLocations
        &finder=findReqs;siteNumber=CX_1,limit=200,offset=0

Three things worth knowing:

* **`siteNumber` is not validated.** CX_1 / CX_2 / CX_1001 all return the same
  board, so there is nothing per-tenant to discover — CX_1 works everywhere.
* **The `keyword` filter is fuzzy, not a word match.** On Honeywell `intern`
  returns 690 of 1350 postings because it also matches "Internal Audit
  Manager". Since these boards are small (Dell 441, Honeywell 1350) we skip
  keyword search entirely and enumerate the board, which keeps the gating in
  filters.py where the rest of the project puts it.
* **A vanity domain may not proxy `/hcmRestApi`.** careers.honeywell.com serves
  the SPA but 302s every REST call to an Oracle error page; the underlying
  `*.fa.*.oraclecloud.com` host answers the identical request. `api_host:` in
  companies.yaml overrides where the API is called, while `url:` stays the
  human-facing base used to build job links.

Descriptions live on a per-requisition detail endpoint, so — as in the
SmartRecruiters and Microsoft scrapers — they are fetched only for postings
that already passed the title and location gate.
"""

import html
import re
from urllib.parse import urlparse

from scraper.base import BaseScraper
from filters import matches_backend_swe, is_us_location

SEARCH_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
DEFAULT_SITE_NUMBER = "CX_1"

PAGE_SIZE = 200
MAX_PAGES = 25            # 5000 postings — far above any board we target
MAX_DETAIL_FETCHES = 60

# Order matters only for readability; all three are concatenated into the text
# categorize() reads.
DESCRIPTION_FIELDS = (
    "ExternalDescriptionStr",
    "ExternalResponsibilitiesStr",
    "ExternalQualificationsStr",
)

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


class OracleScraper(BaseScraper):
    ats_name = "oracle"

    def _fetch_jobs(self, company_cfg):
        base_url = (company_cfg.get("url") or "").rstrip("/")
        if not base_url:
            return []

        api_host = (company_cfg.get("api_host") or "").rstrip("/")
        if not api_host:
            parts = urlparse(base_url)
            api_host = f"{parts.scheme}://{parts.netloc}"
        site_number = company_cfg.get("site_number") or DEFAULT_SITE_NUMBER

        jobs = []
        seen = set()
        for req in self._requisitions(api_host, site_number):
            job_id = str(req.get("Id") or "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            jobs.append({
                "title": (req.get("Title") or "").strip(),
                "url": f"{base_url}/job/{job_id}",
                "location": self._location(req),
                "date_posted": (req.get("PostedDate") or "")[:10],
                "description": "",
                "_id": job_id,
            })

        self._attach_descriptions(jobs, api_host, site_number)
        for job in jobs:
            job.pop("_id", None)
        return jobs

    def _requisitions(self, api_host, site_number):
        offset = 0
        for _ in range(MAX_PAGES):
            finder = (
                f"findReqs;siteNumber={site_number},"
                f"limit={PAGE_SIZE},offset={offset}"
            )
            data = self.fetch_json(
                api_host + SEARCH_PATH,
                params={
                    "onlyData": "true",
                    "expand": "requisitionList.secondaryLocations",
                    "finder": finder,
                },
            )
            items = data.get("items") or []
            batch = (items[0].get("requisitionList") or []) if items else []
            if not batch:
                return
            for req in batch:
                yield req
            offset += len(batch)
            total = items[0].get("TotalJobsCount")
            if isinstance(total, int) and offset >= total:
                return
            self.throttle()

    @staticmethod
    def _location(req):
        """Primary location plus any secondary ones.

        `PrimaryLocation` is already a human string ("Santa Clara, CA, United
        States"), which is what is_us_location() wants — the ISO country code
        in PrimaryLocationCountry is the shape that silently leaked foreign
        roles through the SmartRecruiters scraper.
        """
        parts = [(req.get("PrimaryLocation") or "").strip()]
        for sec in req.get("secondaryLocations") or []:
            name = (sec.get("Name") or sec.get("LocationName") or "").strip()
            if name:
                parts.append(name)
        return "; ".join(p for p in parts if p)

    def _attach_descriptions(self, jobs, api_host, site_number):
        candidates = [
            job for job in jobs
            if matches_backend_swe(job["title"]) and is_us_location(job["location"])
        ]
        for job in candidates[:MAX_DETAIL_FETCHES]:
            try:
                data = self.fetch_json(
                    api_host + DETAIL_PATH,
                    params={
                        "onlyData": "true",
                        "expand": "all",
                        # The Id is quoted inside the finder expression — Oracle
                        # rejects it bare.
                        "finder": f'ById;Id="{job["_id"]}",siteNumber={site_number}',
                    },
                )
            except Exception:
                continue
            items = data.get("items") or []
            if not items:
                continue
            raw = " ".join(items[0].get(field) or "" for field in DESCRIPTION_FIELDS)
            if raw.strip():
                job["description"] = WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", raw)))
            self.throttle()
