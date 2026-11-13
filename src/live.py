"""Is a posting still open? A cheap check before tailoring a resume or opening a form.

Asks each site's public job API where there is one (Greenhouse, Ashby, Lever, Workday, SmartRecruiters);
otherwise reads the posting page for a "no longer accepting applications" message.

A job is called closed only on clear evidence: the site says the posting is gone, or SimplifyJobs lists it
as closed and the site couldn't confirm it is open. A network error, a blocked request (403) or an unknown
page is "unknown", never closed, so a flaky connection can't throw away a job.

Usage:
  python3 src/live.py check [--status approved,tailored,queued] [--max-age-hours 12]
  python3 src/live.py url <posting url>
"""
import argparse
import json
import re
import sys
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import db_connect, html_to_text, http_get, now_iso  # noqa: E402

OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"
USER_OPEN = "user_open"  # the applicant said it's still open: never close it automatically again

CLOSED_TEXT = re.compile(
    r"no longer (accepting|taking) applications|(job|position|posting|role|opportunity|requisition) (is|has been) "
    r"(no longer (available|open|active)|closed|filled|removed|expired)|this (job|position|posting) (has )?(expired|closed)"
    r"|job (posting )?(not found|does not exist)|the page you are looking for (doesn't|does not|no longer) exist"
    r"|applications? (for this (job|role|position) )?(are|is|have been|has been) closed", re.I)


def _http_status(url, headers=None):
    """(status code, body) without raising on 4xx/5xx."""
    try:
        return 200, http_get(url, timeout=20, headers=headers)
    except urllib.error.HTTPError as ex:
        return ex.code, ""


def _gone(code):
    return code in (404, 410)


def check_url(url):
    """Returns (state, reason) for one posting URL. state is open / closed / unknown."""
    u = urlparse(url or "")
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    try:
        if "greenhouse.io" in host:
            q = parse_qs(u.query)
            m = re.search(r"/([\w-]+)/jobs/(\d+)", u.path)
            board, jid = (q["for"][0], q["token"][0]) if "for" in q and "token" in q else (m.groups() if m else (None, None))
            if board:
                code, _ = _http_status(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}")
                if _gone(code):
                    return CLOSED, "Greenhouse says the posting is gone"
                if code == 200:
                    return OPEN, "listed on Greenhouse"
        elif "ashbyhq.com" in host and len(parts) >= 2:
            code, body = _http_status(f"https://api.ashbyhq.com/posting-api/job-board/{parts[0]}")
            if code == 200:
                ids = {j.get("id") for j in json.loads(body).get("jobs", [])}
                return (OPEN, "listed on Ashby") if parts[1] in ids else (CLOSED, "no longer on the Ashby board")
            if _gone(code):
                return CLOSED, "Ashby board is gone"
        elif "lever.co" in host and len(parts) >= 2:
            code, _ = _http_status(f"https://api.lever.co/v0/postings/{parts[0]}/{parts[1]}")
            if _gone(code):
                return CLOSED, "Lever says the posting is gone"
            if code == 200:
                return OPEN, "listed on Lever"
        elif "myworkdayjobs.com" in host and parts:
            if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
                parts = parts[1:]
            key = "job" if "job" in parts else "details" if "details" in parts else None
            if key and parts:
                rest = "/".join(parts[parts.index(key) + 1:])
                code, body = _http_status(f"https://{host}/wday/cxs/{host.split('.')[0]}/{parts[0]}/job/{rest}",
                                          headers={"Accept": "application/json"})
                if _gone(code):
                    return CLOSED, "Workday says the posting is gone"
                if code == 200:
                    info = json.loads(body).get("jobPostingInfo", {})
                    if info.get("canApply") is False:
                        return CLOSED, "Workday no longer takes applications for it"
                    return OPEN, "listed on Workday"
        elif "smartrecruiters.com" in host and len(parts) >= 2:
            pid = parts[1].split("-")[0]
            code, body = _http_status(f"https://api.smartrecruiters.com/v1/companies/{parts[0]}/postings/{pid}")
            if _gone(code):
                return CLOSED, "SmartRecruiters says the posting is gone"
            if code == 200:
                return (OPEN, "listed on SmartRecruiters") if json.loads(body).get("active", True) else \
                    (CLOSED, "SmartRecruiters marks it inactive")
        if not url:
            return UNKNOWN, "no posting link"
        code, body = _http_status(url)
        if _gone(code):
            return CLOSED, f"the posting page is gone ({code})"
        if code == 200:
            m = CLOSED_TEXT.search(html_to_text(body)[:20000])
            return (CLOSED, f'the page says "{m.group(0)}"') if m else (UNKNOWN, "page loads; couldn't confirm it's open")
        return UNKNOWN, f"the site answered {code}"
    except Exception as ex:  # network trouble is never evidence the job closed
        return UNKNOWN, f"couldn't reach the site ({type(ex).__name__})"


