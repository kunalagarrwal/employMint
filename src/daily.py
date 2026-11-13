"""Runs today's batch with Claude in the background: the review page's "Find today's jobs" button.

The same work as saying "Run today's batch" to your assistant (.claude/skills/daily-batch/SKILL.md, steps 1-3):
refresh listings, pick today's jobs, and tailor a resume (plus form answers and a cover letter where needed) for each.
Tailored jobs show up on the review page as they're finished.

Claude runs with only the tools this needs: reading files, writing inside resumes/, and the employMint commands that
refresh and score listings, render and verify resumes and letters, and scan forms. It can't open a form to submit it,
send anything, change profile/, or run other commands.

Usage:
  python3 src/daily.py start    # start in the background (what the button does)
  python3 src/daily.py status   # is a batch running?
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import ROOT, now_iso  # noqa: E402

LOGS = ROOT / "data" / "batch-logs"
STATE = ROOT / "data" / "batch-run.json"  # {pid, started, log} while a batch runs

PROMPT = """Run today's internship batch for the applicant. Read AGENTS.md and profile/guidance.md (if it exists), then
follow .claude/skills/daily-batch/SKILL.md steps 1 to 3.
- Tailor the jobs one after another; don't start subagents.
- Skip steps 4 and 5: the review page is already open and shows each job as soon as it's tailored.
- Never open an application to submit it and never submit anything. Of src/apply.py, only `scan` is allowed.
Finish with one line: how many jobs you tailored and how many you skipped, and why."""


def python_cmd():
    """The interpreter the skills tell Claude to use (AGENTS.md: .venv/bin/python when it exists)."""
    return ".venv/bin/python" if (ROOT / ".venv" / "bin" / "python").exists() else "python3"


def allowed_tools():
    py = python_cmd()
    tools = ["Read", "Glob", "Grep", "Edit(resumes/**)", "Write(resumes/**)", "Bash(sqlite3 data/jobs.sqlite:*)"]
    for cmd in ("src/jobs.py", "src/render.py", "src/cover.py", "src/apply.py scan", "src/profile_check.py"):
        tools.append(f"Bash({py} {cmd}:*)")
    return tools


def find_claude():
    """The claude command: on PATH, or in the usual install places (an app launched from Finder has a short PATH)."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [home / ".claude/local/claude", home / ".local/bin/claude", Path("/opt/homebrew/bin/claude"),
                  Path("/usr/local/bin/claude")] + sorted(home.glob(".nvm/versions/node/*/bin/claude"), reverse=True)
    return next((str(c) for c in candidates if c.exists()), None)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def running():
    """{pid, started, log} for the batch in progress, or None. A run that died leaves no stale state behind."""
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None
    if _alive(state.get("pid")):
        return state
    STATE.unlink(missing_ok=True)
    return None


def start():
    """Starts the batch in the background. Returns (started, message)."""
    if running():
        return False, "Today's batch is already running."
    claude = find_claude()
    if not claude:
        return False, ("Claude Code isn't installed, so the batch can't run from here. Install it from "
                       "claude.com/claude-code, or say \"Run today's batch\" in your AI assistant.")
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{datetime.now():%Y-%m-%d-%H%M}.log"
    log = open(log_path, "a")
    log.write(f"=== {now_iso()} daily batch\n")
    log.flush()
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run", claude], cwd=str(ROOT),
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    STATE.write_text(json.dumps({"pid": proc.pid, "started": now_iso(), "log": str(log_path.relative_to(ROOT))}))
    return True, "Started."


def run(claude):
    """The background runner: Claude does the batch, then a notification says it's ready."""
    try:
        result = subprocess.run([claude, "-p", PROMPT, "--allowedTools", *allowed_tools()], cwd=str(ROOT),
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
        print(result.stdout + result.stderr, flush=True)
        last = (result.stdout.strip().splitlines() or ["Finished."])[-1][:180]
        notify("employMint: today's jobs are ready" if result.returncode == 0 else "employMint: the batch stopped early",
               last if result.returncode == 0 else "Open the review page to see what was done.")
    finally:
        STATE.unlink(missing_ok=True)


def notify(title, message):
    """macOS notification; silently nothing elsewhere."""
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f"display notification {json.dumps(message)} with title {json.dumps(title)}"],
                       capture_output=True, timeout=10, check=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["start", "status", "run"])
    ap.add_argument("claude", nargs="?")
    args = ap.parse_args()
    if args.command == "run":
        return run(args.claude or find_claude())
    if args.command == "start":
        print(start()[1])
    else:
        state = running()
        print(f"Running since {state['started']} (log: {state['log']})" if state else "Not running.")


if __name__ == "__main__":
    main()
