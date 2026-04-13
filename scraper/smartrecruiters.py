from scraper.base import BaseScraper


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
                loc = job.get("location", {})
                location = loc.get("city", "")
                if loc.get("region"):
                    location += f", {loc['region']}"
                if loc.get("country"):
                    location += f", {loc['country']}"

                # SmartRecruiters includes jobAd with description sections
                description = ""
                job_ad = job.get("jobAd", {})
                for section in job_ad.get("sections", {}).values():
                    if isinstance(section, dict):
                        description += " " + section.get("text", "")

                results.append({
                    "title": job.get("name", ""),
                    "url": job.get("ref", ""),
                    "location": location.strip(", "),
                    "date_posted": job.get("releasedDate", ""),
                    "description": description,
                })

            if len(content) < limit:
                break
            offset += limit
            self.throttle()

        return results
