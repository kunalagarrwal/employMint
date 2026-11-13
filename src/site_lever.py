"""Lever: its Submit button has an invisible hCaptcha that rejects script-controlled browsers, so the form
opens in the applicant's own Chrome and this module shows them an answer sheet with Copy buttons instead."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from formjs import EXTRACT_JS  # noqa: E402
import me  # noqa: E402
from answers import job_values, load_job_answers, load_remembered, load_rules, merge_lone_options, norm, resolve, sheet_answer  # noqa: E402

# ---------- Lever: hand off to the applicant's own Chrome ----------
# Lever guards Submit with an invisible hCaptcha that rejects script-controlled browsers
# ("Something went wrong, try again"). So the form opens in their normal Chrome and they
# fill it from an answer sheet shown in the tool's window. We don't try to hide automation.

def open_in_my_chrome(url):
    """Opens url in the applicant's everyday Chrome (their default profile), not the automated window."""
    import subprocess
    subprocess.Popen([me.chrome_path(), url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

def lever_rows(page, job):
    rules, values = load_rules()
    values = job_values(job, values)
    job_answers = load_job_answers(job["resume_dir"])
    remembered = load_remembered()
    qs = [q for q in page.evaluate(EXTRACT_JS) if q["visible"] and q["kind"] != "file" and q["title"]]
    merged = merge_lone_options(qs)
    rows, seen = [], set()
    for q in merged:
        q["title"] = re.split(r"\s+Select \.\.\.", q["title"])[0].strip()
        if norm(q["title"]) in seen:
            continue
        seen.add(norm(q["title"]))
        a, note = sheet_answer(q, resolve(q, rules, values, job_answers, remembered))
        a = re.sub(r"\)\s+(A|All) (person|persons) .*", ")", a, flags=re.S)  # drop EEO definitions
        rows.append({"q": q["title"], "a": a, "note": note, "req": q["required"]})
    if values.get("cover_text") and not any(values["cover_text"][:40] in r["a"] for r in rows):
        rows.append({"q": "Cover letter (paste into Additional information if there's no upload)",
                     "a": values["cover_text"], "note": "", "req": False})
    return rows, values

def lever_sheet_html(job, url, rows, values, queue):
    import html as H
    e = H.escape
    files = [("resume", "Resume", values.get("resume"))] + \
            ([("cover", "Cover letter", values["cover"])] if values.get("cover") else [])
    file_btns = "".join(f'<button data-act="reveal:{k}">Show {e(n.lower())} in {"Finder" if sys.platform == "darwin" else "folder"}</button>' for k, n, f in files if f)
    body = ""
    for r in rows:
        star = ' <span class="req">*</span>' if r["req"] else ""
        note = f'<div class="note">{e(r["note"])}</div>' if r["note"] else ""
        copy = '<button class="copy">Copy</button>' if r["a"] else ""
        body += f'<tr><td class="q">{e(r["q"])}{star}{note}</td><td class="a">{e(r["a"]) or "<i>you</i>"}</td><td>{copy}</td></tr>'
    in_queue = bool(queue and queue.get("total"))
    pos = f'Job {queue["pos"]} of {queue["total"]} · ' if in_queue else ""
    queue_btns = '<button data-act="pass">Not for me</button>' + (
        '<button data-act="skip">Later</button><button data-act="stop">Stop queue</button>' if in_queue else "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Lever answers · {e(job['company'])}</title>
<style>
body{{font:14px/1.45 -apple-system,BlinkMacSystemFont,sans-serif;margin:24px auto;max-width:980px;color:#1b1b1b;background:#fbfaf7;padding:0 16px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#666;margin:0 0 14px}}
ol{{margin:8px 0 14px;padding-left:20px}} li{{margin:3px 0}}
button{{font:13px sans-serif;padding:6px 11px;border:1px solid #bbb;border-radius:8px;background:#fff;cursor:pointer;margin:2px 4px 2px 0}}
button.main{{background:#1a7f37;color:#fff;border-color:#1a7f37}}
table{{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e5e2da;border-radius:10px}}
td{{border-top:1px solid #eee;padding:8px 10px;vertical-align:top}} td.q{{width:38%;font-weight:600}}
td.a{{white-space:pre-wrap;word-break:break-word}} .note{{font-weight:400;color:#b26b00;font-size:12px;margin-top:2px}}
.req{{color:#d92d20}} .bar{{position:sticky;top:0;background:#fbfaf7;padding:8px 0;border-bottom:1px solid #e5e2da;margin-bottom:10px}}
</style></head><body>
<div id="employmint-panel" class="bar"><h1>{e(job['company'])} · {e(job['title'])}</h1>
<p class="sub">{pos}Lever blocks automated browsers at Submit, so this form opened in <b>your own Chrome</b>.</p>
<ol><li>Drag your resume into the form first. Lever fills your name, email and phone from it, so check those.</li>
<li>Copy each answer below into the matching question.</li>
<li>Tick any consent boxes yourself, then click <b>Submit</b> in your Chrome.</li>
<li>Come back here and click <b>I submitted it</b>.</li></ol>
<div>{file_btns}<button data-act="reopen">Open the form again</button></div>
<div style="margin-top:6px"><button class="main" data-act="manual">I submitted it</button>{queue_btns}</div></div>
<table>{body}</table>
<script>
document.querySelectorAll('button[data-act]').forEach(b => b.onclick = () => {{
  const a = b.dataset.act;
  if (!a.startsWith('reveal') && a !== 'reopen') {{ b.disabled = true; b.textContent = 'OK…'; }}
  window.employmintAction(a);
}});
document.querySelectorAll('button.copy').forEach(b => b.onclick = () => {{
  const t = document.createElement('textarea'); t.value = b.closest('tr').querySelector('td.a').innerText;
  document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove();
  b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy', 1200);
}});
</script></body></html>"""

def lever_handoff(page, job, url, queue, action):
    import subprocess
    rows, values = lever_rows(page, job)
    open_in_my_chrome(url)
    paths = {"reveal:resume": values.get("resume"), "reveal:cover": values.get("cover")}
    action["helpers"] = {k: (lambda f=f: me.reveal(f)) for k, f in paths.items() if f}
    action["helpers"]["reopen"] = lambda: open_in_my_chrome(url)
    page.goto("about:blank")
    page.set_content(lever_sheet_html(job, url, rows, values, queue))
    print(f"Opened {job['company']} · {job['title']} (lever): form in your Chrome, {len(rows)} answers on the sheet", flush=True)
    return None
