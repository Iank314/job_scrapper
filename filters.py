import re
from config import INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS

# Cycles relevant to a ~May 2027 graduate. Internships must fall before
# graduation (Spring/Summer 2027); new-grad / early-career roles start on or
# after it (Summer/Fall 2027, plus the season-less "2027 New Grad" bucket for
# campus / class-of-2027 / "graduating Dec 2026 - June 2027" postings).
# Fall 2026 Intern was dropped — that recruiting season is over.
ALLOWED_CATEGORIES = {
    # Internships — still enrolled.
    "Spring 2027 Intern",
    "Summer 2027 Intern",
    # New grad / early career — full-time, starts on/after May 2027 grad.
    "Fall 2026 New Grad",
    "Spring 2027 New Grad",
    "Summer 2027 New Grad",
    "Fall 2027 New Grad",
    "2027 New Grad",
}

# US state abbreviations — matched via regex with word boundaries
US_STATE_ABBREVS = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
]

# Build a regex that matches ", XX" or " XX" where XX is a state abbrev at end or before punctuation
_state_pattern = re.compile(
    r'(?:^|,\s*|;\s*|\s-\s|\s+)(' + '|'.join(US_STATE_ABBREVS) + r')(?:\s|$|,|;)',
    re.IGNORECASE
)

# Positive US signals — must match at least one to be considered US
US_INDICATORS = [
    # Common US city names
    "new york", "san francisco", "los angeles", "seattle", "austin",
    "chicago", "boston", "denver", "atlanta", "dallas", "houston",
    "miami", "philadelphia", "phoenix", "san diego", "san jose",
    "mountain view", "palo alto", "menlo park", "sunnyvale", "cupertino",
    "redmond", "bellevue", "pittsburgh", "ann arbor", "boulder",
    "cambridge", "raleigh", "durham", "salt lake", "portland",
    "minneapolis", "detroit", "charlotte", "nashville", "indianapolis",
    "columbus", "irvine", "santa clara", "plano", "arlington",
    "herndon", "mclean", "tysons", "bethesda", "reston",
    "san mateo", "foster city", "hawthorne", "cape canaveral",
    "woodinville", "cottonwood heights", "honolulu", "tempe",
    "costa mesa", "huntsville",
    # Full state names
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
    # General US indicators
    "united states",
]

# Patterns that explicitly mean US
US_PATTERNS = [
    r'\bus\b',           # "US" as standalone word
    r'\busa\b',          # "USA"
    r'remote.{0,5}us\b', # "Remote - US", "Remote US", "Remote, US"
    r'us\s*\(remote\)',  # "US (remote)"
    r'remote.{0,5}usa',  # "Remote - USA"
    r'\bus\s*-\s*remote', # "US - Remote"
]

# Non-US countries, cities, and regions
NON_US_INDICATORS = [
    # Europe
    "london", "uk", "united kingdom", "dublin", "ireland",
    "berlin", "munich", "germany", "paris", "france",
    "amsterdam", "netherlands", "zurich", "switzerland",
    "stockholm", "sweden", "oslo", "norway", "copenhagen", "denmark",
    "warsaw", "poland", "prague", "czech",
    "reykjavik", "iceland", "helsinki", "finland",
    "lisbon", "portugal", "madrid", "spain", "barcelona",
    "milan", "italy", "rome", "vienna", "austria",
    "bucharest", "romania", "sofia", "bulgaria", "belgrade", "serbia",
    "warszawa", "masovian", "krakow", "wroclaw",
    "emea", "apac", "latam",
    # Asia
    "singapore", "tokyo", "japan",
    "bangalore", "bengaluru", "india", "hyderabad", "mumbai", "pune",
    "chennai", "gurgaon", "noida", "ind",
    "beijing", "shanghai", "china", "shenzhen",
    "hong kong", "seoul", "south korea", "taipei", "taiwan",
    "jakarta", "indonesia", "manila", "philippines", "kuala lumpur", "malaysia",
    "bangkok", "thailand", "vietnam", "ho chi minh",
    "tel aviv", "israel",
    "dubai", "uae", "abu dhabi",
    # Oceania
    "sydney", "australia", "melbourne",
    "auckland", "new zealand",
    # Americas (non-US)
    "toronto", "canada", "vancouver", "montreal", "waterloo", "ottawa",
    "ontario", "quebec", "british columbia", "alberta", "manitoba", "nova scotia",
    "são paulo", "brazil",
    "mexico city", "mexico",
    "argentina", "buenos aires", "bogota", "colombia", "chile", "santiago",
    # Africa
    "cape town", "south africa", "nairobi", "kenya", "lagos", "nigeria",
]