def decide(site_state, site_reason, simplify_active):
    """Combines the site's answer with SimplifyJobs' active flag. The site wins when it is sure."""
    if site_state == UNKNOWN and simplify_active == 0:
        return CLOSED, "SimplifyJobs lists it as closed"
    return site_state, site_reason


def check_job(row):
    state, reason = check_url(row["url"])
    return decide(state, reason, row["active"])


def record(db, job_id, state, reason):
    """Saves the result. A closed approved / tailored / queued job moves to 'closed' (undo puts it back)."""
    db.execute("UPDATE jobs SET live_state=?, live_reason=?, live_checked_at=? WHERE id=?",
               (state, reason, now_iso(), job_id))
    if state == CLOSED:
        db.execute("UPDATE jobs SET app_status='closed', decided_at=? WHERE id=? "
                   "AND app_status IN ('approved','tailored','queued')", (now_iso(), job_id))


def due(row, max_age_hours):
    if row["live_state"] == USER_OPEN:
        return False
    if not row["live_checked_at"] or max_age_hours is None:
        return True
    try:
        checked = datetime.fromisoformat(row["live_checked_at"])
    except ValueError:
        return True
    return datetime.now(timezone.utc) - checked > timedelta(hours=max_age_hours)


def check_statuses(statuses=("approved", "tailored", "queued"), max_age_hours=None, workers=8):
    """Checks every job in these statuses (skipping ones checked recently). Returns {state: [company, ...]}."""
    db = db_connect()
    try:
        marks = ",".join("?" * len(statuses))
        rows = [r for r in db.execute(f"SELECT * FROM jobs WHERE app_status IN ({marks})", statuses).fetchall()
                if due(r, max_age_hours)]
    finally:
        db.close()
    with ThreadPoolExecutor(workers) as pool:  # network first, then one short write
        results = list(pool.map(check_job, rows))
    out = {OPEN: [], CLOSED: [], UNKNOWN: []}
    db = db_connect()
    try:
        for r, (state, reason) in zip(rows, results):
            record(db, r["id"], state, reason)
            out[state].append(f"{r['company']} ({reason})" if state == CLOSED else r["company"])
        db.commit()
    finally:
        db.close()
    return out


def ensure_open(job_id):
    """Checks one job right before work is spent on it. Returns (still_ok, reason); records a closure."""
    db = db_connect()
    try:
        r = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        db.close()
    if not r:
        return False, "no such job"
    if r["live_state"] == USER_OPEN:
        return True, "you said it's open"
    state, reason = check_job(r)
    db = db_connect()
    try:
        record(db, job_id, state, reason)
        db.commit()
    finally:
        db.close()
    return state != CLOSED, reason


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("--status", default="approved,tailored,queued")
    p.add_argument("--max-age-hours", type=float, help="skip jobs checked more recently than this")
    p = sub.add_parser("url")
    p.add_argument("url")
    args = ap.parse_args()
    if args.cmd == "url":
        print(*check_url(args.url), sep=": ")
        return
    out = check_statuses(tuple(s.strip() for s in args.status.split(",") if s.strip()), args.max_age_hours)
    print(f"{len(out[OPEN])} open, {len(out[CLOSED])} closed, {len(out[UNKNOWN])} couldn't check.")
    for c in out[CLOSED]:
        print(f"  closed: {c}")


if __name__ == "__main__":
    main()
