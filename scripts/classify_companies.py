"""Parse the speedyapply/2026-SWE-College-Jobs markdown tables, extract unique
companies with their ATS + board_id inferred from apply URLs, and diff against
the current companies.yaml to suggest additions.

This script is a one-shot tool — it's not imported at runtime.
"""
import os
import re
import sys
import yaml
from collections import OrderedDict
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP = os.environ.get("TEMP") or "/tmp"
INTERN_MD = os.path.join(TEMP, "swe_readme.md")
NEWGRAD_MD = os.path.join(TEMP, "new_grad_usa.md")
YAML_PATH = os.path.join(ROOT, "companies.yaml")

SECTION_ORDER = {"faang": 0, "quant": 1, "other": 2}


def load_md(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_tables(md):
    """Yield (section, company_name, apply_url) tuples from a README.

    Tracks which <!-- TABLE_*_START --> / END block we're inside.
    """
    section = None
    for line in md.splitlines():
        s = line.strip()
        if "TABLE_FAANG_START" in s:
            section = "faang"
            continue
        if "TABLE_QUANT_START" in s:
            section = "quant"
            continue
        if "TABLE_START" in s and "FAANG" not in s and "QUANT" not in s:
            section = "other"
            continue
        if "TABLE_" in s and "_END" in s:
            section = None
            continue
        if section is None:
            continue
        if not s.startswith("|"):
            continue
        # Skip header + separator rows
        if re.match(r"^\|[\s\-\|:]+\|$", s):
            continue
        if "Company" in s and "Position" in s:
            continue
        # Extract company name (first cell) and apply URL (cell with href)
        name_m = re.search(r"<strong>([^<]+)</strong>", s)
        url_m = re.search(r'<a href="([^"]+)"><img', s)
        if not name_m or not url_m:
            continue
        yield section, name_m.group(1).strip(), url_m.group(1).strip()


GREENHOUSE_PATTERNS = [
    r"boards\.greenhouse\.io/([^/?#]+)",
    r"job-boards\.greenhouse\.io/([^/?#]+)",
    r"boards\.eu\.greenhouse\.io/([^/?#]+)",
]
LEVER_PATTERN = r"jobs\.(eu\.)?lever\.co/([^/?#]+)"
ASHBY_PATTERN = r"jobs\.ashbyhq\.com/([^/?#]+)"
SMARTRECRUITERS_PATTERN = r"jobs\.smartrecruiters\.com/([^/?#]+)"
WORKABLE_PATTERN = r"apply\.workable\.com/([^/?#]+)"
ICIMS_PATTERN = r"([a-z0-9\-]+)\.icims\.com"
WORKDAY_PATTERN = r"([a-z0-9\-]+)\.wd\d+\.myworkdayjobs\.com"


def classify(url):
    """Return (ats, board_id_or_None, url_or_None) for an apply URL.

    For greenhouse/lever/ashby/smartrecruiters we use a board_id so the
    existing JSON scrapers can consume it. For workday/icims we keep the URL
    because the scrapers walk it directly. Anything unrecognized → playwright.
    """
    for pat in GREENHOUSE_PATTERNS:
        m = re.search(pat, url)
        if m:
            return "greenhouse", m.group(1), None
    m = re.search(LEVER_PATTERN, url)
    if m:
        return "lever", m.group(2), None
    m = re.search(ASHBY_PATTERN, url)
    if m:
        return "ashby", m.group(1), None
    m = re.search(SMARTRECRUITERS_PATTERN, url)
    if m:
        return "smartrecruiters", m.group(1), None
    m = re.search(WORKDAY_PATTERN, url)
    if m:
        # Normalize to the careers landing: keep /{locale}/{site-slug} and
        # drop /job/... so the scraper hits the board, not one posting.
        parsed = urlparse(url)
        parts = parsed.path.split("/")
        # parts[0]=='', parts[1]='en-US', parts[2]='<site-slug>'
        base_path = "/".join(parts[:3]) if len(parts) >= 3 else parsed.path
        base = f"{parsed.scheme}://{parsed.netloc}{base_path}"
        return "workday", None, base
    m = re.search(ICIMS_PATTERN, url)
    if m:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}/jobs/search"
        return "icims", None, base
    m = re.search(WORKABLE_PATTERN, url)
    if m:
        # No workable scraper yet — use playwright on the board page
        slug = m.group(1)
        return "playwright", None, f"https://apply.workable.com/{slug}/"
    # Unknown host — route to playwright with the apply URL
    return "playwright", None, url


