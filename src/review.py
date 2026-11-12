"""Local review page for the daily batch. Runs only on this laptop (127.0.0.1).

Shows each tailored resume with its fit score and gaps, and lets you Approve or Skip.
Approved jobs get "Open application": Chrome opens with the form filled (src/apply.py),
and you click Submit yourself. Decisions are saved to data/jobs.sqlite. This page never submits anything.

Usage: python3 src/review.py [--port 8765] [--no-open]
"""
import argparse
import html
import json
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import ROOT, db_connect, jd_file, now_iso, pay_from_text, sponsorship_signal  # noqa: E402
import outreach  # noqa: E402
import me  # noqa: E402

RESUMES = (ROOT / "resumes").resolve()
e = html.escape

SECTIONS = [
    ("tailored", "Needs your decision"),
    ("queued", "Still being tailored"),
    ("approved", "Approved, ready to apply"),
    ("offer", "Offers"),
    ("interview", "Interviews"),
    ("assessment", "Coding tests / assessments"),
    ("applied", "Applied, waiting to hear back"),
    ("rejected", "Rejected"),
    ("skip", "Skipped"),
]
APPLYING = {}  # job id -> running apply.py process, so one job never opens twice

OUTREACH_LABELS = {"drafted": "needs your OK", "approved": "sending request now…",
                   "requested": "request sent, waiting", "accepted": "accepted, message failed", "messaged": "messaged",
                   "replied": "replied", "skipped": "skipped", "blocked": "can't connect", "not_accepted": "didn't accept"}



def safe_url(u):
    """Links from scraped or generated data: only http(s), so a 'javascript:' URL can't run on click."""
    return u if urlparse(u or "").scheme in ("http", "https") else "#"

def load_outreach():
    return outreach.load()


def outreach_card(x):
    url, status = e(x.get("url", "")), x.get("status", "")
    if status == "drafted":
        msg = f'<textarea class="msg" rows="4">{e(x.get("message", ""))}</textarea>'
        buttons = (f'<button class="primary" data-url="{url}" data-o="approve">Approve</button>'
                   f'<button data-url="{url}" data-o="skip">Skip</button>')
    else:
        msg = f'<p class="small msg-text">{e(x.get("message", ""))}</p>'
        buttons = f'<button data-url="{url}" data-o="undo">Undo</button>' if status == "skipped" else ""
    return f"""
<article class="card">
  <header>
    <div><h3>{e(x.get("name", ""))}</h3><p class="title">{e(x.get("title", ""))}</p></div>
    <div class="meta"><span class="chip">{e(x.get("company", ""))}</span><span class="chip">{e(OUTREACH_LABELS.get(status, status))}</span></div>
  </header>
  <p class="small"><b>Applied for:</b> {e(x.get("role", ""))}</p>
  {f'<p class="reply"><b>They replied:</b> {e(x["reply"])}</p>' if x.get("reply") else ""}
  {f'<p class="small err">{e(x["last_error"])}</p>' if x.get("last_error") and status not in ("messaged", "replied") else ""}
  {msg}
  <nav><a href="{e(safe_url(x.get('url', '')))}" target="_blank" rel="noopener">LinkedIn profile</a></nav>
  <div class="actions">{buttons}</div>
</article>"""


def section(label, cards, open_=True, intro=""):
    """One collapsible group of cards. Returns (html, card count)."""
    if not cards:
        return "", 0
    o = " open" if open_ else ""
    return (f'<details class="section"{o}><summary><h2>{label}<span class="count">{len(cards)}</span></h2></summary>'
            + (f'<p class="small intro">{intro}</p>' if intro else "") + "".join(cards) + "</details>"), len(cards)


def outreach_sections():
    """Recruiter outreach groups, keyed so page() can place them in tabs."""
    people = load_outreach().get("people", [])
    by = lambda *st: [outreach_card(x) for x in people if x.get("status") in st]
    return {
        "o_drafted": section("Recruiters to message", by("drafted"), intro=(
            "Approve sends a connection request on the next daily run. Once they accept, "
            "they get this message. You can edit it before approving.")),
        "o_approved": section("Going out next run", by("approved")),
        "o_done": section("Outreach history", by("requested", "messaged", "replied", "skipped", "blocked", "not_accepted")),
    }


