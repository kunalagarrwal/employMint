"""Builds a shareable copy of employMint that contains no one's personal data.

Copies only an allowlist (code, tests, docs, skills, website, the made-up sample profile, install and agent
files) into ../employMint-public. The first time, it starts a fresh git history there, so nothing from this
repo's history comes along. If the destination is already a git repo (the published copy), it keeps that
history and adds one new commit, so the update can be pushed normally. profile/, resumes/, data/, evals
results and LinkedIn records are never copied.

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
ALLOW = ["src", "tests", "docs", "examples", "site", ".github", ".claude/skills", "tools/export_public.py", "tools/snapshot.py",
         "README.md", "AGENTS.md", "CLAUDE.md", "install.sh", "requirements.txt", "requirements-dev.txt",
         "pytest.ini", ".gitignore", ".gitattributes", "LICENSE"]
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc"}
SITE_MEDIA = {".png", ".jpg", ".webp", ".mp4"}  # the only binary files allowed, and only under site/
# Always forbidden, whatever the profile says: absolute home-folder paths.
FORBIDDEN_STATIC = ["/" + "Users/", "/" + "home/"]  # split so this file doesn't match itself


def drop_common_words(strings, dictionary):
    """Single ordinary words (a project called "Lamp") can't identify anyone and would match normal text;
    multi-word names, handles, emails and invented words (e.g. "Zorbify") are kept."""
    return {s for s in strings if not (s.isalpha() and s.lower() in dictionary)}


def load_dictionary(path="/usr/share/dict/words"):
    try:
        return {w.strip().lower() for w in open(path, encoding="utf-8", errors="ignore")}
    except OSError:
        return set()  # no word list: keep every string (stricter, never looser)


def strings_from(p, a, dictionary):
    """Identifying strings from a profile and answers. Identity (name, contact, handles, school, employers,
    city, address) is always kept; only project names and ids may be skipped as ordinary words."""
    c = p.get("contact", {})
    identity = {c.get("name"), c.get("email"), c.get("phone")}
    for url in (c.get("linkedin"), c.get("github")):
        identity.add((url or "").rstrip("/").rsplit("/", 1)[-1])  # the handle
    for ed in p.get("education", []):
        identity |= {ed.get("school"), ed.get("gpa")}
    for e in p.get("experience", []):
        identity |= {e.get("id"), e.get("org")}
    for cert in p.get("certifications", []):
        identity |= {cert.get("name"), cert.get("issuer")}
    v = a.get("values", {})
    identity |= {v.get(k) for k in ("full_name", "first_name", "last_name", "email", "phone", "address_line1",
                                    "address_line2", "postal_code", "city", "location", "gpa")}
    digits = re.sub(r"\D", "", c.get("phone") or "")
    if len(digits) >= 7:
        identity.add(f"{digits[-7:-4]}-{digits[-4:]}")
    projects = set()
    for x in p.get("projects", []):
        projects |= {x.get("id"), (x.get("name") or "").split(" - ")[0], x.get("url")}
    keep = lambda ss: {s.strip() for s in ss if isinstance(s, str) and len(s.strip()) >= 4}
    return keep(identity) | drop_common_words(keep(projects), dictionary)


def personal_strings():
    """Exact strings that identify the person whose profile/ is on this machine. Empty if there is none."""
    d = ROOT / "profile"
    try:
        p = json.loads((d / "profile.json").read_text(encoding="utf-8"))
        a = json.loads((d / "answers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return strings_from(p, a, load_dictionary())


def prepare_dest(dest):
    """Empties dest for a new export. Returns True when dest is an existing git repo, whose .git is kept."""
    dest = Path(dest)
    if (dest / ".git").is_dir():
        for child in dest.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
        return True
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    return False


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


def public_urls(owner):
    """The project's own public addresses, which may contain the owner's GitHub handle."""
    return [f"github.com/{owner}/employMint", f"{owner}.github.io/employMint"] if owner else []


def origin_owner(dest):
    """GitHub owner of the published copy's origin remote, or None."""
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=dest, capture_output=True, text=True).stdout
    m = re.search(r"github\.com[:/]([^/]+)/", url)
    return m.group(1) if m else None


def leaks(dest, forbidden, allowed=()):
    found = []
    for f in dest.rglob("*"):
        if not f.is_file() or ".git" in f.relative_to(dest).parts:
            continue
        rel = str(f.relative_to(dest))
        if f.suffix in SITE_MEDIA and f.relative_to(dest).parts[0] == "site":
            text = ""  # website images and the film: only the file name is checked
        else:
            try:
                text = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                found.append(f"{rel}: binary file (not allowed in the public copy)")
                continue
        for url in allowed:  # the project's own public URLs are fine
            text = re.sub(re.escape(url), "", text, flags=re.I)
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
    updating = prepare_dest(dest)
    for rel in ALLOW:
        copy_tree(ROOT / rel, dest / rel)

    found = leaks(dest, forbidden, allowed=public_urls(origin_owner(dest)) if updating else ())
    if found:
        if updating:  # put the published copy back exactly as it was
            subprocess.run(["git", "checkout", "--", "."], cwd=dest, check=False)
            subprocess.run(["git", "clean", "-fdq"], cwd=dest, check=False)
        else:
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
    if not updating:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    n = sum(1 for f in dest.rglob("*") if f.is_file() and ".git" not in f.relative_to(dest).parts)
    if updating and not subprocess.run(["git", "status", "--porcelain"], cwd=dest, capture_output=True,
                                       text=True).stdout.strip():
        print(f"No changes since the last export ({n} files). Nothing to commit.")
        return
    msg = "employMint: update from source" if updating else "employMint: public snapshot"
    subprocess.run(git + ["commit", "-q", "-m", msg], cwd=dest, check=True)
    print(f"{'Updated' if updating else 'Exported'} {n} files in {dest} (one new commit), checked against "
          f"{len(forbidden)} personal strings. Nothing was pushed.")


if __name__ == "__main__":
    main()
