"""Personal settings come from the profile and preferences, never from code."""
import me

PROFILE = {
    "contact": {"name": "Ada  Lovelace-King"},
    "education": [{"graduation": "December 2027", "coursework": {
        "completed": {"cs": ["CMPSC 131 Intro"]}, "in_progress_fall_2026": ["CMPSC 221"], "spring_2027": ["CMPSC 311"]}}],
    "work_authorization": {"status": "US citizen", "form_answers": {
        "authorized_to_work_in_us": "Yes", "will_require_sponsorship": "No"}},
}


def test_file_names_follow_the_name():
    assert me.file_stem("Ada  Lovelace-King") == "Ada_Lovelace-King"
    assert me.file_stem("José Núñez") == "José_Núñez"
    assert me.resume_name(PROFILE) == "Ada_Lovelace-King_Resume.pdf"
    assert me.cover_name(PROFILE) == "Ada_Lovelace-King_Cover_Letter.pdf"
    assert me.transcript_name(PROFILE) == "Ada_Lovelace-King_Transcript.pdf"


def test_unsafe_name_characters_are_dropped():
    assert me.file_stem("A/B: C") == "AB_C"


def test_grad_date_parsed():
    assert me.grad_date(PROFILE) == (2027, 12)
    assert me.grad_date({"education": [{"graduation": "Spring 2029"}]}) == (2029, 5)
    assert me.grad_date({"education": [{}]}) is None


def test_season_and_listings_url():
    assert me.season({"season": "Fall 2027"}) == "Fall 2027"
    assert me.season({}) == "Summer 2027"
    assert me.listings_url("Summer 2028") == (
        "https://raw.githubusercontent.com/SimplifyJobs/Summer2028-Internships/dev/.github/scripts/listings.json")


def test_course_terms():
    cw = PROFILE["education"][0]["coursework"]
    assert me.in_progress_courses(cw) == ["CMPSC 221"]
    assert me.upcoming_term(cw) == ("spring_2027", "Spring 2027")
    assert me.upcoming_term({"completed": {}}) == (None, None)


def test_visa_blocks_only_when_sponsorship_needed():
    full = {"citizenship", "clearance", "export_control", "no_sponsorship", "no_cpt", "permanent_auth"}
    assert me.visa_blocking({"needs_sponsorship": True}) == full
    assert me.visa_blocking({}) == full  # missing setting keeps the strict filter
    assert me.visa_blocking({"needs_sponsorship": False}) == set()


def test_work_auth_rows_come_from_profile():
    rows = me.work_auth_rows(PROFILE)
    assert ("Authorized to work in US?", "Yes") in rows
    assert ("Need sponsorship (now or future)?", "No") in rows
    assert me.visa_type(PROFILE) == "US citizen"
    assert not any(k == "Future visa" for k, _ in rows)


def test_years_allowed_in_letters():
    assert me.known_years(PROFILE, {"season": "Summer 2027"}) == {"2027"}
    assert me.known_years({"education": [{"graduation": "May 2028"}]}, {"season": "Summer 2027"}) == {"2027", "2028"}


def test_chrome_path_honours_chrome_path_env(monkeypatch):
    monkeypatch.setenv("CHROME_PATH", "/opt/x/chrome")
    assert me.chrome_path() == "/opt/x/chrome"


def test_mac_without_chrome_gives_a_clear_message(monkeypatch, tmp_path):
    import pytest
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.setattr(me.sys, "platform", "darwin")
    monkeypatch.setattr(me, "MAC_CHROME", str(tmp_path / "missing" / "Google Chrome"))
    with pytest.raises(SystemExit):
        me.chrome_path()


def test_linux_uses_google_chrome_not_chromium(monkeypatch):
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.setattr(me.sys, "platform", "linux")
    monkeypatch.setattr(me.shutil, "which", lambda n: "/usr/bin/" + n if n.startswith("chromium") else None)
    import pytest
    with pytest.raises(SystemExit):
        me.chrome_path()


def test_upcoming_term_picks_the_earliest_term():
    cw = {"fall_2027": ["A"], "spring_2027": ["B"], "summer_2027": ["C"]}
    assert me.upcoming_term(cw) == ("spring_2027", "Spring 2027")


def test_grad_date_with_abbreviation_dot():
    assert me.grad_date({"education": [{"graduation": "Dec. 2028"}]}) == (2028, 12)
    assert me.grad_date({"education": [{"graduation": "Class of 2028"}]}) is None


def test_empty_name_still_gives_a_file_name():
    assert me.resume_name({"contact": {"name": "  "}}) == "Applicant_Resume.pdf"


def test_missing_profile_exits_with_a_hint(tmp_path):
    import pytest
    with pytest.raises(SystemExit) as ex:
        me.load_json(tmp_path / "profile.json")
    assert "examples/profile" in str(ex.value)


def test_every_module_reads_the_same_profile_folder():
    import answers, jobs, verify
    assert verify.PROFILE_PATH == me.PROFILE_PATH
    assert jobs.PROFILE_PATH == me.PROFILE_PATH and jobs.PREFS_PATH == me.PREFS_PATH
    assert answers.ANSWERS_PATH == me.PROFILE_DIR / "answers.json"
    src = (me.ROOT / "src" / "site_workday.py").read_text()
    assert 'ROOT / "profile"' not in src


def test_workday_experience_ids():
    p = {"experience": [{"id": "a", "start": "2023-01", "end": "2024-01"}, {"id": "b", "start": "2024-02", "end": "present"},
                        {"id": "c", "start": "2022-01", "end": "2022-06"}, {"id": "d", "start": "2024-06", "end": "2024-08"}]}
    assert me.workday_experience_ids(p, {}) == ["b", "d", "a"]
    assert me.workday_experience_ids(p, {"workday_experience": ["c", "a"]}) == ["c", "a"]


def test_degree_and_field_patterns():
    import re
    pats = me.degree_patterns("Bachelor of Science")
    assert any(re.search(x, "bachelor of science") for x in pats)
    assert any(re.search(x, "master of science (ms)") for x in me.degree_patterns("Master of Science"))
    fos = me.field_patterns("Computer Science")
    assert any(re.search(x, "computer and information sciences") for x in fos)
    assert any(re.search(x, "economics") for x in me.field_patterns("Economics"))


def test_long_date_has_no_platform_specific_format():
    import datetime
    assert me.long_date(datetime.date(2026, 11, 5)) == "November 5, 2026"


def test_reveal_command_per_platform():
    assert me.reveal_command("/a/b/c.pdf", "darwin") == ["open", "-R", "/a/b/c.pdf"]
    assert me.reveal_command("/a/b/c.pdf", "linux") == ["xdg-open", "/a/b"]


def test_missing_chrome_gives_a_clear_message(monkeypatch):
    import pytest
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.setattr(me.sys, "platform", "linux")
    monkeypatch.setattr(me.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit) as ex:
        me.chrome_path()
    assert "CHROME_PATH" in str(ex.value)


def test_recruiter_outreach_is_opt_in():
    assert me.outreach_enabled({}) is False
    assert me.outreach_enabled({"recruiter_outreach": True}) is True


def test_outreach_does_nothing_unless_enabled():
    import outreach
    assert not me.outreach_enabled(me.prefs())  # the sample applicant hasn't opted in
    assert outreach.draft_for_new_applications() == []
    assert outreach.start_invites() is None
