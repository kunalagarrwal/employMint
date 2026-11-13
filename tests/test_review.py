import review as R


def test_only_http_links_are_rendered():
    assert R.safe_url("https://jobs.lever.co/x") == "https://jobs.lever.co/x"
    assert R.safe_url("javascript:alert(1)") == "#"
    assert R.safe_url("") == "#"


# ---- recording what happened after you applied (a throwaway database, never data/jobs.sqlite)
import json  # noqa: E402
import threading  # noqa: E402
import urllib.request  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

import pytest  # noqa: E402

import jobs as J  # noqa: E402


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "DATA", tmp_path)
    monkeypatch.setattr(J, "DB_PATH", tmp_path / "jobs.sqlite")
    db = J.db_connect()
    for jid, status in (("a", "applied"), ("b", "interview"), ("c", "rejected"), ("d", "tailored")):
        db.execute("INSERT INTO jobs (id, company, title, url, app_status, batch_date) VALUES (?,?,?,?,?,?)",
                   (jid, "Co " + jid, "Intern", "https://jobs.lever.co/x/" + jid, status, "2026-11-13"))
    db.commit()
    db.close()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), R.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def decide(port, jid, decision):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/decide", method="POST",
                                 data=json.dumps({"id": jid, "decision": decision}).encode(),
                                 headers={"X-Employmint": "1", "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as ex:
        return ex.code


def status(jid):
    db = J.db_connect()
    try:
        return db.execute("SELECT app_status FROM jobs WHERE id=?", (jid,)).fetchone()[0]
    finally:
        db.close()


def test_applied_moves_forward_and_back(server):
    assert decide(server, "a", "interview") == 200 and status("a") == "interview"
    assert decide(server, "a", "offer") == 200 and status("a") == "offer"


def test_rejection_can_be_recorded_and_taken_back(server):
    assert decide(server, "b", "rejected") == 200 and status("b") == "rejected"
    assert decide(server, "c", "unreject") == 200 and status("c") == "applied"


def test_outcomes_need_an_application_first(server):
    assert decide(server, "d", "interview") == 409 and status("d") == "tailored"


def test_row_offers_only_the_next_steps():
    r = {"id": "x", "company": "Co", "title": "Intern", "url": "https://jobs.lever.co/x/1", "app_status": "interview",
         "decided_at": "2026-11-10T10:00:00+00:00", "notes": None, "resume_dir": None, "live_reason": None}
    html = R.row(r)
    assert 'data-d="offer"' in html and 'data-d="rejected"' in html
    assert 'data-d="assessment"' not in html and 'data-d="undo"' not in html
