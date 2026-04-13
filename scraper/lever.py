import re
from scraper.base import BaseScraper


class LeverScraper(BaseScraper):
    ats_name = "lever"

    def _fetch_jobs(self, company_cfg):
        board_id = company_cfg.get("board_id", "")
        if not board_id:
            return []

        # Support EU Lever instances via "eu: true" in company config
        domain = "api.eu.lever.co" if company_cfg.get("eu") else "api.lever.co"
        url = f"https://{domain}/v0/postings/{board_id}"
        data = self.fetch_json(url)

        results = []
        for job in data:
            location = job.get("categories", {}).get("location", "")

            # Lever includes description as HTML in descriptionPlain or description
            desc = job.get("descriptionPlain", "")
            if not desc:
                desc_html = job.get("description", "")
                desc = re.sub(r'<[^>]+>', ' ', desc_html) if desc_html else ""

            # Also grab the lists (requirements, responsibilities, etc.)
            for lst in job.get("lists", []):
                list_text = lst.get("text", "") + " "
                list_text += " ".join(
                    re.sub(r'<[^>]+>', ' ', item.get("content", ""))
                    for item in lst.get("items", []) if isinstance(item, dict)
                )
                desc += " " + list_text

            results.append({
                "title": job.get("text", ""),
                "url": job.get("hostedUrl", ""),
                "location": location,
                "date_posted": "",
                "description": desc,
            })
        return results
