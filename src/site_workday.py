"""Workday: a multi-step wizard. Signs-in handoff, resume upload, My Experience entries, then each step
is filled and saved until the Review page, where the applicant submits."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import ROOT  # noqa: E402
from answers import load_rules, pick_option, resume_path  # noqa: E402
from page_tools import settle, show, visible, wait_fields_stable, wait_while  # noqa: E402
from fill import fill_form, summarize  # noqa: E402
import me  # noqa: E402

WD = {
    "apply": '[data-automation-id="adventureButton"]',
    "autofill": '[data-automation-id="autofillWithResume"]',
    "manual": '[data-automation-id="applyManually"]',
    "cookies_decline": '[data-automation-id="legalNoticeDeclineButton"]',
    "password": 'input[data-automation-id="password"]',
    "email": 'input[data-automation-id="email"]',
    "next": '[data-automation-id="pageFooterNextButton"], [data-automation-id="bottom-navigation-next-button"]',
    "step": '[data-automation-id="progressBarActiveStep"]',
    "error": '[data-automation-id="errorMessage"], [data-automation-id="errorBanner"]',
}

def wd_step(page):
    try:
        if visible(page, WD["step"]):
            return page.locator(WD["step"]).first.inner_text().strip()
        return page.locator("h2").first.inner_text().strip()
    except Exception:
        return ""

WD_GROUPS_JS = r"""(section) => {
  // Tag each entry of a My Experience section ("Work Experience 1", "Education 2", ...) so it can be targeted.
  const groups = [...document.querySelectorAll('[role="group"][aria-labelledby]')].filter(g => {
    const h = document.getElementById(g.getAttribute('aria-labelledby'));
    return h && new RegExp('^' + section + ' \\d+$').test(h.innerText.trim());
  });
  groups.forEach((g, i) => g.setAttribute('data-em-g', section + '-' + i));
  return groups.length;
}"""

WD_ADD_JS = r"""(section) => {
  const h = [...document.querySelectorAll('h4, h3')].find(x => x.innerText.trim() === section);
  let s = h;
  while (s && !s.querySelector('[data-automation-id="add-button"]')) s = s.parentElement;
  const b = s && [...s.querySelectorAll('[data-automation-id="add-button"]')].pop();
  if (b) b.click();
  return !!b;
}"""

def wd_entry(page, section, reuse_if):
    """Returns the locator of an entry in a My Experience section: an empty one if there is one, else a new one."""
    n = page.evaluate(WD_GROUPS_JS, section)
    for k in range(n):
        g = page.locator(f'[data-em-g="{section}-{k}"]')
        if reuse_if(g):
            return g
    if not page.evaluate(WD_ADD_JS, section):
        return None
    page.wait_for_timeout(1500)
    n = page.evaluate(WD_GROUPS_JS, section)
    return page.locator(f'[data-em-g="{section}-{n - 1}"]') if n else None

def wd_type(field, value):
    if field.count() and value and field.first.input_value() != value:
        field.first.page.keyboard.press("Escape")
        field.first.click()
        field.first.fill(value)

def wd_date(group, field_id, ym):
    """ym like '2023-09' or '2024'; Workday splits dates into month and year boxes."""
    ff = group.locator(f'[data-automation-id="formField-{field_id}"]')
    y, _, m = ym.partition("-")
    for part, val in (("Month", m), ("Year", y)):
        if not val:
            continue
        box = ff.locator(f'[data-automation-id="dateSection{part}-input"]')
        if not box.count() or box.first.input_value() == val.lstrip("0") or box.first.input_value() == val:
            continue
        shown = ff.locator(f'[data-automation-id="dateSection{part}-display"]')
        (shown.first if shown.count() else box.first).click(force=True)  # the input hides under a "MM"/"YYYY" overlay
        group.page.keyboard.type(val, delay=60)

def wd_pick(page, group, field_id, prefs, term=None):
    """Workday dropdown button or search-and-pick input inside one entry."""
    ff = group.locator(f'[data-automation-id="formField-{field_id}"]')
    btn = ff.locator('button[aria-haspopup="listbox"]')
    if btn.count():
        btn.first.click()
        page.wait_for_timeout(800)
        opts = page.locator('[role="option"]:visible')
        idx = pick_option([t.strip() for t in opts.all_inner_texts()], prefs, None)
        if idx is not None:
            opts.nth(idx).click()
            return True
        page.keyboard.press("Escape")
        return False
    box = ff.locator('input[data-uxi-widget-type="selectinput"]')
    pills = ff.locator('[data-automation-id="selectedItem"]')
    if pills.count() and pick_option(pills.all_inner_texts(), prefs, term) is not None:
        return True  # already set
    ok = False
    if box.count() and term:
        box.first.click()
        box.first.fill(term)
        box.first.press("Enter")
        page.wait_for_timeout(1800)
        if pills.count() and pick_option(pills.all_inner_texts(), prefs, term) is not None:
            ok = True  # Workday picked the only match itself
        else:
            opts = page.locator('[data-automation-id="promptOption"]:visible')
            idx = pick_option([t.strip() for t in opts.all_inner_texts()], prefs, term)
            if idx is not None:
                opts.nth(idx).click()
                page.wait_for_timeout(800)
                ok = True
    wd_close_popups(page)
    return ok

def wd_close_popups(page):
    """Search popups stay open and block later clicks; close them."""
    for _ in range(2):
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    try:
        if page.locator('[data-automation-id="promptOption"]:visible').count():
            page.locator("h3").first.click()
            page.wait_for_timeout(300)
    except Exception:
        pass

def wd_experience(page, job):
    """Fills Workday's My Experience from the profile: one Education entry and the main work entries.
    Descriptions reuse this job's tailored resume bullets so the application matches the resume."""
    if not page.locator('h4:has-text("Work Experience"), h4:has-text("Education")').count():
        return []
    prof = me.profile()
    _, v = load_rules()
    notes = []
    ed = prof["education"][0]
    g = wd_entry(page, "Education", lambda g: True)  # always finish the first education entry; never add a second
    if g is not None:
        wd_type(g.locator('[data-automation-id="formField-schoolName"] input'), v["school"])
        if not wd_pick(page, g, "degree", me.degree_patterns(v["degree"])):
            notes.append(f"Education: pick the Degree ({v['degree']})")
        if g.locator('[data-automation-id="formField-fieldOfStudy"]').count() and \
                not wd_pick(page, g, "fieldOfStudy", me.field_patterns(v["major"]), v["major"]):
            notes.append(f"Education: pick Field of Study ({v['major']})")
        wd_type(g.locator('[data-automation-id="formField-gradeAverage"] input'), v["gpa"])
        if ed.get("start"):
            wd_date(g, "firstYearAttended", ed["start"][:4])
        wd_date(g, "lastYearAttended", v["grad_year"])
    bullets = {}
    t_path = ROOT / (job["resume_dir"] or "") / "tailored.json"
    if job["resume_dir"] and t_path.exists():
        for e in json.loads(t_path.read_text()).get("experience", []):
            bullets[e["id"]] = [b["text"] for b in e["bullets"]]
    ids = me.workday_experience_ids(prof, me.prefs())
    for e in [x for x in prof["experience"] if x["id"] in ids]:
        company = e["org"]
        key = company.split(" (")[0].split(" - ")[0].lower()
        n = page.evaluate(WD_GROUPS_JS, "Work Experience")
        g = next((page.locator(f'[data-em-g="Work Experience-{k}"]') for k in range(n)
                  if key in page.locator(f'[data-em-g="Work Experience-{k}"] [data-automation-id="formField-companyName"] input').first.input_value().lower()), None)
        if g is None:  # not on the page yet (Workday's resume autofill may have added others): reuse an empty entry or add one
            g = wd_entry(page, "Work Experience", lambda g: not g.locator('[data-automation-id="formField-jobTitle"] input').first.input_value())
        if g is None:
            notes.append("Work Experience: add your jobs")
            break
        wd_type(g.locator('[data-automation-id="formField-jobTitle"] input'), e["title"])
        wd_type(g.locator('[data-automation-id="formField-companyName"] input'), company)
        wd_type(g.locator('[data-automation-id="formField-location"] input'), e.get("location", ""))
        wd_date(g, "startDate", e["start"])
        if e["end"] == "present":
            box = g.locator('[data-automation-id="formField-currentlyWorkHere"] input')
            if box.count() and not box.first.is_checked():
                box.first.check(force=True)
        else:
            wd_date(g, "endDate", e["end"])
        text = "\n".join("• " + b for b in (bullets.get(e["id"]) or e["facts"][:4]))
        wd_type(g.locator('[data-automation-id="formField-roleDescription"] textarea'), text)
    return notes