# Tabs in the top bar. Each lists the section keys it shows, in order.
TABS = [
    ("todo", "To do", ["o_drafted", "tailored", "queued"]),
    ("apply", "Ready to apply", ["approved"]),
    ("progress", "In progress", ["offer", "interview", "assessment", "applied"]),
    ("recruiters", "Recruiters", ["o_approved", "o_done"]),
    ("archive", "Archive", ["rejected", "skip"]),
]
EMPTY = {"todo": "You're all caught up.", "apply": "Nothing approved yet.",
         "progress": "No applications in flight yet.", "recruiters": "No recruiter outreach yet.",
         "archive": "Nothing archived."}


def load_review(resume_dir):
    if not resume_dir:
        return {}
    p = ROOT / resume_dir / "tailored.json"
    try:
        return json.loads(p.read_text()).get("review", {})
    except (OSError, ValueError):
        return {}


def card(r):
    rv = load_review(r["resume_dir"])
    fit = rv.get("fit", r["fit"])
    fit_html = f'<span class="fit fit{int(fit) if fit else 0}">{e(str(fit))}/10 fit</span>' if fit is not None else ""
    gaps = "".join(f"<li>{e(g)}</li>" for g in rv.get("gaps", []))
    emph = ", ".join(e(x) for x in rv.get("emphasized", []))
    jid = e(r["id"])
    status = r["app_status"]
    jd = jd_file(r["id"])
    jd_text = jd.read_text(encoding="utf-8") if jd.exists() else ""
    try:
        locs = " · ".join(json.loads(r["locations"] or "[]"))
    except ValueError:
        locs = r["locations"] or ""
    pay = pay_from_text(jd_text)
    spon_kind, spon_label = sponsorship_signal(jd_text, r["visa_flags"])
    facts = (f'<div class="facts"><span class="chip">{e(locs or "Location not listed")}</span>'
             f'<span class="chip{" good" if pay else ""}">{e(pay or "Pay not listed")}</span>'
             f'<span class="chip visa-{spon_kind}">{e(spon_label)}</span></div>')
    buttons = ""
    if status == "tailored":
        buttons = (f'<button class="primary" data-id="{jid}" data-d="approve">Approve</button>'
                   f'<button data-id="{jid}" data-d="skip">Skip</button>')
    elif status == "approved":
        buttons = (f'<button class="primary" data-id="{jid}" data-d="open">Open application</button>'
                   f'<button data-id="{jid}" data-d="applied">Mark applied</button>'
                   f'<button data-id="{jid}" data-d="undo">Undo</button>')
    elif status in ("skip", "applied"):
        buttons = f'<button data-id="{jid}" data-d="undo">Undo</button>'
    links = [f'<a href="{e(safe_url(r["url"]))}" target="_blank" rel="noopener">Posting</a>']
    if jd_file(r["id"]).exists():
        links.append(f'<a href="/jd?id={jid}" target="_blank">Description</a>')
    preview = ""
    if r["resume_dir"]:
        links.append(f'<a href="/pdf?id={jid}" target="_blank">Resume</a>')
        if (ROOT / r["resume_dir"] / me.cover_name(me.profile())).exists():
            links.append(f'<a href="/pdf?id={jid}&doc=cover" target="_blank">Cover letter</a>')
        preview = (f'<details><summary>Preview resume</summary>'
                   f'<iframe loading="lazy" src="/pdf?id={jid}" title="Resume for {e(r["company"])}"></iframe></details>')
    return f"""
<article class="card">
  <header>
    <div><h3>{e(r["company"])}</h3><p class="title">{e(r["title"])}</p></div>
    <div class="meta">{fit_html}<span class="chip">{e((r["track"] or "").replace("_", " "))}</span>
      <span class="chip">score {e(str(r["score"] or ""))}</span></div>
  </header>
  {facts}
  {f'<p class="why">{e(rv["why"])}</p>' if rv.get("why") else ""}
  {f'<p class="small"><b>Emphasized:</b> {emph}</p>' if emph else ""}
  {f'<div class="gaps"><b>Gaps</b><ul>{gaps}</ul></div>' if gaps else ""}
  {f'<pre class="notes">{e(r["notes"])}</pre>' if r["notes"] and status not in ("tailored", "queued") else ""}
  <nav>{"".join(links)}</nav>
  {preview}
  <div class="actions">{buttons}</div>
</article>"""


