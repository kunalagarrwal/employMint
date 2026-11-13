"""Opens a job application, fills it from the applicant's profile, and stops before Submit.

This script never clicks Submit. The applicant reads the filled form, fixes anything,
and submits it themselves. When a confirmation page appears, the job is marked
'applied'.

Works best on Greenhouse, Ashby and Lever forms. Other sites (Workday, company
career pages) open normally; use `sheet` for copy-paste answers.

Usage:
  python3 src/apply.py scan  <job id>          # headless: list the form's questions and how each will be answered
  python3 src/apply.py open  <job id> [--force] # visible Chrome: fill, highlight, wait for you to submit
  python3 src/apply.py sheet <job id>          # print copy-paste answers for any site
  python3 src/apply.py try   <job id>          # hidden test fill + screenshot, then discard (never submits)
  python3 src/apply.py queue [--limit N] [--group quick|workday|manual]
                                               # go through waiting jobs in one window; Submit is your yes

Before a form opens, the posting is checked (src/live.py). A closed one moves to 'closed' instead of opening.

Colors on the page: green = filled from your profile, blue = drafted for this job
(read it), amber = filled but check it, red = you need to answer.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jobs import ROOT, db_connect, now_iso  # noqa: E402
from formjs import BANNER_JS, EXTRACT_JS, PANEL_JS, READ_JS  # noqa: E402,F401
from answers import job_values, label_matches, load_job_answers, load_remembered, load_rules, merge_lone_options, norm, pick_option, resolve, resume_path, search_term, sheet_answer  # noqa: E402,F401
from page_tools import CONFIRM_TEXT, CONFIRM_URL, LAST_PANEL, launch_browser, settle, submitted  # noqa: E402,F401
from fill import fill_form, summarize  # noqa: E402,F401
import answers  # noqa: E402
import me  # noqa: E402
from site_workday import workday_flow  # noqa: E402,F401
from site_lever import lever_handoff, lever_sheet_html  # noqa: E402,F401

AUTOFILL_SITES = ("greenhouse", "ashby", "lever")
# How much of the work employMint does, per site. The review page and the queue group approved jobs by this.
GROUPS = {"quick": ("greenhouse", "ashby"), "workday": ("workday",), "manual": ("lever", "smartrecruiters", "other")}

def form_url(url):
    base = url.split("?")[0].rstrip("/")
    if "jobs.ashbyhq.com" in url:
        return base if base.endswith("/application") else base + "/application"
    if "jobs.lever.co" in url:
        return base if base.endswith("/apply") else base + "/apply"
    m = re.search(r"boards\.greenhouse\.io/(?!embed)([^/]+)/jobs/(\d+)", url)
    if m:
        return f"https://job-boards.greenhouse.io/{m.group(1)}/jobs/{m.group(2)}"
    m = re.search(r"[?&]gh_jid=(\d+)", url)
    if m:
        return f"https://boards.greenhouse.io/embed/job_app?token={m.group(1)}"
    return url

def site_of(url):
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    for domain, name in (("greenhouse.io", "greenhouse"), ("ashbyhq.com", "ashby"), ("lever.co", "lever"),
                         ("myworkdayjobs.com", "workday"), ("smartrecruiters.com", "smartrecruiters")):
        if host == domain or host.endswith("." + domain):
            return name
    if "gh_jid=" in url:  # Greenhouse embedded on a company careers page
        return "greenhouse"
    return "other"

def group_of(url):
    site = site_of(form_url(url))
    return next(g for g, sites in GROUPS.items() if site in sites or g == "manual")

def get_job(db, job_id):
    r = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        raise LookupError(f"No job with id {job_id}")
    return r

def mark_applied(job_id, final_url):
    db = db_connect()
    try:
        job = get_job(db, job_id)
        db.execute("UPDATE jobs SET app_status='applied', decided_at=? WHERE id=?", (now_iso(), job_id))
        db.commit()
        if job["resume_dir"]:
            try:
                (ROOT / job["resume_dir"] / "applied.json").write_text(
                    json.dumps({"applied_at": now_iso(), "confirmation_url": final_url}, indent=2))
            except OSError as ex:
                print(f"WARN: marked applied, but couldn't write applied.json: {ex}", file=sys.stderr, flush=True)
    finally:
        db.close()
    start_recruiter_drafts()

def mark_passed(job_id):
    """The applicant chose "Not for me" on the form: the job moves to Skipped (Undo on the review page)."""
    db = db_connect()
    try:
        db.execute("UPDATE jobs SET app_status='skip', decided_at=? WHERE id=? AND app_status IN ('tailored','approved')",
                   (now_iso(), job_id))
        db.commit()
    finally:
        db.close()

def review_of(job):
    """Fit, why and gaps from the tailored resume, shown at the top of the form panel."""
    try:
        rv = json.loads((ROOT / job["resume_dir"] / "tailored.json").read_text()).get("review", {})
    except (TypeError, OSError, ValueError):
        rv = {}
    fit = rv.get("fit", job["fit"])
    return {"fit": fit, "why": rv.get("why", ""), "gaps": list(rv.get("gaps") or [])[:3]}

def capture_remembered(page, action, panel):
    """Reads what the applicant entered in the questions they ticked "Remember my answer" (saved once they submit).
    Ticks arrive by field number, which Workday reuses on its next step, so they are turned into question titles."""
    if not panel:
        return
    items = [it for it in panel[0] if it.get("remember")]
    by_i = {it["i"]: it for it in items}
    wanted = action.setdefault("remember_titles", {})
    for i, on in (action.pop("remember", None) or {}).items():
        if i in by_i:
            wanted[by_i[i]["title"]] = on
    captured = action.setdefault("captured", {})
    for t, on in wanted.items():
        if not on:
            captured.pop(t, None)
    for it in items:
        it["on"] = bool(wanted.get(it["title"]))  # keeps the box ticked if the panel is drawn again
    want = [it for it in items if it["on"]]
    if not want:
        return
    for it, got in zip(want, page.evaluate(READ_JS, [it["i"] for it in want])):
        # Only trust a value still inside the same question (the page may have moved on).
        if got and got.get("value") and norm(it["title"])[:40] in norm(got.get("text")):
            captured[it["title"]] = {"title": it["title"], "field": it["kind"], "value": got["value"]}

def save_remembered(action, company):
    entries = list((action.pop("captured", None) or {}).values())
    action.pop("remember", None)
    action.pop("remember_titles", None)
    if not entries:
        return
    try:
        n = answers.remember(entries, company)
        if n:
            print(f"  Saved {n} answer{'s' if n != 1 else ''} to reuse on later forms (profile/remembered.json)", flush=True)
    except OSError as ex:
        print(f"WARN: couldn't save remembered answers: {ex}", file=sys.stderr, flush=True)

def start_recruiter_drafts():
    """Finds LinkedIn recruiters for the new application in the background (they show up on the review page)."""
    try:
        import outreach
        outreach.draft_for_new_applications()
    except Exception as ex:  # never block the apply flow
        import traceback
        print(f"WARN: couldn't start recruiter search: {ex!r}", file=sys.stderr, flush=True)
        traceback.print_exc()

def cmd_scan(job):
    from playwright.sync_api import sync_playwright
    url = form_url(job["url"])
    rules, values = load_rules()
    values = job_values(job, values)
    job_answers = load_job_answers(job["resume_dir"])
    remembered = load_remembered()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)
        qs = [q for q in page.evaluate(EXTRACT_JS) if q["visible"]]
        browser.close()
    rows = []
    for q in qs:
        ans = resolve(q, rules, values, job_answers, remembered)
        if ans is None:
            status = "NEEDS ANSWER" if q["required"] else "optional, left blank"
        elif ans.get("flag") and not ans.get("a") and not ans.get("text"):
            status = "you: " + ans["flag"]
        elif ans["src"] == "job":
            status = "job answer"
        elif ans["src"] == "remembered":
            status = "remembered (check)"
        else:
            status = "profile" + (" (check)" if ans.get("flag") else "")
        preview = (ans or {}).get("text") or ", ".join((ans or {}).get("a") or [])
        rows.append({"label": q["title"], "kind": q["kind"], "required": q["required"], "options": q["options"][:15],
                     "status": status, "answer": (preview or "")[:120]})
    print(f"{job['company']} · {job['title']}\n{url}  ({site_of(url)}, {len(rows)} questions)\n")
    for r in rows:
        shown = f"  [{r['answer'][:50]}]" if r["answer"] and r["status"].startswith(("profile", "job", "remembered")) else ""
        print(f"{'*' if r['required'] else ' '} [{r['kind']:8}] {r['label'][:70]:70}  -> {r['status']}{shown}")
    if job["resume_dir"]:
        out = ROOT / job["resume_dir"] / "questions.json"
        out.write_text(json.dumps({"url": url, "scanned_at": now_iso(), "questions": rows}, indent=2))
        print(f"\nSaved {out.relative_to(ROOT)}")

def manual_items(job, site, resume):
    """Copy-paste answers shown in the panel for sites that aren't auto-filled (Workday etc.)."""
    _, v = load_rules()
    v = job_values(job, v)
    rows = [("Resume file", str(resume))] + ([("Cover letter file", v["cover"])] if v["cover"] else []) + \
           ([("Transcript file", v["transcript"])] if v["transcript"] else []) + [("Name", v["full_name"]), ("Email", v["email"]), ("Phone", v["phone"]),
            ("LinkedIn", v["linkedin"]), ("School", v["school"]), ("Degree", f"{v['degree']}, {v['major']}"),
            ("GPA / Graduation", f"{v['gpa']} / {v['grad']}")] + me.work_auth_rows(me.profile())
    rows += [(ja["q"][:60], ja.get("a") or ", ".join(ja.get("pick") or []) or ja.get("flag", ""))
             for ja in load_job_answers(job["resume_dir"])]
    head = {"i": -1, "title": f"{site.title()} form: not auto-filled",
            "state": "you", "note": "Create an account or sign in yourself if asked, then copy these answers."}
    return [head] + [{"i": -1, "title": k, "state": "check", "note": val} for k, val in rows]

