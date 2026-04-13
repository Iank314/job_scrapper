from scraper.base import BaseScraper


class WorkdayScraper(BaseScraper):
    ats_name = "workday"
    use_browser_headers = True

    def _fetch_jobs(self, company_cfg):
        base_url = company_cfg.get("url", "")
        if not base_url:
            return []

        # Workday career sites expose a search API
        # base_url should be like: https://company.wd5.myworkdayjobs.com/en-US/External
        search_url = base_url.rstrip("/") + "/jobs"

        results = []
        offset = 0
        limit = 20

        while True:
            payload = {
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": "software engineer intern",
            }

            try:
                data = self.fetch_json(search_url, method="POST", json=payload)
            except Exception:
                break

            job_postings = data.get("jobPostings", [])
            if not job_postings:
                break

            for job in job_postings:
                title = job.get("title", "")
                external_path = job.get("externalPath", "")
                # Build full URL from the base
                job_url = base_url.split("/jobs")[0] if "/jobs" in base_url else base_url
                job_url = job_url.rstrip("/") + external_path

                loc_parts = []
                for loc in job.get("locationsText", "").split(","):
                    loc = loc.strip()
                    if loc:
                        loc_parts.append(loc)

                results.append({
                    "title": title,
                    "url": job_url,
                    "location": ", ".join(loc_parts),
                    "date_posted": job.get("postedOn", ""),
                })

            if len(job_postings) < limit:
                break
            offset += limit
            self.throttle()

        return results
