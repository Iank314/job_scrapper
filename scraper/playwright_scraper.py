"""Playwright-based scraper for JS-rendered career portals.

Custom career sites (Google, Meta, Citadel, etc.) are single-page apps that
render job listings via JavaScript, so plain HTTP requests return empty shells.
This scraper launches a headless Chromium once, navigates each site, waits for
the page to settle, then extracts visible job links.

A single browser is shared across all playwright companies to avoid paying the
multi-second chromium startup per company. Companies are scraped sequentially
because Playwright's sync API isn't thread-safe.
"""

import os
import re
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager
from urllib.parse import urljoin, urlparse

from scraper.base import BaseScraper
from filters import extract_us_location

NAV_TIMEOUT_MS = 20_000       # hard timeout for page.goto
NETWORKIDLE_TIMEOUT_MS = 8000  # shorter — many sites never reach networkidle
SETTLE_WAIT_MS = 1000          # extra wait after load for late-rendering widgets
SCROLL_PASSES = 3              # "scroll to bottom" passes to load lazy lists
PER_COMPANY_BUDGET_S = 30      # soft upper bound we log if exceeded

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Links whose text matches this pattern are considered candidate job postings.
TARGET_CYCLE_PATTERN = (
    r'\b(?:spring|winter|summer|fall|autumn)\s*2027\b|'
    r'\bclass\s*of\s*2027\b|'
    r'\b2027\b.{0,50}\b(?:new\s*grad|university\s*grad|graduate)\b|'
    r'\b(?:new\s*grad|university\s*grad|graduate)\b.{0,50}\b2027\b'
)

TARGET_ROLE_PATTERN = (
    r'\b(?:intern(ship)?s?|co[-\s]?ops?|new\s*grad|university\s*grad|'
    r'software\s*engineer|\bswe\b|backend|back[-\s]end|platform|'
    r'infrastructure|\bsre\b|devops|data\s*engineer|ml\s*engineer|'
    r'systems\s*engineer|security\s*engineer|reliability|distributed)\b'
)

JOB_TEXT_PATTERN = re.compile(
    r'(?=.*(?:' + TARGET_CYCLE_PATTERN + r'))(?=.*(?:' + TARGET_ROLE_PATTERN + r'))',
    re.IGNORECASE
)

# Hrefs that almost certainly aren't job posting links.
#
# These are matched anywhere in the href, which makes them dangerous for career
# sites hosted under an informational path: every Google posting lives at
# google.com/**about**/careers/applications/jobs/results/<id>-<slug>, so a bare
# `/about` here silently dropped 100% of Google's jobs. A href that matches
# JOB_HREF_PATTERN is therefore exempt from this list — see _generic_extract.
HREF_SKIP_PATTERN = re.compile(
    r'(^#|^javascript:|^mailto:|/privacy|/terms|/cookie|/accessibility|'
    r'/login|/signin|/register|/about|/contact|/faq|/help)',
    re.IGNORECASE
)
 

# Chromium net errors that mean "the connection broke", not "this page is bad".
# Honeywell's CDN intermittently kills the HTTP/2 stream mid-navigation and the
# very next attempt returns 200, so one flaky socket shouldn't cost the company
# for the run. Timeouts are deliberately NOT retried: they would double the
# per-company wall clock and blow the PER_COMPANY_BUDGET_S budget.
# (Forcing --disable-http2 was tried instead and made Honeywell time out.)
TRANSIENT_NAV_ERRORS = (
    "ERR_HTTP2_PROTOCOL_ERROR",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_ABORTED",
    "ERR_SOCKET_NOT_CONNECTED",
    "ERR_EMPTY_RESPONSE",
    "ERR_NETWORK_CHANGED",
    "ERR_QUIC_PROTOCOL_ERROR",
)
NAV_RETRIES = 2          # total attempts on a transient net error
NAV_RETRY_WAIT_MS = 1500

# Hard ceiling on one URL. Nothing legitimate comes close (20s goto x2 retries +
# 8s networkidle + settle + scrolling lands under 60s), so blowing this means a
# playwright call is blocked, not slow — see _kill_driver.
HARD_DEADLINE_S = 90
TEARDOWN_DEADLINE_S = 20

# A wedged navigation can take the whole driver down, not just the page. When
# that happens every subsequent playwright call raises this instead of a normal
# Playwright error, and the shared browser is unusable for the rest of the run.
DEAD_DRIVER_MARKERS = (
    "connection closed",
    "target page, context or browser has been closed",
    "browser has been closed",
    "browser closed",
    "target crashed",
)

_playwright = None
_browser = None
_poisoned = False  # set by the watchdog; forces a relaunch on next use


