"""Local internship finder. Everything is stored in data/jobs.sqlite on this laptop.

Usage:
  python3 src/jobs.py fetch                 download Summer 2027 listings (SimplifyJobs list)
  python3 src/jobs.py classify              assign tracks, drop roles that don't fit
  python3 src/jobs.py jd [--limit N]        download job descriptions, check visa wording
  python3 src/jobs.py score                 score eligible jobs 0-100
  python3 src/jobs.py shortlist [--n 50]    write data/shortlist.csv
  python3 src/jobs.py run [--limit N]       all of the above
  python3 src/jobs.py stats                 counts by stage
  python3 src/jobs.py recheck               re-run visa scan on saved descriptions
  python3 src/jobs.py mark <id> <status>    set your own status (skip, approved, applied, interview, rejected, offer)
  python3 src/jobs.py batch [--n 10]        pick today's batch to tailor -> data/batches/<date>.json
  python3 src/jobs.py tailored <id> <dir>   record a finished tailored resume for a batch job

Your statuses: queued -> tailored -> approved / skip -> applied -> interview / rejected / offer
"""
import argparse
import csv
import html
import json
import re
import sqlite3
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from datetime import date, datetime, timedelta, timezone

from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import me  # applicant settings, same folder  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify import TECH_TERMS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "jobs.sqlite"
JD_DIR = DATA / "jd"
PREFS_PATH = me.PREFS_PATH
PROFILE_PATH = me.PROFILE_PATH
TERM = me.season(me.prefs())  # internship season, from preferences.json
SIMPLIFY_URL = me.listings_url(TERM)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
USER_STATUSES = {"queued", "tailored", "approved", "skip", "applied", "assessment", "interview", "rejected", "offer"}
BATCH_DIR = DATA / "batches"
# Statuses that count against a company's application limit.
COUNTS_AS_APPLIED = ("approved", "applied", "assessment", "interview", "rejected", "offer")
# Limits seen in postings. Limits found in downloaded descriptions are added automatically.
KNOWN_LIMITS = {"figma": {"max": 5, "days": 30}, "coinbase": {"max": 3, "days": 182}}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT, category TEXT, locations TEXT, url TEXT,
  degrees TEXT, sponsorship TEXT, date_posted INTEGER, active INTEGER, first_seen TEXT, last_seen TEXT,
  track TEXT, pipeline TEXT DEFAULT 'new', reason TEXT,
  jd_status TEXT, jd_words INTEGER, visa_flags TEXT, apply_limit TEXT,
  score REAL, matched TEXT, missing TEXT,
  app_status TEXT, notes TEXT
);
"""

# ---------- filters ----------

US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
                "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
US_STATE_NAMES = ("alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|"
                  "illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
                  "mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|"
                  "north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|"
                  "south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming")
US_WORDS = re.compile(r"\b(usa|u\.s\.a?|united states|remote in usa|nyc|sf|la|bay area|silicon valley|san francisco|"
                      r"seattle|boston|austin|chicago|" + US_STATE_NAMES + r")\b", re.I)

EXCLUDE_TITLE = re.compile(
    r"\b(phd|ph\.d|mba|master'?s|high school|research scientist|research intern|researcher|research engineer|"
    r"hardware|electrical|mechanical|firmware|embedded|asic|fpga|silicon|rf|analog|chemical|civil engineer\w*|manufacturing|"
    r"sales|marketing|legal|accounting|recruit\w*|human resources|hr|tax|audit|clinical|"
    r"quant\w* research\w*|quant\w* trad\w*|trader|trading)\b", re.I)

TRACK_RULES = [
    ("product_design", r"product design|\bux\b|ui/ux|user experience|interaction design|visual design|designer"),
    ("product", r"product manag|\bapm\b|associate product|product owner|program manag|offering manag"),
    ("ai_engineering", r"\bai\b|artificial intelligence|machine learning engineer|\bml engineer|\bllm|genai|generative|applied ai|\bagent"),
    ("fintech_econ", r"product analyst|business analyst|business technology|data analyst|\banalytics\b|strategy|economic|fintech|quant\w* developer|power bi|business intelligence"),
    ("swe_fullstack_mobile", r"software|\bswe\b|full[- ]?stack|front[- ]?end|back[- ]?end|mobile|\bios\b|android|web develop|developer|"
                             r"platform|infrastructure|data engineer|devops|site reliability|\bsre\b|engineer|programmer|"
                             r"computer science|application develop|\btechnology (intern|co-?op)|information technology|it development"),
]

VISA_PATTERNS = {
    "citizenship": r"(u\.?s\.? citizen(ship)?|united states citizen(ship)?)[^.]{0,80}\b(required|must|only)\b|"
                   r"must be (a )?(u\.?s\.?|united states) citizen|citizenship (is )?required",
    "clearance": r"(security|secret|ts/sci|top secret) clearance|clearance (is )?required|ability to obtain (a )?(security )?clearance",
    "export_control": r"\bitar\b|\bu\.?s\.? persons?\b|export control",
    "no_sponsorship": r"\b(will not|won't|unable to|does not|do not|cannot|can not|not able to|is not able to)\b[^.\n]{0,60}?\bsponsor|"
                      r"without (the need for )?(current or future |now or in the future |future )?(visa |employer |immigration |employment )?sponsorship|"
                      r"sponsorship (is )?not (available|offered|provided)|not eligible for (visa )?sponsorship|"
                      # "Candidates who now or in the future require sponsorship ... are not eligible to apply"
                      r"\b(require|need)s?\b[^.\n]{0,80}\bsponsorship\b[^.\n]{0,80}\b(not eligible|ineligible|will not be considered|cannot be considered)|"
                      r"\b(not eligible|ineligible|will not be considered)\b[^.\n]{0,80}\b(require|need)s?\b[^.\n]{0,60}\bsponsorship|"
                      r"\bmust not\b[^.\n]{0,30}\b(require|need)\b[^.\n]{0,60}\bsponsorship",
    "no_cpt": r"\b(not|no|nor)\b[^.\n]{0,220}\b(curricular practical training|cpt)\b|"
              r"\b(curricular practical training|cpt)\b[^.\n]{0,60}\bnot (eligible|accepted|available|supported|permitted)",
    "permanent_auth": r"authori[sz]ed to work in the (u\.?s\.?|united states)[^.\n]{0,20}on a permanent basis",
}
VISA_BLOCKING = set(me.SPONSORSHIP_BLOCKS)  # every flag that can rule out a visa holder

# The applicant's graduation (year, month), from profile.json. Catches "graduating Dec 2028 or later" requirements.
GRAD_DATE = me.grad_date(me.profile())
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
          "nov": 11, "dec": 12, "spring": 5, "summer": 8, "fall": 12, "autumn": 12, "winter": 12}
DATE_RX = re.compile(r"\b(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|spring|summer|fall|autumn|winter)\w*"
                     r"(?:\s*/\s*\w+)?\s+(?:of\s+)?)?(20\d\d)\b", re.I)


def grad_check(text):
    """Returns ('ok'|'mismatch', sentence) when a graduation requirement is clear, else (None, None)."""
    # Only sentences about a graduation date, not "graduate degree program" or URLs.
    grad_rx = re.compile(r"(?<!under)graduat(ion|ing|es?\s+(in|by|before|between|no|prior|after|within))", re.I)
    for sent in re.findall(r"[^.\n]*graduat[^.\n]*", text, re.I):
        if not grad_rx.search(sent) or "http" in sent or "URL:" in sent:
            continue
        dates = [(int(y), MONTHS.get(m.lower(), MONTHS.get(m[:3].lower())) if m else None)
                 for m, y in DATE_RX.findall(sent)]
        dates = [(y, m) for y, m in dates if 2025 <= y <= 2032]
        if not dates:
            continue
        low = sent.lower()
        if re.search(r"\bpreferred\b|pay rate|salary|compensation|hourly", low):
            continue  # a preference or pay note, not a requirement
        mine = GRAD_DATE
        if mine is None:
            return None, None
        if mine in dates:
            ok = True
        elif "between" in low and len(dates) >= 2:
            lo, hi = dates[0], dates[1]
            ok = (lo[0], lo[1] or 1) <= mine <= (hi[0], hi[1] or 12)
        elif re.search(r"or later|or after|and later|onward|no earlier than|or beyond", low):
            y, m = dates[0]
            ok = mine >= (y, m or 1)
        elif re.search(r"\bbefore\b|no later than|prior to|\bby\b", low):
            y, m = dates[0]
            limit = (y, 6 if (m == 8 and "summer" in low) else (m or 12))
            ok = mine < limit if "before" in low or "prior" in low else mine <= limit
        else:
            ok = any(y == mine[0] for y, _ in dates)
        return ("ok" if ok else "mismatch"), " ".join(sent.split())[:200]
    return None, None

APPLY_LIMIT = re.compile(r"[^.\n]{0,100}\b(maximum|up to|limit\w*)\b[^.\n]{0,60}\b\d+\s+applications?[^.\n]{0,80}", re.I)

# ---------- scoring vocabulary (used only for ranking, never for resume claims) ----------

EXTRA_TERMS = {
    "user research": r"user research", "a/b testing": r"a/b test", "prototyping": r"prototyp", "roadmap": r"roadmap",
    "analytics": r"analytics", "metrics": r"\bmetrics\b", "excel": r"\bexcel\b", "accessibility": r"accessib",
    "design systems": r"design system", "mobile": r"\bmobile\b", "ios": r"\bios\b", "android": r"\bandroid\b",
    "api": r"\bapis?\b", "full-stack": r"full[- ]?stack", "frontend": r"front[- ]?end", "backend": r"back[- ]?end",
    "distributed systems": r"distributed system", "data structures": r"data structures", "algorithms": r"algorithms",
    "economics": r"economic", "statistics": r"statistic", "payments": r"\bpayments?\b", "ui/ux": r"\bui\b|\bux\b",
    "testing": r"\btest(ing|s)?\b", "ai-assisted development": r"copilot|cursor|claude|chatgpt|ai[- ]assisted",
}
# Profile skills that imply a broader term (for ranking only).
IMPLIES = {"react native": ["frontend", "mobile", "ios", "android"], "supabase": ["backend", "api"],
           "edge functions": ["backend", "api"], "figma": ["ui/ux", "prototyping"]}


def term_regexes():
    regs = {}
    for t in TECH_TERMS:
        regs[t.replace("\\", "")] = r"(?<![\w+#.])" + t + r"(?![\w+#])"
    regs.update(EXTRA_TERMS)
    return {k: re.compile(v, re.I) for k, v in regs.items()}


TERMS = term_regexes()


def find_terms(text):
    found = {name for name, rx in TERMS.items() if rx.search(text)}
    if "react" in found and not re.search(r"react(?! native)", text, re.I):
        found.discard("react")
    return found


def profile_terms():
    text = PROFILE_PATH.read_text()
    found = find_terms(text)
    for k, extra in IMPLIES.items():
        if k in found or re.search(re.escape(k), text, re.I):
            found.update(extra)
    return found


# ---------- helpers ----------

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_get(url, timeout=25, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def clean_url(url):
    u = urlparse(url)
    q = {k: v for k, v in parse_qs(u.query).items() if not k.lower().startswith(("utm", "ref", "embed"))}
    return urlunparse(u._replace(query=urlencode(q, doseq=True)))


def html_to_text(s):
    s = html.unescape(html.unescape(s or ""))
    s = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|h\d|ul|ol|div|tr|section)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def db_connect():
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)  # several scripts share this file; wait instead of failing
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    cols = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
    for col, typ in {"batch_date": "TEXT", "resume_dir": "TEXT", "fit": "REAL", "decided_at": "TEXT"}.items():
        if col not in cols:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
    return db


def load_prefs():
    return json.loads(PREFS_PATH.read_text())


# ---------- fetch ----------

def cmd_fetch(db, args):
    print("Downloading SimplifyJobs listings...")
    raw = json.loads(http_get(SIMPLIFY_URL, timeout=180))
    stamp, new, seen = now_iso(), 0, 0
    for j in raw:
        if TERM not in j.get("terms", []):
            continue
        seen += 1
        jid = "simplify:" + j["id"]
        active = 1 if j.get("active") and j.get("is_visible", True) else 0
        vals = (j.get("company_name", ""), j.get("title", ""), j.get("category", ""), json.dumps(j.get("locations", [])),
                clean_url(j.get("url", "")), json.dumps(j.get("degrees", [])), j.get("sponsorship", ""),
                j.get("date_posted") or 0, active, stamp)
        if db.execute("SELECT 1 FROM jobs WHERE id=?", (jid,)).fetchone():
            db.execute("UPDATE jobs SET company=?,title=?,category=?,locations=?,url=?,degrees=?,sponsorship=?,"
                       "date_posted=?,active=?,last_seen=? WHERE id=?", vals + (jid,))
        else:
            db.execute("INSERT INTO jobs (company,title,category,locations,url,degrees,sponsorship,date_posted,active,"
                       "last_seen,id,source,first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       vals + (jid, "simplify", stamp))
            new += 1
    db.execute("UPDATE jobs SET active=0 WHERE source='simplify' AND last_seen<>?", (stamp,))
    db.commit()
    print(f"{seen} {TERM} listings, {new} new.")


# ---------- classify ----------

def is_us(locations):
    for loc in locations:
        if US_WORDS.search(loc):
            return True
        m = re.search(r",\s*([A-Z]{2})\b", loc)
        if m and m.group(1) in US_STATES:
            return True
        if loc.strip().lower() == "remote":
            return True
    return False


def classify(row, prefs):
    """Returns (track, reason). reason is None when the job is a candidate."""
    title = row["title"]
    if not row["active"]:
        return None, "closed"
    blocks = me.visa_blocking(prefs)
    if "citizenship" in blocks and row["sponsorship"] == "U.S. Citizenship is Required":
        return None, "visa: citizenship required"
    if "no_sponsorship" in blocks and row["sponsorship"] == "Does Not Offer Sponsorship":
        return None, "visa: no sponsorship"
    degrees = json.loads(row["degrees"] or "[]")
    if degrees and "Bachelor's" not in degrees:
        return None, "graduate degree only"
    if not is_us(json.loads(row["locations"] or "[]")):
        return None, "not in US"
    if row["category"] == "Hardware":
        return None, "hardware"
    if EXCLUDE_TITLE.search(title):
        return None, "title excluded"
    for track, rx in TRACK_RULES:
        if re.search(rx, title, re.I):
            if track not in prefs["tracks"]:
                return track, "track not wanted"
            if row["category"] == "Quant" and track != "fintech_econ" and not re.search(r"software|developer", title, re.I):
                return track, "quant (not software)"
            return track, None
    return None, "no matching track"


def cmd_classify(db, args):
    prefs = load_prefs()
    rows = db.execute("SELECT * FROM jobs").fetchall()
    for row in rows:
        track, reason = classify(row, prefs)
        if reason:
            db.execute("UPDATE jobs SET track=?, pipeline='excluded', reason=? WHERE id=?", (track, reason, row["id"]))
        elif row["pipeline"] in ("new", "excluded", None):
            db.execute("UPDATE jobs SET track=?, pipeline='candidate', reason=NULL WHERE id=?", (track, row["id"]))
        else:
            db.execute("UPDATE jobs SET track=? WHERE id=?", (track, row["id"]))
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM jobs WHERE pipeline<>'excluded'").fetchone()[0]
    print(f"{n} of {len(rows)} listings fit your tracks.")


# ---------- job descriptions ----------

_ashby_cache, _ashby_lock = {}, threading.Lock()


def fetch_jd(url):
    u = urlparse(url)
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]

    if "greenhouse.io" in host:
        q = parse_qs(u.query)
        if "for" in q and "token" in q:
            board, jid = q["for"][0], q["token"][0]
        else:
            m = re.search(r"/([\w-]+)/jobs/(\d+)", u.path)
            if not m:
                raise ValueError("unrecognized greenhouse url")
            board, jid = m.groups()
        j = json.loads(http_get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}"))
        return html_to_text(j.get("content", ""))

    if "ashbyhq.com" in host:
        board, jid = parts[0], parts[1]
        with _ashby_lock:
            jobs = _ashby_cache.get(board)
        if jobs is None:
            data = json.loads(http_get(f"https://api.ashbyhq.com/posting-api/job-board/{board}"))
            jobs = {x["id"]: x for x in data.get("jobs", [])}
            with _ashby_lock:
                _ashby_cache[board] = jobs
        if jid not in jobs:
            raise ValueError("posting no longer on ashby board")
        return html_to_text(jobs[jid].get("descriptionHtml", ""))

    if "lever.co" in host:
        co, jid = parts[0], parts[1]
        j = json.loads(http_get(f"https://api.lever.co/v0/postings/{co}/{jid}"))
        chunks = [j.get("descriptionPlain", "")]
        for lst in j.get("lists", []):
            chunks.append(lst.get("text", "") + "\n" + html_to_text(lst.get("content", "")))
        chunks.append(j.get("additionalPlain", ""))
        return "\n\n".join(c for c in chunks if c)

    if "myworkdayjobs.com" in host:
        if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
            parts = parts[1:]
        site = parts[0]
        key = "job" if "job" in parts else "details"
        rest = "/".join(parts[parts.index(key) + 1:])
        tenant = host.split(".")[0]
        j = json.loads(http_get(f"https://{host}/wday/cxs/{tenant}/{site}/job/{rest}", headers={"Accept": "application/json"}))
        return html_to_text(j["jobPostingInfo"]["jobDescription"])

    return html_to_text(http_get(url))


PAY_RX = re.compile(
    r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?(?:\s?(?:-|–|—|to)\s?\$?\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?)?"
    r"(?:\s*usd)?(?:\s*(?:/|per|an|a)\s*(hour|hr|year|yr|annum|month|mo|week|wk)\b)?", re.I)
PAY_CONTEXT = re.compile(r"pay|salary|compensation|hourly|per hour|/hr|wage|stipend|rate|range|usd", re.I)


def _money(v):
    return f"${float(v):,.2f}".replace(".00", "") if float(v) < 1000 else f"${float(v):,.0f}"


def pay_from_text(text):
    """Best-effort pay from a job description, e.g. '$57/hr', '$18–$28/hr', '$16,500/mo'. None if not stated."""
    if not text:
        return None
    m = re.search(r"salary min:\s*\$?([\d.,]+).{0,80}?salary max:\s*\$?([\d.,]+)", text, re.I | re.S)
    if m:
        lo, hi = (float(x.replace(",", "")) for x in m.groups())
        unit = "/hr" if hi < 300 else "/yr"
        return f"{_money(lo)}–{_money(hi)}{unit}"
    for m in PAY_RX.finditer(text):
        lo, lo_k, hi, hi_k, unit = m.groups()
        if re.match(r"\s?(m|b|mm|bn|million|billion)\b", text[m.end():m.end() + 9], re.I):
            continue  # funding rounds and valuations, not pay
        ctx = text[max(0, m.start() - 80):m.end() + 40]
        if not unit and not PAY_CONTEXT.search(ctx):
            continue
        val = float(lo.replace(",", "")) * (1000 if lo_k else 1)
        top = float(hi.replace(",", "")) * (1000 if hi_k else 1) if hi else None
        if unit:
            u = {"hour": "/hr", "hr": "/hr", "week": "/wk", "wk": "/wk", "month": "/mo", "mo": "/mo"}.get(unit.lower(), "/yr")
        elif re.search(r"monthly|per month|a month", ctx, re.I):
            u = "/mo"
        elif val < 300:
            u = "/hr"
        elif val >= 20000:
            u = "/yr"
        else:
            u = "/mo"
        rng = _money(val) if not top or top == val else f"{_money(val)}–{_money(top)}"
        return rng + u
    return None


SPONSOR_YES = re.compile(
    r"(?<!not )(?<!n't )(?<!unable to )\b(will|can|do|does|is able to|are able to)\s+(provide|offer|sponsor)\w*\s.{0,40}(visa|sponsor|immigration)"
    r"|(visa|immigration) sponsorship (is |will be )?(available|offered|provided|possible)"
    r"|sponsorship (is )?available|open to sponsor", re.I)


def sponsorship_signal(text, flags):
    """('yes'|'cpt'|'check'|'unknown', short label) from the description and visa flags."""
    if SPONSOR_YES.search(text or ""):
        return "yes", "Sponsors visas"
    if re.search(r"\bcpt\b|curricular practical training", text or "", re.I):
        return "cpt", "CPT mentioned"
    if flags and "export_control_maybe" in flags:
        return "check", "Check: export control"
    return "unknown", "Sponsorship not stated · no F-1 blocks"


def visa_flags(text):
    flags = {}
    for name, rx in VISA_PATTERNS.items():
        for m in re.finditer(rx, text, re.I):
            before = text[max(0, m.start() - 200):m.start()].lower()
            after = text[m.end():m.end() + 25].lower()
            if "regardless of" in before or "without regard to" in before:
                continue
            if name == "clearance" and re.match(r"[\s:]*(to start:?\s*)?none", after):
                continue
            key = name
            if name == "export_control" and re.search(r"\b(may|some of these|certain positions|such positions)\b", before[-150:] + after):
                key = "export_control_maybe"  # generic legal text; shown, not blocking
            start, end = max(0, m.start() - 80), min(len(text), m.end() + 80)
            flags[key] = " ".join(text[start:end].split())
            break
    return flags


def jd_file(job_id):
    return JD_DIR / (re.sub(r"[^\w-]", "_", job_id) + ".md")


def cmd_jd(db, args):
    JD_DIR.mkdir(parents=True, exist_ok=True)
    q = "SELECT * FROM jobs WHERE pipeline='candidate' ORDER BY date_posted DESC"
    rows = db.execute(q + (f" LIMIT {int(args.limit)}" if args.limit else "")).fetchall()
    print(f"Downloading {len(rows)} job descriptions...")

    def work(row):
        try:
            return row, fetch_jd(row["url"]), None
        except Exception as ex:  # network errors, removed postings, unknown sites
            return row, None, f"{type(ex).__name__}: {ex}"[:200]

    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for fut in as_completed([pool.submit(work, r) for r in rows]):
            row, text, err = fut.result()
            done += 1
            if err or not text or len(text.split()) < 150:
                db.execute("UPDATE jobs SET pipeline='jd_missing', jd_status=? WHERE id=?",
                           (err or "too short (page likely needs a browser)", row["id"]))
            else:
                header = f"# {row['title']}\nCompany: {row['company']}\nLocation: {', '.join(json.loads(row['locations']))}\nURL: {row['url']}\n\n"
                jd_file(row["id"]).write_text(header + text, encoding="utf-8")
                flags = visa_flags(text)
                limit = APPLY_LIMIT.search(text)
                pipeline, reason = eligibility(flags, text)
                db.execute("UPDATE jobs SET jd_status='ok', jd_words=?, visa_flags=?, apply_limit=?, pipeline=?, reason=? WHERE id=?",
                           (len(text.split()), json.dumps(flags) if flags else None,
                            " ".join(limit.group(0).split()) if limit else None, pipeline, reason, row["id"]))
            if done % 50 == 0:
                db.commit()
                print(f"  {done}/{len(rows)}")
    db.commit()
    for p, n in db.execute("SELECT pipeline, COUNT(*) FROM jobs WHERE pipeline IN ('eligible','visa_blocked','jd_missing') GROUP BY pipeline"):
        print(f"  {p}: {n}")


def eligibility(flags, text):
    """(pipeline, reason) from visa flags and the graduation-date requirement."""
    blocks = me.visa_blocking(me.prefs())
    blocked = [f for f in flags if f in blocks]
    if blocked:
        return "visa_blocked", "visa: " + ", ".join(blocked)
    status, sentence = grad_check(text)
    if status == "mismatch":
        return "grad_mismatch", "grad date: " + sentence
    return "eligible", None


def cmd_recheck(db, args):
    """Re-run the visa and graduation checks on saved descriptions (after changing the rules)."""
    rows = db.execute("SELECT id FROM jobs WHERE pipeline IN ('eligible','visa_blocked','grad_mismatch')").fetchall()
    for row in rows:
        path = jd_file(row["id"])
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        flags = visa_flags(text)
        pipeline, reason = eligibility(flags, text)
        db.execute("UPDATE jobs SET visa_flags=?, pipeline=?, reason=? WHERE id=?",
                   (json.dumps(flags) if flags else None, pipeline, reason, row["id"]))
    db.commit()
    for p, n in db.execute("SELECT pipeline, COUNT(*) FROM jobs WHERE pipeline IN ('eligible','visa_blocked','grad_mismatch') "
                           "GROUP BY pipeline"):
        print(f"  {p}: {n}")


# ---------- scoring ----------

BOILERPLATE = re.compile(r"equal (employment )?opportunit|accommodat|disabilit|e-verify|benefits|401\(?k|insurance plan|"
                         r"paid time off|parental leave|background check|privacy (notice|policy)|criminal histor", re.I)


def strip_boilerplate(text):
    """Drop legal/benefits sentences so words like 'accessibility' there don't count as skills."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return "\n".join(p for p in parts if not BOILERPLATE.search(p))


