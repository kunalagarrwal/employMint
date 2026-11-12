"""Who the applicant is. Every personal setting the code needs comes from here, and here reads it from
profile/profile.json and profile/preferences.json, so the code holds no one's details.

Functions take the profile or preferences dict so they're easy to test; profile() and prefs() load the real files.
"""
import functools
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# EMPLOYMINT_PROFILE_DIR points at another profile folder (e.g. examples/profile) without moving files.
PROFILE_DIR = Path(os.environ.get("EMPLOYMINT_PROFILE_DIR") or ROOT / "profile").resolve()
PROFILE_PATH = PROFILE_DIR / "profile.json"
PREFS_PATH = PROFILE_DIR / "preferences.json"

DEFAULT_SEASON = "Summer 2027"
LISTINGS_URL = "https://raw.githubusercontent.com/SimplifyJobs/{}-Internships/dev/.github/scripts/listings.json"
# Postings that rule out someone who needs a visa (see jobs.VISA_PATTERNS).
SPONSORSHIP_BLOCKS = frozenset({"citizenship", "clearance", "export_control", "no_sponsorship", "no_cpt", "permanent_auth"})
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12, "spring": 5, "summer": 8, "fall": 12, "autumn": 12, "winter": 12}
TERM_KEY = re.compile(r"^(spring|summer|fall|winter)_(20\d\d)$")


def load_json(path):
    """Reads a profile file, or exits with a message saying how to create it."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"{path} not found. Start from the sample: cp -R examples/profile profile")
    except json.JSONDecodeError as ex:
        sys.exit(f"{path} is not valid JSON ({ex})")


@functools.lru_cache(maxsize=None)
def profile():
    """The applicant's profile.json, read once. Treat it as read-only."""
    return load_json(PROFILE_PATH)


@functools.lru_cache(maxsize=None)
def prefs():
    """The applicant's preferences.json, read once. Treat it as read-only."""
    return load_json(PREFS_PATH)


# ---------- names and files ----------

def full_name(p):
    return p["contact"]["name"]


def file_stem(name):
    """'Ada Lovelace' -> 'Ada_Lovelace'. Keeps letters (any language), digits, '-' and '.'."""
    kept = re.sub(r"[^\w\s.-]", "", name or "", flags=re.UNICODE)
    return re.sub(r"\s+", "_", kept.strip()) or "Applicant"


def resume_name(p):
    return f"{file_stem(full_name(p))}_Resume.pdf"


def cover_name(p):
    return f"{file_stem(full_name(p))}_Cover_Letter.pdf"


def transcript_name(p):
    return f"{file_stem(full_name(p))}_Transcript.pdf"


# ---------- school and season ----------

def _date(text):
    """'May 2028', 'Dec. 2028', 'Spring 2029' -> (year, month). None if there's no month or season."""
    for m in re.finditer(r"([a-z]+)\.?\s+(20\d\d)", text or "", re.I):
        word = m.group(1).lower()
        month = MONTHS.get(word, MONTHS.get(word[:3]))
        if month:
            return int(m.group(2)), month
    return None


def grad_date(p):
    """(year, month) of expected graduation, or None if the profile doesn't say."""
    return _date(p["education"][0].get("graduation"))


def season(pr):
    return pr.get("season") or DEFAULT_SEASON


def listings_url(season_name):
    return LISTINGS_URL.format(season_name.replace(" ", ""))


def in_progress_courses(coursework):
    """Courses under any 'in_progress_*' key."""
    return [c for k, v in coursework.items() if k.startswith("in_progress") for c in v]


def upcoming_term(coursework):
    """(key, label) of the next term's courses, e.g. ('spring_2027', 'Spring 2027'), or (None, None).
    With several term keys, the earliest one wins (by year, then spring < summer < fall < winter)."""
    order = {"spring": 1, "summer": 2, "fall": 3, "winter": 4}
    terms = [(int(m.group(2)), order[m.group(1)], k, m) for k in coursework if (m := TERM_KEY.match(k))]
    if not terms:
        return None, None
    *_, k, m = min(terms, key=lambda t: t[:2])
    return k, f"{m.group(1).title()} {m.group(2)}"


