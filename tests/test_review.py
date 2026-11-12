import review as R


def test_only_http_links_are_rendered():
    assert R.safe_url("https://jobs.lever.co/x") == "https://jobs.lever.co/x"
    assert R.safe_url("javascript:alert(1)") == "#"
    assert R.safe_url("") == "#"