def score_job(row, text, prefs, mine):
    priority = prefs["tracks"][row["track"]]["priority"]
    s = {1: 30, 2: 20, 3: 10}.get(priority, 5)

    # Skill overlap: half for coverage of what the job asks, half for how many real matches.
    wanted = find_terms(strip_boilerplate(text))
    matched, missing = wanted & mine, wanted - mine
    if wanted:
        s += 40 * (0.5 * len(matched) / len(wanted) + 0.5 * min(len(matched), 6) / 6)
    else:
        s += 10

    if "Bachelor's" in json.loads(row["degrees"] or "[]"):
        s += 5
    if grad_check(text)[0] == "ok":
        s += 10  # posting explicitly targets their graduation date
    if row["sponsorship"] == "Offers Sponsorship":
        s += 10
    if row["date_posted"]:
        age_days = (datetime.now(timezone.utc).timestamp() - row["date_posted"]) / 86400
        s += 10 if age_days <= 14 else 5 if age_days <= 30 else 0
    return round(max(0, min(s, 100)), 1), sorted(matched), sorted(missing)


def cmd_score(db, args):
    prefs, mine = load_prefs(), profile_terms()
    rows = db.execute("SELECT * FROM jobs WHERE pipeline='eligible'").fetchall()
    for row in rows:
        path = jd_file(row["id"])
        if not path.exists():
            continue
        s, matched, missing = score_job(row, path.read_text(encoding="utf-8"), prefs, mine)
        db.execute("UPDATE jobs SET score=?, matched=?, missing=? WHERE id=?",
                   (s, ", ".join(matched), ", ".join(missing), row["id"]))
    db.commit()
    print(f"Scored {len(rows)} eligible jobs.")


