import re
from scraper.base import BaseScraper


class GreenhouseScraper(BaseScraper):
    ats_name = "greenhouse"

    def _fetch_jobs(self, company_cfg):
        board_id = company_cfg.get("board_id", "")
        if not board_id:
            return []

        # content=true includes the job description HTML
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs?content=true"
        data = self.fetch_json(url)
        jobs = data.get("jobs", [])

        results = []
        for job in jobs:
            loc_parts = []
            if job.get("location", {}).get("name"):
                loc_parts.append(job["location"]["name"])

            # Strip HTML tags from description
            desc_html = job.get("content", "")
            description = re.sub(r'<[^>]+>', ' ', desc_html) if desc_html else ""

            results.append({
                "title": job.get("title", ""),
                "url": job.get("absolute_url", ""),
                "location": ", ".join(loc_parts) if loc_parts else "",
                "date_posted": job.get("updated_at", ""),
                "description": description,
            })
        return results