GENERIC_APPLY = re.compile(r"^(apply|apply now|apply for this (job|position|role)( online)?|i'?m interested|start (your )?application|apply online)$", re.I)

def click_generic_apply(page):
    """Many company sites show the description first, with an Apply button that opens the form."""
    if page.locator("input:visible, textarea:visible, select:visible").count() >= 4:
        return False
    for el in page.locator("a:visible, button:visible").all()[:300]:
        try:
            if GENERIC_APPLY.match((el.inner_text() or "").strip()):
                el.click()
                settle(page, 2000)
                return True
        except Exception:
            continue
    return False

def prepare(page, job, queue=None, action=None):
    """Opens the job's form, fills it, and shows the panel. Returns the panel arguments (to re-show it later)."""
    action = action if action is not None else {}
    action.pop("helpers", None)
    resume = resume_path(job)
    url = form_url(job["url"])
    site = site_of(url)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    settle(page)
    if site == "workday":
        panel = workday_flow(page, job, queue, action)
        print(f"Opened {job['company']} · {job['title']} (workday)", flush=True)
        return panel
    if site == "lever":
        return lever_handoff(page, job, url, queue, action)
    if site not in AUTOFILL_SITES:
        click_generic_apply(page)
    results = fill_form(page, job, resume)
    filled, items = summarize(results)
    if site not in AUTOFILL_SITES:
        items = items + manual_items(job, site, resume)[1:]  # copy-paste sheet for whatever didn't fill
    panel = [items, filled, f"{job['company']} · {job['title']}", queue]
    LAST_PANEL["panel"] = panel
    page.evaluate(PANEL_JS, panel)
    page.evaluate("() => window.scrollTo(0, 0)")
    print(f"Opened {job['company']} · {job['title']} ({site}): {filled} filled, "
          f"{sum(1 for it in items if it['state'] == 'you')} for you to answer", flush=True)
    return panel

