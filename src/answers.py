"""Deciding what to answer. Pure logic, no browser: saved rules (profile/answers.json), per-job drafts
(resumes/<slug>/answers.json), option picking, and the file paths each application needs."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import me  # noqa: E402
from jobs import ROOT  # noqa: E402

ANSWERS_PATH = me.PROFILE_DIR / "answers.json"

RESUME_NAME = me.resume_name(me.profile())

def norm(s):
    s = (s or "").replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", re.sub(r"[*✱]", " ", s)).strip().lower()

def load_rules():
    """Rules from profile/answers.json. Every pattern is checked here, so a typo fails loudly up front."""
    data = json.loads(ANSWERS_PATH.read_text())
    for r in data["rules"]:
        for pat in [r["q"]] + list(r.get("a") or []):
            try:
                re.compile(pat)
            except re.error as ex:
                sys.exit(f"Bad pattern in profile/answers.json: {pat!r} ({ex})")
    return data["rules"], data["values"]

def load_job_answers(resume_dir):
    p = ROOT / resume_dir / "answers.json" if resume_dir else None
    if not p or not p.exists():
        return []
    return json.loads(p.read_text()).get("answers", [])

def fill_values(text, values):
    if text is None:
        return None
    # ", {address_line2}" with an empty value disappears with its comma, so no "St, , City".
    text = re.sub(r",\s*\{(\w+)\}", lambda m: "" if values.get(m.group(1)) == "" else m.group(0), text)
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), text)

def label_matches(label, key):
    if not key or not label:
        return False
    if label == key:
        return True
    short, long_ = sorted((label, key), key=len)
    # A saved question may carry extra text (options, "Select ..."), but a short generic key such as
    # "why do you want to" must not swallow every question that starts with it.
    return (len(short) >= 20 and long_.startswith(short) and not long_[len(short)].isalnum()
            and len(short) >= 0.5 * len(long_))

def resolve(q, rules, values, job_answers, remembered=None):
    """Returns {src, text, a, flag, note} for a question, or None if nothing knows the answer.
    `remembered` (from load_remembered) only fills questions that would otherwise be left to the applicant."""
    label = norm(q["title"])
    if not label:
        return None
    for ja in job_answers:
        if label_matches(label, norm(ja.get("q"))):
            if remembered and ja.get("flag") and not ja.get("a") and not ja.get("pick"):
                # Drafting only flagged it as the applicant's call; their own saved answer fills it, with the note kept.
                mine = recall(q, remembered)
                if mine:
                    mine["flag"] += f". For this job: {ja['flag']}"
                    return mine
            return {"src": "job", "text": ja.get("a"), "a": ja.get("pick"), "flag": ja.get("flag"), "note": ja.get("note")}
    found = None
    for r in rules:
        kinds = r.get("kind")
        if kinds and q["kind"] not in ([kinds] if isinstance(kinds, str) else kinds):
            continue
        if re.search(r["q"], label, re.I):
            found = {"src": "profile", "text": fill_values(r.get("text"), values), "a": r.get("a"),
                     "flag": r.get("flag"), "search": r.get("search")}
            break
    if remembered and (found is None or (found.get("flag") and not found.get("text") and not found.get("a"))):
        return recall(q, remembered) or found
    return found


# ---- Answers the applicant chose to remember ("answer once")
# Some questions are the applicant's own call and come back on form after form: pay, working in person,
# travel, availability. The first time one comes up, the form panel offers "Remember my answer"; if they
# tick it and submit, what *they* entered is saved here and fills the same kind of question on later forms,
# marked amber so they still check it. employMint never picks these answers itself.
REMEMBERED_PATH = me.PROFILE_DIR / "remembered.json"

DECISION_KINDS = [  # (id, words for the panel, label pattern). The first match wins, so specific ones come first.
    ("birth_country", "country of birth", r"country of (birth|origin)"),
    ("high_school", "high school", r"high school"),
    ("class_standing", "class standing", r"year in school|class standing|academic (year|standing)|current year|year of study|class year"),
    ("pay", "pay", r"salary|compensation|pay (expectation|range)|hourly (rate|range|pay|wage)|desired pay|expected pay|pay range"),
    ("agreements", "agreements with past employers", r"non[- ]?compete|non[- ]?solicit|subject to any agreements?|restrictive covenant"),
    ("offers", "other offers", r"outstanding offers?|other offers?|offer deadline|competing offers?"),
    ("travel", "travel", r"\btravel"),
    ("in_person", "working in person", r"relocat|in[- ]person|on[- ]?site|in[- ]office|hybrid|commut|reside in|live in|days (a|per) week"),
    ("availability", "availability", r"full[- ]time|entire (internship|duration|period|summer)|availab|start date|when can you start"),
]
# Never remembered, whatever else the label says: consent and certification (always ticked by hand),
# demographics (they already default to decline) and anything about one company's own process.
NEVER_REMEMBER = re.compile(
    r"consent|acknowledg|i agree|agree to|privacy|terms|certif|attest|accurate|truthful|sms|text messag|opt[- ]?in"
    r"|whatsapp|signature|gender|race|ethnic|veteran|disab|sexual|transgender|pronoun|applied .{0,40}before"
    r"|previously applied|relative|family member|related to|know anyone|referr", re.I)
TEXT_KINDS = ("text", "textarea", "number")

def decision_kind(title, kind=None):
    """(id, words) when this is a question the applicant may answer once for all forms, else None."""
    label = norm(title)
    if not label or NEVER_REMEMBER.search(label) or kind in ("file", "check"):
        return None
    for kid, words, pat in DECISION_KINDS:
        if re.search(pat, label, re.I):
            return kid, words
    return None

def load_remembered():
    try:
        data = json.loads(REMEMBERED_PATH.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as ex:
        print(f"WARN: ignoring {REMEMBERED_PATH.name}: {ex}", file=sys.stderr)
        return []
    return [a for a in data.get("answers", []) if isinstance(a, dict) and a.get("value")]

def _family(kind):
    return "text" if kind in TEXT_KINDS else "choice"

def recall(q, remembered):
    """The applicant's own saved answer for this question: the same question first, else the same kind of question."""
    dk = decision_kind(q["title"], q["kind"])
    if not dk:
        return None
    label, fam = norm(q["title"]), _family(q["kind"])
    same_kind = [a for a in remembered if a.get("kind") == dk[0] and _family(a.get("field")) == fam]
    hit = (next((a for a in reversed(same_kind) if norm(a.get("label")) == label), None)
           or (same_kind[-1] if same_kind else None))
    if not hit:
        return None
    where = f" on {hit['from']}'s form" if hit.get("from") else ""
    note = f"Your saved answer for {dk[1]} (you gave it{where}). Check it fits this question"
    if fam == "text":
        return {"src": "remembered", "text": hit["value"], "a": None, "flag": note}
    picks = [v.strip() for v in hit["value"].split(", ") if v.strip()]
    return {"src": "remembered", "text": None, "a": ["^" + re.escape(norm(v)) + "$" for v in picks], "flag": note}

