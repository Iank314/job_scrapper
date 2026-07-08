import html
import re
from scraper.base import BaseScraper
from filters import is_senior_role

# Some boards put the intern/new-grad signal ONLY in Greenhouse's custom
# metadata, not the title — e.g. Jane Street titles every campus role plain
# "Software Engineer" and marks it via "Employment Type": "Full-Time: New
# Grad" / "Summer Internship" / "Winter Co-Op". Since categorize() treats the
# title as authoritative, append early-career metadata values to the title so
# those roles are recognized instead of silently dropped.
_EARLY_CAREER_META = re.compile(
    r'\b(intern(ship)?s?|co[-\s]?ops?|new\s*grad(uate)?s?|campus|'
    r'early[-\s]?career|university)\b',
    re.IGNORECASE,
)


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

            # content arrives entity-escaped (&lt;p&gt;…), so unescape before
            # stripping tags or the regex never sees the real markup.
            desc_html = html.unescape(job.get("content", "") or "")
            description = re.sub(r'<[^>]+>', ' ', desc_html) if desc_html else ""

            title = (job.get("title") or "").strip()
            meta_tags = []
            for meta in job.get("metadata") or []:
                value = meta.get("value")
                if isinstance(value, str) and _EARLY_CAREER_META.search(value):
                    tag = value.strip()
                    # Never let a metadata value inject a seniority marker
                    # (e.g. "University Program Lead") into a junior title.
                    if (tag and tag.lower() not in title.lower()
                            and tag not in meta_tags and not is_senior_role(tag)):
                        meta_tags.append(tag)
            if meta_tags:
                title = f"{title} ({'; '.join(meta_tags)})"

            results.append({
                "title": title,
                "url": job.get("absolute_url", ""),
                "location": ", ".join(loc_parts) if loc_parts else "",
                "date_posted": job.get("updated_at", ""),
                "description": description,
            })
        return results
