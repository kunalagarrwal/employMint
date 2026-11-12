"""The resume renderer works for any valid profile, not only one with every optional field."""
import copy
import json
from pathlib import Path

import render as R

SAMPLE = json.loads((Path(__file__).resolve().parent.parent / "examples" / "profile" / "profile.json").read_text())
TAILORED = {"experience": [{"id": "campus-it", "bullets": [{"text": "Built a room-booking app", "sources": ["campus-it:0"]}]}]}


def test_sample_profile_renders_minor_and_gpa():
    html = R.build_html(TAILORED, SAMPLE, 10.5)
    assert "Minor in Mathematics" in html and "GPA: 3.60/4.0" in html


def test_profile_without_minor_or_gpa_renders():
    p = copy.deepcopy(SAMPLE)
    del p["education"][0]["minor"]
    del p["education"][0]["gpa"]
    html = R.build_html(TAILORED, p, 10.5)
    assert "B.S. Computer Science" in html
    assert "Minor in" not in html and "GPA" not in html


def test_project_without_subtitle_has_no_stray_separator():
    t = {"projects": [{"id": "budget-bot", "bullets": [{"text": "x", "sources": ["budget-bot:0"]}]}]}
    html = R.build_html(t, SAMPLE, 10.5)
    assert "github.com/example/budgetbot" in html
    assert '| <a href="https://github.com/example/budgetbot"' not in html


def test_empty_links_leave_no_empty_anchor_or_double_separator():
    p = copy.deepcopy(SAMPLE)
    p["contact"]["github"] = ""
    p["contact"]["linkedin"] = ""
    html = R.build_html(TAILORED, p, 10.5)
    assert '<a href=""' not in html and "|  |" not in html and "| |" not in html
    import cover as C
    cover = {"job": {"company": "Acme", "title": "SWE Intern"}, "paragraphs": [{"text": "Hi.", "sources": []}]}
    letter = C.build_html(cover, p, 11.0)
    assert '<a href=""' not in letter and "|  |" not in letter and "| |" not in letter