def _driver_pid(playwright=None):
    """PID of the node driver playwright talks to, or None.

    Private API, and deliberately so: it is the only handle that makes a blocked
    sync-API call interruptible, and there is no public equivalent. Every access
    is defensive because the path is not a stable contract.
    """
    playwright = playwright if playwright is not None else _playwright
    try:
        return playwright._impl_obj._connection._transport._proc.pid
    except Exception:
        return None


def _kill_driver(pid=None):
    """Kill the driver process so blocked playwright calls raise instead of hang.

    This is the escape hatch for a wedged browser. careers.honeywell.com wedged
    chromium on a retried navigation and page.close() then sat there for ~172
    seconds before the connection finally dropped — with no timeout parameter
    anywhere in the sync API to bound it. Killing the process the call is
    waiting on is what turns that hang into an exception we can handle.

    `pid` is passed explicitly by callers that have already detached the module
    globals, since _driver_pid() reads them.
    """
    global _poisoned
    _poisoned = True
    pid = pid if pid is not None else _driver_pid()
    if not pid:
        return
    try:
        if sys.platform == "win32":
            # /T so chromium's children go too, rather than being orphaned.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=15)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


@contextmanager
def _watchdog(seconds, what, pid=None):
    """Kill the driver if the wrapped block hasn't finished in `seconds`.

    Resolve the pid up front: _discard_browser() clears the globals before it
    starts closing, so a watchdog that looked the pid up at fire time would have
    nothing left to kill.
    """
    pid = pid if pid is not None else _driver_pid()

    def fire():
        print(f"  [!] playwright: {what} exceeded {seconds}s — killing the browser",
              flush=True)
        _kill_driver(pid)

    timer = threading.Timer(seconds, fire)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()


def _driver_is_dead(exc):
    return any(marker in str(exc).lower() for marker in DEAD_DRIVER_MARKERS)


def _ensure_browser():
    """Start playwright and chromium on first use. Returns the shared browser.

    The browser is shared across all playwright companies, which means one site
    that kills chromium would otherwise take every company after it down with
    it — careers.honeywell.com did exactly that: its HTTP/2 failure killed the
    driver mid-navigation, and the run then hung inside page.close() with three
    companies left to scrape and the notification flush never reached. So the
    handle is health-checked here and transparently relaunched when it's dead.
    """
    global _playwright, _browser, _poisoned
    if _browser is not None:
        try:
            healthy = not _poisoned and _browser.is_connected()
        except Exception:
            healthy = False
        if healthy:
            return _browser
        print("  [.] playwright: browser died — relaunching", flush=True)
        _discard_browser()

    _poisoned = False
    from playwright.sync_api import sync_playwright  # imported lazily

    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    return _browser


def _discard_browser():
    """Drop the shared browser without waiting on a driver that may be gone.

    close_browser() is the graceful path; this is the one taken when the driver
    is already dead, where any protocol call would block forever rather than
    raise.
    """
    global _playwright, _browser, _poisoned
    browser, playwright, poisoned = _browser, _playwright, _poisoned
    pid = _driver_pid()
    _browser = _playwright = None

    if poisoned:
        # The driver was killed (or is wedged), so browser.close() is exactly the
        # call that would block — skip it. playwright.stop() still has to run:
        # it is what tears down the sync API's asyncio loop, and without it the
        # next sync_playwright().start() refuses outright with "It looks like you
        # are using Playwright Sync API inside the asyncio loop". Against a dead
        # driver it returns immediately.
        _kill_driver(pid)
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        _poisoned = False
        return

    # A graceful teardown still has to be bounded: is_connected() reports True
    # for a wedged driver just as it does for a healthy one.
    with _watchdog(TEARDOWN_DEADLINE_S, "browser teardown", pid=pid):
        if browser is not None:
            try:
                if browser.is_connected():
                    browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
    _poisoned = False


def close_browser():
    """Tear down the shared browser at the end of a scrape run."""
    _discard_browser()