def normalize_name(name):
    """Canonicalize company name for deduping."""
    n = name.lower()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[^a-z0-9]+", "", n)
    return n


def load_current_yaml():
    with open(YAML_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("companies", [])


def main():
    intern_md = load_md(INTERN_MD)
    newgrad_md = load_md(NEWGRAD_MD)

    # Collect candidates, keyed by normalized name. Keep the best tier
    # (lowest SECTION_ORDER) seen across both files, and the first URL.
    candidates = OrderedDict()
    for md, source in [(intern_md, "intern"), (newgrad_md, "newgrad")]:
        for section, name, url in parse_tables(md):
            key = normalize_name(name)
            ats, board_id, url_out = classify(url)
            entry = candidates.get(key)
            new_tier = SECTION_ORDER.get(section, 9)
            if entry is None or new_tier < entry["tier"]:
                candidates[key] = {
                    "name": name,
                    "tier": new_tier,
                    "section": section,
                    "ats": ats,
                    "board_id": board_id,
                    "url": url_out,
                    "source": source,
                    "sample_url": url,
                }

    current = load_current_yaml()
    current_keys = {normalize_name(c["name"]) for c in current}

    # Split into already-present vs missing
    missing = [v for k, v in candidates.items() if k not in current_keys]
    present = [v for k, v in candidates.items() if k in current_keys]

    # Sort missing by tier (faang→quant→other) then name
    missing.sort(key=lambda v: (v["tier"], v["name"].lower()))

    print(f"Total unique candidates: {len(candidates)}")
    print(f"  Already in yaml: {len(present)}")
    print(f"  Missing: {len(missing)}")
    print()
    print(f"Current yaml size: {len(current)}")
    target = 400
    need = max(0, target - len(current))
    print(f"Need to reach {target}: {need} additions")
    print()

    # Report by tier
    from collections import Counter
    tier_counts = Counter(v["section"] for v in missing)
    print("Missing by tier:")
    for t, n in tier_counts.most_common():
        print(f"  {t}: {n}")

    print()
    print("Missing by ATS:")
    ats_counts = Counter(v["ats"] for v in missing)
    for a, n in ats_counts.most_common():
        print(f"  {a}: {n}")

    # Take the first `need` missing — already sorted by tier
    selected = missing[:need]
    print()
    print(f"Selected top {len(selected)} for addition")

    # Write out as YAML snippet
    out_path = os.path.join(TEMP, "additions.yaml")
    grouped = {"faang": [], "quant": [], "other": []}
    for v in selected:
        grouped[v["section"]].append(v)

    lines = []
    for section_key, header in [
        ("faang", "FAANG+ (from speedyapply)"),
        ("quant", "QUANT (from speedyapply)"),
        ("other", "OTHER (from speedyapply)"),
    ]:
        items = grouped[section_key]
        if not items:
            continue
        lines.append("")
        lines.append("  # " + "=" * 60)
        lines.append(f"  # {header}")
        lines.append("  # " + "=" * 60)
        for v in items:
            lines.append(f"  - name: {v['name']}")
            lines.append(f"    ats: {v['ats']}")
            if v["board_id"]:
                lines.append(f"    board_id: {v['board_id']}")
            if v["url"]:
                lines.append(f"    url: {v['url']}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote additions to {out_path}")
    print(f"Final yaml will have {len(current) + len(selected)} companies")


if __name__ == "__main__":
    main()