def remember(entries, company):
    """Saves what the applicant entered for questions they ticked "Remember". entries: [{title, field, value}]."""
    from datetime import datetime, timezone
    try:
        data = json.loads(REMEMBERED_PATH.read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("_about", "Answers you chose to reuse (the 'Remember my answer' box on a form). They fill the "
                              "same kind of question on later forms, marked amber. Delete an entry to stop reusing it.")
    saved = [a for a in data.get("answers", []) if isinstance(a, dict)]
    n = 0
    for x in entries:
        dk = decision_kind(x.get("title"), x.get("field"))
        value = (x.get("value") or "").strip()
        if not dk or not value:
            continue
        saved = [a for a in saved if not (norm(a.get("label")) == norm(x["title"]) and a.get("field") == x["field"])]
        saved.append({"kind": dk[0], "label": x["title"], "field": x["field"], "value": value[:2000], "from": company,
                      "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        n += 1
    if n:
        data["answers"] = saved
        REMEMBERED_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return n

def pick_option(options, prefs, text):
    pats = list(prefs or [])
    if text:
        pats += ["^" + re.escape(norm(text)) + "$", r"(?<!\w)" + re.escape(norm(text)) + r"(?!\w)"]
    for p in pats:
        for i, o in enumerate(options):
            if re.search(p, norm(o), re.I):
                return i
    return None

def search_term(pattern):
    """Turns an option pattern like '^united states' into something to type into a search box."""
    t = re.sub(r"\\[bdsw]|\\.|[\^$()?*+\[\]|{}]", " ", pattern)
    return re.sub(r"\s+", " ", t).strip()

TRANSCRIPT = me.PROFILE_DIR / me.transcript_name(me.profile())  # unofficial transcript, if saved

def job_values(job, values):
    """Standard answers plus this job's files: resume, cover letter (PDF and text) and transcript."""
    resume = resume_path(job)
    d = ROOT / job["resume_dir"] if job["resume_dir"] else None
    cover = d / me.cover_name(me.profile()) if d else None
    cover_txt = d / "cover.txt" if d else None
    return dict(values,
                resume=str(resume) if resume else "",
                cover=str(cover) if cover and cover.exists() else "",
                cover_text=cover_txt.read_text(encoding="utf-8") if cover_txt and cover_txt.exists() else "",
                transcript=str(TRANSCRIPT) if TRANSCRIPT.exists() else "")

def resume_path(job):
    if not job["resume_dir"]:
        return None
    p = ROOT / job["resume_dir"] / RESUME_NAME
    return p if p.exists() else None

CHOICE_KINDS = ("select", "radio", "yesno", "checks", "check", "listbox", "prompt", "combo")

def sheet_answer(q, ans):
    """(answer text, note) for one question on the answer sheet."""
    if ans is None:
        return "", ("No saved answer: fill this in" if q["required"] else "Optional")
    text, prefs, flag = ans.get("text"), ans.get("a"), ans.get("flag")
    drafted = "Drafted for this job: read and edit" if ans["src"] == "job" else ""
    if q["kind"] == "checks" and q["options"] and prefs and ans["src"] == "job":
        # A job answer can list several boxes to tick; profile rules list fallbacks, best first.
        picks = [o for o in q["options"] if any(re.search(pt, norm(o)) for pt in prefs)]
        if picks:
            return "Tick: " + ", ".join(picks), flag or drafted
    if q["kind"] in CHOICE_KINDS and q["options"]:
        idx = pick_option(q["options"], prefs, text)
        if idx is not None:
            pick = q["options"][idx]
            return (("Tick: " + pick) if q["kind"] in ("check", "checks") else pick), flag or drafted
    if text:
        return text, flag or drafted
    if prefs:
        t = search_term(prefs[0])
        return t[:1].upper() + t[1:], flag or ""
    return "", flag or ("Fill this in" if q["required"] else "Optional")

def merge_lone_options(qs):
    """Merges runs of 3+ single-option radios/checkboxes into one question."""
    # Lever's race question arrives as one single-option radio per race; merge each run into one question.
    # Pronoun checkboxes come the same way. Runs shorter than 3 stay separate (e.g. two consent boxes).
    merged = []
    for q in qs:
        lone = q["kind"] in ("radio", "check") and len(q["options"]) == 1
        if lone and merged and merged[-1].get("_parts") and merged[-1]["kind"] == q["kind"]:
            merged[-1]["_parts"].append(q)
            continue
        merged.append(dict(q, _parts=[q]) if lone else q)
    out = []
    for q in merged:
        parts = q.get("_parts")
        if not parts or len(parts) < 3:
            out += parts or [q]
            continue
        opts = [x["options"][0] for x in parts]
        joined = norm(" ".join(opts))
        title = ("Race / ethnicity" if "hispanic" in joined else "Pronouns" if "he/him" in joined
                 else parts[0]["title"] if q["kind"] == "radio" else "Select all that apply")
        out.append(dict(parts[0], title=title, options=opts, kind="radio" if q["kind"] == "radio" else "checks"))
    return out