def wait_outcome(ctx, action, panel):
    """Waits until the applicant submits (confirmation page) or presses a panel button.
    Returns (outcome, url): outcome is applied / manual / pass / skip / stop / closed."""
    while True:
        try:
            pages = [pg for pg in ctx.pages if not pg.is_closed()]
        except Exception:
            return "closed", None
        if not pages:
            return "closed", None
        if action.get("v"):
            v, action["v"] = action["v"], None
            helper = (action.get("helpers") or {}).get(v)
            if helper:  # Lever sheet buttons: show a file in Finder, reopen the form
                helper()
                continue
            return v, pages[-1].url
        url = submitted(ctx)
        if url:
            return "applied", url
        try:
            pg = pages[0]
            capture_remembered(pg, action, panel)
            if panel and not pg.evaluate("() => !!document.getElementById('employmint-panel')"):
                pg.evaluate(PANEL_JS, panel)  # the site moved to another page (e.g. Workday step 2)
            pg.wait_for_timeout(1500)
        except Exception:
            time.sleep(1)  # page is mid-navigation or was just closed

def cmd_open(job, force):
    from playwright.sync_api import sync_playwright
    if job["app_status"] not in ("approved", "tailored") and not force:
        sys.exit(f"{job['company']} is '{job['app_status']}', not waiting to be applied to (pass --force to open it anyway).")
    if not resume_path(job):
        sys.exit("No resume PDF for this job yet. Tailor it first.")
    if not force:
        import live
        ok, reason = live.ensure_open(job["id"])
        if not ok:
            sys.exit(f"{job['company']} looks closed ({reason}). Moved it to Closed on the review page; "
                     f"use Undo there if it's still open.")
    action = {}
    with sync_playwright() as p:
        ctx = launch_browser(p, action)
        action["tick"] = lambda pg: capture_remembered(pg, action, LAST_PANEL.get("panel"))  # Workday's own waits
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        panel = prepare(page, job, {"review": review_of(job)}, action)
        print("Review the form and click Submit yourself. Waiting for the confirmation page.", flush=True)
        outcome, url = wait_outcome(ctx, action, panel)
        if outcome == "pass":
            mark_passed(job["id"])
            print(f"Not for you: moved {job['company']} to Skipped.")
        if outcome in ("applied", "manual"):
            save_remembered(action, job["company"])
            mark_applied(job["id"], url)
            print(f"Marked {job['company']} as applied ({'confirmation page seen' if outcome == 'applied' else 'you said you submitted'}).")
            try:
                ctx.pages[-1].evaluate(BANNER_JS, "employMint: recorded as applied. You can close this window.")
                ctx.pages[-1].wait_for_event("close", timeout=10 * 60 * 1000)
            except Exception:
                pass
        elif outcome != "pass":
            print("Closed without submitting; status unchanged.")
        try:
            ctx.close()
        except Exception:
            pass

