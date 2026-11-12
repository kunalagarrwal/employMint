import apply as A


def lone(kind, label, i):
    return {"i": i, "title": label, "kind": kind, "options": [label], "required": False, "value": ""}


def test_race_radios_merge_into_one_question():
    races = ["Hispanic or Latino", "White (Not Hispanic or Latino)", "Asian (Not Hispanic or Latino)",
             "Two or More Races (Not Hispanic or Latino)"]
    out = A.merge_lone_options([lone("radio", r, i) for i, r in enumerate(races)])
    assert len(out) == 1 and out[0]["title"] == "Race / ethnicity" and out[0]["options"] == races


def test_pronoun_checkboxes_merge():
    out = A.merge_lone_options([lone("check", p, i) for i, p in enumerate(["He/him", "She/her", "They/them"])])
    assert [q["title"] for q in out] == ["Pronouns"] and out[0]["kind"] == "checks"


def test_two_consent_boxes_stay_separate():
    qs = [lone("check", "I agree to the privacy policy", 0), lone("check", "Contact me about future roles", 1)]
    assert A.merge_lone_options(qs) == qs


def test_lever_sheet_escapes_scraped_text():
    rows = [{"q": "<script>alert(1)</script>", "a": "<b>x</b>", "note": "", "req": True}]
    job = {"company": "Acme <Inc>", "title": "Intern"}
    html = A.lever_sheet_html(job, "https://jobs.lever.co/x", rows, {"resume": "/tmp/r.pdf"}, None)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html and "Acme &lt;Inc&gt;" in html