# ---------- output ----------

def cmd_shortlist(db, args):
    """Top N overall, plus the best few of every track so no track gets buried."""
    base = ("SELECT * FROM jobs WHERE pipeline='eligible' AND score IS NOT NULL "
            "AND (app_status IS NULL OR app_status NOT IN ('skip','approved','applied','rejected','offer','interview')) ")
    rows = db.execute(base + "ORDER BY score DESC, date_posted DESC LIMIT ?", (args.n,)).fetchall()
    have = {r["id"] for r in rows}
    per_track = max(3, args.n // 10)
    for track in load_prefs()["tracks"]:
        for r in db.execute(base + "AND track=? ORDER BY score DESC LIMIT ?", (track, per_track)):
            if r["id"] not in have:
                rows.append(r)
                have.add(r["id"])
    rows.sort(key=lambda r: (-r["score"], -(r["date_posted"] or 0)))
    out = DATA / "shortlist.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "score", "track", "company", "title", "locations", "posted", "matched", "missing",
                    "visa_notes", "apply_limit", "url", "id"])
        for i, r in enumerate(rows, 1):
            posted = datetime.fromtimestamp(r["date_posted"], timezone.utc).strftime("%Y-%m-%d") if r["date_posted"] else ""
            w.writerow([i, r["score"], r["track"], r["company"], r["title"], ", ".join(json.loads(r["locations"])), posted,
                        r["matched"], r["missing"], r["visa_flags"] or "", r["apply_limit"] or "", r["url"], r["id"]])
    print(f"Wrote {len(rows)} jobs to {out}\n")
    for i, r in enumerate(rows[:25], 1):
        print(f"{i:>3}. {r['score']:>5}  {r['track']:<22} {r['company'][:22]:<22} {r['title'][:60]}")


