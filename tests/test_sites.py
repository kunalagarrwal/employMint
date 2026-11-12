import apply as A


def test_form_urls():
    assert A.form_url("https://jobs.lever.co/acme/123") == "https://jobs.lever.co/acme/123/apply"
    assert A.form_url("https://jobs.ashbyhq.com/acme/abc?src=x") == "https://jobs.ashbyhq.com/acme/abc/application"
    assert A.form_url("https://boards.greenhouse.io/acme/jobs/42") == "https://job-boards.greenhouse.io/acme/jobs/42"


def test_site_detection():
    assert A.site_of("https://acme.wd5.myworkdayjobs.com/x") == "workday"
    assert A.site_of("https://jobs.lever.co/acme/1/apply") == "lever"
    assert A.site_of("https://example.com/careers") == "other"


def test_confirmation_pages_detected():
    for text in ["Application Submitted. Your application has successfully been submitted.",
                 "Thank you for applying!", "We've received your application"]:
        assert A.CONFIRM_TEXT.search(text), text
    assert A.CONFIRM_URL.search("https://x.myworkdayjobs.com/en-US/jobTasks/completed/application")


def test_not_a_confirmation():
    assert not A.CONFIRM_TEXT.search("Thank you for your interest in our company")


def test_site_by_hostname_not_substring():
    assert A.site_of("https://clever.co/jobs/1") == "other"
    assert A.site_of("https://example.com/?ref=greenhouse") == "other"
    assert A.site_of("https://acme.com/careers?gh_jid=123") == "greenhouse"
