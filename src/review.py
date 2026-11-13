"""Local review page for the daily batch. Runs only on this laptop (127.0.0.1).

Four tabs: Review (new tailored jobs: apply now or skip), Apply (start the apply queue, or open one job),
Sent (what you've sent and what came back) and Archive. Chrome opens each form filled (src/apply.py),
and you click Submit yourself. Decisions are saved to data/jobs.sqlite. This page never submits anything.

Usage: python3 src/review.py [--port 8765] [--no-open]
"""
import argparse
import html
import json
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import ROOT, db_connect, jd_file, now_iso, pay_from_text, sponsorship_signal  # noqa: E402
import outreach  # noqa: E402
import me  # noqa: E402
import live  # noqa: E402
from apply import GROUPS, group_of  # noqa: E402

RESUMES = (ROOT / "resumes").resolve()
e = html.escape

APPLYING = {}  # job id -> running apply.py process, so one job never opens twice
LIVE = {"running": False, "stamp": 0}  # posting checks; the page reloads when stamp changes

OUTREACH_LABELS = {"drafted": "needs your OK", "approved": "sending request now", "requested": "request sent",
                   "accepted": "accepted, message failed", "messaged": "messaged", "replied": "replied",
                   "skipped": "skipped", "blocked": "can't connect", "not_accepted": "didn't accept"}
STATUS_WORD = {"applied": "Applied", "assessment": "Assessment", "interview": "Interview", "offer": "Offer",
               "closed": "Closed", "rejected": "Rejected", "skip": "Skipped"}
OUTCOMES = ["applied", "assessment", "interview", "offer"]  # the order an application moves through
OUTCOME_LABEL = {"assessment": "Got a coding test", "interview": "Got an interview", "offer": "Got an offer"}
GROUP_LABEL = {"quick": ("Quick", "fills itself"), "workday": ("Workday", "sign in, then it walks the steps"),
               "manual": ("Manual", "answers beside the form to copy in")}
# The leaf-dot wordmark from the website.
WORDMARK = ('<span class="wm" aria-hidden="true">employM<span class="wm-i">ı<svg class="wm-leaf" viewBox="0 0 10 16">'
            '<path d="M5 .6C9.2 4 9.4 10.6 5 15.4 .6 10.6.8 4 5 .6Z"/><path class="vein" d="M5 3v11"/></svg></span>nt</span>')


# Line icons for the four sections, drawn like the website's pencil plates.
_I = '<svg class="ico" viewBox="0 0 20 20" aria-hidden="true">{}</svg>'
ICONS = {
    "review": _I.format('<rect x="3.5" y="2.5" width="13" height="15" rx="2"/><path d="M7 7h6M7 10.5h6M7 14l1.5 1.5L12 12"/>'),
    "apply": _I.format('<path d="M3 10.5 17 3l-4 14-3.2-5.6L3 10.5Z"/><path d="m9.8 11.4 3-3"/>'),
    "sent": _I.format('<path d="M3 11.5 5 4h10l2 7.5V16H3v-4.5Z"/><path d="M3 11.5h4l1 2h4l1-2h4"/>'),
    "archive": _I.format('<rect x="2.5" y="3.5" width="15" height="4" rx="1"/><path d="M4 7.5V16h12V7.5M8 11h4"/>'),
}
LEAF = ('<svg class="leaf" viewBox="0 0 10 16" aria-hidden="true"><path d="M5 .6C9.2 4 9.4 10.6 5 15.4 .6 10.6.8 4 5 .6Z"/>'
        '<path class="vein" d="M5 3v11"/></svg>')