# Seniority markers that disqualify a role from intern/new-grad categorization.
# Matched as whole words against the title only.
SENIORITY_EXCLUDE = re.compile(
    r'\b('
    r'senior|sr\.?|staff|principal|lead|director|manager|mgr\.?|'
    r'vp|head\s+of|distinguished|fellow|'
    r'ii|iii|iv|'
    r'l[3-9]|l1[0-9]'
    r')\b',
    re.IGNORECASE
)


def is_senior_role(title):
    """Return True if the title denotes a senior/experienced role."""
    return bool(SENIORITY_EXCLUDE.search(title))


def _kw_regex(keywords):
    """Compile a whole-word alternation regex from a keyword list.

    Escapes each keyword and uses \b word boundaries so "build engineer"
    doesn't match "Build Engineering intern" inside "Inlet Design & Build
    Engineering intern".
    """
    escaped = [re.escape(k) for k in keywords]
    return re.compile(r'\b(?:' + '|'.join(escaped) + r')\b', re.IGNORECASE)


_INCLUDE_RE = _kw_regex(INCLUDE_KEYWORDS)
_EXCLUDE_RE = _kw_regex(EXCLUDE_KEYWORDS)


def matches_backend_swe(title):
    """Return True if the job title looks like a backend SWE role."""
    if is_senior_role(title):
        return False
    if _EXCLUDE_RE.search(title):
        return False
    return bool(_INCLUDE_RE.search(title))


def is_us_location(location):
    """Return True unless the location is *clearly* non-US.

    Recall-first (per project priority): a US-based user would rather see a few
    extra roles than miss a real one, so anything without an explicit non-US
    signal is kept — blank, remote, and ambiguous locations included. A location
    is rejected only when it carries a non-US signal and no US signal (e.g.
    "London", "Sydney, Australia", "EMEA"). Multi-location strings that name both
    (e.g. "New York / London") are kept.
    """
    if not location or not location.strip():
        return True  # unknown location — keep it rather than risk missing a US role

    loc = location.lower().strip()

    has_non_us = any(indicator in loc for indicator in NON_US_INDICATORS)

    has_us = any(indicator in loc for indicator in US_INDICATORS)
    if not has_us and _state_pattern.search(location):
        has_us = True
    if not has_us:
        has_us = any(re.search(pattern, loc, re.IGNORECASE) for pattern in US_PATTERNS)

    # Reject only when clearly non-US with no US signal; keep everything else.
    return not (has_non_us and not has_us)


def extract_us_location(text):
    """Best-effort US location extraction from nearby card/listing text."""
    if not text:
        return ""

    parts = re.split(r'[\n|;]+', text)
    for part in parts:
        candidate = re.sub(r'\s+', ' ', part).strip(" -,\t")
        if 2 <= len(candidate) <= 140 and is_us_location(candidate):
            return candidate

    compact = re.sub(r'\s+', ' ', text).strip()
    if len(compact) <= 180 and is_us_location(compact):
        return compact

    return ""


def requires_phd(title, description=""):
    """Return True if the role requires a PhD."""
    text = (title + " " + description).lower()

    # Strong PhD requirement signals
    phd_required_patterns = [
        r'\bph\.?d\.?\s+(is\s+)?required\b',
        r'\brequires?\s+(a\s+)?ph\.?d\.?\b',
        r'\bmust\s+have\s+(a\s+)?ph\.?d\.?\b',
        r'\bdoctoral\s+degree\s+(is\s+)?required\b',
    ]
    for pattern in phd_required_patterns:
        if re.search(pattern, text):
            return True

    # Title contains PhD explicitly
    if re.search(r'\bphd\b|\bph\.?d\.?\b', title.lower()):
        return True

    return False


def _season_from(text):
    """Return 'fall' / 'spring' / 'summer' if the text has one and only one
    season signal, else None. 'winter' counts as 'spring' (spring co-op).
    """
    has_fall = bool(re.search(r'\b(fall|autumn)\b', text))
    has_spring = bool(re.search(r'\b(spring|winter)\b', text))
    has_summer = bool(re.search(r'\bsummer\b', text))
    seasons = [s for s, h in (("fall", has_fall), ("spring", has_spring), ("summer", has_summer)) if h]
    return seasons[0] if len(seasons) == 1 else None