def page(db):
    rows = db.execute(
        "SELECT * FROM jobs WHERE app_status IN ('queued','tailored','approved','skip','applied',"
        "'assessment','interview','rejected','offer') "
        "AND (batch_date IS NOT NULL OR resume_dir IS NOT NULL) ORDER BY fit DESC, score DESC").fetchall()
    groups = {status: section(label, [card(r) for r in rows if r["app_status"] == status])
              for status, label in SECTIONS}
    groups.update(outreach_sections())
    pending = sum(1 for r in rows if r["app_status"] == "tailored")
    to_message = sum(1 for x in load_outreach().get("people", []) if x.get("status") == "drafted")
    ready = sum(1 for r in rows if r["app_status"] == "approved" and r["fit"] is not None and r["resume_dir"])
    queue = (f'<div class="queue"><button class="primary" id="start-queue">Start applying ({ready})</button>'
             f'<span class="small">Chrome opens each approved job filled in, one after another. You check it and click Submit; '
             f'the next one opens by itself.</span></div>' if ready else "")
    tab_links, panels = [], []
    for key, label, keys in TABS:
        n = sum(groups[k][1] for k in keys)
        inner = "".join(groups[k][0] for k in keys)
        if key == "apply":
            inner = queue + inner
        tab_links.append(f'<a href="#{key}" data-tab="{key}">{label}{f"<span class=badge>{n}</span>" if n else ""}</a>')
        panels.append(f'<section class="panel" id="panel-{key}" data-tab="{key}">'
                      f'{inner or f"<p class=empty>{EMPTY[key]}</p>"}</section>')
    # Open on the first tab that needs something from the applicant.
    default = "todo" if pending or to_message else "apply" if ready else "progress"
    if not rows and not to_message:
        panels = ['<p class="empty">Nothing to review yet. Ask Claude to run today\'s batch.</p>']
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Daily Review – employMint</title>
<style>
:root {{ --bg:#f5f5f7; --card:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#d2d2d7; --fill:#f5f5f7; --bar:rgba(251,251,253,.8);
  --accent:#0071e3; --accent-hover:#0077ed; --good:#248a3d; --warn:#b25000; --bad:#d70015;
  --shadow:0 2px 12px rgba(0,0,0,.06); --shadow-hover:0 8px 28px rgba(0,0,0,.10); }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#000; --card:#1d1d1f; --fg:#f5f5f7; --muted:#a1a1a6; --line:#424245; --fill:#2c2c2e; --bar:rgba(22,22,23,.8);
  --accent:#2997ff; --accent-hover:#47a6ff; --good:#30d158; --warn:#ff9f0a; --bad:#ff453a;
  --shadow:none; --shadow-hover:none; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); -webkit-font-smoothing:antialiased;
  font:17px/1.47 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif; letter-spacing:-.022em; }}
.bar {{ position:sticky; top:0; z-index:10; height:48px; display:flex; align-items:center; justify-content:center;
  background:var(--bar); backdrop-filter:saturate(180%) blur(20px); -webkit-backdrop-filter:saturate(180%) blur(20px);
  border-bottom:1px solid rgba(0,0,0,.08); font-size:14px; font-weight:600; letter-spacing:-.01em; }}
@media (prefers-color-scheme: dark) {{ .bar {{ border-bottom-color:rgba(255,255,255,.1); }} }}
main {{ max-width:980px; margin:0 auto; padding:56px 22px 96px; }}
.hero {{ text-align:center; margin-bottom:48px; }}
h1 {{ font-family:-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", sans-serif;
  font-size:clamp(40px, 6vw, 56px); line-height:1.07; font-weight:700; letter-spacing:-.005em; margin:0 0 12px; }}
