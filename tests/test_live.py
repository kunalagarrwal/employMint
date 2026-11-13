"""Posting checks (src/live.py) and how approved jobs are grouped and ordered. No network: http_get is faked."""
import json
import sqlite3
import urllib.error

import pytest

import apply as A
import live as L


def fake_http(monkeypatch, responses):
    """responses: {url prefix: (status, body)}. Anything unmatched raises a network error."""
    def get(url, timeout=25, headers=None):
        for prefix, (code, body) in responses.items():
            if url.startswith(prefix):
                if code != 200:
                    raise urllib.error.HTTPError(url, code, "x", {}, None)
                return body
        raise OSError("offline")
    monkeypatch.setattr(L, "http_get", get)


def test_greenhouse_404_is_closed(monkeypatch):
    fake_http(monkeypatch, {"https://boards-api.greenhouse.io/": (404, "")})
    assert L.check_url("https://job-boards.greenhouse.io/brex/jobs/123")[0] == L.CLOSED


def test_greenhouse_listed_is_open(monkeypatch):
    fake_http(monkeypatch, {"https://boards-api.greenhouse.io/": (200, "{}")})
    assert L.check_url("https://boards.greenhouse.io/virtu/jobs/9")[0] == L.OPEN


def test_ashby_missing_id_is_closed(monkeypatch):
    fake_http(monkeypatch, {"https://api.ashbyhq.com/": (200, json.dumps({"jobs": [{"id": "other"}]}))})
    assert L.check_url("https://jobs.ashbyhq.com/notion/abc")[0] == L.CLOSED


def test_workday_cannot_apply_is_closed(monkeypatch):
    fake_http(monkeypatch, {"https://acme.wd5.myworkdayjobs.com/wday/": (200, json.dumps({"jobPostingInfo": {"canApply": False}}))})
    assert L.check_url("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/NY/Intern_R1")[0] == L.CLOSED


def test_blocked_request_is_never_closed(monkeypatch):
    fake_http(monkeypatch, {"https://acme.wd5.myworkdayjobs.com/": (403, "")})
    assert L.check_url("https://acme.wd5.myworkdayjobs.com/careers/job/NY/Intern_R1")[0] == L.UNKNOWN


def test_network_error_is_never_closed(monkeypatch):
    fake_http(monkeypatch, {})
    assert L.check_url("https://jobs.lever.co/zoox/abc")[0] == L.UNKNOWN


def test_company_page_closed_message(monkeypatch):
    fake_http(monkeypatch, {"https://careers.example.com/": (200, "<h1>Sorry, this position has been filled.</h1>")})
    assert L.check_url("https://careers.example.com/jobs/1")[0] == L.CLOSED


def test_ordinary_company_page_is_unknown(monkeypatch):
    fake_http(monkeypatch, {"https://careers.example.com/": (200, "<h1>Software Intern</h1><p>Apply now</p>")})
    assert L.check_url("https://careers.example.com/jobs/1")[0] == L.UNKNOWN


def test_simplify_closed_only_decides_when_the_site_cannot():
    assert L.decide(L.UNKNOWN, "?", 0)[0] == L.CLOSED
    assert L.decide(L.OPEN, "listed", 0)[0] == L.OPEN  # the site's own answer wins
    assert L.decide(L.UNKNOWN, "?", 1)[0] == L.UNKNOWN


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "jobs.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, company TEXT, url TEXT, active INTEGER, app_status TEXT,"
                " decided_at TEXT, live_state TEXT, live_reason TEXT, live_checked_at TEXT)")
    con.executemany("INSERT INTO jobs (id, company, url, active, app_status) VALUES (?,?,?,?,?)", [
        ("a", "Gone Co", "https://jobs.lever.co/gone/1", 1, "approved"),
        ("b", "Open Co", "https://jobs.lever.co/open/1", 1, "approved"),
        ("c", "Kept Co", "https://jobs.lever.co/gone/2", 1, "approved"),
        ("d", "Applied Co", "https://jobs.lever.co/gone/3", 1, "applied"),
    ])
    con.execute("UPDATE jobs SET live_state=? WHERE id='c'", (L.USER_OPEN,))
    con.commit()
    con.close()

    def connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(L, "db_connect", connect)
    fake_http(monkeypatch, {"https://api.lever.co/v0/postings/gone/": (404, ""), "https://api.lever.co/v0/postings/open/": (200, "{}")})
    return connect


def test_closed_approved_job_moves_to_closed(db):
    out = L.check_statuses(("approved",))
    con = db()
    status = dict(con.execute("SELECT id, app_status FROM jobs").fetchall())
    assert status == {"a": "closed", "b": "approved", "c": "approved", "d": "applied"}
    assert len(out[L.CLOSED]) == 1 and len(out[L.OPEN]) == 1


def test_job_you_reopened_is_not_closed_again(db):
    assert L.ensure_open("c") == (True, "you said it's open")


def test_groups():
    assert A.group_of("https://job-boards.greenhouse.io/x/jobs/1") == "quick"
    assert A.group_of("https://jobs.ashbyhq.com/x/1") == "quick"
    assert A.group_of("https://x.wd1.myworkdayjobs.com/careers/job/1") == "workday"
    assert A.group_of("https://jobs.lever.co/x/1") == "manual"
    assert A.group_of("https://careers.example.com/1") == "manual"


def test_queue_is_quickest_group_first_then_longest_waiting(monkeypatch):
    rows = [  # already in the SQL order: oldest approval first
        {"id": "1", "url": "https://x.wd1.myworkdayjobs.com/careers/job/1", "decided_at": "2026-11-01"},
        {"id": "2", "url": "https://job-boards.greenhouse.io/x/jobs/2", "decided_at": "2026-11-02"},
        {"id": "3", "url": "https://job-boards.greenhouse.io/x/jobs/3", "decided_at": "2026-11-05"},
        {"id": "4", "url": "https://jobs.lever.co/x/4", "decided_at": "2026-11-03"},
    ]

    class FakeDB:
        def execute(self, *a):
            return self

        def fetchall(self):
            return rows

        def close(self):
            pass
    monkeypatch.setattr(A, "db_connect", FakeDB)
    monkeypatch.setattr(A, "resume_path", lambda r: "resume.pdf")
    assert [r["id"] for r in A.queue_jobs()] == ["2", "3", "1", "4"]
    assert [r["id"] for r in A.queue_jobs(group="workday")] == ["1"]