def queue_jobs(limit=None, group=None):
    """Every job waiting to be applied to: approved ones, and tailored ones nobody has decided on yet (the filled
    form is where the applicant decides: Submit is yes, "Not for me" is no). Quickest sites first; within each,
    approved jobs by longest wait, then tailored jobs from the oldest batch (postings close fast)."""
    db = db_connect()
    try:
        rows = db.execute("SELECT * FROM jobs WHERE app_status IN ('approved','tailored') AND fit IS NOT NULL "
                          "ORDER BY app_status != 'approved', decided_at, batch_date, fit DESC, score DESC").fetchall()
    finally:
        db.close()
    jobs = [r for r in rows if resume_path(r) and (group is None or group_of(r["url"]) == group)]
    order = list(GROUPS)
    jobs.sort(key=lambda r: order.index(group_of(r["url"])))  # stable: keeps oldest-first inside a group
    return jobs[:limit] if limit else jobs

def cmd_queue(limit=None, group=None):
    """Goes through waiting jobs one by one in one Chrome window. The applicant reads each filled form and either
    submits it (yes) or presses "Not for me" (no); the next one opens by itself."""
    from playwright.sync_api import sync_playwright
    import live
    jobs = queue_jobs(limit, group)
    if not jobs:
        print("Nothing in the queue: no tailored or approved jobs with a scored resume.")
        return
    print(f"Queue: {len(jobs)} jobs to apply to.", flush=True)
    done, skipped, closed, passed = [], [], [], []
    action = {}
    with sync_playwright() as p:
        ctx = launch_browser(p, action)
        action["tick"] = lambda pg: capture_remembered(pg, action, LAST_PANEL.get("panel"))  # Workday's own waits
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for n, job in enumerate(jobs, 1):
            action["v"] = None
            for k in ("remember", "remember_titles", "captured"):
                action.pop(k, None)
            ok, reason = live.ensure_open(job["id"])
            if not ok:
                closed.append(job["company"])
                print(f"  Closed, not opened: {job['company']} ({reason})", flush=True)
                continue
            try:
                page = next((pg for pg in ctx.pages if not pg.is_closed()), None) or ctx.new_page()
                panel = prepare(page, job, {"pos": n, "total": len(jobs), "review": review_of(job)}, action)
            except Exception as ex:
                if not any(not pg.is_closed() for pg in ctx.pages):
                    print("Chrome was closed; stopping the queue.", flush=True)
                    break
                print(f"Couldn't open {job['company']} ({type(ex).__name__}: {str(ex)[:120]}); skipping it.", flush=True)
                skipped.append(job["company"])
                continue
            outcome, url = wait_outcome(ctx, action, panel)
            if outcome in ("applied", "manual"):
                save_remembered(action, job["company"])
                try:
                    mark_applied(job["id"], url)
                except Exception as ex:
                    print(f"FAILED to record {job['company']} as applied ({ex!r}). Mark it on the review page.",
                          file=sys.stderr, flush=True)
                done.append(job["company"])
                print(f"  Applied: {job['company']}", flush=True)
                try:
                    ctx.pages[-1].evaluate(BANNER_JS, f"Recorded {job['company']} as applied. Opening the next one…")
                    ctx.pages[-1].wait_for_timeout(2500)
                except Exception:
                    pass
            elif outcome == "pass":
                mark_passed(job["id"])
                passed.append(job["company"])
                print(f"  Not for you: {job['company']}", flush=True)
            elif outcome == "skip":
                skipped.append(job["company"])
                print(f"  Skipped for now: {job['company']}", flush=True)
            else:
                break  # stop or window closed
        print(f"Queue finished: {len(done)} applied ({', '.join(done) or 'none'}), "
              f"{len(passed)} not for you ({', '.join(passed) or 'none'}), "
              f"{len(skipped)} left for later ({', '.join(skipped) or 'none'}), "
              f"{len(closed)} already closed ({', '.join(closed) or 'none'}).", flush=True)
        try:
            pg = next(pg for pg in ctx.pages if not pg.is_closed())
            pg.evaluate(BANNER_JS, f"Queue done: {len(done)} applied, {len(passed)} not for you, {len(skipped)} for later, "
                                   f"{len(closed)} already closed. "
                                   "You can close this window.")
            pg.wait_for_event("close", timeout=10 * 60 * 1000)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass

