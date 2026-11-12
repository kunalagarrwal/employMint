"""Refactor guard: records what the pipeline produces for the current profile, as hashes.

Run it before a refactor and after, then compare. Any difference means the refactor changed real output.
Only hashes and file names are written (to data/, which git ignores), never personal text.

Usage:
  python3 tools/snapshot.py save before
  python3 tools/snapshot.py save after
  python3 tools/snapshot.py diff before after
"""
import contextlib
import hashlib
import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "data"


def h(obj):
    text = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def collect():
    import answers as A
    import apply as AP
    import cover as C
    import jobs as J
    import render as R
    import verify as V

    profile = json.loads(V.PROFILE_PATH.read_text())
    prefs = J.load_prefs()
    snap = {"names": {"resume": A.RESUME_NAME, "render": R.OUTPUT_NAME, "cover": C.OUTPUT_NAME,
                      "transcript": str(A.TRANSCRIPT.relative_to(ROOT))}}

    for t in sorted(ROOT.glob("resumes/*/tailored.json")):
        tailored = json.loads(t.read_text())
        key = t.parent.name
        snap[f"resume:{key}"] = h(R.build_html(tailored, profile, 10.5))
        snap[f"verify:{key}"] = h(V.verify(tailored, profile))
    for c in sorted(ROOT.glob("resumes/*/cover.json")):
        cover = json.loads(c.read_text())
        key = c.parent.name
        snap[f"cover:{key}"] = h(C.build_html(cover, profile, 11.0)) + h(C.check(cover, profile)) + h(C.plain_text(cover, profile))

    for jd in sorted(J.JD_DIR.glob("*.md")):
        text = jd.read_text(encoding="utf-8", errors="ignore")
        flags = J.visa_flags(text)
        snap[f"jd:{jd.name}"] = h([J.eligibility(flags, text), J.grad_check(text), J.sponsorship_signal(text, ",".join(flags))])

    db = sqlite3.connect(J.DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    snap["classify"] = h([[r["id"], J.classify(r, prefs)] for r in rows])
    for r in rows:
        if r["resume_dir"]:
            job = dict(r)
            vals = A.job_values(job, A.load_rules()[1])
            items = AP.manual_items(job, "workday", A.resume_path(job))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                AP.cmd_sheet(job)
            snap[f"apply:{r['id']}"] = h([vals, items, buf.getvalue()])
    return snap


def main():
    cmd, *names = sys.argv[1:] or ["help"]
    if cmd == "save" and len(names) == 1:
        snap = collect()
        path = OUT / f"snapshot-{names[0]}.json"
        path.write_text(json.dumps(snap, indent=1, sort_keys=True))
        print(f"Saved {len(snap)} entries to {path.relative_to(ROOT)}")
    elif cmd == "diff" and len(names) == 2:
        a, b = (json.loads((OUT / f"snapshot-{n}.json").read_text()) for n in names)
        changed = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
        for k in changed:
            print(f"  {k}: {a.get(k)} -> {b.get(k)}")
        print(f"{len(changed)} of {len(a)} entries differ.")
        sys.exit(1 if changed else 0)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
