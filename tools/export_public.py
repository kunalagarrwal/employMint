"""Builds a shareable copy of employMint that contains no one's personal data.

Copies only an allowlist (code, tests, docs, skills, the made-up sample profile, install and agent files)
into ../employMint-public and starts a fresh git history there, so nothing from this repo's history comes
along. profile/, resumes/, data/, evals results and LinkedIn records are never copied.

Before finishing it scans every copied file (names and contents) for this machine's personal details,
read from profile/ (name, email, phone, links, school, address, employers, projects), plus a fixed list.
Any hit deletes the copy and stops. Then it runs the tests inside the copy. Nothing is pushed anywhere.

Usage: python3 tools/export_public.py [--dest ../employMint-public]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW = ["src", "tests", "docs", "examples", ".claude/skills", "tools/export_public.py", "tools/snapshot.py",
         "README.md", "AGENTS.md", "CLAUDE.md", "install.sh", "requirements.txt", "requirements-dev.txt",
         "pytest.ini", ".gitignore", ".gitattributes", "LICENSE"]
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc"}
# Always forbidden, whatever the profile says: absolute home-folder paths.
FORBIDDEN_STATIC = ["/" + "Users/", "/" + "home/"]  # split so this file doesn't match itself


def personal_strings():
    """Exact strings that identify the person whose profile/ is on this machine. Empty if there is none."""
    d = ROOT / "profile"
    try:
        p = json.loads((d / "profile.json").read_text(encoding="utf-8"))
        a = json.loads((d / "answers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    c = p.get("contact", {})
    out = {c.get("name"), c.get("email"), c.get("phone")}
    for url in (c.get("linkedin"), c.get("github")):
        out.add((url or "").rstrip("/").rsplit("/", 1)[-1])  # the handle
    for ed in p.get("education", []):
        out |= {ed.get("school"), ed.get("gpa")}
    for e in p.get("experience", []):
        out |= {e.get("id"), e.get("org")}
    for x in p.get("projects", []):
        out |= {x.get("id"), (x.get("name") or "").split(" - ")[0], x.get("url")}
    for cert in p.get("certifications", []):
        out |= {cert.get("name"), cert.get("issuer")}
    v = a.get("values", {})
    out |= {v.get(k) for k in ("full_name", "first_name", "last_name", "email", "phone", "address_line1",
                               "address_line2", "postal_code", "city", "location", "gpa")}
    digits = re.sub(r"\D", "", c.get("phone") or "")
    if len(digits) >= 7:
        out.add(f"{digits[-7:-4]}-{digits[-4:]}")
    # Keep strings long enough to be identifying; drop empties and short words that match ordinary text.
    return {s.strip() for s in out if isinstance(s, str) and len(s.strip()) >= 4}


def copy_tree(src, dst):
    if src.is_file():
        files = [(src, dst)]
    elif src.is_dir():
        files = [(f, dst / f.relative_to(src)) for f in src.rglob("*") if f.is_file()]
    else:
        files = []
    for f, out in files:
        if SKIP_PARTS & set(f.parts) or f.suffix in SKIP_SUFFIXES:
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)  # keeps install.sh executable


def leaks(dest, forbidden):
    found = []
    for f in dest.rglob("*"):
        if not f.is_file() or ".git" in f.relative_to(dest).parts:
            continue
        rel = str(f.relative_to(dest))
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            found.append(f"{rel}: binary file (not allowed in the public copy)")
            continue
        # Whole words only, so a short project name doesn't match inside a longer word.
        found += [f"{rel}: contains {s!r}" for s in forbidden
                  if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", text + "\n" + rel, re.I)]
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", default=str(ROOT.parent / "employMint-public"))
    dest = Path(ap.parse_args().dest).resolve()
    if dest == ROOT or ROOT in dest.parents:
        sys.exit("Destination must be outside this project.")
    personal = personal_strings()
    if not personal:
        print("WARN no profile/ found, so only the fixed checks run.")
    forbidden = sorted(personal | set(FORBIDDEN_STATIC))
    if dest.exists():
        shutil.rmtree(dest)
    for rel in ALLOW:
        copy_tree(ROOT / rel, dest / rel)

    found = leaks(dest, forbidden)
    if found:
        shutil.rmtree(dest)
        sys.exit("Personal data found; nothing exported:\n  " + "\n  ".join(found))

    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=dest,
                           capture_output=True, text=True)
    last = tests.stdout.strip().splitlines()[-1] if tests.stdout.strip() else tests.stderr[-500:]
    print(f"Tests in the copy: {last}")
    if tests.returncode != 0:
        sys.exit(f"Tests failed in {dest}; fix them before sharing.")
    for junk in dest.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)
    name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True).stdout.strip() or "employMint"
    git = ["git", "-c", f"user.name={name}", "-c", "user.email=employmint@example.com"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(git + ["commit", "-q", "-m", "employMint: public snapshot"], cwd=dest, check=True)
    n = sum(1 for f in dest.rglob("*") if f.is_file() and ".git" not in f.relative_to(dest).parts)
    print(f"Exported {n} files to {dest}, checked against {len(forbidden)} personal strings. Nothing was pushed.")


if __name__ == "__main__":
    main()
