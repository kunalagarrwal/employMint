"""Answer once: questions only the applicant can answer (pay, travel, ...) are saved when they tick "Remember my
answer" and submit, then reused on later forms for them to check. Plus the queue that has no approve step."""
import json

import pytest

import answers as AN
import apply as A
import jobs as J

RULES, VALUES = AN.load_rules()
YES_NO = ["Select...", "Yes", "No"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(AN, "REMEMBERED_PATH", tmp_path / "remembered.json")
    return tmp_path / "remembered.json"


def q(title, kind="radio", options=YES_NO):
    return {"i": 0, "title": title, "kind": kind, "options": list(options), "required": True, "value": ""}


PAY = "Does the posted salary or hourly pay range align with your expectations?"


@pytest.mark.parametrize("title, kind", [
    ("Does the posted salary range align with your expectations?", "radio"),
    ("If hired, would you be able to travel to our headquarters?", "radio"),
    ("Are you available to work full-time for the entire internship?", "yesno"),
    ("Are you subject to any agreements with any current or former employer?", "radio"),
    ("Do you have any outstanding offers or deadlines?", "text"),
])
def test_recurring_personal_questions_can_be_remembered(title, kind):
    assert AN.decision_kind(title, kind)


@pytest.mark.parametrize("title, kind", [
    ("Yes, I consent to receiving text messages", "radio"),
    ("Applicant privacy acknowledgement", "radio"),
    ("I certify that the information above is accurate", "radio"),
    ("Gender", "select"),
    ("Have you applied to Acme before?", "radio"),
    ("Do you know anyone who works here?", "radio"),
    ("Why do you want to work here?", "textarea"),
    ("I am available to start in May", "check"),  # a lone box to tick is never pre-ticked
])
def test_consent_demographics_and_company_questions_are_never_remembered(title, kind):
    assert AN.decision_kind(title, kind) is None


def test_nothing_is_filled_until_the_applicant_saves_an_answer(store):
    ans = AN.resolve(q(PAY), RULES, VALUES, [], AN.load_remembered())
    assert ans["src"] == "profile" and not ans.get("a") and not ans.get("text")  # still theirs to answer


def test_saved_answer_fills_the_same_question_later_amber(store):
    assert AN.remember([{"title": PAY, "field": "radio", "value": "Yes"}], "Acme") == 1
    ans = AN.resolve(q(PAY), RULES, VALUES, [], AN.load_remembered())
    assert ans["src"] == "remembered" and "Acme" in ans["flag"]
    assert AN.sheet_answer(q(PAY), ans)[0] == "Yes"
    saved = json.loads(store.read_text())["answers"][0]
    assert saved["kind"] == "pay" and saved["from"] == "Acme" and saved["saved_at"].endswith("+00:00")


def test_saved_answer_fills_the_same_kind_of_question(store):
    AN.remember([{"title": PAY, "field": "radio", "value": "Yes"}], "Acme")
    other = q("Is the pay range listed for this internship acceptable to you?", "yesno", ["Yes", "No"])
    assert AN.sheet_answer(other, AN.resolve(other, RULES, VALUES, [], AN.load_remembered()))[0] == "Yes"


def test_a_choice_answer_never_fills_a_text_box(store):
    AN.remember([{"title": PAY, "field": "radio", "value": "Yes"}], "Acme")
    text_q = q("What are your salary expectations?", "text", [])
    assert AN.resolve(text_q, RULES, VALUES, [], AN.load_remembered())["src"] == "profile"


def test_profile_and_job_answers_still_win(store):
    AN.remember([{"title": "Are you able to work in person in our office?", "field": "radio", "value": "No"}], "Acme")
    onsite = q("Are you able to work in person in our office?")
    assert AN.sheet_answer(onsite, AN.resolve(onsite, RULES, VALUES, [], AN.load_remembered()))[0] == "Yes"  # profile rule
    AN.remember([{"title": PAY, "field": "radio", "value": "Yes"}], "Acme")
    job = [{"q": PAY, "pick": ["^no$"], "note": "drafted"}]
    assert AN.resolve(q(PAY), RULES, VALUES, job, AN.load_remembered())["src"] == "job"


def test_saved_answer_fills_a_question_drafting_only_flagged(store):
    AN.remember([{"title": PAY, "field": "radio", "value": "Yes"}], "Acme")
    job = [{"q": PAY, "flag": "Pay is your call: posting says $40/hr"}]
    ans = AN.resolve(q(PAY), RULES, VALUES, job, AN.load_remembered())
    assert ans["src"] == "remembered" and "$40/hr" in ans["flag"] and AN.sheet_answer(q(PAY), ans)[0] == "Yes"


def test_consent_is_not_saved_even_if_sent(store):
    assert AN.remember([{"title": "Yes, I consent to receiving text messages", "field": "radio", "value": "Yes"}], "Acme") == 0
    assert not store.exists()


def test_newer_answer_replaces_the_old_one(store):
    AN.remember([{"title": PAY, "field": "radio", "value": "Yes"}], "Acme")
    AN.remember([{"title": PAY, "field": "radio", "value": "No"}], "Beta")
    saved = AN.load_remembered()
    assert len(saved) == 1 and saved[0]["value"] == "No" and saved[0]["from"] == "Beta"


def test_capture_reads_only_ticked_questions_and_keys_by_title():
    class Page:
        def evaluate(self, js, ids):
            return [{"i": i, "text": PAY + " Yes No", "value": "Yes"} for i in ids]
    item = {"i": 3, "title": PAY, "state": "you", "kind": "radio", "remember": "pay"}
    panel = [[item, {"i": 4, "title": "Other", "state": "you", "kind": "text"}], 0, "Acme", {}]
    action = {"remember": {3: True, 4: True}}
    A.capture_remembered(Page(), action, panel)
    assert action["captured"] == {PAY: {"title": PAY, "field": "radio", "value": "Yes"}} and item["on"]
    action["remember"] = {3: False}
    A.capture_remembered(Page(), action, panel)
    assert action["captured"] == {} and not item["on"]


# ---- no approve step: tailored jobs go straight into the queue
@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "DATA", tmp_path)
    monkeypatch.setattr(J, "DB_PATH", tmp_path / "jobs.sqlite")
    d = J.db_connect()
    for jid, status, decided in (("t", "tailored", None), ("a", "approved", "2026-11-01T00:00:00+00:00"),
                                 ("s", "skip", None)):
        rd = tmp_path / jid
        rd.mkdir()
        (rd / AN.RESUME_NAME).write_bytes(b"%PDF")
        d.execute("INSERT INTO jobs (id, company, title, url, app_status, fit, resume_dir, decided_at, batch_date) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (jid, "Co " + jid, "Intern", "https://job-boards.greenhouse.io/x/jobs/1",
                                                status, 8, str(rd), decided, "2026-11-13"))
    d.commit()
    d.close()
    return tmp_path


def status(jid):
    d = J.db_connect()
    try:
        return d.execute("SELECT app_status FROM jobs WHERE id=?", (jid,)).fetchone()[0]
    finally:
        d.close()


def test_queue_holds_approved_then_tailored_jobs(db):
    assert [r["id"] for r in A.queue_jobs()] == ["a", "t"]


def test_not_for_me_moves_a_job_to_skipped(db):
    A.mark_passed("t")
    assert status("t") == "skip"
    A.mark_passed("a")
    assert status("a") == "skip"


def test_review_page_offers_one_start_button_for_everything(db):
    import review as R
    d = J.db_connect()
    try:
        html = R.page(d)
    finally:
        d.close()
    assert "Start applying (2)" in html and 'data-d="open">Apply now' in html and 'data-d="approve"' not in html
