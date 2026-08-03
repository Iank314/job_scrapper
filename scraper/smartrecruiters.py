from scraper.base import BaseScraper
from filters import matches_backend_swe, is_us_location

# The postings list is a summary view: it carries no description and its `ref`
# field is the *API* URL, not something a human can open. The per-posting detail
# endpoint has both, but one request per job is far too expensive on boards with
# hundreds of listings (ServiceNow ~445, Western Digital ~362), so descriptions
# are fetched only for the handful that already pass the title/location gate.
PUBLIC_JOB_URL = "https://jobs.smartrecruiters.com/{company}/{job_id}"
MAX_DETAIL_FETCHES = 60


class SmartRecruitersScraper(BaseScraper):
    ats_name = "smartrecruiters"

    def _fetch_jobs(self, company_cfg):
        board_id = company_cfg.get("board_id", "")
        if not board_id:
            return []

        results = []
        offset = 0
        limit = 100

        while True:
            url = f"https://api.smartrecruiters.com/v1/companies/{board_id}/postings"
            data = self.fetch_json(url, params={"offset": offset, "limit": limit})

            content = data.get("content", [])
            if not content:
                break

            for job in content:
                job_id = job.get("id", "")
                if not job_id:
                    continue

                # `company.identifier` is the tenant slug as SmartRecruiters
                # spells it, which is what jobs.smartrecruiters.com expects;
                # board_id in companies.yaml may differ in case.
                identifier = (job.get("company") or {}).get("identifier") or board_id

                results.append({
                    "title": job.get("name", ""),
                    "url": PUBLIC_JOB_URL.format(company=identifier, job_id=job_id),
                    "location": self._location_text(job),
                    "date_posted": job.get("releasedDate", ""),
                    "description": "",
                    "_detail_url": f"{url}/{job_id}",
                })

            if len(content) < limit:
                break
            offset += limit
            self.throttle()

        self._attach_descriptions(results)
        for job in results:
            job.pop("_detail_url", None)
        return results

    def _location_text(self, job):
        """Prefer the API's fullLocation — it names the country.

        The city/region/country fields spell the country as a lowercase ISO-2
        code ("Petaling Jaya, Selangor, my"), which the non-US filter cannot
        recognize, so composing from them let every foreign posting through.
        fullLocation gives "Petaling Jaya, Selangor, Malaysia" instead.
        """
        loc = job.get("location") or {}
        full = (loc.get("fullLocation") or "").strip()
        if full:
            return full

        parts = [loc.get("city"), loc.get("region"), loc.get("country")]
        return ", ".join(p for p in parts if p).strip(", ")

    def _attach_descriptions(self, jobs):
        """Fill in descriptions for jobs that survive the title/location gate.

        Mirrors base.scrape_company's first two checks so the expensive detail
        request is only spent on postings that could actually be saved. A single
        posting failing to load must not cost the whole company, so per-job
        errors are swallowed and the job keeps its empty description.
        """
        candidates = [
            job for job in jobs
            if matches_backend_swe(job["title"]) and is_us_location(job["location"])
        ]

        for job in candidates[:MAX_DETAIL_FETCHES]:
            try:
                detail = self.fetch_json(job["_detail_url"])
            except Exception:
                continue

            sections = (detail.get("jobAd") or {}).get("sections") or {}
            text = []
            for section in sections.values():
                if isinstance(section, dict) and section.get("text"):
                    text.append(section["text"])
            job["description"] = " ".join(text)
            self.throttle()
