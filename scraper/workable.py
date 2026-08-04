from scraper.base import BaseScraper


class WorkableScraper(BaseScraper):
    """Scrape Workable-hosted boards (apply.workable.com/{account}).

    The visible board is a JS app that renders no anchors, so these entries were
    previously configured as `playwright` or `generic` and returned zero rows.
    The widget API behind it is public JSON and needs no key:

        https://apply.workable.com/api/v1/widget/accounts/{account}?details=true

    `details=true` is what includes each posting's description, which is worth
    the same single request — Workable boards are small, so the description is
    available for free as a categorize() tiebreaker.
    """

    ats_name = "workable"

    def _fetch_jobs(self, company_cfg):
        account = company_cfg.get("board_id", "")
        if not account:
            return []

        url = f"https://apply.workable.com/api/v1/widget/accounts/{account}?details=true"
        data = self.fetch_json(url)

        results = []
        for job in data.get("jobs", []) or []:
            # Location arrives split across fields; join whatever is present so
            # is_us_location() sees "Austin, TX, United States" rather than "".
            parts = [job.get(k) for k in ("city", "state", "country")]
            location = ", ".join(p for p in parts if p) or job.get("location", "") or ""

            results.append({
                "title": (job.get("title") or "").strip(),
                "url": job.get("url") or job.get("shortlink") or "",
                "location": location,
                "date_posted": job.get("published_on", "") or job.get("created_at", ""),
                "description": job.get("description", "") or "",
            })
        return results
