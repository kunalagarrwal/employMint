"""Shared helpers for linkedin/outreach.json (recruiter outreach).

Flow:
  applied job -> draft_for_new_applications() starts a background Claude run that finds recruiters
  and writes their messages (status 'drafted') -> the applicant approves on the review page ('approved')
  -> linkedin.py invite sends the connection request ('requested') -> linkedin.py check, 3x a day,
  sends the approved message once they accept ('messaged') and flags replies ('replied').

Usage (used by the background Claude draft run):
  python3 src/outreach.py add  '<json object>'        # add one drafted recruiter
  python3 src/outreach.py skip '<company>' '<reason>'  # no good recruiter found
  python3 src/outreach.py sweep                        # start drafts for applied companies with no outreach yet
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import ROOT, db_connect, now_iso  # noqa: E402
import me  # noqa: E402

OUTREACH = ROOT / "linkedin" / "outreach.json"
LOCK = ROOT / "linkedin" / ".outreach.lock"
LOGS = ROOT / "data" / "outreach-logs"
APPLIED_STATUSES = ("applied", "assessment", "interview")


def load():
    """The outreach records. A missing file means none yet; a damaged one stops everything, because
    treating it as empty would let the next save wipe the history and re-invite people."""
    try:
        return json.loads(OUTREACH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"people": [], "skipped": []}
    except ValueError as ex:
        backup = OUTREACH.with_suffix(".corrupt.json")
        shutil.copy2(OUTREACH, backup)
        raise RuntimeError(f"{OUTREACH} is damaged ({ex}); a copy is at {backup}. Fix it before continuing.")


@contextmanager
def editing():
    """Locked read-modify-write across processes. Yields the data; saves it atomically on exit."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = load()
        data.setdefault("people", [])
        data.setdefault("skipped", [])
        yield data
        fd, tmp = tempfile.mkstemp(dir=OUTREACH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, OUTREACH)


def set_fields(url, **fields):
    with editing() as data:
        for p in data["people"]:
            if p.get("url") == url:
                p.update(fields)
                return dict(p)
    return None


def today():
    return date.today().isoformat()


def norm(company):
    """'C3.ai', 'C3 AI' and 'c3ai' are the same company."""
    import re
    return re.sub(r"[^a-z0-9]", "", (company or "").lower())


def known_companies(data):
    return ({norm(p.get("company")) for p in data.get("people", [])}
            | {norm(s.get("company")) for s in data.get("skipped", [])})


def notify(title, message):
    """macOS notification. Never fails the caller."""
    try:
        subprocess.run(["osascript", "-e", f"display notification {json.dumps(message)} with title {json.dumps(title)}"],
                       timeout=10, capture_output=True)
    except Exception:
        pass


def background(args, log_name):
    """Starts a detached process that outlives the caller (review page, apply window)."""
    LOGS.mkdir(parents=True, exist_ok=True)
    log = open(LOGS / log_name, "a")
    log.write(f"\n=== {now_iso()} {' '.join(map(str, args))[:300]}\n")
    log.flush()
    return subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def start_invites():
    """Sends every approved request now. linkedin.py holds a browser lock, so overlapping calls are harmless."""
    if not me.outreach_enabled(me.prefs()):
        return None
    return background([sys.executable, str(ROOT / "src" / "linkedin.py"), "invite"], "invite.log")


# ---------- drafting with Claude ----------

DRAFT_PROMPT = """You are finding LinkedIn recruiters for {name}, who just applied to an internship.
Company: {company}
Role(s) applied for: {roles}
Job posting(s): {urls}

Steps:
1. Search LinkedIn people with: python3 src/linkedin.py search "<query>"   (prints JSON: name, title, url)
   Try "{company} university recruiter" first, then "{company} recruiter" or "{company} talent" if needed. At most 4 searches.
2. Pick 1 person (2 if it's a large company with several fitting recruiters) whose title says they CURRENTLY do recruiting,
   talent, university relations or campus recruiting at exactly this company. Prefer university / early career / campus, then
   technical recruiters, then talent/HR. Skip "Ex-" people and companies that only share the name.
3. Read each picked person's profile: python3 src/linkedin.py profile "<url>"  (prints their headline, about, experience,
   education, location). Look for something real you share with {first}.
4. Read profile/profile.json and profile/answers.json. They are the ONLY sources of facts about {first}. Also read the
   "Recruiter outreach" section of profile/guidance.md if it exists: it lists the personal facts worth mentioning and the
   kinds of shared links to look for. Never claim anything not in those files (no hometown, languages, or experiences
   you're guessing).
5. For each person write the message {first} will send AFTER they accept the connection request. Make it sound like a
   real college student wrote it to one specific person:
   - Start "Hi <first name>, thanks for connecting!" or "Hi <first name>, thanks for accepting!"
   - A little about {first} as a person (guidance.md says what to lead with).
   - If their profile gives a GENUINE link, mention it briefly and specifically (same school or region, a shared
     background or interest, a company {first} admires for a concrete reason). One link at most. If there's no real
     link, don't invent one and don't force it; skip it.
   - Say {first} applied to the exact role, plus ONE specific true thing from profile.json that fits it.
   - End with one easy question.
   - 60-90 words, warm and casual, like a text to someone you respect. Use contractions (I'm, I've, it's) and don't
     introduce {first} by name ("I am {first}"); they can see the name. No em dashes, no flattery, no "I hope this finds
     you well", no "I came across your profile", no buzzwords, no exclamation-mark overload (two at most).
6. Save each person with:
   python3 src/outreach.py add '{{"company": "{company}", "role": "<role>", "name": "...", "title": "...", "url": "https://www.linkedin.com/in/.../", "personal_link": "<the shared thing you used, or empty>", "message": "..."}}'
   If nobody fits, run: python3 src/outreach.py skip "{company}" "<short reason>"

Never send invitations or messages. Only search, read profiles, and save drafts. Finish with one line saying who you saved."""