class PlaywrightScraper(BaseScraper):
    ats_name = "playwright"

    def __init__(self):
        # Skip BaseScraper's requests.Session setup — we don't use it.
        pass

    def _fetch_jobs(self, company_cfg):
        """Scrape every configured URL for this company and merge the results.

        `url:` may be a single string or a list. Search-driven career SPAs only
        return what the query asks for, so an intern-keyword URL structurally
        cannot surface new-grad roles (and vice versa) — a list lets one company
        cover both cycles without duplicating the entry.
        """
        urls = company_cfg.get("url", "")
        if isinstance(urls, str):
            urls = [urls] if urls else []
        if not urls:
            return []

        merged = []
        seen = set()
        for url in urls:
            for job in self._fetch_one_url(company_cfg, url):
                if job["url"] not in seen:
                    seen.add(job["url"])
                    merged.append(job)
        return merged

    def _fetch_one_url(self, company_cfg, url):
        import time
        name = company_cfg.get("name", "?")

        try:
            browser = _ensure_browser()
        except ImportError:
            print("  [!] playwright not installed — run: pip install playwright && playwright install chromium")
            return []
        except Exception as e:
            print(f"  [!] playwright launch failed: {e}")
            return []

        print(f"  [.] playwright/{name}: loading {url[:80]}", flush=True)
        started = time.monotonic()

        context = page = None
        # Every playwright call below is under the watchdog: a wedged driver
        # blocks forever otherwise, and one wedged company used to take the rest
        # of the run — and the notification flush at the end of it — with it.
        with _watchdog(HARD_DEADLINE_S, f"{name} scrape"):
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1440, "height": 900},
                    locale="en-US",
                )
                page, _ = _goto_with_retry(context, url)
                try:
                    page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
                except Exception:
                    pass  # many sites keep long-poll connections open — proceed anyway
                page.wait_for_timeout(SETTLE_WAIT_MS)
                _auto_scroll(page)

                site = company_cfg.get("site", "generic")
                handler = SITE_HANDLERS.get(site, _generic_extract)
                jobs = handler(page, company_cfg, url)
                elapsed = time.monotonic() - started
                if elapsed > PER_COMPANY_BUDGET_S:
                    print(f"  [.] playwright/{name}: slow ({elapsed:.0f}s)", flush=True)
                return jobs
            except Exception as e:
                elapsed = time.monotonic() - started
                msg = str(e).splitlines()[0][:120]
                print(f"  [!] playwright/{name}: {msg} (after {elapsed:.0f}s)", flush=True)
                return []
            finally:
                _close_quietly(page, context)


def _close_quietly(*closeables):
    """Close pages/contexts, tolerating a driver that is already gone."""
    for closeable in closeables:
        if closeable is None:
            continue
        try:
            closeable.close()
        except Exception:
            pass


def _goto_with_retry(context, url):
    """Navigate to url on a fresh page, retrying transient net errors.

    Returns (page, response) — the caller works with the page this hands back,
    because **each attempt gets its own page**. Reusing the page across a retry
    is what took the whole run down: a second goto into a renderer that had just
    failed with ERR_HTTP2_PROTOCOL_ERROR left chromium wedged, and the eventual
    page.close() blocked for ~172s before the driver connection dropped. One
    attempt per page fails in 0.1s and closes instantly. (Measured on
    careers.honeywell.com, which reproduces it every time.)
    """
    page = None
    for attempt in range(NAV_RETRIES):
        _close_quietly(page)
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            return page, response
        except Exception as e:
            transient = any(code in str(e) for code in TRANSIENT_NAV_ERRORS)
            if not transient or attempt == NAV_RETRIES - 1:
                # The failed page is left open; the caller closes the whole
                # context in its finally, which takes every page with it.
                raise
    return page, None


def _auto_scroll(page):
    """Scroll the page a few times so lazy-loaded job cards render."""
    for _ in range(SCROLL_PASSES):
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(700)
        except Exception:
            break


def _absolutize(href, base_url):
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base_url, href)


def _registered_domain(host):
    """Return the last two labels of a hostname — good enough for grouping
    `metacareers.com`, `careers.metacareers.com`, `jobs.metacareers.com`
    together without pulling in tldextract as a dependency."""
    if not host:
        return ""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _same_site(href, base_url):
    """Allow same registered domain (any subdomain) — many career SPAs
    redirect detail pages to a different subdomain (e.g. meta.com →
    metacareers.com) which a strict netloc check would reject."""
    try:
        href_host = urlparse(href).netloc
        base_host = urlparse(base_url).netloc
        if href_host == base_host:
            return True
        return _registered_domain(href_host) == _registered_domain(base_host)
    except Exception:
        return False


# URL path fragments that indicate a job detail page. Applies to href paths
# so we can pick up listings where the visible link text is something like
# "Apply" or "View details" rather than the job title itself.
JOB_HREF_PATTERN = re.compile(
    r'/(jobs?|careers?|positions?|openings?|roles?|vacanc|opportunit|details|posting)/'
    r'|/job[_-]?id|gh_jid=|job[_-]?post|requisition|/req[_-]?|jobDetails/',
    re.IGNORECASE
)


# Accessible names on job cards are usually a call-to-action wrapped around the
# real title — Google renders a text-less button labelled "Learn more about
# Software Engineer III, Cloud Networking". Strip the lead-in so what reaches
# the title filter is the role, not the verb.
ARIA_LEADIN_RE = re.compile(
    r'^(?:learn\s+more|read\s+more|more\s+info(?:rmation)?|find\s+out\s+more|'
    r'view|see|open|go\s+to|apply(?:\s+now)?|apply\s+to|details?)'
    r'(?:\s+(?:about|for|to|on))?\s*[:\-–]?\s*',
    re.IGNORECASE
)

