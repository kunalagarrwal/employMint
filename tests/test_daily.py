"""The "Find today's jobs" runner (src/daily.py). Never starts Claude: the claude lookup and processes are faked."""
import json

import daily as D


def test_claude_can_only_scan_forms_never_open_or_submit():
    tools = " ".join(D.allowed_tools())
    assert "src/apply.py scan" in tools
    for risky in ("apply.py open", "apply.py queue", "apply.py:", "outreach", "linkedin", "Bash(python3:*)", "Bash(*)"):
        assert risky not in tools


def test_writing_is_limited_to_resumes():
    writes = [t for t in D.allowed_tools() if t.startswith(("Edit", "Write"))]
    assert writes and all(t.endswith("(resumes/**)") for t in writes)


def test_friendly_message_without_claude(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "STATE", tmp_path / "batch-run.json")
    monkeypatch.setattr(D, "find_claude", lambda: None)
    started, message = D.start()
    assert not started and "Claude Code" in message and "Run today's batch" in message


def test_a_run_that_died_does_not_block_the_button(monkeypatch, tmp_path):
    state = tmp_path / "batch-run.json"
    state.write_text(json.dumps({"pid": 999_999_999, "started": "2026-11-13T10:00:00+00:00", "log": "x"}))
    monkeypatch.setattr(D, "STATE", state)
    assert D.running() is None and not state.exists()


def test_only_one_batch_at_a_time(monkeypatch, tmp_path):
    monkeypatch.setattr(D, "running", lambda: {"pid": 1})
    assert D.start() == (False, "Today's batch is already running.")