def is_today(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().date() == datetime.now().date()
    except (TypeError, ValueError):
        return False


def hero(tab, title, sub, today):
    return (f'<div class="hero"><p class="eyebrow">{tab} · {e(today)}</p><h1>{title}</h1>'
            + (f'<p class="hero-sub">{sub}</p>' if sub else "") + '</div>')


def safe_url(u):
    """Links from scraped or generated data: only http(s), so a 'javascript:' URL can't run on click."""
    return u if urlparse(u or "").scheme in ("http", "https") else "#"


def load_outreach():
    return outreach.load()


def load_review(resume_dir):
    if not resume_dir:
        return {}
    p = ROOT / resume_dir / "tailored.json"
    try:
        return json.loads(p.read_text()).get("review", {})
    except (OSError, ValueError):
        return {}


def days_since(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return None


def short_date(iso):
    try:
        d = datetime.fromisoformat(iso)
        return f"{d.day} {d.strftime('%b')}"
    except (TypeError, ValueError):
        return ""


def place(r):
    """First location, plus how many more."""
    try:
        locs = json.loads(r["locations"] or "[]")
    except ValueError:
        locs = [r["locations"]] if r["locations"] else []
    return (locs[0] + (f" +{len(locs) - 1}" if len(locs) > 1 else "")) if locs else ""


def job_links(r, *, resume=True):
    jid = e(r["id"])
    links = [f'<a href="{e(safe_url(r["url"]))}" target="_blank" rel="noopener">Posting</a>']
    if resume and r["resume_dir"]:
        links.insert(0, f'<a href="/pdf?id={jid}" target="_blank">Resume</a>')
        if (ROOT / r["resume_dir"] / me.cover_name(me.profile())).exists():
            links.insert(1, f'<a href="/pdf?id={jid}&doc=cover" target="_blank">Cover letter</a>')
    return links


def fit_label(fit):
    try:
        f = float(fit)
    except (TypeError, ValueError):
        return ""
    return str(int(f)) if f.is_integer() else str(f)


def review_card(r):
    """A new tailored job: the decision-making facts up front, the rest under Details. "Apply now" opens the
    filled form; submitting it is the yes. The apply queue includes these jobs too."""
    rv = load_review(r["resume_dir"])
    fit = rv.get("fit", r["fit"])
    jid = e(r["id"])
    jd = jd_file(r["id"])
    jd_text = jd.read_text(encoding="utf-8") if jd.exists() else ""
    pay = pay_from_text(jd_text)
    spon_kind, spon_label = sponsorship_signal(jd_text, r["visa_flags"])
    facts = [e(x) for x in (place(r), pay) if x]
    if spon_kind in ("yes", "cpt", "check"):
        facts.append(f'<span class="visa-{spon_kind}">{e(spon_label)}</span>')
    gaps = "".join(f"<li>{e(g)}</li>" for g in rv.get("gaps", []))
    emph = ", ".join(e(x) for x in rv.get("emphasized", []))
    links = job_links(r) + ([f'<a href="/jd?id={jid}" target="_blank">Description</a>'] if jd.exists() else [])
    more = "".join([
        f'<div><h4>Gaps</h4><ul>{gaps}</ul></div>' if gaps else "",
        f'<div><h4>Resume leans on</h4><p>{emph}</p></div>' if emph else "",
        f'<div><h4>Visa</h4><p>{e(spon_label)}</p></div>',
        f'<p class="links">{"".join(links)}</p>',
        f'<iframe loading="lazy" src="/pdf?id={jid}" title="Resume for {e(r["company"])}"></iframe>' if r["resume_dir"] else "",
    ])
    label = fit_label(fit)
    fit_html = ""
    if label:
        tier, word = ("high", "strong fit") if float(fit) >= 8 else ("mid", "fair fit") if float(fit) >= 6 else ("low", "long shot")
        fit_html = (f'<div class="fit fit-{tier}" title="How well you fit, out of 10">{label}<small>/10</small>'
                    f'<span>{word}</span></div>')
    return f"""
<article class="card" data-co="{e(r["company"])}">
  <div class="card-top"><div><h3>{e(r["company"])}</h3><p class="role">{e(r["title"])}</p></div>{fit_html}</div>
  {f'<p class="facts">{" · ".join(facts)}</p>' if facts else ""}
  {f'<p class="why">{e(rv["why"])}</p>' if rv.get("why") else ""}
  <div class="actions">
    <button class="btn" data-id="{jid}" data-d="open">Apply now</button>
    <button class="btn btn-quiet" data-id="{jid}" data-d="skip">Skip</button>
    <details class="more"><summary>Details</summary><div class="more-body">{more}</div></details>
  </div>
</article>"""


def row(r):
    """One line for a job that's already decided: approved, in progress, or archived."""
    jid, status = e(r["id"]), r["app_status"]
    meta, actions, note = "", "", ""
    if status == "approved":
        d = days_since(r["decided_at"])
        if d is not None and d >= 1:
            meta = f'<span class="{"late" if d >= 3 else ""}">waiting {d} day{"s" if d != 1 else ""}</span>'
        actions = (f'<button class="btn btn-small" data-id="{jid}" data-d="open">Open</button>'
                   f'<button class="link" data-id="{jid}" data-d="applied">Mark applied</button>'
                   f'<button class="link" data-id="{jid}" data-d="undo">Undo</button>')
    elif status in ("applied", "assessment", "interview", "offer"):
        tip = f' title="{e(r["notes"].strip())}"' if r["notes"] and r["notes"].strip() else ""
        meta = (f'<span class="tag tag-{status}">{STATUS_WORD[status]}</span>' if status != "applied" else "") + \
            f'<span{tip}>{short_date(r["decided_at"])}</span>'
        nxt = OUTCOMES[OUTCOMES.index(status) + 1:] if status in OUTCOMES else []
        actions = "".join(f'<button class="link" data-id="{jid}" data-d="{o}">{OUTCOME_LABEL[o]}</button>' for o in nxt)
        actions += f'<button class="link" data-id="{jid}" data-d="rejected">Got rejected</button>' if status != "offer" else ""
        if status == "applied":
            actions += f'<button class="link" data-id="{jid}" data-d="undo">Undo</button>'
    elif status == "closed":
        meta = f'<span title="{e(r["live_reason"] or "")}">closed {short_date(r["decided_at"])}</span>'
        actions = f'<button class="link" data-id="{jid}" data-d="reopen">It\'s still open</button>'
    elif status == "skip":
        actions = f'<button class="link" data-id="{jid}" data-d="undo">Undo</button>'
    elif status == "rejected":
        meta = f'<span>{short_date(r["decided_at"])}</span>'
        actions = f'<button class="link" data-id="{jid}" data-d="unreject">Not rejected after all</button>'
    primary = ""
    if status == "approved":  # Open stays visible; everything else waits in the menu
        primary, actions = actions.split("</button>", 1)[0] + "</button>", actions.split("</button>", 1)[1]
    menu = "".join(job_links(r, resume=status != "skip")) + actions
    return f"""
<div class="row" data-co="{e(r["company"])}">
  <div class="row-main"><b>{e(r["company"])}</b><span class="row-role">{e(r["title"])}</span>{note}</div>
  <div class="row-meta">{meta}</div>
  <div class="row-act">{primary}<details class="menu"><summary aria-label="More for {e(r["company"])}">···</summary>
    <div class="menu-body">{menu}</div></details></div>
</div>"""


def recruiter_card(x):
    url = e(x.get("url", ""))
    return f"""
<article class="card">
  <div class="card-top"><div><h3>{e(x.get("name", ""))}</h3><p class="role">{e(x.get("title", ""))} · {e(x.get("company", ""))}</p></div></div>
  <p class="facts">You applied for {e(x.get("role", ""))}</p>
  <textarea class="msg" rows="4" aria-label="Message to {e(x.get("name", ""))}">{e(x.get("message", ""))}</textarea>
  <div class="actions">
    <button class="btn" data-url="{url}" data-o="approve">Send request</button>
    <button class="btn btn-quiet" data-url="{url}" data-o="skip">Skip</button>
    <span class="links"><a href="{e(safe_url(x.get('url', '')))}" target="_blank" rel="noopener">LinkedIn</a></span>
  </div>
</article>"""


def recruiter_row(x):
    url, status = e(x.get("url", "")), x.get("status", "")
    undo = f'<button class="link" data-url="{url}" data-o="undo">Undo</button>' if status == "skipped" else ""
    reply = f'<p class="note">They replied: {e(x["reply"])}</p>' if x.get("reply") else ""
    return f"""
<div class="row">
  <div class="row-main"><b>{e(x.get("name", ""))}</b><span class="row-role">{e(x.get("company", ""))}</span>{reply}</div>
  <div class="row-meta"><span>{e(OUTREACH_LABELS.get(status, status))}</span></div>
  <div class="row-act"><details class="menu"><summary aria-label="More for {e(x.get("name", ""))}">···</summary>
    <div class="menu-body"><a href="{e(safe_url(x.get('url', '')))}" target="_blank" rel="noopener">LinkedIn</a>{undo}</div></details></div>
</div>"""


def group(label, items, note="", gid=""):
    if not items:
        return ""
    return (f'<section class="group" id="{gid}"><h2 class="eyebrow">{label}<span>{len(items)}</span>'
            f'{f"<em>{note}</em>" if note else ""}</h2><div class="rows">{"".join(items)}</div></section>')


def page(db):
    rows = db.execute(
        "SELECT * FROM jobs WHERE app_status IN ('queued','tailored','approved','skip','applied',"
        "'assessment','interview','rejected','offer','closed') "
        "AND (batch_date IS NOT NULL OR resume_dir IS NOT NULL) ORDER BY fit DESC, score DESC").fetchall()
    by = lambda *st: [r for r in rows if r["app_status"] in st]
    newest = lambda rs: sorted(rs, key=lambda r: r["decided_at"] or "", reverse=True)
    approved = sorted(by("approved"), key=lambda r: r["decided_at"] or "~")  # longest-waiting first
    people = load_outreach().get("people", [])
    drafted = [x for x in people if x.get("status") == "drafted"]
    history = [x for x in people if x.get("status") != "drafted"]
    tailored, queued = by("tailored"), by("queued")

    # Review: decide on each tailored job (and any recruiter message waiting for an OK).
    review = "".join(review_card(r) for r in tailored)
    if drafted:
        review += '<h2 class="eyebrow sep" id="g-messages">Recruiters to message</h2>' + "".join(recruiter_card(x) for x in drafted)
    if queued:
        review += f'<p class="aside">{len(queued)} more {"is" if len(queued) == 1 else "are"} still being tailored.</p>'

    # One button for the whole queue: approved jobs, then new tailored ones. The filled form is where you decide.
    queueable = [r for r in approved + tailored if r["fit"] is not None and r["resume_dir"]]
    per = {g: sum(1 for r in queueable if group_of(r["url"]) == g) for g in GROUPS}
    only = "".join(f'<button class="link" data-group="{g}">Only {GROUP_LABEL[g][0] if g == "workday" else g} ({n})</button>'
                   for g, n in per.items() if n)
    checking = LIVE["running"]
    start = (f'<div class="start"><button class="btn btn-big" data-group="">Start applying ({len(queueable)})</button>'
             f'<p>Chrome opens each form filled in, quickest first. Read it: Submit is your yes, '
             f'&ldquo;Not for me&rdquo; your no. The next one follows.</p>'
             f'<p class="start-more">{only}<button class="link" id="check-live"{" disabled" if checking else ""}>'
             f'{"Checking postings…" if checking else "Check which are still open"}</button></p></div>') if queueable else ""
    review = (start if tailored else "") + review
    apply_ = start + "".join(
        group(GROUP_LABEL[g][0], [row(r) for r in approved if group_of(r["url"]) == g], GROUP_LABEL[g][1], f"g-{g}")
        for g in GROUPS)

    # Each tab's groups: (id, label in the sidebar, count). Empty groups are left out everywhere.
    subs = {
        "review": [("g-messages", "Recruiter messages", len(drafted))] if drafted else [],
        "apply": [(f"g-{g}", GROUP_LABEL[g][0], sum(1 for r in approved if group_of(r["url"]) == g)) for g in GROUPS],
        "sent": [("g-offers", "Offers", len(by("offer"))), ("g-talks", "Interviews & tests", len(by("interview", "assessment"))),
                 ("g-waiting", "Waiting to hear back", len(by("applied"))), ("g-recruiters", "Recruiters", len(history))],
        "archive": [("g-closed", "Closed", len(by("closed"))), ("g-rejected", "Rejected", len(by("rejected"))),
                    ("g-skipped", "Skipped", len(by("skip")))],
    }
    subs = {k: [x for x in v if x[2]] for k, v in subs.items()}
    applied = "".join([
        group("Offers", [row(r) for r in newest(by("offer"))], gid="g-offers"),
        group("Interviews & coding tests", [row(r) for r in newest(by("interview", "assessment"))], gid="g-talks"),
        group("Waiting to hear back", [row(r) for r in newest(by("applied"))], gid="g-waiting"),
        group("Recruiters", [recruiter_row(x) for x in history], gid="g-recruiters"),
    ])
    archive = "".join([
        group("Closed before you applied", [row(r) for r in newest(by("closed"))], gid="g-closed"),
        group("Rejected", [row(r) for r in newest(by("rejected"))], gid="g-rejected"),
        group("Skipped", [row(r) for r in newest(by("skip"))], gid="g-skipped"),
    ])

    n_review, n_apply = len(tailored) + len(drafted), len(approved)
    in_flight = by("applied", "assessment", "interview", "offer")
    n_applied, n_talks = len(in_flight), len(by("assessment", "interview", "offer"))
    now = datetime.now()
    today = f"{now.strftime('%a')} {now.day} {now.strftime('%b')}"
    oldest = max((days_since(r["decided_at"]) or 0 for r in approved), default=0)
    approved_today = sum(1 for r in approved if is_today(r["decided_at"]))
    sent_today = sum(1 for r in in_flight if is_today(r["decided_at"]))
    # One leaf per application sent today: a small reward that stays on the page.
    tally = (f'Today: {approved_today} approved · {sent_today} sent'
             + (f'<span class="leaves">{LEAF * min(sent_today, 12)}</span>' if sent_today else ""))

    heroes = {
        "review": hero("Review", f'{n_review} new. <em>Decide on the filled form, or skip here.</em>' if n_review
                       else 'All caught up. <em>Nothing to review.</em>', "", today),
        "apply": hero("Apply", f'{n_apply} approved. <em>' + (f'The oldest has waited {oldest} days.' if oldest >= 3
                      else 'You submit each one.') + '</em>' if n_apply else 'Nothing approved. <em>New jobs wait in Review.</em>',
                      "", today),
        "sent": hero("Sent", (f'{n_applied} sent. <em>' + (f'{n_talks} moving forward.' if n_talks else 'Waiting to hear back.')
                        + '</em>') if n_applied else 'Nothing sent yet. <em>Your first one is close.</em>',
                        "Heard back? Record it from the three-dot menu on that application." if n_applied else "", today),
        "archive": hero("Archive", 'The archive. <em>Closed, rejected, skipped.</em>', "", today),
    }
    caught_up = (f'<div class="caught-up">{LEAF}<p>Ask Claude to run today\'s batch for more.</p>'
                 + (f'<p><a href="#apply">Go to Apply ({n_apply})</a></p>' if n_apply else "") + '</div>')
    tabs = [("review", "Review", n_review, review or caught_up),
            ("apply", "Apply", n_apply, apply_),
            ("sent", "Sent", n_applied, applied),
            ("archive", "Archive", len(by("closed", "rejected", "skip")), archive)]
    default = "review" if n_review else "apply" if n_apply else "sent"

    def sub_links(k):
        return "".join(f'<a href="#{k}" data-tab="{k}" data-jump="{gid}">{e(label)}<span>{n}</span></a>' for gid, label, n in subs[k])
    side_nav = "".join(
        f'<a class="side-link" href="#{k}" data-tab="{k}" title="{label} (press {i + 1})">{ICONS[k]}<span class="lbl">{label}</span>'
        f'{f"<span class=count>{n}</span>" if n else ""}</a>'
        + (f'<div class="side-sub" data-for="{k}">{sub_links(k)}</div>' if subs[k] else "")
        for i, (k, label, n, _) in enumerate(tabs))
    bottom = "".join(f'<a href="#{k}" data-tab="{k}">{ICONS[k]}<span>{label}</span>{f"<b>{n}</b>" if n and k != "archive" else ""}</a>'
                     for k, label, n, _ in tabs)
    # On a phone the sidebar is gone, so each tab's groups become a row of chips under its heading.
    chips = {k: (f'<nav class="chips" aria-label="Jump to">{sub_links(k)}</nav>' if len(subs[k]) > 1 else "") for k in subs}
    panels = "".join(f'<section class="panel" id="panel-{k}" data-tab="{k}">{heroes[k]}{chips[k]}{body}</section>'
                     for k, _, _, body in tabs)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Daily review · employMint</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Newsreader:ital,opsz,wght@0,6..72,400;1,6..72,400&display=swap" rel="stylesheet">
<script>try {{ var t = localStorage.getItem("employmint-theme"); if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t); }} catch (e) {{}}</script>
<style>{CSS}</style></head><body data-default="{default}">
<div class="frame" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
<aside class="side">
  <a class="brand" href="#{default}" aria-label="employMint">{WORDMARK}</a>
  <label class="search"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="5"/><path d="M11 11l3.5 3.5"/></svg>
    <input id="q" type="search" autocomplete="off" placeholder="Search" aria-label="Search jobs"><kbd>/</kbd></label>
  <nav class="side-nav" aria-label="Sections">{side_nav}</nav>
  <div class="side-foot">
    <p class="tally">{tally}</p>
    <button class="pill theme-toggle" type="button" aria-label="Darkroom (dark mode)"><svg viewBox="0 0 24 24"><path class="moon" d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z"/><g class="sun"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></g></svg><span>Darkroom</span></button>
    <p class="keys"><kbd>1</kbd>–<kbd>4</kbd> sections · <kbd>/</kbd> search<span class="review-keys"><br><kbd>A</kbd> approve · <kbd>S</kbd> skip top card</span></p>
  </div>
</aside>
<main>
  {panels}
  <p class="empty no-results">No matches.</p>
</main>
<nav class="bottom" aria-label="Sections">{bottom}</nav>
<div class="toast" role="status" aria-live="polite" hidden></div>
<script>{JS}</script></body></html>"""


CSS = """
:root { --paper:#f2ede2; --paper-2:#e8e1d2; --card:#f8f4ec; --ink:#1f1d19; --ink-2:#4a463f; --muted:#625b51; --line:#d4cab7;
  --graphite:#2b2925; --gold:#b08a3c; --mint:#2f6b52; --mint-ink:#f4f1ea; --mint-soft:#dbe7df; --clay:#b75a32;
  --serif:"Newsreader", Georgia, serif; --sans:"Instrument Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono:"JetBrains Mono", ui-monospace, Menlo, monospace; color-scheme:light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --paper:#171613; --paper-2:#1f1d1a; --card:#23211d; --ink:#efe9dd;
  --ink-2:#cfc7b8; --muted:#a39b8d; --line:#3a3630; --graphite:#e4ddcf; --gold:#cfa95e; --mint:#7cc3a1; --mint-ink:#10241b;
  --mint-soft:#1f3329; --clay:#e08a63; color-scheme:dark; } }
:root[data-theme="dark"] { --paper:#171613; --paper-2:#1f1d1a; --card:#23211d; --ink:#efe9dd; --ink-2:#cfc7b8; --muted:#a39b8d;
  --line:#3a3630; --graphite:#e4ddcf; --gold:#cfa95e; --mint:#7cc3a1; --mint-ink:#10241b; --mint-soft:#1f3329; --clay:#e08a63; color-scheme:dark; }
*, *::before, *::after { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:400 16px/1.55 var(--sans); -webkit-font-smoothing:antialiased; }
a { color:inherit; }
:focus-visible { outline:2px solid var(--mint); outline-offset:3px; }
h1, h2, h3, h4 { margin:0; font-weight:400; }
p { margin:0; }

/* The drafting frame from the website. */
.frame { position:fixed; inset:14px; border:1px solid var(--line); pointer-events:none; z-index:40; }
.frame span { position:absolute; width:12px; height:12px; border:0 solid var(--graphite); }
.frame span:nth-child(1) { top:-1px; left:-1px; border-top-width:1.5px; border-left-width:1.5px; }
.frame span:nth-child(2) { top:-1px; right:-1px; border-top-width:1.5px; border-right-width:1.5px; }
.frame span:nth-child(3) { bottom:-1px; left:-1px; border-bottom-width:1.5px; border-left-width:1.5px; }
.frame span:nth-child(4) { bottom:-1px; right:-1px; border-bottom-width:1.5px; border-right-width:1.5px; }

/* Sidebar: every section and its groups, always in view. */
.side { position:fixed; top:14px; bottom:14px; left:14px; width:250px; z-index:30; display:flex; flex-direction:column; gap:22px;
  padding:30px 20px 22px 26px; border-right:1px solid var(--line); overflow-y:auto; scrollbar-width:none; }
.brand { text-decoration:none; padding-left:2px; }
.wm { display:inline-block; font:700 22px/1 var(--sans); letter-spacing:.045em; color:var(--ink); white-space:nowrap; }
.wm-i { position:relative; display:inline-block; }
.wm-leaf { position:absolute; left:50%; top:-.27em; width:.36em; height:.58em; transform:translateX(-42%) rotate(30deg); fill:var(--mint); overflow:visible; }
.wm-leaf .vein { fill:none; stroke:var(--paper); stroke-width:.9; stroke-linecap:round; opacity:.7; }
.search { position:relative; display:block; }
.search svg { position:absolute; left:12px; top:50%; width:14px; height:14px; transform:translateY(-50%); fill:none; stroke:var(--muted);
  stroke-width:1.6; stroke-linecap:round; pointer-events:none; }
.search kbd { position:absolute; right:9px; top:50%; transform:translateY(-50%); }
#q { width:100%; height:38px; padding:0 34px 0 34px; font:14px var(--sans); border-radius:10px; border:1px solid var(--line);
  background:var(--card); color:var(--ink); outline:none; transition:border-color .2s; }
#q:focus { border-color:var(--ink-2); }
#q:focus + kbd, #q:not(:placeholder-shown) + kbd { display:none; }
#q::placeholder { color:var(--muted); }
.side-nav { display:flex; flex-direction:column; gap:2px; }
.side-link { display:flex; align-items:center; gap:11px; height:42px; padding:0 12px; border-radius:10px; text-decoration:none;
  color:var(--ink-2); font:500 15px var(--sans); transition:background .15s, color .15s; }
.side-link:hover { background:var(--paper-2); color:var(--ink); }
.side-link .lbl { flex:1; }
.side-link .count { font:500 12px var(--mono); color:var(--muted); }
.side-link.active { background:var(--ink); color:var(--paper); }
.side-link.active .count { color:var(--paper); opacity:.75; }
.ico { width:19px; height:19px; flex:none; fill:none; stroke:currentColor; stroke-width:1.5; stroke-linecap:round; stroke-linejoin:round; }
.side-sub { display:none; flex-direction:column; margin:6px 0 10px 21px; padding-left:12px; border-left:1px solid var(--line); }
.side-sub.open { display:flex; }
.side-sub a { display:flex; justify-content:space-between; gap:10px; padding:6px 10px; margin-left:-13px; border-left:2px solid transparent;
  font-size:14px; color:var(--muted); text-decoration:none; transition:color .15s, border-color .15s; }
.side-sub a span { font:500 11.5px var(--mono); }
.side-sub a:hover { color:var(--ink); }
.side-sub a.here { color:var(--ink); border-left-color:var(--mint); }
.side-foot { margin-top:auto; display:flex; flex-direction:column; align-items:flex-start; gap:14px; }
.tally { display:flex; flex-wrap:wrap; align-items:center; gap:8px; font-size:13px; color:var(--muted); }
.pill { display:inline-flex; align-items:center; gap:8px; height:36px; padding:0 14px 0 11px; border-radius:999px; border:1px solid var(--line);
  background:var(--paper-2); color:var(--ink-2); font:500 14px var(--sans); cursor:pointer; }
.pill:hover { color:var(--ink); border-color:var(--ink-2); }
.theme-toggle svg { width:17px; height:17px; fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; }
.theme-toggle .moon { display:none; }
:root[data-theme="dark"] .theme-toggle .sun { display:none; }
:root[data-theme="dark"] .theme-toggle .moon { display:block; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .theme-toggle .sun { display:none; }
  :root:not([data-theme="light"]) .theme-toggle .moon { display:block; } }

body { padding-left:278px; }
main { width:min(800px, 100% - 96px); margin:0 auto; padding:56px 0 120px; }
.group, .sep { scroll-margin-top:28px; }
.bottom, .chips { display:none; }
.hero { margin-bottom:40px; }
.hero-sub { margin-top:14px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; font-size:14px; color:var(--muted); }
.leaves { display:inline-flex; gap:3px; }
.leaf { width:9px; height:14px; fill:var(--mint); transform:rotate(30deg); }
.leaf .vein { fill:none; stroke:var(--paper); stroke-width:.9; stroke-linecap:round; opacity:.7; }
.leaves .leaf { animation:sprout .5s cubic-bezier(.3,1.6,.5,1) both; transform-origin:50% 100%; }
.leaves .leaf:nth-child(2) { animation-delay:.06s; } .leaves .leaf:nth-child(3) { animation-delay:.12s; }
.leaves .leaf:nth-child(4) { animation-delay:.18s; } .leaves .leaf:nth-child(n+5) { animation-delay:.24s; }
@keyframes sprout { from { transform:rotate(30deg) scale(0); } to { transform:rotate(30deg) scale(1); } }
.caught-up { display:flex; flex-direction:column; align-items:flex-start; gap:10px; padding:8px 0 40px; color:var(--muted); }
.caught-up .leaf { width:26px; height:42px; animation:sway 4s ease-in-out infinite; transform-origin:50% 100%; }
@keyframes sway { 0%, 100% { transform:rotate(22deg); } 50% { transform:rotate(38deg); } }
.caught-up a { color:var(--ink); text-underline-offset:3px; }
.eyebrow { font:500 11px/1.4 var(--mono); letter-spacing:.2em; text-transform:uppercase; color:var(--muted); }
.hero .eyebrow::after { content:""; display:block; width:36px; height:1.5px; background:var(--gold); margin-top:14px; }
h1 { font:400 clamp(32px, 4.6vw, 46px)/1.1 var(--serif); letter-spacing:-.012em; margin-top:16px; text-wrap:balance; }
h1 em { color:var(--mint); font-style:italic; }

.panel { display:none; }
.panel.show { display:block; animation:rise .35s cubic-bezier(.2,.7,.2,1); }
@keyframes rise { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }

/* Review cards */
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:24px 28px 22px; margin-bottom:14px;
  transition:border-color .2s, transform .2s; }
.card:hover { border-color:color-mix(in srgb, var(--ink) 25%, var(--line)); }
#panel-review .card:first-of-type { border-color:var(--ink-2); }
.card-top { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }
h3 { font:400 26px/1.15 var(--serif); }
.role { color:var(--ink-2); margin-top:3px; font-size:15px; }
.fit { text-align:right; font:400 30px/1 var(--serif); white-space:nowrap; color:var(--ink); }
.fit small { font:500 12px var(--mono); color:var(--muted); margin-left:2px; }
.fit span { display:block; margin-top:6px; font:500 10px var(--mono); letter-spacing:.16em; text-transform:uppercase; color:var(--muted); }
.fit-high, .fit-high span { color:var(--mint); }
.fit-low, .fit-low span { color:var(--clay); }
.facts { margin-top:10px; font-size:14px; color:var(--muted); }
.visa-yes, .visa-cpt { color:var(--mint); }
.visa-check { color:var(--clay); }
.why { margin-top:14px; padding-left:14px; border-left:2px solid var(--line); font:italic 17px/1.5 var(--serif); color:var(--ink-2); max-width:40em; }
.actions { display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-top:20px; }
.btn { display:inline-flex; align-items:center; height:40px; padding:0 20px; border-radius:999px; border:0; cursor:pointer;
  background:var(--ink); color:var(--paper); font:500 15px var(--sans); transition:background .2s, color .2s; }
.btn:hover { background:var(--mint); color:var(--mint-ink); }
.btn-quiet { background:transparent; color:var(--ink); box-shadow:inset 0 0 0 1px var(--line); }
.btn-quiet:hover { background:var(--paper-2); color:var(--ink); }
.btn-small { height:32px; padding:0 15px; font-size:13px; }
.btn-big { height:50px; padding:0 30px; font-size:17px; }
.btn:disabled, .link:disabled { opacity:.45; cursor:default; }
.link { background:none; border:0; padding:0; cursor:pointer; font:500 13px var(--sans); color:var(--muted);
  text-decoration:underline; text-decoration-color:var(--line); text-underline-offset:3px; }
.link:hover { color:var(--ink); text-decoration-color:currentColor; }
.actions .more { margin-left:auto; }
.more[open] { flex-basis:100%; margin-left:0; }
.more summary { cursor:pointer; list-style:none; font:500 13px var(--sans); color:var(--muted); }
.more summary::-webkit-details-marker { display:none; }
.more summary::after { content:" +"; }
.more[open] summary::after { content:" −"; }
.more[open] summary { margin-bottom:16px; }
.more-body { display:grid; gap:16px; border-top:1px solid var(--line); padding-top:16px; font-size:14px; color:var(--ink-2); }
.more-body h4 { font:500 10.5px var(--mono); letter-spacing:.18em; text-transform:uppercase; color:var(--muted); margin-bottom:6px; }
.more-body ul { margin:0; padding-left:18px; }
.more-body iframe { width:100%; height:70vh; border:1px solid var(--line); border-radius:10px; background:#fff; }
.links { display:inline-flex; flex-wrap:wrap; gap:4px 16px; font-size:13px; }
.links a { color:var(--ink-2); text-decoration:underline; text-decoration-color:var(--line); text-underline-offset:3px; }
.links a:hover { color:var(--mint); text-decoration-color:currentColor; }
textarea.msg { width:100%; margin-top:14px; font:15px/1.5 var(--sans); color:var(--ink); background:var(--paper); border:1px solid var(--line);
  border-radius:10px; padding:12px 14px; resize:vertical; }
.aside { margin-top:22px; color:var(--muted); font:italic 16px var(--serif); }
.sep { margin:40px 0 14px; }

/* Apply */
.start { padding:4px 0 36px; border-bottom:1px solid var(--line); }
.start p { margin-top:14px; color:var(--ink-2); max-width:36em; font-size:15px; }
.start .start-more { display:flex; flex-wrap:wrap; gap:6px 18px; margin-top:12px; }

/* Lists of decided jobs */
.group { margin-top:36px; }
.group .eyebrow { display:flex; align-items:baseline; gap:10px; padding-bottom:10px; border-bottom:1px solid var(--graphite); color:var(--ink-2); }
.group .eyebrow span { color:var(--ink); }
.group .eyebrow em { font:italic 14px var(--serif); letter-spacing:0; text-transform:none; color:var(--muted); }
.row { display:grid; grid-template-columns:minmax(0, 1fr) auto auto; align-items:center; gap:8px 22px; padding:14px 8px;
  margin:0 -8px; border-bottom:1px solid var(--line); border-radius:6px; transition:background .15s; }
.row:hover { background:color-mix(in srgb, var(--paper-2) 60%, transparent); }
.row-main { min-width:0; }
.row-main b { display:block; font:400 19px/1.3 var(--serif); }
.row-role { display:block; color:var(--muted); font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.row-meta { display:flex; gap:10px; align-items:center; font-size:13px; color:var(--muted); white-space:nowrap; }
.row-meta .late { color:var(--clay); }
.row-act { display:flex; gap:10px; align-items:center; justify-content:flex-end; white-space:nowrap; }
.menu { position:relative; }
.menu summary { list-style:none; cursor:pointer; width:32px; height:32px; display:grid; place-items:center; border-radius:999px;
  color:var(--muted); font:600 14px/1 var(--sans); letter-spacing:.05em; }
.menu summary::-webkit-details-marker { display:none; }
.menu summary:hover, .menu[open] summary { background:var(--paper-2); color:var(--ink); }
.menu-body { position:absolute; right:0; top:38px; z-index:20; min-width:170px; display:flex; flex-direction:column; padding:6px;
  background:var(--card); border:1px solid var(--line); border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,.12); }
.menu-body a, .menu-body .link { display:block; text-align:left; padding:8px 12px; border-radius:8px; font:500 14px var(--sans);
  color:var(--ink-2); text-decoration:none; }
.menu-body a:hover, .menu-body .link:hover { background:var(--paper-2); color:var(--ink); }
.note { font-size:13px; color:var(--muted); margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tag { font:500 10.5px var(--mono); letter-spacing:.14em; text-transform:uppercase; padding:3px 8px; border-radius:999px; border:1px solid var(--line); }
.tag-interview, .tag-assessment { color:var(--mint); border-color:currentColor; }
.tag-offer { color:var(--gold); border-color:currentColor; }

.empty { color:var(--muted); font:italic 22px var(--serif); padding:40px 0; }
.keys { font-size:12px; line-height:2; color:var(--muted); }
.keys .review-keys { display:none; }
body.on-review .keys .review-keys { display:inline; }
kbd { font:500 11px var(--mono); padding:1px 6px; border:1px solid var(--line); border-bottom-width:2px; border-radius:5px;
  background:var(--card); color:var(--ink-2); }
.toast { position:fixed; left:50%; bottom:34px; z-index:50; transform:translateX(-50%); display:flex; gap:16px; align-items:center;
  padding:12px 14px 12px 20px; border-radius:999px; background:var(--ink); color:var(--paper); font-size:14px;
  box-shadow:0 10px 30px rgba(0,0,0,.18); animation:pop .3s cubic-bezier(.2,.7,.2,1); }
.toast[hidden] { display:none; }
.toast button { background:none; border:0; cursor:pointer; color:inherit; font:600 14px var(--sans); padding:4px 10px; border-radius:999px;
  text-decoration:underline; text-underline-offset:3px; }
.toast button:hover { background:color-mix(in srgb, var(--paper) 15%, transparent); }
@keyframes pop { from { opacity:0; transform:translate(-50%, 10px); } to { opacity:1; transform:translate(-50%, 0); } }
.no-results { display:none; }
body.searching .no-results.on { display:block; }

/* Phone and narrow windows: a slim top bar with search, and the sections as a tab bar at the bottom. */
@media (max-width:900px) {
  body { padding-left:0; padding-bottom:calc(72px + env(safe-area-inset-bottom)); }
  .side { position:sticky; top:0; inset:auto; width:auto; flex-direction:row; align-items:center; gap:12px; padding:12px 24px;
    border-right:0; overflow:visible; background:color-mix(in srgb, var(--paper) 94%, transparent);
    backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); }
  .side-nav, .tally, .keys, .search kbd { display:none; }
  .search { flex:1; max-width:340px; margin-left:auto; }
  .side-foot { margin:0; }
  .theme-toggle span { display:none; } .pill { padding:0 10px; }
  main { width:calc(100% - 48px); padding-top:28px; }
  .group, .sep { scroll-margin-top:124px; }
  .bottom { display:grid; grid-template-columns:repeat(4, 1fr); position:fixed; left:0; right:0; bottom:0; z-index:45;
    padding:6px 8px calc(6px + env(safe-area-inset-bottom)); background:var(--paper-2); border-top:1px solid var(--line); }
  .bottom a { position:relative; display:flex; flex-direction:column; align-items:center; gap:3px; padding:6px 0; border-radius:10px;
    text-decoration:none; color:var(--muted); font:500 12px var(--sans); }
  .bottom a.active { color:var(--ink); background:var(--paper); }
  .bottom a b { position:absolute; top:2px; left:calc(50% + 6px); min-width:18px; padding:0 5px; border-radius:999px;
    background:var(--ink); color:var(--paper); font:600 10px/16px var(--mono); text-align:center; }
  .chips { display:flex; gap:8px; overflow-x:auto; scrollbar-width:none; margin:-18px 0 24px; padding-bottom:2px;
    position:sticky; top:62px; z-index:5; background:var(--paper); padding-top:8px; }
  .chips a { flex:none; display:flex; gap:7px; align-items:center; height:32px; padding:0 13px; border-radius:999px;
    border:1px solid var(--line); text-decoration:none; font-size:13px; color:var(--ink-2); }
  .chips a span { font:500 11px var(--mono); color:var(--muted); }
  .chips a.here { background:var(--ink); color:var(--paper); border-color:var(--ink); }
  .chips a.here span { color:var(--paper); }
  .row { grid-template-columns:1fr auto; }
  .row-main { grid-column:1 / -1; }
  .toast { bottom:calc(84px + env(safe-area-inset-bottom)); }
}
@media (max-width:520px) {
  .frame { display:none; }
  .side { padding:10px 16px; }
  main { width:calc(100% - 32px); }
  .card { padding:20px; }
  h3 { font-size:22px; }
}
@media (prefers-reduced-motion: reduce) { .panel.show, .leaves .leaf, .caught-up .leaf, .toast { animation:none; } }
"""

JS = r"""
const DEFAULT = document.body.dataset.default;
const tabs = [...document.querySelectorAll(".side-link")];  // the four sections, in order (keys 1-4)
const navLinks = [...document.querySelectorAll("a[data-tab]:not([data-jump])")];
const q = document.getElementById("q");
const post = (path, body) => fetch(path, { method: "POST",
  headers: { "Content-Type": "application/json", "X-Employmint": "1" }, body: JSON.stringify(body || {}) });

// Tabs: the URL hash picks the tab, so a reload after a decision keeps you where you were.
const current = () => { const k = location.hash.slice(1); return k === "applied" ? "sent" : k; };  // old links still work
function show(key) {
  if (!document.getElementById("panel-" + key)) key = DEFAULT;
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("show", p.dataset.tab === key));
  navLinks.forEach(a => a.classList.toggle("active", a.dataset.tab === key));
  document.querySelectorAll(".side-sub").forEach(d => d.classList.toggle("open", d.dataset.for === key));
  document.body.classList.toggle("on-review", key === "review" && !!document.querySelector("#panel-review .card [data-d=approve]"));
  spy(key);
}
window.addEventListener("hashchange", () => {
  if (q.value) { q.value = ""; q.dispatchEvent(new Event("input")); }
  show(current()); window.scrollTo({ top: 0 });
});

// Group links (sidebar and phone chips): open the section, then scroll to that group.
document.addEventListener("click", ev => {
  const a = ev.target.closest("a[data-jump]");
  if (!a) return;
  ev.preventDefault();
  if (current() !== a.dataset.tab) {  // switch section without the hashchange scroll-to-top
    if (q.value) { q.value = ""; q.dispatchEvent(new Event("input")); }
    history.pushState(null, "", "#" + a.dataset.tab);
    show(a.dataset.tab);
  }
  const reduce = document.hidden || matchMedia("(prefers-reduced-motion: reduce)").matches;
  const target = document.getElementById(a.dataset.jump);
  if (!target) return;
  mark(a.dataset.jump);
  target.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
  // Backstop: if the smooth scroll didn't get there (some browsers skip it), jump straight to the group.
  setTimeout(() => { if (Math.abs(target.getBoundingClientRect().top) > 140) target.scrollIntoView(); }, 700);
});
window.addEventListener("popstate", () => show(current() || DEFAULT));

// Marks the group you're looking at, in the sidebar and in the chips.
let observer;
const mark = id => document.querySelectorAll("a[data-jump]").forEach(a => a.classList.toggle("here", a.dataset.jump === id));
function spy(key) {
  observer?.disconnect();
  const groups = [...document.querySelectorAll(`#panel-${key} .group[id], #panel-${key} .sep[id]`)];
  mark(groups[0]?.id);
  if (!groups.length || !("IntersectionObserver" in window)) return;
  observer = new IntersectionObserver(entries => {
    const top = groups.filter(g => g.getBoundingClientRect().top < innerHeight * 0.4).pop() || groups[0];
    mark(top.id);
    // Slide the chip row sideways only: scrollIntoView here would cancel a smooth page scroll that's under way.
    const chip = document.querySelector(`#panel-${key} .chips a.here`);
    if (chip) chip.parentElement.scrollTo({ left: chip.offsetLeft - 16, behavior: "smooth" });
  }, { rootMargin: "0px 0px -55% 0px", threshold: [0, 1] });
  groups.forEach(g => observer.observe(g));
}
show(current() || DEFAULT);

// After an action the page reloads; come back to the same place instead of the top.
try {
  const at = JSON.parse(sessionStorage.getItem("em-scroll") || "null");
  sessionStorage.removeItem("em-scroll");
  if (at && at.tab === (current() || DEFAULT)) requestAnimationFrame(() => window.scrollTo(0, at.y));
} catch (e) {}
function reloadHere() {
  try { sessionStorage.setItem("em-scroll", JSON.stringify({ tab: current() || DEFAULT, y: scrollY })); } catch (e) {}
  location.reload();
}

// Search: matches across every tab.
q.addEventListener("input", () => {
  const term = q.value.trim().toLowerCase();
  document.body.classList.toggle("searching", !!term);
  let hits = 0;
  document.querySelectorAll(".panel").forEach(p => {
    let n = 0;
    p.querySelectorAll(".card, .row").forEach(c => {
      const ok = !term || c.textContent.toLowerCase().includes(term);
      c.style.display = ok ? "" : "none"; if (ok) n++;
    });
    p.querySelectorAll(".group").forEach(g => g.style.display = [...g.querySelectorAll(".row")].some(r => r.style.display !== "none") ? "" : "none");
    p.querySelectorAll(".start, .aside, .sep, .empty").forEach(x => x.style.display = term ? "none" : "");
    if (term) p.classList.toggle("show", n > 0);
    hits += n;
  });
  document.querySelector(".no-results").classList.toggle("on", !hits);
  if (!term) show(current() || DEFAULT);
});
document.addEventListener("keydown", ev => {
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
  if (ev.key === "Escape" && document.activeElement === q) { q.value = ""; q.dispatchEvent(new Event("input")); q.blur(); }
  if (typing || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  if (ev.key === "/") { ev.preventDefault(); q.focus(); }
  if (ev.key >= "1" && ev.key <= String(tabs.length)) location.hash = tabs[+ev.key - 1].dataset.tab;
  // A / S act on the top card of Review, the one outlined.
  const top = document.querySelector("#panel-review.show .card [data-d=approve]")?.closest(".card");
  if (top && (ev.key === "a" || ev.key === "s")) top.querySelector(`[data-d=${ev.key === "a" ? "approve" : "skip"}]`).click();
});

// Darkroom: remembered on this computer.
document.querySelector(".theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("employmint-theme", root.dataset.theme); } catch (e) {}
});

// Reload when a posting check finishes or recruiter outreach changes in the background.
(() => {
  let v = null;
  setInterval(async () => {
    try {
      const t = await (await fetch("/outreach-version")).text();
      if (v !== null && t !== v && !document.querySelector("textarea.msg:focus")) reloadHere();
      v = t;
    } catch (_) {}
  }, 5000);
})();

document.addEventListener("click", ev => {
  document.querySelectorAll("details.menu[open]").forEach(m => { if (!m.contains(ev.target)) m.open = false; });
});
// After a decision the page reloads; this note survives it and offers Undo where there is one.
const UNDO = { approve: "undo", skip: "undo", applied: "undo", rejected: "unreject" };
const DONE = { approve: "Approved {co}. It's waiting in Apply.", skip: "Skipped {co}.", applied: "Marked {co} as applied.",
  assessment: "Nice. {co} sent a coding test.", interview: "{co} wants to talk. Good luck!", offer: "An offer from {co}!",
  rejected: "Recorded the rejection from {co}. On to the next.", reopen: "{co} is back in Apply.", undo: "Undone.",
  unreject: "{co} is back in Sent." };
function remember(id, d, co) {
  try { sessionStorage.setItem("em-toast", JSON.stringify({ id, d, text: (DONE[d] || "Saved.").replace("{co}", co) })); } catch (e) {}
}
(() => {
  let t; try { t = JSON.parse(sessionStorage.getItem("em-toast")); sessionStorage.removeItem("em-toast"); } catch (e) {}
  if (!t) return;
  const box = document.querySelector(".toast");
  box.textContent = t.text;
  if (UNDO[t.d]) {
    const u = document.createElement("button"); u.textContent = "Undo";
    u.onclick = async () => { u.disabled = true; const r = await post("/decide", { id: t.id, decision: UNDO[t.d] });
      if (r.ok) { remember(t.id, "undo", ""); reloadHere(); } else box.textContent = await r.text(); };
    box.append(u);
  }
  box.hidden = false;
  setTimeout(() => box.hidden = true, 6000);
})();

function say(after, text) {
  after.parentElement.querySelector(".said")?.remove();
  const p = document.createElement("p"); p.className = "aside said"; p.textContent = text;
  after.after(p);
}

document.addEventListener("click", async ev => {
  const b = ev.target.closest("button");
  if (!b || b.disabled) return;

  if ("group" in b.dataset) {  // apply queue
    const box = b.closest(".start"); box.querySelectorAll("button").forEach(x => x.disabled = true);
    const res = await post("/queue", { group: b.dataset.group || null });
    say(box.lastElementChild, res.ok ? "Chrome is opening your first application. Check it, click Submit, and the next one follows. Use the panel in Chrome to skip or stop."
                                     : await res.text());
    return;
  }
  if (b.id === "check-live") {
    b.disabled = true; b.textContent = "Checking postings…";
    await fetch("/live", { method: "POST", headers: { "X-Employmint": "1" } });
    return;
  }
  if (b.dataset.url) {  // recruiter outreach
    const card = b.closest(".card, .row"); card.querySelectorAll("button").forEach(x => x.disabled = true);
    const box = card.querySelector("textarea.msg");
    const res = await post("/outreach", { url: b.dataset.url, decision: b.dataset.o, message: box ? box.value : null });
    if (res.ok) reloadHere(); else { alert("Could not save: " + await res.text()); card.querySelectorAll("button").forEach(x => x.disabled = false); }
    return;
  }
  if (b.dataset.id) {  // a job decision
    const scope = b.closest(".card, .row"); const btns = scope.querySelectorAll("button[data-id]");
    btns.forEach(x => x.disabled = true);
    const res = await post("/decide", { id: b.dataset.id, decision: b.dataset.d });
    if (res.ok && b.dataset.d === "open") {
      b.textContent = "Opening in Chrome…";
      setTimeout(() => { btns.forEach(x => x.disabled = false); b.textContent = "Open"; }, 4000);
    } else if (res.ok) { remember(b.dataset.id, b.dataset.d, scope.dataset.co || "it"); reloadHere(); }
    else if (b.dataset.d === "open") { alert(await res.text()); reloadHere(); }
    else { alert("Could not save: " + await res.text()); btns.forEach(x => x.disabled = false); }
  }
});
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def job(self, db, qs):
        jid = parse_qs(qs).get("id", [""])[0]
        return db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()

    def trusted(self):
        """Blocks DNS rebinding: a hostile site whose domain points at 127.0.0.1 still sends its own Host
        header, so only requests addressed to this server by its local name get through."""
        port = self.server.server_address[1]
        ok = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return self.headers.get("Host") in ok and (origin is None or origin.split("//", 1)[-1] in ok)

    def do_GET(self):
        if not self.trusted():
            return self.send(403, "forbidden", "text/plain")
        u = urlparse(self.path)
        db = db_connect()
        try:
            if u.path == "/":
                return self.send(200, page(db))
            if u.path == "/outreach-version":
                try:
                    mtime = outreach.OUTREACH.stat().st_mtime_ns
                except OSError:
                    mtime = 0
                return self.send(200, f"{mtime}-{LIVE['stamp']}-{int(LIVE['running'])}", "text/plain")
            if u.path == "/pdf":
                r = self.job(db, u.query)
                if not r or not r["resume_dir"]:
                    return self.send(404, "not found", "text/plain")
                doc = parse_qs(u.query).get("doc", [""])[0]
                name = me.cover_name(me.profile()) if doc == "cover" else me.resume_name(me.profile())
                pdf = (ROOT / r["resume_dir"] / name).resolve()
                if RESUMES not in pdf.parents or not pdf.exists():
                    return self.send(404, "not found", "text/plain")
                return self.send(200, pdf.read_bytes(), "application/pdf")
            if u.path == "/jd":
                r = self.job(db, u.query)
                p = jd_file(r["id"]) if r else None
                if not p or not p.exists():
                    return self.send(404, "not found", "text/plain")
                return self.send(200, p.read_text(encoding="utf-8"), "text/plain; charset=utf-8")
            return self.send(404, "not found", "text/plain")
        finally:
            db.close()

    def open_application(self, r):
        """Starts apply.py in a visible Chrome window. It fills the form and waits; the applicant submits."""
        running = APPLYING.get(r["id"])
        if running and running.poll() is None:
            return self.send(409, "That application is already open in Chrome.", "text/plain")
        ok, reason = live.ensure_open(r["id"])
        if not ok:
            return self.send(409, f"This posting looks closed ({reason}), so it moved to Archive > Closed. "
                                  "If it's still open, use \"It's still open\" there.", "text/plain")
        logs = ROOT / "data" / "apply-logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = open(logs / (Path(r["resume_dir"] or "job").name + ".log"), "a")
        APPLYING[r["id"]] = subprocess.Popen(
            [sys.executable, str(ROOT / "src" / "apply.py"), "open", r["id"]],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()  # the child keeps its own copy
        return self.send(200, '{"ok":true,"opened":true}', "application/json")

    def start_queue(self):
        """Starts apply.py queue: one Chrome window that walks through approved and new tailored jobs. The applicant submits each."""
        running = APPLYING.get("__queue__")
        if running and running.poll() is None:
            return self.send(409, "The apply queue is already open in Chrome.", "text/plain")
        try:
            group = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}").get("group")
        except ValueError:
            return self.send(400, "bad request", "text/plain")
        if group is not None and group not in GROUPS:
            return self.send(400, "unknown group", "text/plain")
        logs = ROOT / "data" / "apply-logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = open(logs / "queue.log", "a")
        APPLYING["__queue__"] = subprocess.Popen(
            [sys.executable, str(ROOT / "src" / "apply.py"), "queue"] + (["--group", group] if group else []),
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()  # the child keeps its own copy
        return self.send(200, '{"ok":true}', "application/json")

    def decide_outreach(self):
        """Approve, skip or undo one drafted recruiter. Only changes status (and the message on approve)."""
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            url, decision, message = body["url"], body["decision"], body.get("message")
        except (ValueError, KeyError):
            return self.send(400, "bad request", "text/plain")
        with outreach.editing() as data:
            x = next((p for p in data.get("people", []) if p.get("url") == url), None)
            if not x:
                return self.send(404, "no such recruiter", "text/plain")
            status = x.get("status")
            if decision == "approve" and status == "drafted":
                if isinstance(message, str) and message.strip():
                    x["message"] = message.strip()
                x["status"], x["approved_at"] = "approved", now_iso()
            elif decision == "skip" and status == "drafted":
                x["status"] = "skipped"
            elif decision == "undo" and status == "skipped":
                x["status"] = "drafted"
            else:
                return self.send(409, f"can't {decision} a recruiter that is '{status}'", "text/plain")
        if decision == "approve":
            outreach.start_invites()  # sends the connection request right away
        return self.send(200, '{"ok":true}', "application/json")

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.trusted() or self.headers.get("X-Employmint") != "1" or path not in ("/decide", "/queue", "/outreach", "/live"):
            return self.send(403, "forbidden", "text/plain")
        if path == "/queue":
            return self.start_queue()
        if path == "/live":
            started = start_live_check()
            return self.send(200 if started else 409, '{"ok":true}' if started else "Already checking.",
                             "application/json" if started else "text/plain")
        if path == "/outreach":
            return self.decide_outreach()
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            jid, decision = body["id"], body["decision"]
        except (ValueError, KeyError):
            return self.send(400, "bad request", "text/plain")
        db = db_connect()
        try:
            r = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            if not r:
                return self.send(404, "no such job", "text/plain")
            if decision == "approve" and r["app_status"] == "tailored":
                db.execute("UPDATE jobs SET app_status='approved', decided_at=? WHERE id=?", (now_iso(), jid))
            elif decision == "skip" and r["app_status"] in ("tailored", "queued"):
                db.execute("UPDATE jobs SET app_status='skip', decided_at=? WHERE id=?", (now_iso(), jid))
            elif decision == "open" and r["app_status"] in ("approved", "tailored"):
                return self.open_application(r)
            elif decision == "applied" and r["app_status"] == "approved":
                db.execute("UPDATE jobs SET app_status='applied', decided_at=? WHERE id=?", (now_iso(), jid))
                db.commit()
                outreach.draft_for_new_applications()
            elif decision == "reopen" and r["app_status"] == "closed":
                db.execute("UPDATE jobs SET app_status='approved', live_state=?, decided_at=? WHERE id=?",
                           (live.USER_OPEN, now_iso(), jid))
            elif decision in ("assessment", "interview", "offer", "rejected") and r["app_status"] in OUTCOMES[:-1] + (
                    ["offer"] if decision == "rejected" else []):
                db.execute("UPDATE jobs SET app_status=?, decided_at=? WHERE id=?", (decision, now_iso(), jid))
            elif decision == "unreject" and r["app_status"] == "rejected":
                db.execute("UPDATE jobs SET app_status='applied', decided_at=? WHERE id=?", (now_iso(), jid))
            elif decision == "undo" and r["app_status"] == "applied":
                db.execute("UPDATE jobs SET app_status='approved', decided_at=? WHERE id=?", (now_iso(), jid))
            elif decision == "undo" and r["app_status"] in ("approved", "skip"):
                back = "tailored" if r["resume_dir"] else "queued"
                db.execute("UPDATE jobs SET app_status=?, decided_at=NULL WHERE id=?", (back, jid))
            else:
                return self.send(409, f"can't {decision} a job that is '{r['app_status']}'", "text/plain")
            db.commit()
            return self.send(200, '{"ok":true}', "application/json")
        finally:
            db.close()


def start_live_check(max_age_hours=None):
    """Checks approved jobs' postings in the background; closed ones move to Closed. False if one is running."""
    if LIVE["running"]:
        return False
    LIVE["running"] = True

    def run():
        try:
            live.check_statuses(("approved",), max_age_hours)
        except Exception as ex:  # a failed check must not take the review page down
            print(f"WARN: posting check failed: {ex!r}", file=sys.stderr, flush=True)
        finally:
            LIVE["running"] = False
            LIVE["stamp"] += 1
    threading.Thread(target=run, daemon=True).start()
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Review page: {url}  (Ctrl+C to stop)")
    start_live_check(max_age_hours=12)  # approved jobs not checked in the last 12 hours
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