.sub {{ color:var(--muted); font-size:21px; line-height:1.38; letter-spacing:.011em; margin:0; }}
.sub b {{ color:var(--fg); font-weight:600; }}
.section {{ margin-top:40px; }}
.section > summary {{ list-style:none; cursor:pointer; }}
.section > summary::-webkit-details-marker {{ display:none; }}
h2 {{ font-family:-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif; font-size:28px; line-height:1.14; font-weight:600;
  letter-spacing:.007em; margin:0 0 20px; display:flex; align-items:center; gap:10px; }}
h2::after {{ content:"›"; color:var(--muted); font-weight:400; transition:transform .25s ease; }}
.section[open] > summary h2::after {{ transform:rotate(90deg); }}
h2 .count {{ font-size:14px; font-weight:600; color:var(--muted); background:var(--card); border-radius:999px; padding:2px 10px; letter-spacing:0; }}
.card {{ background:var(--card); border-radius:18px; padding:28px 30px; margin-bottom:16px; box-shadow:var(--shadow);
  transition:box-shadow .3s ease, transform .3s ease; }}
.card:hover {{ box-shadow:var(--shadow-hover); }}
.card header {{ display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
h3 {{ margin:0; font-size:24px; line-height:1.17; font-weight:600; letter-spacing:.009em; }}
.title {{ margin:4px 0 0; color:var(--muted); font-size:17px; }}
.meta {{ display:flex; gap:6px; flex-wrap:wrap; align-items:flex-start; }}
.chip, .fit {{ font-size:12px; line-height:1.33; font-weight:500; letter-spacing:0; padding:5px 11px; border-radius:999px;
  background:var(--fill); color:var(--muted); white-space:nowrap; }}
.fit {{ font-weight:600; }}
.fit8, .fit9, .fit10 {{ color:var(--good); }}
.fit6, .fit7 {{ color:var(--warn); }}
.fit0, .fit1, .fit2, .fit3, .fit4, .fit5 {{ color:var(--bad); }}
.why {{ margin:18px 0 4px; font-size:17px; }}
.small {{ font-size:14px; line-height:1.43; color:var(--muted); letter-spacing:-.016em; margin:6px 0; }}
.small b, .gaps b {{ color:var(--fg); font-weight:600; }}
.gaps {{ font-size:14px; margin:12px 0; color:var(--muted); }}
.gaps ul {{ margin:6px 0 0; padding-left:18px; }}
nav {{ display:flex; flex-wrap:wrap; gap:6px 22px; font-size:14px; margin-top:18px; }}
nav a::after {{ content:" ›"; }}
a {{ color:var(--accent); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
details iframe {{ width:100%; height:70vh; border:0; border-radius:12px; margin-top:12px; background:#fff; box-shadow:0 0 0 1px var(--line); }}
.card details > summary {{ cursor:pointer; font-size:14px; margin-top:10px; color:var(--accent); list-style:none; }}
.card details > summary::-webkit-details-marker {{ display:none; }}
.card details > summary::after {{ content:" ›"; }}
.actions {{ display:flex; gap:10px; margin-top:22px; flex-wrap:wrap; }}
.actions:empty {{ display:none; }}
button {{ font:inherit; font-size:15px; letter-spacing:-.01em; padding:9px 20px; border-radius:980px; border:0;
  background:var(--fill); color:var(--fg); cursor:pointer; transition:background .2s ease, opacity .2s ease; }}
button:hover {{ filter:brightness(.96); }}
button.primary {{ background:var(--accent); color:#fff; }}
button.primary:hover {{ background:var(--accent-hover); filter:none; }}
button:disabled {{ opacity:.4; cursor:default; }}
.empty {{ color:var(--muted); text-align:center; font-size:21px; }}
.queue {{ display:flex; flex-direction:column; align-items:center; gap:14px; text-align:center; background:var(--card);
  border-radius:18px; padding:36px 30px; box-shadow:var(--shadow); }}
.queue button {{ font-size:17px; padding:12px 28px; }}
.queue .small {{ max-width:520px; margin:0; }}
textarea.msg {{ width:100%; margin-top:14px; font:inherit; font-size:15px; line-height:1.47; color:var(--fg);
  background:var(--fill); border:1px solid var(--line); border-radius:12px; padding:12px 14px; resize:vertical; }}
.msg-text {{ margin-top:12px; }}
.reply {{ margin:14px 0 0; padding:12px 14px; border-radius:12px; background:var(--fill); font-size:15px; }}
.err {{ color:var(--bad); }}
.center {{ text-align:center; margin-top:28px; }}
.facts {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:16px; }}
.facts .chip {{ font-size:13px; }}
.chip.good, .chip.visa-yes, .chip.visa-cpt {{ color:var(--good); }}
.chip.visa-check {{ color:var(--warn); }}
.notes {{ font:12px/1.5 ui-monospace, "SF Mono", Menlo, monospace; letter-spacing:0; white-space:pre-wrap; background:var(--fill);
  border-radius:12px; padding:12px 14px; margin:12px 0; color:var(--muted); }}
@media (max-width:600px) {{ main {{ padding:36px 16px 64px; }} .card {{ padding:22px 20px; }} .sub {{ font-size:19px; }} h2 {{ font-size:24px; }} }}
.bar {{ justify-content:space-between; gap:20px; padding:0 max(22px, calc((100% - 980px) / 2)); height:52px; }}
.brand {{ font-size:21px; font-weight:600; letter-spacing:.011em; color:var(--fg); white-space:nowrap; }}
.brand:hover {{ text-decoration:none; }}
.tabs {{ display:flex; flex-wrap:nowrap; align-items:center; gap:4px; margin:0; overflow-x:auto; scrollbar-width:none; }}
.tabs a::after {{ content:none; }}
.tabs::-webkit-scrollbar {{ display:none; }}
.tabs a {{ display:flex; align-items:center; gap:6px; white-space:nowrap; font-size:12px; font-weight:400; letter-spacing:-.01em;
  color:var(--fg); opacity:.8; padding:6px 10px; border-radius:980px; transition:opacity .2s, background .2s; }}
.tabs a:hover {{ opacity:1; text-decoration:none; }}
.tabs a.active {{ opacity:1; background:var(--fg); color:var(--bg); font-weight:500; }}
.badge {{ font-size:11px; font-weight:600; min-width:18px; text-align:center; padding:1px 6px; border-radius:980px; background:var(--fill); color:var(--muted); }}
.tabs a.active .badge {{ background:var(--accent); color:#fff; }}
.search {{ position:relative; flex:0 0 auto; }}
.search input {{ font:inherit; font-size:12px; letter-spacing:-.01em; width:150px; padding:6px 12px 6px 28px; border-radius:980px;
  border:1px solid transparent; background:var(--fill); color:var(--fg); outline:none; transition:width .25s ease, border-color .2s; }}
.search input:focus {{ width:220px; border-color:var(--accent); }}
.search svg {{ position:absolute; left:10px; top:50%; transform:translateY(-50%); width:12px; height:12px; color:var(--muted); pointer-events:none; }}
.panel {{ display:none; }}
.panel.show {{ display:block; animation:fade .35s ease; }}
@keyframes fade {{ from {{ opacity:0; transform:translateY(8px); }} to {{ opacity:1; transform:none; }} }}
.panel > .section:first-child, .panel > .queue + .section {{ margin-top:0; }}
.panel > .queue {{ margin-bottom:40px; }}
.intro {{ margin:-8px 0 20px; }}
.panel .empty {{ padding:80px 0; }}
.no-results {{ display:none; }}
body.searching .no-results.on {{ display:block; }}
.top {{ position:fixed; right:24px; bottom:24px; width:40px; height:40px; border-radius:50%; padding:0; font-size:18px;
  background:var(--bar); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px); box-shadow:0 2px 12px rgba(0,0,0,.12);
  opacity:0; pointer-events:none; transition:opacity .3s; }}
.top.on {{ opacity:1; pointer-events:auto; }}
@media (max-width:760px) {{
  .bar {{ flex-wrap:wrap; height:auto; padding:10px 16px; gap:8px; }}
  .brand {{ font-size:19px; }}
  .tabs {{ order:3; width:100%; }}
  .search input, .search input:focus {{ width:140px; }}
}}
</style></head><body>
<header class="bar">
  <a class="brand" href="#{default}" data-tab="{default}">employMint</a>
  <nav class="tabs" aria-label="Sections">{"".join(tab_links)}</nav>
  <label class="search"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="7" cy="7" r="5"/><path d="M11 11l3.5 3.5" stroke-linecap="round"/></svg>
    <input id="q" type="search" autocomplete="off" placeholder="Search" aria-label="Search jobs and recruiters"></label>
</header>
<main>
<div class="hero"><h1>Daily Review.</h1>
<p class="sub"><b>{pending}</b> waiting for your decision. <b>{ready}</b> ready to apply.{f" <b>{to_message}</b> recruiter{'s' if to_message != 1 else ''} to OK." if to_message else ""}</p></div>
{"".join(panels)}
<p class="empty no-results">No matches.</p>
</main>
<button class="top" aria-label="Back to top">↑</button>
<script>
// Tabs: the URL hash picks the tab, so a reload after Approve/Skip keeps you where you were.
const tabs = [...document.querySelectorAll(".tabs a")];
const q = document.getElementById("q");
function show(key) {{
  if (!document.getElementById("panel-" + key)) key = "{default}";
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("show", p.dataset.tab === key));
  tabs.forEach(a => a.classList.toggle("active", a.dataset.tab === key));
  tabs.find(a => a.dataset.tab === key)?.scrollIntoView({{ block: "nearest", inline: "nearest" }});
}}
window.addEventListener("hashchange", () => {{
  if (q.value) {{ q.value = ""; q.dispatchEvent(new Event("input")); }}
  show(location.hash.slice(1)); window.scrollTo({{ top: 0, behavior: "smooth" }});
}});
tabs.forEach(a => a.addEventListener("click", () => {{
  if (q.value && a.getAttribute("href") === location.hash) {{ q.value = ""; q.dispatchEvent(new Event("input")); }}
}}));
show(location.hash.slice(1) || "{default}");

// Search: matches across every tab, hides cards and groups that don't match.
q.addEventListener("input", () => {{
  const term = q.value.trim().toLowerCase();
  document.body.classList.toggle("searching", !!term);
  let hits = 0;
  document.querySelectorAll(".panel").forEach(p => {{
    let panelHits = 0;
    p.querySelectorAll(".section").forEach(s => {{
      let n = 0;
      s.querySelectorAll(".card").forEach(c => {{
        const ok = !term || c.textContent.toLowerCase().includes(term);
        c.style.display = ok ? "" : "none"; if (ok) n++;
      }});
      s.style.display = n ? "" : "none";
      if (term && n) s.open = true;
      panelHits += n;
    }});
    p.querySelectorAll(".queue, .empty").forEach(x => x.style.display = term ? "none" : "");
    if (term) p.classList.toggle("show", panelHits > 0);
    hits += panelHits;
  }});
  document.querySelector(".no-results").classList.toggle("on", !hits);
  if (!term) show(location.hash.slice(1) || "{default}");
}});
document.addEventListener("keydown", ev => {{
  if (ev.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {{ ev.preventDefault(); q.focus(); }}
  if (ev.key === "Escape" && document.activeElement === q) {{ q.value = ""; q.dispatchEvent(new Event("input")); q.blur(); }}
}});

const top_ = document.querySelector(".top");
window.addEventListener("scroll", () => top_.classList.toggle("on", scrollY > 600), {{ passive: true }});
top_.addEventListener("click", () => window.scrollTo({{ top: 0, behavior: "smooth" }}));

(() => {{
  let v = null;
  setInterval(async () => {{
    try {{
      const r = await fetch("/outreach-version"); const t = await r.text();
      if (v !== null && t !== v && !document.querySelector("textarea.msg:focus")) location.reload();
      v = t;
    }} catch (_) {{}}
  }}, 5000);
}})();
document.getElementById("start-queue")?.addEventListener("click", async (ev) => {{
  const b = ev.currentTarget; b.disabled = true;
  const res = await fetch("/queue", {{ method: "POST", headers: {{ "X-Employmint": "1" }} }});
  b.insertAdjacentHTML("afterend", res.ok
    ? '<p class="small">Chrome is opening your first application. Check it, click Submit, and the next one follows. Use the panel to skip or stop.</p>'
    : '<p class="small">' + await res.text() + '</p>');
}});
document.addEventListener("click", async (ev) => {{
  const b = ev.target.closest("button[data-url]");
  if (!b) return;
  const acts = b.closest(".actions");
  acts.querySelectorAll("button").forEach(x => x.disabled = true);
  const box = b.closest(".card").querySelector("textarea.msg");
  const res = await fetch("/outreach", {{ method: "POST",
    headers: {{ "Content-Type": "application/json", "X-Employmint": "1" }},
    body: JSON.stringify({{ url: b.dataset.url, decision: b.dataset.o, message: box ? box.value : null }}) }});
  if (res.ok) location.reload(); else {{
    alert("Could not save: " + await res.text());
    acts.querySelectorAll("button").forEach(x => x.disabled = false);
  }}
}});
document.addEventListener("click", async (ev) => {{
  const b = ev.target.closest("button[data-id]");
  if (!b) return;
  b.closest(".actions").querySelectorAll("button").forEach(x => x.disabled = true);
  const res = await fetch("/decide", {{ method: "POST",
    headers: {{ "Content-Type": "application/json", "X-Employmint": "1" }},
    body: JSON.stringify({{ id: b.dataset.id, decision: b.dataset.d }}) }});
  if (res.ok && b.dataset.d === "open") {{
    b.closest(".actions").insertAdjacentHTML("afterend",
      '<p class="small">Chrome is opening with the form filled in. Check the highlighted fields, then click Submit yourself. ' +
      'This page updates to Applied once the confirmation page shows.</p>');
    setTimeout(() => b.closest(".actions").querySelectorAll("button").forEach(x => x.disabled = false), 4000);
  }} else if (res.ok) location.reload(); else {{
    alert("Could not save: " + await res.text());
    b.closest(".actions").querySelectorAll("button").forEach(x => x.disabled = false);
  }}
}});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def job(self, db, qs):
        jid = parse_qs(qs).get("id", [""])[0]
        return db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()

    def trusted(self):
        """Blocks DNS rebinding: a hostile site whose domain points at 127.0.0.1 still sends its own Host
        header, so only requests addressed to this server by its local name get through."""
        port = self.server.server_address[1]
        ok = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return self.headers.get("Host") in ok and (origin is None or origin.split("//", 1)[-1] in ok)

    def do_GET(self):
        if not self.trusted():
            return self.send(403, "forbidden", "text/plain")
        u = urlparse(self.path)
        db = db_connect()
        try:
            if u.path == "/":
                return self.send(200, page(db))
            if u.path == "/outreach-version":
                try:
                    return self.send(200, str(outreach.OUTREACH.stat().st_mtime_ns), "text/plain")
                except OSError:
                    return self.send(200, "0", "text/plain")
            if u.path == "/pdf":
                r = self.job(db, u.query)
                if not r or not r["resume_dir"]:
                    return self.send(404, "not found", "text/plain")
                doc = parse_qs(u.query).get("doc", [""])[0]
                name = me.cover_name(me.profile()) if doc == "cover" else me.resume_name(me.profile())
                pdf = (ROOT / r["resume_dir"] / name).resolve()
                if RESUMES not in pdf.parents or not pdf.exists():
                    return self.send(404, "not found", "text/plain")
                return self.send(200, pdf.read_bytes(), "application/pdf")
            if u.path == "/jd":
                r = self.job(db, u.query)
                p = jd_file(r["id"]) if r else None
                if not p or not p.exists():
                    return self.send(404, "not found", "text/plain")
                return self.send(200, p.read_text(encoding="utf-8"), "text/plain; charset=utf-8")
            return self.send(404, "not found", "text/plain")
        finally:
            db.close()

    def open_application(self, r):
        """Starts apply.py in a visible Chrome window. It fills the form and waits; the applicant submits."""
        running = APPLYING.get(r["id"])
        if running and running.poll() is None:
            return self.send(409, "That application is already open in Chrome.", "text/plain")
        logs = ROOT / "data" / "apply-logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = open(logs / (Path(r["resume_dir"] or "job").name + ".log"), "a")
        APPLYING[r["id"]] = subprocess.Popen(
            [sys.executable, str(ROOT / "src" / "apply.py"), "open", r["id"]],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()  # the child keeps its own copy
        return self.send(200, '{"ok":true,"opened":true}', "application/json")

    def start_queue(self):
        """Starts apply.py queue: one Chrome window that walks through every approved job. The applicant submits each."""
        running = APPLYING.get("__queue__")
        if running and running.poll() is None:
            return self.send(409, "The apply queue is already open in Chrome.", "text/plain")
        logs = ROOT / "data" / "apply-logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = open(logs / "queue.log", "a")
        APPLYING["__queue__"] = subprocess.Popen(
            [sys.executable, str(ROOT / "src" / "apply.py"), "queue"],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()  # the child keeps its own copy
        return self.send(200, '{"ok":true}', "application/json")

    def decide_outreach(self):
        """Approve, skip or undo one drafted recruiter. Only changes status (and the message on approve)."""
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            url, decision, message = body["url"], body["decision"], body.get("message")
        except (ValueError, KeyError):
            return self.send(400, "bad request", "text/plain")
        with outreach.editing() as data:
            x = next((p for p in data.get("people", []) if p.get("url") == url), None)
            if not x:
                return self.send(404, "no such recruiter", "text/plain")
            status = x.get("status")
            if decision == "approve" and status == "drafted":
                if isinstance(message, str) and message.strip():
                    x["message"] = message.strip()
                x["status"], x["approved_at"] = "approved", now_iso()
            elif decision == "skip" and status == "drafted":
                x["status"] = "skipped"
            elif decision == "undo" and status == "skipped":
                x["status"] = "drafted"
            else:
                return self.send(409, f"can't {decision} a recruiter that is '{status}'", "text/plain")
        if decision == "approve":
            outreach.start_invites()  # sends the connection request right away
        return self.send(200, '{"ok":true}', "application/json")

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.trusted() or self.headers.get("X-Employmint") != "1" or path not in ("/decide", "/queue", "/outreach"):
            return self.send(403, "forbidden", "text/plain")
        if path == "/queue":
            return self.start_queue()
        if path == "/outreach":
            return self.decide_outreach()
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            jid, decision = body["id"], body["decision"]
        except (ValueError, KeyError):
            return self.send(400, "bad request", "text/plain")
        db = db_connect()
        try:
            r = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            if not r:
                return self.send(404, "no such job", "text/plain")
            if decision == "approve" and r["app_status"] == "tailored":
                db.execute("UPDATE jobs SET app_status='approved', decided_at=? WHERE id=?", (now_iso(), jid))
            elif decision == "skip" and r["app_status"] in ("tailored", "queued"):
                db.execute("UPDATE jobs SET app_status='skip', decided_at=? WHERE id=?", (now_iso(), jid))
            elif decision == "open" and r["app_status"] == "approved":
                return self.open_application(r)
            elif decision == "applied" and r["app_status"] == "approved":
                db.execute("UPDATE jobs SET app_status='applied', decided_at=? WHERE id=?", (now_iso(), jid))
                db.commit()
                outreach.draft_for_new_applications()
            elif decision == "undo" and r["app_status"] == "applied":
                db.execute("UPDATE jobs SET app_status='approved', decided_at=? WHERE id=?", (now_iso(), jid))
            elif decision == "undo" and r["app_status"] in ("approved", "skip"):
                back = "tailored" if r["resume_dir"] else "queued"
                db.execute("UPDATE jobs SET app_status=?, decided_at=NULL WHERE id=?", (back, jid))
            else:
                return self.send(409, f"can't {decision} a job that is '{r['app_status']}'", "text/plain")
            db.commit()
            return self.send(200, '{"ok":true}', "application/json")
        finally:
            db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Review page: {url}  (Ctrl+C to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
