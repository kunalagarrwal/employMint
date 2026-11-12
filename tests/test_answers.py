"""Form answers, checked on the sample applicant (US citizen, demographics set to decline).
Most cases here are bugs that once filled a real application wrongly; the answer logic is the same for everyone."""
import pytest

import apply as A

RULES, VALUES = A.load_rules()
DECLINE = "Decline to self-identify"


def answer(title, kind="text", options=None, required=True, job_answers=()):
    """What the tool would enter for one question (the same logic the Lever sheet shows)."""
    q = {"i": 0, "title": title, "kind": kind, "options": list(options or []), "required": required, "value": ""}
    text, _note = A.sheet_answer(q, A.resolve(q, RULES, VALUES, list(job_answers)))
    return text


YES_NO = ["Select...", "Yes", "No"]


def test_runs_on_the_sample_profile():
    assert VALUES["full_name"] == "Alex Rivera"


@pytest.mark.parametrize("title", [
    "Will you now or in the future require sponsorship for employment visa status?",
    "Will you now or in the future require our company to file a petition or application for "
    "employment-based immigration status on your behalf to begin or continue employment with our company?",
])
def test_sponsorship_follows_the_profile(title):
    assert answer(title, "select", YES_NO) == "No"


def test_authorized_to_work_is_yes():
    assert answer("Are you legally authorized to work in the United States?", "select", YES_NO) == "Yes"


@pytest.mark.parametrize("title,options", [
    ("I identify my ethnicity as", ["East Asian (Chinese, Japanese, Korean)", "White", DECLINE]),
    ("Race", ["Hispanic or Latino", "White (Not Hispanic or Latino)", DECLINE]),
    ("Gender", ["Select ...", "Male", "Female", DECLINE]),
    ("Veteran status", ["I identify as one or more of the classifications of protected veteran",
                        "I am not a protected veteran", DECLINE]),
])
def test_demographics_default_to_decline(title, options):
    assert answer(title, "select", options) == DECLINE


def test_name_pronunciation_is_not_the_name():
    assert answer("Name Pronunciation | How do you pronounce your name?", required=False) != VALUES["full_name"]


def test_high_school_year_is_not_college_grad_year():
    assert answer("Year of High School Graduation") != VALUES["grad_year"]


def test_level_of_education_is_bachelor_not_a_date():
    opts = ["Select the best option", "GED or High School", "Bachelor", "Masters", "Doctorate"]
    assert answer("Level of education completed once you've graduated?", "select", opts) == "Bachelor"


def test_graduation_year():
    assert answer("What is your anticipated graduation year?") == VALUES["grad_year"]


def test_currently_enrolled_is_yes_not_school_name():
    assert answer("Are you currently enrolled in a college or university?", "radio", ["Yes", "No"]) == "Yes"


def test_which_university_gives_school_name():
    assert VALUES["school"] in answer("Which university are you currently attending?")


def test_first_hear_about_job():
    opts = ["Select...", "LinkedIn - Job Posting", "Indeed", "Google", "Other"]
    assert answer("Where did you first hear about this job?", "select", opts) == "Other"


def test_current_company_comes_from_answers():
    assert answer("Current company", required=False) == "University of Example IT Services (Student Developer)"


def test_plain_company_field_left_alone():
    # A bare "Company" box usually sits inside work history; it must not get the current-company answer.
    assert answer("Company", required=False) == ""


def test_salary_is_never_auto_answered():
    assert answer("What are your salary expectations? (Hourly rate)") == ""


def test_job_answer_beats_profile_rule():
    ja = [{"q": "Will you now or in the future require sponsorship for employment visa status?", "a": "Yes"}]
    assert answer("Will you now or in the future require sponsorship for employment visa status?",
                  job_answers=ja) == "Yes"


def test_job_answer_can_tick_several_boxes():
    ja = [{"q": "What best describes the type of opportunities you're interested in:", "pick": ["^ios$", "^android$"]}]
    opts = ["iOS", "Backend", "Android", "Product"]
    got = answer("What best describes the type of opportunities you're interested in:", "checks", opts, job_answers=ja)
    assert got == "Tick: iOS, Android"


def test_no_does_not_match_prefer_not_to_say():
    assert A.pick_option(["Prefer not to say", "Unknown", "No"], None, "No") == 2
    assert A.pick_option(["Prefer not to say", "Unknown"], None, "No") is None


def test_short_saved_question_does_not_swallow_others():
    assert not A.label_matches("why do you want to work at acme on the payments team?", "why do you want to")
    assert A.label_matches("gender select ... male female", "gender select ... male female decline to self-identify")


def test_empty_placeholder_leaves_no_double_comma():
    # The sample has no apartment number (address_line2 is ""), the common case.
    assert answer("Street address") == "100 Example St, Springfield, Illinois 00000"