def cmd_stats(db, args):
    print("By stage:")
    for p, n in db.execute("SELECT pipeline, COUNT(*) FROM jobs GROUP BY pipeline ORDER BY 2 DESC"):
        print(f"  {p:<14} {n}")
    print("Top exclusion reasons:")
    for r, n in db.execute("SELECT reason, COUNT(*) FROM jobs WHERE reason IS NOT NULL GROUP BY reason ORDER BY 2 DESC LIMIT 10"):
        print(f"  {n:>5}  {r}")
    print("Eligible by track:")
    for t, n in db.execute("SELECT track, COUNT(*) FROM jobs WHERE pipeline='eligible' GROUP BY track ORDER BY 2 DESC"):
        print(f"  {t:<22} {n}")


def cmd_mark(db, args):
    if args.status not in USER_STATUSES:
        sys.exit(f"status must be one of {sorted(USER_STATUSES)}")
    cur = db.execute("UPDATE jobs SET app_status=?, decided_at=? WHERE id=?", (args.status, now_iso(), args.id))
    if cur.rowcount and getattr(args, "note", None):
        line = f"[{now_iso()[:10]}] {args.note}"
        db.execute("UPDATE jobs SET notes = CASE WHEN notes IS NULL OR notes = '' THEN ? ELSE notes || char(10) || ? END "
                   "WHERE id=?", (line, line, args.id))
    db.commit()
    print("updated" if cur.rowcount else "no job with that id")
    if cur.rowcount and args.status == "applied":
        try:
            import outreach
            started = outreach.draft_for_new_applications()
            if started:
                print("finding LinkedIn recruiters for:", ", ".join(started))
        except Exception as ex:
            print(f"(couldn't start recruiter search: {ex})")


