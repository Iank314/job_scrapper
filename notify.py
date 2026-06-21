"""Discord webhook notifier for new job postings.

Sends an embed-rich message per batch of new jobs. Respects Discord's
rate limits (max 10 embeds per message). Does nothing if
DISCORD_WEBHOOK_URL is not set.
"""

import requests
from config import DISCORD_WEBHOOK_URL

MAX_EMBEDS_PER_MSG = 10


def _category_color(cat):
    if "Fall 2026" in cat:
        return 0xF0A050
    if "Summer 2027" in cat and "New Grad" not in cat:
        return 0x50A0F0
    if "Spring 2027" in cat and "New Grad" not in cat:
        return 0x50F090
    if "New Grad" in cat:  # all new-grad cycles (incl. Fall 2027 / general 2027)
        return 0xD070F0
    return 0x888888


def send_new_jobs(new_jobs):
    """Send a Discord notification for a list of new job dicts.

    Each dict must have: company, title, url, category, location.
    Does nothing if DISCORD_WEBHOOK_URL is empty or the list is empty.
    """
    if not DISCORD_WEBHOOK_URL or not new_jobs:
        return

    # Build embeds, chunked to respect Discord's 10-embed-per-message limit.
    embeds = []
    for job in new_jobs:
        loc = job.get("location") or "—"
        embeds.append({
            "title": job["title"],
            "url": job["url"],
            "color": _category_color(job.get("category", "")),
            "fields": [
                {"name": "Company", "value": job["company"], "inline": True},
                {"name": "Category", "value": job.get("category", "—"), "inline": True},
                {"name": "Location", "value": loc, "inline": True},
            ],
        })

    for i in range(0, len(embeds), MAX_EMBEDS_PER_MSG):
        chunk = embeds[i : i + MAX_EMBEDS_PER_MSG]
        payload = {
            "username": "Job Scraper",
            "content": f"**{len(chunk)} new job{'s' if len(chunk) != 1 else ''} found**" if i == 0 else None,
            "embeds": chunk,
        }
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 1)
                import time
                time.sleep(retry_after)
                requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            elif not resp.ok:
                print(f"  [!] Discord webhook failed: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [!] Discord webhook error: {e}")