def known_years(p, pr):
    """Years a letter may mention without a source: the internship season and graduation."""
    years = set(re.findall(r"20\d\d", season(pr)))
    g = grad_date(p)
    if g:
        years.add(str(g[0]))
    return years


# ---------- work authorization ----------

def visa_blocking(pr):
    """Job-posting visa flags that rule this person out. None unless they need sponsorship."""
    return set(SPONSORSHIP_BLOCKS) if pr.get("needs_sponsorship", True) else set()


def work_auth_rows(p):
    """Copy-paste rows for application forms, from profile work_authorization."""
    wa = p.get("work_authorization", {})
    fa = wa.get("form_answers", {})
    rows = [("Authorized to work in US?", fa.get("authorized_to_work_in_us", "")),
            ("Need sponsorship (now or future)?", fa.get("will_require_sponsorship", ""))]
    if wa.get("future_visa"):
        rows.append(("Future visa", wa["future_visa"]))
    return rows


def visa_type(p):
    return p.get("work_authorization", {}).get("status", "")


# ---------- optional features ----------

def outreach_enabled(pr):
    """LinkedIn recruiter outreach is off unless preferences.recruiter_outreach is true. Automating LinkedIn
    breaks its user agreement and can get an account restricted, so each person decides for themselves."""
    return pr.get("recruiter_outreach") is True


# ---------- form helpers ----------

def workday_experience_ids(p, pr):
    """Experience ids to enter on Workday: preferences.workday_experience if set, else the 3 most recent."""
    if pr.get("workday_experience"):
        return list(pr["workday_experience"])
    def recency(x):
        return ("9999-99" if x.get("end") == "present" else x.get("end", ""), x.get("start", ""))
    return [x["id"] for x in sorted(p.get("experience", []), key=recency, reverse=True)[:3]]


DEGREE_ABBR = {"bachelor": "b", "master": "m", "associate": "a", "doctor": "d"}


def degree_patterns(degree):
    """Option patterns for a degree dropdown, e.g. 'Bachelor of Science' -> bachelor's of science, bachelor, B.S."""
    d = (degree or "").lower().strip()
    level, _, field = d.partition(" of ")
    if not field:
        return ["^" + re.escape(d), re.escape(d)] if d else []
    pats = [f"^{re.escape(level)}'?s? of {re.escape(field)}", f"^{re.escape(level)}"]
    if level in DEGREE_ABBR:
        pats.append(rf"\b{DEGREE_ABBR[level]}\.?{re.escape(field[0])}\b")
    return pats


def field_patterns(major):
    """Option patterns for a field-of-study dropdown."""
    m = (major or "").lower().strip()
    if not m:
        return []
    pats = [f"^{re.escape(m)}$", re.escape(m)]
    if m == "computer science":
        return pats + ["computer and information sci", "^computer"]
    return pats + ["^" + re.escape(m.split()[0])]


# ---------- browser ----------

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def chrome_path():
    """Google Chrome on this computer: CHROME_PATH if set, else the usual install spot for the OS.
    Google Chrome itself, not Chromium: form filling uses Playwright's channel="chrome", which only finds Chrome."""
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]
    if sys.platform == "darwin":
        if Path(MAC_CHROME).exists():
            return MAC_CHROME
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            exe = Path(base or "") / "Google" / "Chrome" / "Application" / "chrome.exe"
            if base and exe.exists():
                return str(exe)
    for name in ("google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("Google Chrome not found. Install it from google.com/chrome, or set CHROME_PATH to its full path.")


def reveal_command(path, platform=None):
    """Command that shows a file in the system file browser (Finder on macOS)."""
    platform = platform or sys.platform
    if platform == "darwin":
        return ["open", "-R", str(path)]
    if platform.startswith("win"):
        return ["explorer", "/select,", str(path)]
    return ["xdg-open", str(Path(path).parent)]


def reveal(path):
    """Shows a file in the file browser; prints its path if the OS has no way to do that."""
    import subprocess
    try:
        subprocess.run(reveal_command(path), check=False)
    except OSError:
        print(f"File: {path}")


def long_date(d):
    """'November 5, 2026' on every OS (strftime's %-d is not available on Windows)."""
    return f"{d:%B} {d.day}, {d.year}"