# ---------- daily batch ----------

def parse_limit(text):
    """'up to 5 applications during any rolling 30-day period' -> {'max': 5, 'days': 30}"""
    if not text:
        return None
    n = re.search(r"(\d+)\s+applications?", text, re.I)
    d = re.search(r"(\d+)[- ]?(day|week|month|year)", text, re.I)
    if not n or not d:
        return None
    days = int(d.group(1)) * {"day": 1, "week": 7, "month": 30, "year": 365}[d.group(2).lower()]
    return {"max": int(n.group(1)), "days": days}


def company_limit(db, company):
    limit = KNOWN_LIMITS.get(company.lower())
    if limit:
        return limit
    for (text,) in db.execute("SELECT apply_limit FROM jobs WHERE company=? AND apply_limit IS NOT NULL", (company,)):
        parsed = parse_limit(text)
        if parsed:
            return parsed
    return None


def at_limit(db, company):
    limit = company_limit(db, company)
    if not limit:
        return False
    since = (datetime.now(timezone.utc) - timedelta(days=limit["days"])).isoformat(timespec="seconds")
    used = db.execute(
        f"SELECT COUNT(*) FROM jobs WHERE company=? AND app_status IN ({','.join('?' * len(COUNTS_AS_APPLIED))}) "
        "AND decided_at >= ?", (company, *COUNTS_AS_APPLIED, since)).fetchone()[0]
    return used >= limit["max"]