def _year_from(text):
    """Return 2026 or 2027 if exactly one of them is present, else None.

    Ambiguous when both appear (e.g. a "Dec 2026 - June 2027" grad window).
    The new-grad path resolves those windows via _grad_window_targets_2027().
    """
    has_2026 = "2026" in text
    has_2027 = "2027" in text
    if has_2026 and not has_2027:
        return 2026
    if has_2027 and not has_2026:
        return 2027
    return None


# Explicit "{season} {year}" tokens, normalizing autumn->fall, winter->spring.
_CYCLE_TOKEN_RE = re.compile(
    r'\b(fall|autumn|spring|winter|summer)\s*(20\d{2})\b', re.IGNORECASE
)


def _explicit_cycles(text):
    """Ordered list of (season, year) cycle tokens found in the text.

    Lets a multi-cycle posting like "SWE Intern - Fall 2026 / Spring 2027" be
    recognized instead of being dropped as ambiguous.
    """
    cycles = []
    for m in _CYCLE_TOKEN_RE.finditer(text):
        season = m.group(1).lower()
        season = {"autumn": "fall", "winter": "spring"}.get(season, season)
        cycles.append((season, int(m.group(2))))
    return cycles


# A graduation keyword followed (within ~80 chars) by a 2027 date. Captures
# eligibility windows like "graduating December 2026 - June 2027" that name
# BOTH years and would otherwise read as ambiguous to _year_from().
_GRAD_KEYWORD_RE = re.compile(
    r'\b(?:graduat\w*|degree\s+completion|complete\s+your\s+degree|'
    r'expected\s+graduation|conferral)\b',
    re.IGNORECASE,
)


def _grad_window_targets_2027(text):
    """True if a graduation window/date in the text includes 2027."""
    if not text or "2027" not in text:
        return False
    for m in _GRAD_KEYWORD_RE.finditer(text):
        if "2027" in text[m.start(): m.start() + 80]:
            return True
    return False


# Signals that a role is new-grad / early-career / campus (vs. an internship).
# These are the phrasings ATS postings use for the 2026-2027 graduating class:
# "new grad", "university graduate", "campus graduate program", "early career",
# "class of 2027", "graduating December 2026 - June 2027".
NEW_GRAD_PATTERNS = [
    r'\bnew\s*grad(uate)?s?\b',
    r'\buniversity\s+(?:grad(?:uate)?s?|hire[sd]?|hiring|program|recruit\w*)\b',
    r'\bcampus\s+(?:hire[sd]?|hiring|recruit\w*|grad(?:uate)?s?|program)\b',
    r'\brecent\s*grad(uate)?s?\b',
    r'\bgraduate\s+(?:software\s+)?(?:engineer|developer|swe|architect|programmer)\b',
    r'\bgraduate\s+(?:program|rotation\w*|scheme|hir(?:e|ing))\b',
    r'\bearly[-\s]?career\b',
    r'\bentry[-\s]?level\b',
    r'\bclass\s*of\s*20(2[6-9]|3\d)\b',
    r'\bgraduat(?:e|es|ing|ion)\s*(?:in|by|date|between)?\s*(?:\w+\s+)?20(2[6-9]|3\d)\b',
]
_NEW_GRAD_RE = [re.compile(p, re.IGNORECASE) for p in NEW_GRAD_PATTERNS]


# (season, year) -> category, per role type.
_INTERN_CYCLES = {
    ("spring", 2027): "Spring 2027 Intern",
    ("summer", 2027): "Summer 2027 Intern",
}
_INTERN_ORDER = ["Spring 2027 Intern", "Summer 2027 Intern"]

_NEWGRAD_CYCLES = {
    ("fall", 2026): "Fall 2026 New Grad",
    ("spring", 2027): "Spring 2027 New Grad",
    ("summer", 2027): "Summer 2027 New Grad",
    ("fall", 2027): "Fall 2027 New Grad",
}
_NEWGRAD_ORDER = [
    "Fall 2026 New Grad", "Spring 2027 New Grad",
    "Summer 2027 New Grad", "Fall 2027 New Grad",
]

# The season-less "2027 New Grad" bucket and the specific 2027 new-grad cycles.
_GENERAL_2027 = "2027 New Grad"
_SPECIFIC_2027_NG = {"Spring 2027 New Grad", "Summer 2027 New Grad", "Fall 2027 New Grad"}


