"""Fills one form from the answers: one question at a time, never clicking Submit."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from formjs import EXTRACT_JS, MARK_JS  # noqa: E402
from answers import job_values, load_job_answers, load_rules, norm, pick_option, resolve, search_term  # noqa: E402

def fill_question(page, q, ans):
    """Fills one question. Returns (state, note): state is filled / drafted / check / you / skip."""
    i = q["i"]
    ctrl = page.locator(f'[data-em-c="{i}-0"]')
    kind = q["kind"]
    if q.get("disabled"):
        return "skip", ""  # e.g. End Date while "Still a student" is ticked
    prefilled = q.get("value") or ""
    if prefilled and (ans is None or (not ans.get("a") and not ans.get("text"))):
        return "check", f"Already filled by the site (e.g. from your resume): '{prefilled[:40]}'. Check it"
    if ans is None:
        return ("you", "No saved answer: fill this in") if q["required"] else ("skip", "")
    text, prefs, flag = ans.get("text"), ans.get("a"), ans.get("flag")
    if flag and not prefs and not text:
        return ("skip", "") if kind == "file" and not q["required"] else ("you", flag)
    if ans["src"] == "job":
        done = ("drafted", ans.get("note") or "Drafted for this job: read and edit")
    else:
        done = ("check", flag) if flag else ("filled", "")

    if kind == "file":
        if not text or not Path(text).exists():
            return ("you", flag or "Upload this yourself") if q["required"] else ("skip", "")
        ctrl.set_input_files(text)
        return done
    if kind in ("text", "textarea") and text and prefilled and norm(text) in norm(prefilled):
        return done  # already holds this answer (e.g. a legal name "Ada Grace" contains "Ada")
    if kind == "number" and text and prefilled.strip() == text.strip():
        return done  # already holds this answer (e.g. a legal name "Ada Grace" contains "Ada")
    if kind in ("listbox", "prompt", "select", "radio", "checks") and prefilled and \
            any(pick_option([v.strip()], prefs, text) is not None for v in prefilled.split(", ")):
        return done  # already set to an acceptable option
    if kind in ("text", "textarea", "number"):
        if not text:
            return ("you", flag or "Fill this in") if q["required"] or (text is None and flag) else ("skip", "")
        if kind == "number" and not re.fullmatch(r"-?\d+(\.\d+)?", text):
            return "you", "Needs a number"
        ctrl.fill(text)
        return done
    if kind == "select":
        idx = pick_option(q["options"], prefs, text)
        if idx is None:
            return "you", flag or "No matching option: pick one"
        ctrl.select_option(label=q["options"][idx])
        return done
    if kind in ("radio", "checks", "yesno"):
        idx = pick_option(q["options"], prefs, text)
        if idx is None:
            return "you", flag or "No matching option: pick one"
        page.locator(f'[data-em-o="{i}-{idx}"]').first.click()
        return done
    if kind == "check":
        if prefs and any(re.search(p, "yes") for p in prefs):
            if not q.get("checked"):  # clicking an already-ticked box would untick it
                page.locator(f'[data-em-o="{i}-0"]').first.click()
            return done
        return ("you", flag or "Tick this if it applies") if q["required"] else ("skip", "")
    if kind == "listbox":
        ctrl.click()
        page.wait_for_timeout(800)
        opts = page.locator('[role="option"]:visible')
        idx = pick_option([t.strip() for t in opts.all_inner_texts()], prefs, text)
        if idx is None:
            page.keyboard.press("Escape")
            return "you", flag or "No matching option: pick one"
        opts.nth(idx).click()
        return done
    if kind == "prompt":
        opts = page.locator('[data-automation-id="promptOption"]:visible')
        for term in [t for t in (ans.get("search") or []) + ([text] if text else []) + [search_term(p) for p in (prefs or [])] if t]:
            ctrl.click()
            ctrl.fill(term[:40])
            ctrl.press("Enter")
            page.wait_for_timeout(1800)
            idx = pick_option([t.strip() for t in opts.all_inner_texts()], prefs, text)
            if idx is not None:
                opts.nth(idx).click()
                page.wait_for_timeout(800)
                return done
            ctrl.fill("")
        page.keyboard.press("Escape")
        return "you", flag or "No matching option: search and pick one"
    if kind == "combo":
        opts = page.locator('[role="option"]:visible, [data-automation-id="promptOption"]:visible')
        # Short lists (Yes/No, demographics) show every option on open; long or remote lists need typing.
        terms = [None] + (ans.get("search") or []) + ([text] if text else []) + [search_term(p) for p in (prefs or [])]
        seen = set()
        for term in terms:
            if term in seen or term == "":
                continue
            seen.add(term)
            ctrl.click()
            if term:
                ctrl.fill("")
                ctrl.type(term[:40], delay=25)
            page.wait_for_timeout(1500 if term else 600)
            if term and opts.count() == 0:
                ctrl.press("Enter")  # Workday search prompts list matches only after Enter
                page.wait_for_timeout(1500)
            texts = [t.strip() for t in opts.all_inner_texts()]
            idx = pick_option(texts, prefs, text)
            if idx is not None:
                opts.nth(idx).click()
                return done
            page.keyboard.press("Escape")
        return "you", flag or "No matching option: pick one"
    return "you", "Unknown field type"

def fill_form(page, job, resume):
    rules, values = load_rules()
    values = job_values(job, values)
    job_answers = load_job_answers(job["resume_dir"])
    qs = [q for q in page.evaluate(EXTRACT_JS) if q["visible"]]
    # Upload the resume first: Lever and Ashby parse it and may overwrite fields filled before it.
    qs.sort(key=lambda q: 0 if q["kind"] == "file" else 1)
    results = []
    for q in qs:
        if q.get("inEntry"):  # Workday work/education entries are filled by wd_experience
            results.append(dict(q, state="skip", note="", source=None))
            continue
        ans = None
        try:
            ans = resolve(q, rules, values, job_answers)
            state, note = fill_question(page, q, ans)
        except Exception as ex:  # one bad field shouldn't stop the rest, but say why
            print(f"  couldn't fill '{q['title'][:60]}': {ex!r}"[:300], file=sys.stderr, flush=True)
            state, note = "you", f"Couldn't fill automatically ({type(ex).__name__}: {str(ex)[:80]})"
        if q["kind"] == "file" and state != "skip":
            page.wait_for_timeout(2500)
        results.append(dict(q, state=state, note=note, source=ans["src"] if ans else None))
    # Ticking a box like "Still a student" can grey out other fields (End Date); don't flag those.
    now_disabled = page.evaluate("ids => ids.map(i => { const el = document.querySelector(`[data-em-c=\"${i}-0\"]`); "
                                 "return !!(el && el.disabled); })", [r["i"] for r in results])
    for r, off in zip(results, now_disabled):
        if off and r["state"] == "you":
            r["state"], r["note"] = "skip", ""
    for r in results:
        if r["state"] != "skip":
            page.evaluate(MARK_JS, [r["i"], r["state"], r["note"]])
    return results

def summarize(results):
    filled = sum(1 for r in results if r["state"] == "filled")
    order = {"you": 0, "drafted": 1, "check": 2}
    items = [{"i": r["i"], "title": r["title"] or "(untitled field)", "state": r["state"], "note": r["note"]}
             for r in results if r["state"] in order]
    items.sort(key=lambda x: order[x["state"]])
    return filled, items