def slugify(company, title, job_id):
    base = re.sub(r"[^a-z0-9]+", "-", f"{company} {title}".lower()).strip("-")[:50].rstrip("-")
    return f"{base}-{hashlib.md5(job_id.encode()).hexdigest()[:4]}"


def cmd_batch(db, args):
    today = date.today().isoformat()
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    out = BATCH_DIR / f"{today}.json"
    if out.exists() and not args.force:
        print(f"Today's batch already exists: {out} (use --force to add more)")
        return
    prefs = load_prefs()
    tracks = [t for t in prefs["tracks"] if not t.startswith("_")]
    tracks.sort(key=lambda t: prefs["tracks"][t]["priority"])

    pending = {r[0].lower() for r in db.execute("SELECT company FROM jobs WHERE app_status IN ('queued','tailored')")}
    cands = db.execute("SELECT * FROM jobs WHERE pipeline='eligible' AND score IS NOT NULL AND app_status IS NULL "
                       "ORDER BY score DESC, date_posted DESC").fetchall()
    picked, used, limited = [], set(pending), set()
    if getattr(args, "ids", None):  # hand-picked list (e.g. AI-native / vibe-coding roles), in the given order
        wanted = [i.strip() for i in args.ids.split(",") if i.strip()]
        by_id = {r["id"]: r for r in cands}
        for i in wanted:
            r = by_id.get(i)
            if r and not at_limit(db, r["company"]):
                picked.append(r)
        cands = []
        args.n = len(picked)

    def ok(r):
        c = r["company"].lower()
        if c in used or c in limited:
            return False
        if at_limit(db, r["company"]):
            limited.add(c)
            return False
        return True

    for track in tracks:  # best job of each track first, so every track shows up
        r = next((r for r in cands if r["track"] == track and ok(r)), None)
        if r and len(picked) < args.n:
            picked.append(r)
            used.add(r["company"].lower())
    for r in cands:  # then fill by score
        if len(picked) >= args.n:
            break
        if r not in picked and ok(r):
            picked.append(r)
            used.add(r["company"].lower())

    batch = []
    for r in sorted(picked, key=lambda r: -r["score"]):
        db.execute("UPDATE jobs SET app_status='queued', batch_date=? WHERE id=?", (today, r["id"]))
        batch.append({"id": r["id"], "company": r["company"], "title": r["title"], "track": r["track"],
                      "score": r["score"], "url": r["url"], "jd_path": str(jd_file(r["id"]).relative_to(ROOT)),
                      "slug": slugify(r["company"], r["title"], r["id"])})
    db.commit()
    existing = json.loads(out.read_text()) if out.exists() else []
    out.write_text(json.dumps(existing + batch, indent=2))
    print(f"Queued {len(batch)} jobs -> {out}")
    if limited:
        print(f"Skipped (application limit reached): {', '.join(sorted(limited))}")
    for b in batch:
        print(f"  {b['score']:>5}  {b['track']:<22} {b['company'][:22]:<22} {b['title'][:55]}")


