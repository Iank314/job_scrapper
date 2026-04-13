import re
from scraper.base import BaseScraper


class AshbyScraper(BaseScraper):
    ats_name = "ashby"

    def _fetch_jobs(self, company_cfg):
        board_id = company_cfg.get("board_id", "")
        if not board_id:
            return []

        url = "https://api.ashbyhq.com/posting-api/job-board/" + board_id
        data = self.fetch_json(url)
        jobs = data.get("jobs", [])

        results = []
        for job in jobs:
            location = job.get("location", "")
            if isinstance(location, dict):
                location = location.get("name", "")

            # Ashby includes descriptionHtml or descriptionPlain
            desc_html = job.get("descriptionHtml", "") or job.get("descriptionSafeHtml", "")
            description = re.sub(r'<[^>]+>', ' ', desc_html) if desc_html else ""
            if not description:
                description = job.get("descriptionPlain", "")

            results.append({
                "title": job.get("title", ""),
                "url": job.get("jobUrl", job.get("applyUrl", "")),
                "location": location,
                "date_posted": job.get("publishedAt", ""),
                "description": description,
            })
        return results
