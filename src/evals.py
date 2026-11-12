"""Measures the quality of employMint's output, so changes can be judged by numbers instead of by feel.

  1. Form answers: accuracy of the answer rules on a hand-checked set (evals/golden_answers.json).
  2. Coverage: share of required questions on real scanned forms that get answered without the applicant.
  3. Resumes: every bullet traced to a profile fact (verify.py), one-line bullets, bullets with a number.
  4. Cover letters: fact checks pass (cover.py), length in range, no stock phrases.
  5. Page fill (--fill, slow): how full each one-page resume is, using headless Chrome.

Writes evals/report.md and appends a summary line to evals/history.jsonl.
Usage: python3 src/evals.py [--fill] [--quiet]
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply as A  # noqa: E402
import cover as C  # noqa: E402
import verify as V  # noqa: E402
from jobs import ROOT  # noqa: E402

EVALS = ROOT / "evals"
RESUMES = ROOT / "resumes"


def pct(n, d):
    return round(100 * n / d, 1) if d else 0.0


def answer_for(title, kind="text", options=(), required=True, job_answers=(), rules=None, values=None):
    q = {"i": 0, "title": title, "kind": kind, "options": list(options), "required": required, "value": ""}
    text, note = A.sheet_answer(q, A.resolve(q, rules, values, list(job_answers)))
    return text, note


def eval_answers(rules, values):
    golden = EVALS / "golden_answers.json"
    if not golden.exists():  # a new user has no hand-checked set yet
        return {"cases": 0, "correct": 0, "accuracy": 0.0, "misses": []}
    cases = json.loads(golden.read_text(encoding="utf-8"))["cases"]
    misses = []
    for c in cases:
        got, _ = answer_for(c["q"], c.get("kind", "text"), c.get("options", []), rules=rules, values=values)
        ok = (got == "" if c.get("blank") else
              c["contains"].lower() in got.lower() if "contains" in c else got == c["expect"])
        if not ok:
            want = "(blank)" if c.get("blank") else c.get("expect") or f"contains {c['contains']!r}"
            misses.append({"q": c["q"], "want": want, "got": got or "(blank)"})
    return {"cases": len(cases), "correct": len(cases) - len(misses), "accuracy": pct(len(cases) - len(misses), len(cases)),
            "misses": misses}


def eval_coverage(rules, values):
    """Required, non-file questions on every scanned form: answered automatically vs left for the applicant."""
    total = answered = 0
    gaps = Counter()
    for qf in sorted(RESUMES.glob("*/questions.json")):
        data = json.loads(qf.read_text())
        ja_path = qf.parent / "answers.json"
        job_answers = json.loads(ja_path.read_text()).get("answers", []) if ja_path.exists() else []
        for q in data.get("questions", []):
            if not q.get("required") or q.get("kind") == "file":
                continue
            total += 1
            got, _ = answer_for(q["label"], q.get("kind", "text"), q.get("options", []), True, job_answers, rules, values)
            if got:
                answered += 1
            else:
                gaps[A.norm(q["label"])[:70]] += 1
    return {"forms": len(list(RESUMES.glob("*/questions.json"))), "required_questions": total, "auto_answered": answered,
            "coverage": pct(answered, total), "top_gaps": gaps.most_common(8)}


def eval_resumes(profile):
    rows, bullets, one_line, with_number, cliches = [], 0, 0, 0, 0
    for tf in sorted(RESUMES.glob("*/tailored.json")):
        t = json.loads(tf.read_text())
        errors, warnings = V.verify(t, profile)
        bs = [b["text"] for sec in ("experience", "projects") for it in t.get(sec, []) for b in it.get("bullets", [])]
        bullets += len(bs)
        one_line += sum(len(b) <= 100 for b in bs)
        with_number += sum(bool(re.search(r"\d", b)) for b in bs)
        cliches += sum("cliche" in w for w in warnings)
        rows.append({"resume": tf.parent.name, "errors": len(errors), "first_error": errors[0] if errors else ""})
    clean = sum(r["errors"] == 0 for r in rows)
    return {"resumes": len(rows), "fully_grounded": clean, "grounded_pct": pct(clean, len(rows)), "bullets": bullets,
            "one_line_pct": pct(one_line, bullets), "with_number_pct": pct(with_number, bullets), "cliche_warnings": cliches,
            "failing": [r for r in rows if r["errors"]]}


def eval_covers(profile):
    rows = []
    for cf in sorted(RESUMES.glob("*/cover.json")):
        cv = json.loads(cf.read_text())
        errors, warnings = C.check(cv, profile)
        words = sum(len(p["text"].split()) for p in cv.get("paragraphs", []))
        stock = sum("stock" in w.lower() or "phrase" in w.lower() for w in warnings)
        rows.append({"letter": cf.parent.name, "errors": len(errors), "words": words, "stock": stock,
                     "first_error": errors[0] if errors else ""})
    n = len(rows)
    return {"letters": n, "fact_checked_pct": pct(sum(r["errors"] == 0 for r in rows), n),
            "length_ok_pct": pct(sum(C.WORDS[0] <= r["words"] <= C.WORDS[1] for r in rows), n),
            "stock_phrase_letters": sum(r["stock"] > 0 for r in rows), "failing": [r for r in rows if r["errors"]]}


def eval_fill(profile):
    import render as R
    fills = []
    for tf in sorted(RESUMES.glob("*/tailored.json")):
        t = json.loads(tf.read_text())
        fill, _ = R.measure(R.build_html(t, profile, R.FONT_SIZES[0], measure=True))
        if fill is not None:
            fills.append(min(fill, 1.0))
    return {"measured": len(fills), "avg_fill_pct": pct(sum(fills), len(fills)),
            "under_90_pct": sum(f < R.TARGET_FILL for f in fills)}


def report_md(res):
    a, cov, r, c = res["answers"], res["coverage"], res["resumes"], res["covers"]
    out = [f"# employMint quality report", f"_Generated {res['at']}_", "",
           "| Measure | Result |", "|---|---|",
           (f"| Form-answer accuracy (hand-checked set) | **{a['accuracy']}%** ({a['correct']}/{a['cases']}) |" if a["cases"]
            else "| Form-answer accuracy (hand-checked set) | none yet: add cases to evals/golden_answers.json |"),
           f"| Required questions answered automatically | **{cov['coverage']}%** ({cov['auto_answered']}/{cov['required_questions']} on {cov['forms']} real forms) |",
           f"| Resumes with every bullet traced to a fact | **{r['grounded_pct']}%** ({r['fully_grounded']}/{r['resumes']}) |",
           f"| Bullets that fit on one line | {r['one_line_pct']}% of {r['bullets']} |",
           f"| Bullets with a measurable number | {r['with_number_pct']}% |",
           f"| Cover letters passing the fact check | **{c['fact_checked_pct']}%** of {c['letters']} |",
           f"| Cover letters within 220–380 words | {c['length_ok_pct']}% |"]
    if "fill" in res:
        out.append(f"| Average resume page fill | {res['fill']['avg_fill_pct']}% ({res['fill']['under_90_pct']} under 90%) |")
    if a["misses"]:
        out += ["", "## Form answers it got wrong", ""] + [f"- **{m['q']}**: wanted {m['want']}, got {m['got']}" for m in a["misses"]]
    out += ["", "## Questions most often left for you", ""] + [f"- {q} ({n}×)" for q, n in cov["top_gaps"]]
    if r["failing"]:
        out += ["", "## Resumes that fail the fact check", ""] + [f"- {x['resume']}: {x['first_error']}" for x in r["failing"]]
    if c["failing"]:
        out += ["", "## Cover letters that fail the fact check", ""] + [f"- {x['letter']}: {x['first_error']}" for x in c["failing"]]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fill", action="store_true", help="also measure page fill in Chrome (slow)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    rules, values = A.load_rules()
    profile = json.loads(V.PROFILE_PATH.read_text())
    res = {"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "answers": eval_answers(rules, values),
           "coverage": eval_coverage(rules, values), "resumes": eval_resumes(profile), "covers": eval_covers(profile)}
    if args.fill:
        res["fill"] = eval_fill(profile)
    md = report_md(res)
    (EVALS / "report.md").write_text(md, encoding="utf-8")
    summary = {"at": res["at"], "answer_accuracy": res["answers"]["accuracy"], "coverage": res["coverage"]["coverage"],
               "resumes_grounded": res["resumes"]["grounded_pct"], "covers_checked": res["covers"]["fact_checked_pct"]}
    with open(EVALS / "history.jsonl", "a") as f:
        f.write(json.dumps(summary) + "\n")
    if not args.quiet:
        print(md)
    # Non-zero exit when a hand-checked answer is wrong, so this can gate changes to the rules.
    sys.exit(1 if res["answers"]["misses"] else 0)


if __name__ == "__main__":
    main()
