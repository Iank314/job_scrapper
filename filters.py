import re
from config import INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS

ALLOWED_CATEGORIES = {
    "Fall 2026 Intern",
    "Fall 2026 New Grad",
    "Spring 2027 Intern",
    "Spring 2027 New Grad",
    "Summer 2027 Intern",
    "Summer 2027 New Grad",
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
    r'vp|head\s+of|distinguished|fellow|architect|'
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
    """Return True only if the location is clearly in the US."""
    if not location or not location.strip():
        return False

    loc = location.lower().strip()

    # Generic/ambiguous labels do not prove US eligibility.
    if loc in ("n/a", "tbd", "various", "multiple", "hybrid", "flexible",
               "in-office", "on-site", "onsite"):
        return False

    # Company-specific flexible locations (e.g., "Flexible - Any SpaceX Site")
    if "spacex" in loc or "any site" in loc:
        return True

    # Check for explicit non-US indicators first
    has_non_us = False
    for indicator in NON_US_INDICATORS:
        if indicator in loc:
            has_non_us = True
            break

    # Check for explicit US indicators
    has_us = False
    for indicator in US_INDICATORS:
        if indicator in loc:
            has_us = True
            break

    # Check state abbreviation regex (e.g., ", CA", ", NY")
    if not has_us and _state_pattern.search(location):
        has_us = True

    # Also check regex US patterns (e.g., standalone "US", "Remote US")
    if not has_us:
        for pattern in US_PATTERNS:
            if re.search(pattern, loc, re.IGNORECASE):
                has_us = True
                break

    # If it has both US and non-US (multi-location), keep it
    if has_us and has_non_us:
        return True

    # If it's clearly non-US with no US signal, reject
    if has_non_us and not has_us:
        return False

    # If it has a clear US signal, keep
    if has_us:
        return True

    # "Remote" alone without a country qualifier is ambiguous.
    if loc in ("remote",):
        return False

    # "Remote - X" where X could be a country; check if X is US.
    remote_match = re.match(r'remote\s*[-,]\s*(.+)', loc)
    if remote_match:
        remainder = remote_match.group(1).strip()
        # Check if the remainder is a US state or "US"/"USA"
        for indicator in US_INDICATORS:
            if indicator.strip(", ") in remainder:
                return True
        for pattern in US_PATTERNS:
            if re.search(pattern, remainder, re.IGNORECASE):
                return True
        # "Remote - <non-US country>" — reject
        return False

    # Unknown location — reject to be safe (no US signal found)
    return False


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
    """Return 2026 or 2027 if exactly one year is present, else None."""
    has_2026 = "2026" in text
    has_2027 = "2027" in text
    if has_2026 and not has_2027:
        return 2026
    if has_2027 and not has_2026:
        return 2027
    return None


def categorize(title, description=""):
    """Determine the category based on job title AND description text.

    Season is resolved from the TITLE first — descriptions often mention
    multiple cycles (e.g. "we hire in Spring, Summer, and Fall"), which
    previously caused a clearly-Summer role to get mis-tagged as Spring.
    Only if the title has no season signal does the description get
    consulted.

    Returns one of ALLOWED_CATEGORIES, or None if the title/description does
    not match one of the target cycles.
    """
    # Seniority check — defensive, in case categorize() is called directly.
    if is_senior_role(title):
        return None

    t = title.lower()
    d = description.lower() if description else ""
    combined = t + " " + d

    is_intern = bool(re.search(r'\b(intern(ship)?s?|co[-\s]?ops?)\b', combined))

    # New grad must have an explicit graduation / campus / new-graduate signal.
    new_grad_patterns = [
        r'\bnew\s*grad(uate)?s?\b',
        r'\buniversity\s*grad(uate)?s?\b',
        r'\bcampus\s*(hire|hiring|recruit)',
        r'\brecent\s*grad(uate)?s?\b',
        r'\bclass\s*of\s*20(2[6-9]|3\d)\b',
        r'\bgraduating\s*(in\s*)?20(2[6-9]|3\d)\b',
        r'\bgraduat(es|ing)\s*(in\s*)?20(2[6-9]|3\d)\b',
    ]
    is_new_grad = any(re.search(p, combined) for p in new_grad_patterns)

    # Past cycle exclusion — if the TITLE explicitly names a past cycle, drop.
    # (Description alone isn't enough because it can mention past cycles in
    # prose.)
    if re.search(r'\b(spring|winter|summer)\s*2026\b', t):
        return None

    # Resolve season: title wins. Description is a tiebreaker only when the
    # title has no season.
    season = _season_from(t) or _season_from(d)

    # Resolve year: title wins. Description tiebreaker.
    year = _year_from(t) or _year_from(d)

    if is_intern:
        # Require BOTH season AND year to assign a specific bucket.
        # "Summer Intern" without a year is ambiguous and should not be saved.
        if season and year:
            if season == "summer" and year == 2026:
                return None  # past cycle
            if season == "spring" and year == 2026:
                return None  # past cycle
            if season == "fall" and year == 2026:
                return "Fall 2026 Intern"
            if season == "spring" and year == 2027:
                return "Spring 2027 Intern"
            if season == "summer" and year == 2027:
                return "Summer 2027 Intern"

        return None

    if is_new_grad:
        if season and year:
            if season == "fall" and year == 2026:
                return "Fall 2026 New Grad"
            if season == "spring" and year == 2027:
                return "Spring 2027 New Grad"
            if season == "summer" and year == 2027:
                return "Summer 2027 New Grad"

        # Common phrasing such as "Class of 2027" often omits an explicit
        # start season. Keep it only when there is no conflicting season.
        if year == 2027 and season is None:
            return "Summer 2027 New Grad"
        return None

    return None
