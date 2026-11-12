"""Turns resumes/<slug>/cover.json into a one-page cover letter PDF (+ cover.txt for paste-in boxes).

Every paragraph cites the profile facts it uses ("sources": ["<entry id>:12", ...]). The checker refuses to
render if a paragraph has a number or tech term that isn't in its cited facts, the profile's skills, or the
job description (facts about the company may come from the posting). It also flags stock cover-letter phrases.

cover.json:
{
  "job": {"id": "simplify:...", "company": "...", "title": "..."},
  "greeting": "Dear Hive Financial Systems Hiring Team,",
  "paragraphs": [{"text": "...", "sources": ["<entry id>:12"]}],
  "closing": "Sincerely,"
}

Usage: python3 src/cover.py resumes/<slug>/cover.json
"""
import datetime
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import jd_file  # noqa: E402
from render import to_pdf  # noqa: E402
import me  # noqa: E402
from verify import PROFILE_PATH, all_profile_skills, numbers_in, profile_entries, terms_in  # noqa: E402

OUTPUT_NAME = me.cover_name(me.profile())
WORDS = (220, 380)
STOCK_PHRASES = [
    "i am writing to express", "i am excited to apply", "i am thrilled", "passionate", "esteemed", "leverage",
    "synergy", "dynamic team", "fast-paced environment", "team player", "hard-working", "go-getter",
    "perfect fit", "dream job", "to whom it may concern", "spearhead", "utilize", "i believe i would be",
]
e = html.escape


def check(cover, profile):
    errors, warnings = [], []
    entries = profile_entries(profile)
    skills_vocab = " ".join(all_profile_skills(profile))
    jd = jd_file(cover["job"]["id"]) if cover.get("job", {}).get("id") else None
    jd_text = jd.read_text(encoding="utf-8") if jd and jd.exists() else ""
    if not jd_text:
        warnings.append("no saved job description: company facts can't be checked")
    profile_numbers = numbers_in(json.dumps({k: profile[k] for k in ("contact", "education")}))
    all_words = 0
    for n, para in enumerate(cover.get("paragraphs", []), 1):
        text = para["text"]
        all_words += len(text.split())
        source_text = ""
        for ref in para.get("sources", []):
            eid, _, idx = ref.partition(":")
            if eid not in entries:
                errors.append(f"paragraph {n}: unknown source '{ref}'")
                continue
            entry = entries[eid][1]
            facts = entry.get("facts", [])
            if not idx.isdigit() or int(idx) >= len(facts):
                errors.append(f"paragraph {n}: source '{ref}' out of range")
                continue
            source_text += " " + facts[int(idx)] + " " + " ".join(entry.get("skills", []))
        allowed_text = source_text + " " + jd_text
        extra = numbers_in(text) - numbers_in(allowed_text) - profile_numbers - me.known_years(profile, me.prefs())
        if extra:
            errors.append(f"paragraph {n}: numbers not in its sources or the posting: {sorted(extra)}")
        extra_terms = terms_in(text) - terms_in(allowed_text + " " + skills_vocab)
        if extra_terms:
            errors.append(f"paragraph {n}: tech not in its sources, skills or the posting: {sorted(extra_terms)}")
        for p in STOCK_PHRASES:
            if p in text.lower():
                warnings.append(f"paragraph {n}: stock phrase '{p}'")
    if not WORDS[0] <= all_words <= WORDS[1]:
        warnings.append(f"{all_words} words (aim for {WORDS[0]}-{WORDS[1]})")
    return errors, warnings


def build_html(cover, profile, font_pt):
    c = profile["contact"]

    def short(u):
        return re.sub(r"^https?://(www\.)?", "", u)

    contact = " | ".join(x for x in [e(c["phone"]), e(c["email"]), e(short(c["linkedin"])), e(short(c["github"]))] if x)
    today = me.long_date(datetime.date.today())
    paras = "".join(f"<p>{e(p['text'])}</p>" for p in cover["paragraphs"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(c['name'])} Cover Letter</title>
<style>
@page {{ size: Letter; margin: 0.8in 0.9in; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "Times New Roman", Times, serif; font-size: {font_pt}pt; line-height: 1.35; color: #000; }}
h1 {{ font-size: {font_pt * 2:.1f}pt; text-align: center; }}
.contact {{ text-align: center; font-size: {font_pt - 1.5}pt; white-space: nowrap; margin: 3pt 0 6pt; padding-bottom: 6pt; border-bottom: 0.8pt solid #000; }}
.meta {{ margin: 14pt 0 12pt; }}
p {{ margin-bottom: 10pt; }}
.sign {{ margin-top: 14pt; }}
</style></head><body>
<h1>{e(c['name'])}</h1><div class="contact">{contact}</div>
<div class="meta">{e(today)}<br>{e(cover['job']['company'])}<br>Re: {e(cover['job']['title'])}</div>
<p>{e(cover.get('greeting', 'Dear Hiring Team,'))}</p>
{paras}
<div class="sign">{e(cover.get('closing', 'Sincerely,'))}<br>{e(c['name'])}</div>
</body></html>"""


def plain_text(cover, profile):
    return "\n\n".join([cover.get("greeting", "Dear Hiring Team,")] + [p["text"] for p in cover["paragraphs"]]
                       + [f"{cover.get('closing', 'Sincerely,')}\n{profile['contact']['name']}"])


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1]).resolve()
    cover = json.loads(path.read_text())
    profile = json.loads(PROFILE_PATH.read_text())
    errors, warnings = check(cover, profile)
    for w in warnings:
        print("WARN ", w)
    if errors:
        for err in errors:
            print("ERROR", err)
        sys.exit(f"Not rendered: {len(errors)} errors. Fix the wording or the sources; never add facts.")
    out = path.parent / OUTPUT_NAME
    for size in (11.5, 11.0, 10.5):
        if to_pdf(build_html(cover, profile, size), out) == 1:
            break
    else:
        sys.exit("Doesn't fit on one page. Cut it down.")
    (path.parent / "cover.txt").write_text(plain_text(cover, profile), encoding="utf-8")
    words = sum(len(p["text"].split()) for p in cover["paragraphs"])
    print(f"OK  {out}  (1 page, {size}pt, {words} words)")


if __name__ == "__main__":
    main()
