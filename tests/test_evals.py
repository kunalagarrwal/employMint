"""evals.py works for a new user who has no hand-checked answer set and no resumes yet."""
import json

import evals


def test_new_user_report_is_built_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(evals, "EVALS", tmp_path)
    monkeypatch.setattr(evals, "RESUMES", tmp_path / "resumes")
    rules, values = evals.A.load_rules()
    profile = json.loads(evals.V.PROFILE_PATH.read_text())
    res = {"at": "now", "answers": evals.eval_answers(rules, values), "coverage": evals.eval_coverage(rules, values),
           "resumes": evals.eval_resumes(profile), "covers": evals.eval_covers(profile)}
    assert res["answers"]["cases"] == 0 and res["answers"]["misses"] == []
    assert "golden_answers.json" in evals.report_md(res)