def workday_flow(page, job, queue, action):
    """Apply -> Autofill with Resume -> (the applicant signs in) -> fill each step and Save and Continue -> stop at Review.
    Never clicks Submit. Returns the panel shown on the last page."""
    resume = resume_path(job)
    title = f"{job['company']} · {job['title']}"
    if visible(page, WD["cookies_decline"]):
        page.locator(WD["cookies_decline"]).first.click()  # most private cookie choice
    if visible(page, WD["apply"]):
        page.locator(WD["apply"]).first.click()
        settle(page)
    for key in ("autofill", "manual"):
        if visible(page, WD[key]):
            page.locator(WD[key]).first.click()
            settle(page)
            break
    if visible(page, 'input[data-automation-id="verifyPassword"]') and visible(page, '[data-automation-id="signInLink"]'):
        page.locator('[data-automation-id="signInLink"]').first.click()  # most of the time the applicant already has an account
        settle(page)
    if visible(page, WD["password"]):
        if visible(page, WD["email"]):
            page.locator(WD["email"]).first.fill(load_rules()[1]["email"])
        show(page, [{"i": -1, "title": f"Sign in or create your {job['company']} Workday account", "state": "you",
                     "note": "Your email is filled in; type your password and click Sign In (no account here yet? click Create Account). "
                             "If they email you a verification link, open it, then come back. Everything after this fills itself."}],
             0, title, queue)
        print(f"  Waiting for you to sign in to {job['company']} Workday…", flush=True)
        if wait_while(page, action, lambda: visible(page, WD["password"])):
            return show(page, [], 0, title, queue)
        settle(page, 2500)
    uploaded, last_step, stuck = False, None, 0
    for _ in range(12):  # Workday applications have about 5-7 steps
        if action.get("v") and action["v"] != "manual":
            break
        if "Something went wrong" in (page.locator("body").inner_text() or ""):
            page.reload()  # Workday's own advice; happens after resume parsing
            settle(page, 4000)
        step = wd_step(page)
        nxt = page.locator(WD["next"]).first
        nxt_text = nxt.inner_text().strip() if visible(page, WD["next"]) else ""
        if "review" in step.lower() or re.search(r"submit", nxt_text, re.I):
            return show(page, [{"i": -1, "title": "Review page", "state": "you",
                                "note": "Check every section, then click Submit yourself. This tool never submits."}],
                        0, title, queue)
        wait_fields_stable(page)
        upload_note = None
        if not uploaded and resume and page.locator('input[type="file"]').count():
            try:
                page.locator('input[type="file"]').first.set_input_files(str(resume))
                uploaded = True
                settle(page, 4000)  # let Workday parse the resume into the form
            except Exception as ex:
                print(f"  resume upload failed: {ex!r}"[:300], file=sys.stderr, flush=True)
                upload_note = f"Upload your resume yourself: {resume}"
        exp_notes = wd_experience(page, job) if "experience" in step.lower() else []
        results = fill_form(page, job, resume)
        filled, items = summarize(results)
        items += [{"i": -1, "title": "My Experience", "state": "you", "note": n} for n in exp_notes]
        if upload_note:
            items.insert(0, {"i": -1, "title": "Resume", "state": "you", "note": upload_note})
        try:  # local snapshot of this step, so problems can be fixed precisely (stays on this laptop)
            snap = ROOT / "data" / "apply-logs" / "workday" / re.sub(r"[^a-z0-9]+", "-", f"{job['company']} {step}".lower())[:80]
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.with_suffix(".html").write_text(page.content(), encoding="utf-8")
            snap.with_suffix(".json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
        except Exception as ex:
            print(f"  (couldn't save the step snapshot: {ex!r})", file=sys.stderr, flush=True)
        panel = show(page, items, filled, f"{title} · {step or 'step'}", queue)
        print(f"  Workday step '{step}': {filled} filled, {sum(1 for it in items if it['state'] == 'you')} for you", flush=True)
        must = [r for r in results if r["state"] == "you" and r["required"]]
        stuck = stuck + 1 if step == last_step else 0
        last_step = step
        if must or stuck >= 1 or not nxt_text:
            # The applicant answers the red fields and clicks Save and Continue themselves; continue when the step changes.
            if wait_while(page, action, lambda: wd_step(page) == step):
                return panel
            settle(page)
            continue
        page.wait_for_timeout(1200)
        nxt.click()  # "Save and Continue" only saves this step as a draft
        settle(page, 2500)
        if visible(page, WD["error"]):
            show(page, items + [{"i": -1, "title": "Workday flagged something on this page", "state": "you",
                                 "note": "Fix the fields marked in red, then click Save and Continue."}], filled, title, queue)
            if wait_while(page, action, lambda: wd_step(page) == step):
                return panel
            settle(page)
    return show(page, [{"i": -1, "title": "Finish in this window", "state": "you",
                        "note": "Continue through the remaining steps, then click Submit yourself."}], 0, title, queue)
