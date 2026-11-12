"""profile_check catches a broken or unfinished profile before anything else runs."""
import json
import shutil
from pathlib import Path

import profile_check as PC

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "profile"


def copy_sample(tmp_path, edit=None, name="profile.json"):
    d = tmp_path / "profile"
    shutil.copytree(SAMPLE, d)
    if edit:
        path = d / name
        data = json.loads(path.read_text())
        edit(data)
        path.write_text(json.dumps(data))
    return d


def errors(d):
    return PC.check(d)[0]


def test_sample_has_no_errors_but_is_flagged_as_sample(tmp_path):
    errs, warns = PC.check(copy_sample(tmp_path))
    assert errs == []
    assert any("sample" in w for w in warns)


def test_missing_file(tmp_path):
    d = copy_sample(tmp_path)
    (d / "answers.json").unlink()
    assert any("answers.json" in e and "missing" in e for e in errors(d))


def test_invalid_json(tmp_path):
    d = copy_sample(tmp_path)
    (d / "preferences.json").write_text("{not json")
    assert any("preferences.json" in e and "JSON" in e for e in errors(d))


def test_missing_contact_field(tmp_path):
    d = copy_sample(tmp_path, lambda p: p["contact"].pop("email"))
    assert any("contact.email" in e for e in errors(d))


def test_bad_dates_and_duplicate_ids(tmp_path):
    def edit(p):
        p["experience"][0]["start"] = "Jan 2025"
        p["projects"][0]["id"] = p["experience"][0]["id"]
    errs = errors(copy_sample(tmp_path, edit))
    assert any("start" in e and "YYYY-MM" in e for e in errs)
    assert any("duplicate id" in e for e in errs)


def test_entry_without_facts(tmp_path):
    d = copy_sample(tmp_path, lambda p: p["projects"][0].update(facts=[]))
    assert any("facts" in e for e in errors(d))


def test_unknown_placeholder_in_answers(tmp_path):
    d = copy_sample(tmp_path, lambda a: a["rules"].append({"q": "nickname", "text": "{nickname}"}), "answers.json")
    assert any("{nickname}" in e for e in errors(d))


def test_bad_regex_in_answers(tmp_path):
    d = copy_sample(tmp_path, lambda a: a["rules"].append({"q": "broken(", "text": "x"}), "answers.json")
    assert any("broken(" in e for e in errors(d))


def test_bad_season(tmp_path):
    d = copy_sample(tmp_path, lambda pr: pr.update(season="Summer"), "preferences.json")
    assert any("season" in e for e in errors(d))


def test_sponsorship_mismatch_is_a_warning(tmp_path):
    d = copy_sample(tmp_path, lambda pr: pr.update(needs_sponsorship=True), "preferences.json")
    errs, warns = PC.check(d)
    assert errs == [] and any("sponsorship" in w for w in warns)


def test_unreadable_graduation_is_a_warning(tmp_path):
    d = copy_sample(tmp_path, lambda p: p["education"][0].update(graduation="soon"))
    errs, warns = PC.check(d)
    assert errs == [] and any("graduation" in w for w in warns)


# ---- review findings: profiles that passed the checker but crashed the pipeline ----

def test_answers_need_rules_and_required_string_values(tmp_path):
    assert any("rules" in e for e in errors(copy_sample(tmp_path, lambda a: a.pop("rules"), "answers.json")))


def test_answers_values_required_keys(tmp_path):
    errs = errors(copy_sample(tmp_path, lambda a: a["values"].pop("grad_year"), "answers.json"))
    assert any("values.grad_year" in e for e in errs)


def test_answers_values_must_be_strings(tmp_path):
    errs = errors(copy_sample(tmp_path, lambda a: a["values"].update(gpa=3.6), "answers.json"))
    assert any("values.gpa" in e and "text" in e for e in errs)


def test_tracks_required_with_int_priority(tmp_path):
    assert any("tracks" in e for e in errors(copy_sample(tmp_path, lambda pr: pr.pop("tracks"), "preferences.json")))
    def edit(pr):
        pr["tracks"]["product"] = {"titles": []}
    assert any("tracks.product" in e and "priority" in e for e in errors(copy_sample(tmp_path / "b", edit, "preferences.json")))


def test_null_contact_field_is_an_error(tmp_path):
    assert any("contact.github" in e for e in errors(copy_sample(tmp_path, lambda p: p["contact"].update(github=None))))


def test_empty_github_is_fine(tmp_path):
    assert errors(copy_sample(tmp_path, lambda p: p["contact"].update(github=""))) == []


def test_coursework_shape(tmp_path):
    def edit(p):
        cw = p["education"][0]["coursework"]
        cw["completed"] = ["CS 101"]
        cw["Spring_2028"] = ["CS 400"]
    errs = errors(copy_sample(tmp_path, edit))
    assert any("coursework.completed" in e for e in errs)
    assert any("Spring_2028" in e for e in errs)


def test_wrong_types_report_errors_not_tracebacks(tmp_path):
    d = copy_sample(tmp_path, lambda a: a["rules"].append({"q": 5, "a": "yes", "text": 7}), "answers.json")
    errs = errors(d)
    assert any("rules[" in e for e in errs)
    (d / "profile.json").write_text("[]")
    assert any("profile.json" in e and "object" in e for e in errors(d))


def test_entry_field_types(tmp_path):
    def edit(p):
        p["projects"][0]["id"] = ["x"]
        p["experience"][0]["skills"] = "Python"
        p["experience"][1]["title"] = 3
    errs = errors(copy_sample(tmp_path, edit))
    assert any("id" in e and "text" in e for e in errs)
    assert any("skills" in e for e in errs)
    assert any("title" in e for e in errs)
