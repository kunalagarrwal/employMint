#!/usr/bin/env python3
"""Stops a git push that would publish someone's personal details.

Your profile/, resumes/ and data/ are git-ignored, so they're never committed. This is the safety net for the
rest: it reads the personal details in profile/ (name, email, phone, links, school, employers, projects) and
checks every file in the commit being pushed, plus the commits' author and committer emails. Any match stops
the push and says where.

Install once:  ln -sf ../../tools/check_private.py .git/hooks/pre-push
Run by hand:   python3 tools/check_private.py
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_public import FORBIDDEN_STATIC, SITE_MEDIA, origin_owner, personal_strings, public_urls  # noqa: E402

ZERO = "0" * 40


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def find(texts, forbidden, allowed=()):
    """texts: {label: text}. Returns 'label: contains ...' for each personal string found (whole words only)."""
    hits = []
    for label, text in texts.items():
        for url in allowed:  # the project's own public addresses may carry the owner's GitHub handle
            text = re.sub(re.escape(url), "", text, flags=re.I)
        hits += [f"{label}: contains {s!r}" for s in forbidden
                 if re.search(rf"(?<!\w){re.escape(s)}(?!\w)", text + "\n" + label, re.I)]
    return hits


def files_at(rev):
    """{path: text} for every file in that commit. Binary files and website media are checked by name only."""
    out = {}
    for path in git("ls-tree", "-r", "--name-only", rev).splitlines():
        if Path(path).suffix in SITE_MEDIA and path.startswith("site/"):
            out[path] = ""
            continue
        blob = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True).stdout
        try:
            out[path] = blob.decode("utf-8")
        except UnicodeDecodeError:
            out[path] = ""
    return out


def pushed_ranges(stdin):
    """(local sha, remote sha) pairs from git's pre-push input; HEAD when run by hand."""
    text = "" if stdin.isatty() else stdin.read()
    if not text.strip():
        return [("HEAD", ZERO)]
    pairs = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1] != ZERO:  # a zero local sha means a branch is being deleted
            pairs.append((parts[1], parts[3]))
    return pairs


def main():
    personal = personal_strings()
    if not personal:
        print("check_private: no profile/ here, so only the fixed checks run.", file=sys.stderr)
    forbidden = sorted(personal | set(FORBIDDEN_STATIC))
    allowed = public_urls(origin_owner(ROOT))
    hits = []
    for local, remote in pushed_ranges(sys.stdin):
        hits += find(files_at(local), forbidden, allowed)
        span = local if remote == ZERO else f"{remote}..{local}"
        people = {f"commit {sha}": emails for sha, emails in
                  (line.split(" ", 1) for line in git("log", "--format=%h %ae %ce", span).splitlines())}
        hits += find(people, [s for s in forbidden if "@" in s])  # author and committer emails
    if hits:
        print("Push stopped: personal details found.\n  " + "\n  ".join(sorted(set(hits))), file=sys.stderr)
        sys.exit(1)
    print(f"check_private: no personal details found ({len(forbidden)} checked).", file=sys.stderr)


if __name__ == "__main__":
    main()