# Trailing chrome some sites append to the accessible name.
ARIA_TRAILER_RE = re.compile(
    r'\s*[,–-]?\s*(?:opens?\s+in\s+(?:a\s+)?new\s+(?:tab|window)|'
    r'\(opens?\s+in\s+(?:a\s+)?new\s+(?:tab|window)\))\s*\.?$',
    re.IGNORECASE
)


def _clean_aria_label(aria):
    """Reduce an accessible name to the job title it wraps."""
    if not aria:
        return ""
    cleaned = ARIA_TRAILER_RE.sub("", aria.strip())
    # Stacked lead-ins are common ("View details for X") — strip repeatedly,
    # but never all the way to empty.
    for _ in range(3):
        stripped = ARIA_LEADIN_RE.sub("", cleaned).strip()
        if stripped == cleaned or not stripped:
            break
        cleaned = stripped
    return cleaned[:180]


def _generic_extract(page, company_cfg, base_url=None):
    """Pull candidate job postings from all <a> tags on the page.

    A link is kept if EITHER:
    - its visible text looks like a job title, OR
    - its href path looks like a job detail URL (/jobs/NNN/..., gh_jid=, etc.)

    The second rule catches SPAs where the visible text is "View" / "Apply"
    rather than the role title. When the URL rule fires we try to pick up a
    nearby title from the parent element's text.
    """
    if not base_url:
        cfg_url = company_cfg.get("url", "")
        base_url = cfg_url[0] if isinstance(cfg_url, list) and cfg_url else cfg_url
    results = []
    seen = set()

    try:
        # For each anchor also capture (a) its accessible name and (b) the
        # closest ancestor's visible text, so there is still a title when the
        # link itself renders as "Apply", an icon, or nothing at all.
        links = page.evaluate("""
            () => {
                const out = [];
                const anchors = document.querySelectorAll('a');
                for (const a of anchors) {
                    const text = (a.innerText || a.textContent || '').trim();
                    const href = a.href || '';
                    const aria = (a.getAttribute('aria-label') ||
                                  a.getAttribute('title') || '').trim();
                    // Walk up for a richer ancestor. The ancestor must be
                    // meaningfully longer than the link text, otherwise a
                    // wrapper reading just "Learn more" wins and the real job
                    // card (title + location + team) is never reached.
                    const floor = Math.max(text.length, 20);
                    let ctx = '';
                    let ctxFull = '';
                    let node = a.parentElement;
                    for (let i = 0; i < 5 && node; i++) {
                        const t = (node.innerText || '').trim();
                        if (t && t.length > floor && t.length < 400) {
                            ctxFull = t;
                            ctx = t.split('\\n')[0].trim();
                            break;
                        }
                        node = node.parentElement;
                    }
                    out.push({ text, href, aria, ctx, ctxFull });
                }
                return out;
            }
        """)
    except Exception:
        links = []

    for link in links:
        text = (link.get("text") or "").strip()
        href = (link.get("href") or "").strip()
        aria = _clean_aria_label(link.get("aria") or "")
        ctx = (link.get("ctx") or "").strip()
        ctx_full = (link.get("ctxFull") or ctx).strip()

        if not href:
            continue

        text_hit = bool(text) and 5 <= len(text) <= 200 and JOB_TEXT_PATTERN.search(text)
        href_hit = bool(JOB_HREF_PATTERN.search(href))
        if not (text_hit or href_hit):
            continue

        # A href that looks like a job *detail* URL outranks the boilerplate
        # skip list — otherwise career sites nested under /about, /help, etc.
        # lose every posting to a substring match on their own base path.
        if not href_hit and HREF_SKIP_PATTERN.search(href):
            continue

        abs_href = _absolutize(href, base_url)
        if not _same_site(abs_href, base_url):
            continue
        if abs_href in seen:
            continue

        # Pick the best title: prefer visible text if it looks like a role,
        # then the accessible name, then the ancestor context text.
        if text_hit:
            title = text
        elif ctx and JOB_TEXT_PATTERN.search(ctx):
            title = ctx[:180]
        elif aria and 5 <= len(aria) <= 200:
            title = aria
        elif text and 5 <= len(text) <= 200:
            title = text
        elif ctx and 5 <= len(ctx) <= 200:
            title = ctx
        else:
            # No usable title — skip rather than pollute the DB with "Apply".
            continue

        seen.add(abs_href)
        results.append({
            "title": title,
            "url": abs_href,
            "location": extract_us_location(ctx_full),
            "date_posted": "",
        })

    return results


# Per-site handlers — register here when generic extraction isn't sufficient.
# Signature: handler(page, company_cfg, base_url)
#   -> list[{title, url, location, date_posted, description?}]
SITE_HANDLERS = {
    "generic": _generic_extract,
}