def start_draft(company, roles, urls):
    name = me.full_name(me.profile())
    prompt = DRAFT_PROMPT.format(company=company, roles="; ".join(roles), urls=" ".join(urls),
                                 name=name, first=name.split()[0])
    claude = shutil.which("claude")
    if not claude:
        sys.exit("The claude command was not found on PATH. Install Claude Code to draft outreach messages.")
    allowed = ["Read", "Bash(python3 src/linkedin.py search:*)", "Bash(python3 src/linkedin.py profile:*)",
               "Bash(python3 src/outreach.py add:*)",
               "Bash(python3 src/outreach.py skip:*)"]
    safe = "".join(c if c.isalnum() else "-" for c in company.lower())[:40]
    return background([claude, "-p", prompt, "--allowedTools", *allowed], f"draft-{safe}.log")


def clear_stale_drafting(data, hours=2):
    """A draft run that never saved anything shouldn't block that company forever."""
    cutoff = datetime.now().astimezone() - timedelta(hours=hours)
    for c, started in list(data.get("drafting", {}).items()):
        try:
            if datetime.fromisoformat(started) < cutoff:
                del data["drafting"][c]
        except ValueError:
            del data["drafting"][c]


def draft_for_new_applications():
    """Starts one background draft per applied company with no outreach entry yet. Returns the companies started.
    Does nothing unless recruiter outreach is turned on in preferences.json."""
    if not me.outreach_enabled(me.prefs()):
        return []
    db = db_connect()
    try:
        rows = db.execute("SELECT company, title, url FROM jobs WHERE app_status IN (?,?,?) OR pipeline='applied'",
                          APPLIED_STATUSES).fetchall()
    finally:
        db.close()
    with editing() as data:
        clear_stale_drafting(data)
        skip = known_companies(data) | {norm(c) for c in data.get("drafting", {})}
        by_company = {}
        for r in rows:
            if norm(r["company"]) in skip:
                continue
            g = by_company.setdefault(r["company"], {"roles": [], "urls": []})
            g["roles"].append(r["title"])
            g["urls"].append(r["url"])
        data.setdefault("drafting", {}).update({c: now_iso() for c in by_company})
    for company, g in by_company.items():
        start_draft(company, g["roles"], g["urls"])
    return list(by_company)


# ---------- CLI for the draft run ----------

def cmd_add(raw):
    x = json.loads(raw)
    for k in ("company", "name", "url", "message"):
        if not str(x.get(k, "")).strip():
            sys.exit(f"missing {k}")
    if "linkedin.com/in/" not in x["url"]:
        sys.exit("url must be a linkedin.com/in/ profile")
    x["url"] = x["url"].split("?")[0].rstrip("/") + "/"
    with editing() as data:
        if any(p.get("url") == x["url"] for p in data["people"]):
            print("already in the list")
            return
        data["people"].append({"company": x["company"], "role": x.get("role", ""), "name": x["name"],
                               "title": x.get("title", ""), "url": x["url"], "status": "drafted",
                               "personal_link": x.get("personal_link", ""),
                               "message": x["message"].strip(), "drafted_at": today()})
        for c in list(data.get("drafting", {})):
            if norm(c) == norm(x["company"]):
                del data["drafting"][c]
    print(f"saved {x['name']} ({x['company']})")


def cmd_skip(company, reason):
    with editing() as data:
        if norm(company) not in {norm(s.get("company")) for s in data["skipped"]}:
            data["skipped"].append({"company": company, "reason": reason})
        for c in list(data.get("drafting", {})):
            if norm(c) == norm(company):
                del data["drafting"][c]
    print(f"skipped {company}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["add"] and len(a) == 2:
        cmd_add(a[1])
    elif a[:1] == ["skip"] and len(a) == 3:
        cmd_skip(a[1], a[2])
    elif a[:1] == ["sweep"]:
        started = draft_for_new_applications()
        print("drafting:", ", ".join(started) if started else "nothing new")
    else:
        sys.exit(__doc__)