def cmd_tailored(db, args):
    rdir = (ROOT / args.dir).resolve()
    tailored, pdf = rdir / "tailored.json", rdir / me.resume_name(me.profile())
    if not tailored.exists() or not pdf.exists():
        sys.exit(f"Missing tailored.json or PDF in {rdir}")
    fit = json.loads(tailored.read_text()).get("review", {}).get("fit")
    cur = db.execute("UPDATE jobs SET app_status='tailored', resume_dir=?, fit=? WHERE id=?",
                     (str(rdir.relative_to(ROOT)), fit, args.id))
    db.commit()
    print("recorded" if cur.rowcount else "no job with that id")


def cmd_run(db, args):
    for step in (cmd_fetch, cmd_classify, cmd_jd, cmd_score, cmd_shortlist):
        step(db, args)
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "classify", "score", "stats", "recheck"):
        sub.add_parser(name)
    p = sub.add_parser("jd")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("shortlist")
    p.add_argument("--n", type=int, default=50)
    p = sub.add_parser("run")
    p.add_argument("--limit", type=int)
    p.add_argument("--n", type=int, default=50)
    p = sub.add_parser("mark")
    p.add_argument("id")
    p.add_argument("status")
    p.add_argument("--note", help="appended to the job's notes with today's date (e.g. what an email said)")
    p = sub.add_parser("batch")
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--force", action="store_true")
    p.add_argument("--ids", help="comma-separated job ids to queue instead of picking by score")
    p = sub.add_parser("tailored")
    p.add_argument("id")
    p.add_argument("dir")
    args = ap.parse_args()
    db = db_connect()
    {"fetch": cmd_fetch, "classify": cmd_classify, "jd": cmd_jd, "score": cmd_score, "shortlist": cmd_shortlist,
     "stats": cmd_stats, "mark": cmd_mark, "run": cmd_run, "recheck": cmd_recheck,
     "batch": cmd_batch, "tailored": cmd_tailored}[args.cmd](db, args)


if __name__ == "__main__":
    main()
