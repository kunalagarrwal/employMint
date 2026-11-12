"""Checks a profile folder (profile.json, answers.json, preferences.json) before anything uses it.

Errors are things that would crash or mislead the pipeline; warnings are things to look at.
Exit code 1 when there are errors, so setup scripts can stop on them.

Usage: python3 src/profile_check.py [profile folder, default: profile/]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import me  # noqa: E402

FILES = ("profile.json", "answers.json", "preferences.json")
CONTACT = ("name", "email", "phone", "linkedin", "github")
EDUCATION = ("school", "location", "degree", "graduation")
EXPERIENCE = ("id", "org", "title", "location", "start", "end", "facts")
PROJECT = ("id", "name", "date", "facts")
TEXT_FIELDS = ("id", "org", "title", "location", "name", "url")
# answers.json values the code reads directly (apply.py sheets, Workday, cover upload names).
REQUIRED_VALUES = ("full_name", "email", "phone", "linkedin", "school", "degree", "major", "gpa", "grad", "grad_year",
                   "heard_from")
MONTH = re.compile(r"^20\d\d-(0[1-9]|1[0-2])$")
SEASON = re.compile(r"^(Spring|Summer|Fall|Winter) 20\d\d$")
JOB_VALUES = {"resume", "cover", "cover_text", "transcript"}  # added per job by answers.job_values
SAMPLE_MARKERS = ("Alex Rivera", "@example.com", "University of Example")


def is_text_list(x, allow_empty=True):
    return isinstance(x, list) and (allow_empty or bool(x)) and all(isinstance(s, str) and s.strip() for s in x)


def load(d, name, errors):
    path = d / name
    if not path.exists():
        errors.append(f"{name}: missing (copy it from examples/profile/)")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        errors.append(f"{name}: not valid JSON ({ex})")
        return None
    except (OSError, UnicodeDecodeError) as ex:
        errors.append(f"{name}: can't be read ({ex})")
        return None
    if not isinstance(data, dict):
        errors.append(f"{name}: must be a JSON object {{...}}, not {type(data).__name__}")
        return None
    return data


def check_contact(p, errors):
    contact = p.get("contact")
    if not isinstance(contact, dict):
        errors.append("profile.json: contact must be an object with name, email, phone, linkedin, github")
        return
    for k in CONTACT:
        if k not in contact:
            errors.append(f"profile.json: contact.{k} is missing (use \"\" if you don't have one)")
        elif not isinstance(contact[k], str):
            errors.append(f"profile.json: contact.{k} must be text (use \"\" if you don't have one)")
        elif not contact[k].strip() and k in ("name", "email"):
            errors.append(f"profile.json: contact.{k} is empty")


def check_coursework(cw, errors):
    where = "profile.json: education[0].coursework"
    if not isinstance(cw, dict):
        errors.append(f"{where} must be an object")
        return
    for k, v in cw.items():
        if k.startswith("_"):
            continue
        if k == "completed":
            if not isinstance(v, dict) or not all(is_text_list(x) for x in v.values()):
                errors.append(f"{where}.completed must be an object of subject -> list of course names")
        elif k.startswith("in_progress") or me.TERM_KEY.match(k):
            if not is_text_list(v):
                errors.append(f"{where}.{k} must be a list of course names")
        else:
            errors.append(f"{where}: unknown key '{k}'. Use 'completed', 'in_progress_<term>_<year>' or "
                          "'<term>_<year>' in lowercase (e.g. 'spring_2027')")


def check_education(p, errors, warnings):
    edu = p.get("education")
    if not isinstance(edu, list) or not edu or not isinstance(edu[0], dict):
        errors.append("profile.json: education must be a list with at least one school")
        return
    ed = edu[0]
    for k in EDUCATION:
        if not isinstance(ed.get(k), str) or not ed[k].strip():
            errors.append(f"profile.json: education[0].{k} is missing or empty")
    for k in ("minor", "gpa", "start", "college"):
        if k in ed and not isinstance(ed[k], str):
            errors.append(f"profile.json: education[0].{k} must be text")
    if "coursework" in ed:
        check_coursework(ed["coursework"], errors)
    if isinstance(ed.get("graduation"), str) and ed["graduation"].strip() and me.grad_date(p) is None:
        warnings.append(f"profile.json: can't read a month and year from graduation '{ed['graduation']}' "
                        "(write it like 'May 2028'); graduation-date filters stay off")


def check_entries(p, errors, warnings):
    seen = set()
    for section, required in (("experience", EXPERIENCE), ("projects", PROJECT)):
        entries = p.get(section) or []
        if not isinstance(entries, list):
            errors.append(f"profile.json: {section} must be a list")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"profile.json: {section}[{i}] must be an object")
                continue
            eid = entry.get("id")
            where = f"profile.json: {section}[{i}] ({eid if isinstance(eid, str) else '?'})"
            for k in required:
                if k not in entry:
                    errors.append(f"{where}: {k} is missing")
            for k in TEXT_FIELDS:
                if k in entry and not isinstance(entry[k], str):
                    errors.append(f"{where}: {k} must be text")
            for k in ("start", "date"):
                if k in entry and not MONTH.match(str(entry[k])):
                    errors.append(f"{where}: {k} '{entry[k]}' must be YYYY-MM")
            if "end" in entry and entry["end"] != "present" and not MONTH.match(str(entry["end"])):
                errors.append(f"{where}: end '{entry['end']}' must be YYYY-MM or 'present'")
            if "facts" in entry and not is_text_list(entry["facts"], allow_empty=False):
                errors.append(f"{where}: facts must be a non-empty list of sentences")
            if "skills" in entry and not is_text_list(entry["skills"]):
                errors.append(f"{where}: skills must be a list of names")
            if isinstance(eid, str):
                if eid in seen:
                    errors.append(f"{where}: duplicate id '{eid}' (ids must be unique across experience and projects)")
                seen.add(eid)
    if not seen:
        warnings.append("profile.json: no experience or projects yet, so resumes will have nothing to show")


def check_profile(p, errors, warnings):
    check_contact(p, errors)
    if any(m in json.dumps(p) for m in SAMPLE_MARKERS):
        warnings.append("profile.json still contains the sample applicant (Alex Rivera). Replace it with your own details.")
    check_education(p, errors, warnings)
    check_entries(p, errors, warnings)

    skills = p.get("skills", {})
    if not isinstance(skills, dict) or not all(is_text_list(v) for k, v in skills.items() if not k.startswith("_")):
        errors.append("profile.json: skills must be an object of group -> list of names")
    for k in ("interests", "interests_on_resume"):
        if k in p and not is_text_list(p[k]):
            errors.append(f"profile.json: {k} must be a list of text")
    certs = p.get("certifications") or []
    for i, c in enumerate(certs if isinstance(certs, list) else [None]):
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("issuer"), str):
            errors.append(f"profile.json: certifications[{i}] needs name and issuer (text)")

    wa = p.get("work_authorization") or {}
    fa = wa.get("form_answers") or {} if isinstance(wa, dict) else {}
    for k in ("authorized_to_work_in_us", "will_require_sponsorship"):
        if not isinstance(fa, dict) or not fa.get(k):
            warnings.append(f"profile.json: work_authorization.form_answers.{k} is empty; forms will leave it for you")


def check_answers(a, errors):
    values = a.get("values")
    if not isinstance(values, dict):
        errors.append("answers.json: 'values' must be an object of standard answers")
        values = {}
    for k in REQUIRED_VALUES:
        if k not in values:
            errors.append(f"answers.json: values.{k} is missing (use \"\" if it doesn't apply)")
    for k, v in values.items():
        if not isinstance(v, str):
            errors.append(f"answers.json: values.{k} must be text, e.g. \"{v}\"")
    rules = a.get("rules")
    if not isinstance(rules, list):
        errors.append("answers.json: 'rules' must be a list (copy it from examples/profile/answers.json)")
        return
    known = set(values) | JOB_VALUES
    for i, r in enumerate(rules):
        if not isinstance(r, dict) or not isinstance(r.get("q"), str):
            errors.append(f"answers.json: rules[{i}] needs a 'q' pattern (text)")
            continue
        opts = r.get("a")
        if opts is not None and not (isinstance(opts, list) and all(isinstance(x, str) for x in opts)):
            errors.append(f"answers.json: rules[{i}] 'a' must be a list of patterns")
            opts = []
        for pat in [r["q"]] + list(opts or []):
            try:
                re.compile(pat)
            except re.error as ex:
                errors.append(f"answers.json: rules[{i}] bad pattern {pat!r} ({ex})")
        for k in ("text", "flag", "note"):
            if k in r and r[k] is not None and not isinstance(r[k], str):
                errors.append(f"answers.json: rules[{i}] '{k}' must be text")
        for name in re.findall(r"\{(\w+)\}", r["text"] if isinstance(r.get("text"), str) else ""):
            if name not in known:
                errors.append(f"answers.json: rules[{i}] uses {{{name}}} but values has no '{name}'")


def check_prefs(pr, p, errors, warnings):
    if not SEASON.match(str(pr.get("season", ""))):
        errors.append(f"preferences.json: season '{pr.get('season')}' must look like 'Summer 2027'")
    if not isinstance(pr.get("needs_sponsorship"), bool):
        warnings.append("preferences.json: needs_sponsorship should be true or false (missing means true: strict visa filter)")
    tracks = pr.get("tracks")
    if not isinstance(tracks, dict) or not [k for k in tracks if not k.startswith("_")]:
        errors.append("preferences.json: tracks must list at least one role track (copy them from examples/profile)")
    else:
        for k, v in tracks.items():
            if not k.startswith("_") and not (isinstance(v, dict) and isinstance(v.get("priority"), int)
                                              and not isinstance(v.get("priority"), bool)):
                errors.append(f"preferences.json: tracks.{k} needs a whole-number priority (1 = most wanted)")
    wd = pr.get("workday_experience")
    if wd is not None and not is_text_list(wd):
        errors.append("preferences.json: workday_experience must be a list of experience ids")
    if p is not None:
        wa = p.get("work_authorization") or {}
        if isinstance(wa, dict) and "requires_future_sponsorship" in wa and isinstance(pr.get("needs_sponsorship"), bool) \
                and wa["requires_future_sponsorship"] != pr["needs_sponsorship"]:
            warnings.append("preferences.needs_sponsorship and profile work_authorization.requires_future_sponsorship "
                            "disagree; set both to the same value")


def check(profile_dir):
    """Returns (errors, warnings) for the profile folder."""
    d = Path(profile_dir)
    errors, warnings = [], []
    p, a, pr = (load(d, name, errors) for name in FILES)
    if p is not None:
        check_profile(p, errors, warnings)
    if a is not None:
        check_answers(a, errors)
        contact = p.get("contact") if p is not None else None
        full = (a.get("values") or {}).get("full_name") if isinstance(a.get("values"), dict) else None
        if isinstance(contact, dict) and full not in (None, contact.get("name")):
            warnings.append("answers.json values.full_name differs from profile.json contact.name")
    if pr is not None:
        check_prefs(pr, p, errors, warnings)
    return errors, warnings


def main():
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else me.PROFILE_DIR
    errors, warnings = check(d)
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    if errors:
        sys.exit(f"{d}: {len(errors)} errors. Fix them before running the pipeline.")
    print(f"{d}: OK ({len(warnings)} warnings)")


if __name__ == "__main__":
    main()