def cycle_compatible(title_category, stored_category):
    """True if a title-derived category doesn't contradict the stored one.

    "2027 New Grad" (no season in the title) is treated as compatible with any
    specific 2027 new-grad cycle — that's a refinement, not a conflict — so a
    description-derived season isn't wrongly rejected at display time.
    """
    if title_category == stored_category:
        return True
    pair = {title_category, stored_category}
    if _GENERAL_2027 in pair and (pair - {_GENERAL_2027}) <= _SPECIFIC_2027_NG:
        return True
    return False


def _past_cycle_in_title(t):
    """Title explicitly names a past 2026 cycle. Fall 2026 stays valid for new
    grad, so only spring/winter/summer 2026 count as past here."""
    return bool(re.search(r'\b(spring|winter|summer)\s*2026\b', t))


def _soonest(valid, order):
    return sorted(set(valid), key=order.index)[0] if valid else None


def _intern_category(t, d, title_is_intern):
    valid = [_INTERN_CYCLES[c] for c in (_explicit_cycles(t) or _explicit_cycles(d))
             if c in _INTERN_CYCLES]
    soonest = _soonest(valid, _INTERN_ORDER)
    if soonest:
        return soonest
    if _past_cycle_in_title(t):
        return None
    # Beyond an explicit "{season} {year}" token (handled above), only infer an
    # intern cycle when the TITLE itself says intern. Otherwise a new-grad role
    # that merely mentions a "summer internship program" in its description would
    # be mislabeled an intern instead of falling through to the new-grad path.
    if not title_is_intern:
        return None
    season = _season_from(t) or _season_from(d)
    year = _year_from(t) or _year_from(d)
    # Recall-first: the only live intern cycles for the ~2027 class are Spring
    # and Summer 2027 (2026 cycles were already excluded above by title), so a
    # missing year defaults to 2027 rather than dropping the role.
    if year is None:
        year = 2027
    if season:
        return _INTERN_CYCLES.get((season, year))
    # Title says intern but names no season — default to the dominant cycle.
    if year == 2027:
        return "Summer 2027 Intern"
    return None


def _newgrad_category(t, d, combined):
    valid = [_NEWGRAD_CYCLES[c] for c in (_explicit_cycles(t) or _explicit_cycles(d))
             if c in _NEWGRAD_CYCLES]
    soonest = _soonest(valid, _NEWGRAD_ORDER)
    if soonest:
        return soonest
    if _past_cycle_in_title(t):
        return None
    # Season is taken from the TITLE only — description prose routinely names an
    # unrelated season (e.g. a general new-grad post mentioning a "summer
    # internship program"), which must not drive the cycle. Adjacent
    # "{season} {year}" tokens in the description were already handled above.
    season = _season_from(t)
    year = _year_from(t) or _year_from(d)
    if season and year and (season, year) in _NEWGRAD_CYCLES:
        return _NEWGRAD_CYCLES[(season, year)]
    # Recall-first: reaching here means is_new_grad matched (a genuine new-grad /
    # early-career / campus signal) and the title named no past 2026 cycle, so
    # this is a role for the target class that simply didn't spell out a cycle.
    # Keep it — use the title's season when present, else the season-less
    # "2027 New Grad" bucket — instead of dropping it for lacking an explicit
    # year (e.g. "Graduate Software Engineer" with no date).
    if season in ("fall", "spring", "summer"):
        return _NEWGRAD_CYCLES[(season, 2027)]
    return _GENERAL_2027


def categorize(title, description=""):
    """Determine the target cycle from the job title and description text.

    The TITLE is authoritative for season/year — descriptions often name
    several cycles in prose (e.g. "we hire in Spring, Summer, and Fall"), which
    would otherwise mis-tag a role. The description is only a tiebreaker.

    Returns one of ALLOWED_CATEGORIES, or None if the role is not a target
    intern / new-grad cycle for the ~May 2027 graduating class.
    """
    # Seniority check — defensive, in case categorize() is called directly.
    if is_senior_role(title):
        return None

    t = title.lower()
    d = description.lower() if description else ""
    combined = t + " " + d

    _intern_re = re.compile(r'\b(intern(ship)?s?|co[-\s]?ops?)\b')
    title_is_intern = bool(_intern_re.search(t))
    is_intern = bool(_intern_re.search(combined))
    is_new_grad = any(rx.search(combined) for rx in _NEW_GRAD_RE)

    category = None
    if is_intern:
        category = _intern_category(t, d, title_is_intern)
    # A posting can mention "internship" in prose yet actually be a new-grad
    # role; if the intern path found no cycle, fall through to the new-grad one.
    if category is None and is_new_grad:
        category = _newgrad_category(t, d, combined)
    return category