def cmd_try(job):
    """Fills the form in a hidden browser, saves a full-page screenshot, then throws everything away.
    For checking how well a form fills without opening a window. Never submits."""
    from playwright.sync_api import sync_playwright
    url = form_url(job["url"])
    resume = resume_path(job)
    out_dir = ROOT / "data" / "apply-logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / (re.sub(r"[^a-z0-9]+", "-", job["company"].lower()) + "-try.png")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1500)
        results = fill_form(page, job, resume)
        filled, items = summarize(results)
        page.evaluate(PANEL_JS, [items, filled, job["company"], None])
        page.screenshot(path=str(shot), full_page=True)
        browser.close()
    print(f"{job['company']}: {filled} filled, {len(items)} to look at")
    for r in results:
        print(f"  {r['state']:8} [{r['kind']:8}] {r['title'][:60]:60} {r['note'][:70]}")
    print(f"Screenshot: {shot}")

def cmd_sheet(job):
    _, values = load_rules()
    resume = resume_path(job)
    print(f"{job['company']} · {job['title']}\nApply at: {form_url(job['url'])}\nResume: {resume or '(not tailored yet)'}\n")
    for k in ("full_name", "email", "phone", "linkedin", "github", "location", "school", "degree", "major", "minor", "gpa", "grad"):
        print(f"  {k:10} {values[k]}")
    print()
    for label, answer in me.work_auth_rows(me.profile()):
        print(f"  {label:38} {answer}")
    print(f"  {'Visa type':38} {me.visa_type(me.profile())}")
    print(f"  How did you hear about us?             {values['heard_from']}")
    print("  Demographic questions                  Decline to self-identify (or your choice)")
    for ja in load_job_answers(job["resume_dir"]):
        print(f"\n  Q: {ja['q']}\n  A: {ja.get('a') or ', '.join(ja.get('pick') or [])}")

def main():
    ap = argparse.ArgumentParser(description="Fill a job application and stop before Submit.")
    ap.add_argument("command", choices=["scan", "open", "sheet", "try", "queue"])
    ap.add_argument("job_id", nargs="?")
    ap.add_argument("--force", action="store_true", help="open even if the job isn't approved yet")
    ap.add_argument("--limit", type=int, help="queue: stop after this many jobs")
    ap.add_argument("--group", choices=list(GROUPS), help="queue: only quick (auto-filled), workday or manual sites")
    args = ap.parse_args()
    if args.command == "queue":
        return cmd_queue(args.limit, args.group)
    if not args.job_id:
        ap.error("job_id is required")
    db = db_connect()
    try:
        job = get_job(db, args.job_id)
    finally:
        db.close()
    if args.command == "scan":
        cmd_scan(job)
    elif args.command == "open":
        cmd_open(job, args.force)
    elif args.command == "try":
        cmd_try(job)
    else:
        cmd_sheet(job)

if __name__ == "__main__":
    main()
