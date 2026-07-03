"""Decide whether a scheduled scrape is 'due' right now.

The scraper is triggered by Windows Task Scheduler at three fixed times a day
(00:30, 12:00, 18:00 local). If the laptop was asleep across one or more of
those times, Task Scheduler fires *every* missed trigger the moment it wakes.
Left unguarded, that would run the scraper several times back-to-back.

To collapse a backlog of missed slots into a single catch-up run, each run is
gated on a timestamp file: a scrape is "due" only if none has run since the
most recent scheduled slot. So if it missed 12:00 and it's now 19:00, the
first trigger to fire scrapes once and every other queued trigger sees the
fresh timestamp and skips.
"""

import os
from datetime import datetime, time, timedelta

from config import BASE_DIR

# Daily scrape times (local). Keep in sync with the triggers created by
# scripts/setup_scheduler.py.
SCHEDULE_SLOTS = (time(0, 30), time(12, 0), time(18, 0))

STAMP_PATH = os.path.join(BASE_DIR, ".last_scrape")


def most_recent_slot(now):
    """Datetime of the latest scheduled slot at or before `now`."""
    candidates = []
    for day_offset in (0, -1):  # -1 covers the pre-00:30 window (yesterday's 18:00)
        day = (now + timedelta(days=day_offset)).date()
        for slot in SCHEDULE_SLOTS:
            dt = datetime.combine(day, slot)
            if dt <= now:
                candidates.append(dt)
    return max(candidates)


def read_last_scrape():
    """Timestamp of the last recorded scrape, or None if never / unreadable."""
    try:
        with open(STAMP_PATH, "r", encoding="utf-8") as f:
            return datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return None


def record_scrape(now=None):
    """Stamp the current time as the last successful scrape."""
    now = now or datetime.now()
    with open(STAMP_PATH, "w", encoding="utf-8") as f:
        f.write(now.isoformat())


def is_due(now=None):
    """True if no scrape has run since the most recent scheduled slot."""
    now = now or datetime.now()
    last = read_last_scrape()
    if last is None:
        return True
    return last < most_recent_slot(now)
