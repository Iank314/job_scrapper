"""Discord webhook notifier for new job postings.

Sends an embed-rich message per batch of new jobs. Respects Discord's
rate limits (max 10 embeds per message). Does nothing if
DISCORD_WEBHOOK_URL is not set.
"""

import requests
from config import DISCORD_WEBHOOK_URL

MAX_EMBEDS_PER_MSG = 10


def _category_color(cat):
    if "Summer 2027" in cat and "New Grad" not in cat:
        return 0x50A0F0
    if "Spring 2027" in cat and "New Grad" not in cat:
        return 0x50F090
    if "New Grad" in cat:  # all new-grad cycles (incl. Fall 2027 / general 2027)
        return 0xD070F0
    return 0x888888


def _embed(job):
    return {
        "title": job["title"],
        "url": job["url"],
        "color": _category_color(job.get("category", "")),
        "fields": [
            {"name": "Company", "value": job["company"], "inline": True},
            {"name": "Category", "value": job.get("category", "—"), "inline": True},
            {"name": "Location", "value": job.get("location") or "—", "inline": True},
        ],
    }


def send_new_jobs(new_jobs):
    """Announce a list of new job dicts. Returns the ones actually delivered.

    Each dict must have: company, title, url, category, location.

    The return value is what makes delivery durable: the caller only records a
    job as announced once its message really landed, so a webhook outage leaves
    it pending for the next run instead of losing the alert. Chunks are tracked
    individually — a failure halfway through a large batch keeps the delivered
    half from being re-sent.

    With no webhook configured there is nothing to retry, so every job counts as
    delivered; otherwise a backlog would build up and flood the channel the day
    a webhook is added.
    """
    if not new_jobs:
        return []
    if not DISCORD_WEBHOOK_URL:
        return list(new_jobs)

    delivered = []
    for i in range(0, len(new_jobs), MAX_EMBEDS_PER_MSG):
        chunk = new_jobs[i : i + MAX_EMBEDS_PER_MSG]
        payload = {
            "username": "Job Scraper",
            "content": (
                f"**{len(chunk)} new job{'s' if len(chunk) != 1 else ''} found**"
                if i == 0 else None
            ),
            "embeds": [_embed(job) for job in chunk],
        }
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 1)
                import time
                time.sleep(retry_after)
                resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            if resp.ok:
                delivered.extend(chunk)
            else:
                print(f"  [!] Discord webhook failed: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [!] Discord webhook error: {e}")

    return delivered
