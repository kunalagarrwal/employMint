"""Turns a tailored resume JSON into a one-page PDF.

Contact info, school, titles, orgs and dates always come from the profile;
the tailored JSON only picks entries, bullets, skills and coursework.
Runs the verifier first and refuses to render if it finds errors.
Shrinks the font slightly if needed to fit one page.

Usage: python3 src/render.py resumes/<slug>/tailored.json
"""
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import me  # noqa: E402
from verify import PROFILE_PATH, profile_entries, verify  # noqa: E402

OUTPUT_NAME = me.resume_name(me.profile())
# Largest first: the biggest size that still fits on one page wins, so sparse pages grow a little.
FONT_SIZES = [11.0, 10.75, 10.5, 10.25, 10.0, 9.75, 9.5]
PAGE_HEIGHT_PX = 10.1 * 96  # Letter height minus top/bottom margins, in CSS pixels
TARGET_FILL = 0.90  # warn when the page is less full than this
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"]

e = html.escape


def fmt_date(d):
    if d == "present":
        return "Present"
    y, m = d.split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def fmt_range(start, end):
    if end != "present" and start[:4] == end[:4]:
        return f"{MONTHS[int(start[5:7]) - 1]} – {fmt_date(end)}"
    return f"{fmt_date(start)} – {fmt_date(end)}"


def strip_code(course):
    return re.sub(r"\s*\(.*?\)\s*$", "", course)


def entry_html(heading_left, heading_right, sub_left, sub_right, bullets):
    items = "".join(f"<li>{e(b['text'])}</li>" for b in bullets)
    return (
        '<div class="entry">'
        f'<div class="row"><span class="b">{heading_left}</span><span class="b">{heading_right}</span></div>'
        f'<div class="row"><span class="i">{sub_left}</span><span class="i">{sub_right}</span></div>'
        f"<ul>{items}</ul></div>"
    )


MEASURE_JS = """<script>
(function () {
  var widows = [];
  document.querySelectorAll('li').forEach(function (li) {
    var r = document.createRange(); r.selectNodeContents(li);
    var lines = {};
    Array.prototype.forEach.call(r.getClientRects(), function (x) {
      if (x.width > 0) { var k = Math.round(x.top); lines[k] = Math.max(lines[k] || 0, x.right); }
    });
    var tops = Object.keys(lines).map(Number).sort(function (a, b) { return a - b; });
    var box = li.getBoundingClientRect();
    if (tops.length > 1 && (lines[tops[tops.length - 1]] - box.left) < box.width * 0.3) {
      widows.push(li.textContent.slice(0, 60));
    }
  });
  document.body.setAttribute('data-measure', JSON.stringify({h: document.body.scrollHeight, widows: widows}));
})();
</script>"""


