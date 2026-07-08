import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env from the project root if present. Silently no-ops if the file
# doesn't exist or python-dotenv isn't installed.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass

DB_PATH = os.path.join(BASE_DIR, "jobs.db")
COMPANIES_FILE = os.path.join(BASE_DIR, "companies.yaml")

# Web UI auth — single user. Override by setting APP_PASSWORD / APP_SECRET_KEY
# environment variables; the default password is shown on startup so you know
# to change it. The session secret defaults to a random per-process value,
# which means restarting the server logs you out.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")
APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)

# Discord webhook for new-job notifications. Leave blank to disable.
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "20"))  # concurrent scraper threads
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "20"))  # seconds per HTTP request
RATE_LIMIT_DELAY = float(os.environ.get("RATE_LIMIT_DELAY", "0.25"))  # seconds between paged requests

# Backend SWE keywords — job title must match at least one
INCLUDE_KEYWORDS = [
    "software engineer", "software engineering", "swe",
    "software developer", "software development engineer", "sde",
    "programmer",
    "software architect", "system architect", "systems architect",
    "solutions architect", "cloud architect", "data architect", "architect",
    "backend", "back-end", "back end",
    "platform", "infrastructure",
    "distributed systems", "systems engineer",
    "embedded", "firmware", "sre",
    "devops", "dev ops",
    "cloud engineer", "cloud infrastructure",
    "data engineer", "data engineering", "data infrastructure",
    "ml infrastructure", "ml engineer", "machine learning engineer",
    "api engineer", "api developer",
    "microservices",
    "kernel", "operating systems",
    "networking engineer", "network engineer",
    "storage engineer",
    "database engineer",
    "security engineer", "security engineering",
    "automation engineer",
    "reliability engineer",
    "production engineer",
    "tools engineer",
    "build engineer",
    "release engineer",
    "systems software",
    "core engineer",
    "runtime engineer",
    # Campus-program titles that omit SWE words entirely — e.g. Capital One's
    # "Technology Development Program - 2027" (their SWE new-grad program) and
    # "Technology Internship Program - Summer 2027".
    "technology development program",
    "technology internship",
    "technology intern",
    # Quant-shop SWE titles (Tower Research, HRT, etc.) that omit
    # "software engineer" — e.g. "Quantitative Developer Intern - Summer 2027".
    "quantitative developer", "quant developer",
    "python developer", "c++ developer", "java developer",
    "low latency developer",
]

# Jobs matching these keywords are excluded
EXCLUDE_KEYWORDS = [
    "frontend", "front-end", "front end",
    "ui/ux", "ux/ui", "ux designer", "ui designer",
    "product design", "graphic design", "visual design",
    "marketing", "sales", "account executive", "account manager",
    "recruiter", "recruiting", "talent acquisition",
    "human resources", "hr ",
    "content writer", "copywriter", "technical writer",
    "customer success", "customer support",
    "business analyst", "business development",
    "project manager", "program manager",
    "data analyst",  # different from data engineer
    "financial analyst",
    "legal", "paralegal",
    "administrative",
    # Electrical / hardware roles
    "electrical engineer", "electrical engineering", "electrical",
    "hardware engineer", "hardware engineering", "hardware",
    "electronics engineer", "electronics engineering", "electronics",
    "silicon", "semiconductor", "chip",
    "asic", "fpga", "rtl", "vlsi", "soc",
    "circuit", "circuits", "analog", "mixed signal", "mixed-signal",
    "pcb", "board design", "signal integrity", "power electronics",
]
