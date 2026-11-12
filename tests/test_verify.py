"""The resume verifier must block anything not backed by profile.json (checked on the sample applicant)."""
import json

import verify as V

PROFILE = json.loads(V.PROFILE_PATH.read_text())


def run(bullet, sources=("campus-it:0",), **extra):
    t = {"experience": [{"id": "campus-it", "bullets": [{"text": bullet, "sources": list(sources)}]}]}
    t.update(extra)
    return V.verify(t, PROFILE)[0]


def test_runs_on_the_sample_profile():
    assert PROFILE["contact"]["name"] == "Alex Rivera"


def test_true_bullet_passes():
    assert run("Built a room-booking app in React and Flask used by 3 campus offices") == []


def test_invented_number_blocked():
    assert any("numbers not in its sources" in e for e in run("Built a room-booking app used by 12 campus offices"))


def test_unsourced_tech_blocked():
    assert any("tech not in its sources" in e for e in run("Deployed a room-booking app on Kubernetes for 3 offices"))


def test_bullet_without_sources_blocked():
    assert any("cites no sources" in e for e in run("Built things", sources=()))


def test_unknown_skill_blocked():
    errs = run("Built a room-booking app", skills=[{"label": "Languages", "items": ["Rust"]}])
    assert any("'Rust' is not in the profile" in e for e in errs)


def test_course_not_in_profile_blocked():
    errs = run("Built a room-booking app", upcoming_coursework=["Quantum Computing (CS 498)"])
    assert any("CS 498" in e for e in errs)


def test_unknown_certification_blocked():
    assert any("certifications" in e for e in run("Built a room-booking app", certifications=["AWS Solutions Architect"]))