def build_html(tailored, profile, font_pt, measure=False):
    c = profile["contact"]
    ed = profile["education"][0]
    entries = profile_entries(profile)

    def link(url):
        short = re.sub(r"^https?://(www\.)?", "", url)
        return f'<a href="{e(url)}">{e(short)}</a>'

    contact = " | ".join(x for x in [e(c["phone"]), link(c["linkedin"]) if c["linkedin"] else "",
                                     f'<a href="mailto:{e(c["email"])}">{e(c["email"])}</a>', link(c["github"]) if c["github"] else ""] if x)

    edu_lines = [
        f'<div class="row"><span class="b">{e(ed["school"])}</span><span class="b">{e(ed["location"])}</span></div>',
        f'<div class="row"><span>{e(ed["degree"])}{", Minor in " + e(ed["minor"]) if ed.get("minor") else ""}</span><span class="i">Expected {e(ed["graduation"])}</span></div>',
    ]
    extras = []
    if tailored.get("show_gpa", True) and ed.get("gpa"):
        extras.append(f"GPA: {e(ed['gpa'])}")
    extras += [e(h) for h in ed.get("honors", [])]
    if extras:
        edu_lines.append(f'<div class="row"><span>{" | ".join(extras)}</span></div>')
    if tailored.get("coursework"):
        cw = ", ".join(e(strip_code(x)) for x in tailored["coursework"])
        edu_lines.append(f'<div class="cw"><span class="b">Relevant Coursework:</span> {cw}</div>')
    if tailored.get("upcoming_coursework"):
        term = me.upcoming_term(ed.get("coursework", {}))[1] or "Upcoming"
        up = ", ".join(e(strip_code(x)) for x in tailored["upcoming_coursework"])
        edu_lines.append(f'<div class="cw"><span class="b">{e(term)}:</span> {up}</div>')

    sections = {"education": ("Education", "".join(edu_lines))}

    def recency(item):  # newest first; "present" beats any end date
        en = entries[item["id"]][1]
        return ("9999-99" if en["end"] == "present" else en["end"], en["start"])

    exp = []
    for item in sorted(tailored.get("experience", []), key=recency, reverse=True):
        en = entries[item["id"]][1]
        exp.append(entry_html(e(en["org"]), e(en["location"]), e(en["title"]),
                              fmt_range(en["start"], en["end"]), item["bullets"]))
    sections["experience"] = ("Experience", "".join(exp))

    proj = []
    for item in tailored.get("projects", []):
        p = entries[item["id"]][1]
        name, _, subtitle = p["name"].partition(" - ")
        y, m = p["date"].split("-")
        sub = " | ".join(x for x in (e(subtitle), link(p["url"]) if p.get("url") else "") if x)
        proj.append(entry_html(e(name), "", sub, f"{MONTHS[int(m) - 1]} {y}", item["bullets"]))
    sections["projects"] = ("Projects", "".join(proj))

    skill_rows = "".join(
        f'<div class="sk"><span class="b">{e(g["label"])}:</span> {", ".join(e(s) for s in g["items"])}</div>'
        for g in tailored.get("skills", [])
    )
    # Interests: a human line recruiters ask about. tailored.json can override or hide it ("interests": []).
    # Certifications: only when a tailored resume lists them (e.g. AI roles), names must match profile.certifications.
    certs = {c["name"]: c for c in profile.get("certifications", [])}
    shown = [certs[n] for n in tailored.get("certifications", []) if n in certs]
    if shown:
        skill_rows += ('<div class="sk"><span class="b">Certifications:</span> '
                       + ", ".join(f'{e(c["name"])} ({e(c["issuer"])})' for c in shown) + '</div>')
    interests = tailored.get("interests", profile.get("interests_on_resume", []))
    if interests:
        skill_rows += f'<div class="sk"><span class="b">Interests:</span> {", ".join(e(s) for s in interests)}</div>'
    sections["skills"] = ("Skills", skill_rows)

    order = tailored.get("section_order", ["education", "experience", "projects", "skills"])
    body = "".join(
        f'<h2>{sections[k][0]}</h2>{sections[k][1]}' for k in order if k in sections and sections[k][1]
    )

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(c['name'])} Resume</title>
<style>
@page {{ size: Letter; margin: 0.45in 0.55in; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "Times New Roman", Times, serif; font-size: {font_pt}pt; line-height: 1.22; color: #000; }}
h1 {{ font-size: {font_pt * 2.1:.1f}pt; text-align: center; font-weight: bold; }}
.contact {{ text-align: center; font-size: {font_pt - 0.5}pt; margin: 2pt 0 4pt; }}
a {{ color: #000; text-decoration: none; }}
h2 {{ font-size: {font_pt + 1}pt; text-transform: uppercase; border-bottom: 0.8pt solid #000; margin: 7pt 0 3pt; padding-bottom: 1pt; }}
.row {{ display: flex; justify-content: space-between; gap: 12pt; }}
.b {{ font-weight: bold; }}
.i {{ font-style: italic; }}
.entry {{ margin-bottom: 4pt; }}
ul {{ margin: 1pt 0 0 14pt; }}
li {{ margin-bottom: 0.5pt; }}
.cw, .sk {{ margin-top: 1pt; }}
@media screen {{ html {{ width: 7.4in; }} }}
</style></head><body>
<h1>{e(c['name'])}</h1><div class="contact">{contact}</div>
{body}
{MEASURE_JS if measure else ""}
</body></html>"""


def measure(html_text):
    """Lays the page out in headless Chrome; returns (fraction of the page used, bullets ending in a lonely word)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "measure.html"
        src.write_text(html_text, encoding="utf-8")
        out = subprocess.run(
            [me.chrome_path(), "--headless=new", "--disable-gpu", f"--user-data-dir={tmp}/chrome",
             "--virtual-time-budget=2000", "--dump-dom", src.as_uri()],
            check=True, capture_output=True, timeout=60, text=True).stdout
    m = re.search(r'data-measure="([^"]*)"', out)
    if not m:
        print("WARN couldn't measure the page in Chrome; the fill and lonely-word checks were skipped")
        return None, []
    data = json.loads(html.unescape(m.group(1)))
    return data["h"] / PAGE_HEIGHT_PX, data["widows"]


def to_pdf(html_text, out_pdf):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "resume.html"
        src.write_text(html_text, encoding="utf-8")
        subprocess.run(
            [me.chrome_path(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--user-data-dir={tmp}/chrome", f"--print-to-pdf={out_pdf}", src.as_uri()],
            check=True, capture_output=True, timeout=60,
        )
    return len(re.findall(rb"/Type\s*/Page(?!s)", Path(out_pdf).read_bytes()))


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tailored_path = Path(sys.argv[1]).resolve()
    tailored = json.loads(tailored_path.read_text())
    profile = json.loads(PROFILE_PATH.read_text())

    errors, warnings = verify(tailored, profile)
    for w in warnings:
        print("WARN ", w)
    if errors:
        for err in errors:
            print("ERROR", err)
        sys.exit(f"Not rendered: {len(errors)} errors. Fix the bullets, don't add facts.")

    out_pdf = tailored_path.parent / OUTPUT_NAME
    pages = None
    for size in FONT_SIZES:
        fill, widows = measure(build_html(tailored, profile, size, measure=True))
        if fill is not None and fill > 0.985:
            continue  # too tall at this size; try smaller
        pages = to_pdf(build_html(tailored, profile, size), out_pdf)
        if pages != 1:
            continue
        print(f"OK  {out_pdf}  (1 page, {size}pt, {round((fill or 0) * 100)}% full)")
        for w in widows:
            print(f"WARN bullet ends with a lonely word on its own line: \"{w}...\" (shorten it or add a few true words)")
        if fill is not None and fill < TARGET_FILL:
            print(f"WARN page is only {round(fill * 100)}% full: add true bullets, an entry, or coursework (never filler)")
        return
    sys.exit(f"Doesn't fit on one page even at {FONT_SIZES[-1]}pt. Cut the weakest bullets or drop an entry, then re-run.")


if __name__ == "__main__":
    main()
