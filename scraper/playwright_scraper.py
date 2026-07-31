"""Playwright-based scraper for JS-rendered career portals.

Custom career sites (Google, Meta, Citadel, etc.) are single-page apps that
render job listings via JavaScript, so plain HTTP requests return empty shells.
This scraper launches a headless Chromium once, navigates each site, waits for
the page to settle, then extracts visible job links.

A single browser is shared across all playwright companies to avoid paying the
multi-second chromium startup per company. Companies are scraped sequentially
because Playwright's sync API isn't thread-safe.
"""

import re
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
    r'\b(?:fall|autumn)\s*2026\b|'
    r'\b(?:spring|winter|summer)\s*2027\b|'
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

# Hrefs that almost certainly aren't job posting links
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

_playwright = None
_browser = None


def _ensure_browser():
    """Start playwright and chromium on first use. Returns the shared browser."""
    global _playwright, _browser
    if _browser is not None:
        return _browser

    from playwright.sync_api import sync_playwright  # imported lazily

    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    return _browser


def close_browser():
    """Tear down the shared browser at the end of a scrape run."""
    global _playwright, _browser
    if _browser is not None:
        try:
            _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
        _playwright = None


class PlaywrightScraper(BaseScraper):
    ats_name = "playwright"

    def __init__(self):
        # Skip BaseScraper's requests.Session setup — we don't use it.
        pass

    def _fetch_jobs(self, company_cfg):
        import time
        url = company_cfg.get("url", "")
        name = company_cfg.get("name", "?")
        if not url:
            return []

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

        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        try:
            _goto_with_retry(page, url)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
            except Exception:
                pass  # many sites keep long-poll connections open — proceed anyway
            page.wait_for_timeout(SETTLE_WAIT_MS)
            _auto_scroll(page)

            site = company_cfg.get("site", "generic")
            handler = SITE_HANDLERS.get(site, _generic_extract)
            jobs = handler(page, company_cfg)
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
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass


def _goto_with_retry(page, url):
    """Navigate to url, retrying only transient connection-level net errors."""
    for attempt in range(NAV_RETRIES):
        try:
            return page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception as e:
            transient = any(code in str(e) for code in TRANSIENT_NAV_ERRORS)
            if not transient or attempt == NAV_RETRIES - 1:
                raise
            page.wait_for_timeout(NAV_RETRY_WAIT_MS)


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


def _generic_extract(page, company_cfg):
    """Pull candidate job postings from all <a> tags on the page.

    A link is kept if EITHER:
    - its visible text looks like a job title, OR
    - its href path looks like a job detail URL (/jobs/NNN/..., gh_jid=, etc.)

    The second rule catches SPAs where the visible text is "View" / "Apply"
    rather than the role title. When the URL rule fires we try to pick up a
    nearby title from the parent element's text.
    """
    base_url = company_cfg.get("url", "")
    results = []
    seen = set()

    try:
        # For each anchor, also capture the closest ancestor's visible text
        # so we have a fallback title when the link itself just says "Apply".
        links = page.evaluate("""
            () => {
                const out = [];
                const anchors = document.querySelectorAll('a');
                for (const a of anchors) {
                    const text = (a.innerText || a.textContent || '').trim();
                    const href = a.href || '';
                    // Walk up a few levels to find a richer title
                    let ctx = '';
                    let ctxFull = '';
                    let node = a.parentElement;
                    for (let i = 0; i < 4 && node; i++) {
                        const t = (node.innerText || '').trim();
                        if (t && t.length > text.length && t.length < 400) {
                            ctxFull = t;
                            ctx = t.split('\\n')[0].trim();
                            break;
                        }
                        node = node.parentElement;
                    }
                    out.push({ text, href, ctx, ctxFull });
                }
                return out;
            }
        """)
    except Exception:
        links = []

    for link in links:
        text = (link.get("text") or "").strip()
        href = (link.get("href") or "").strip()
        ctx = (link.get("ctx") or "").strip()
        ctx_full = (link.get("ctxFull") or ctx).strip()

        if not href or HREF_SKIP_PATTERN.search(href):
            continue

        text_hit = bool(text) and 5 <= len(text) <= 200 and JOB_TEXT_PATTERN.search(text)
        href_hit = bool(JOB_HREF_PATTERN.search(href))
        if not (text_hit or href_hit):
            continue

        abs_href = _absolutize(href, base_url)
        if not _same_site(abs_href, base_url):
            continue
        if abs_href in seen:
            continue

        # Pick the best title: prefer visible text if it looks like a role,
        # otherwise use the ancestor context text.
        if text_hit:
            title = text
        elif ctx and JOB_TEXT_PATTERN.search(ctx):
            title = ctx[:180]
        elif text and 5 <= len(text) <= 200:
            title = text
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
# Signature: handler(page, company_cfg) -> list[{title, url, location, date_posted, description?}]
SITE_HANDLERS = {
    "generic": _generic_extract,
}
