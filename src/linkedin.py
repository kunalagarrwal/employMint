"""LinkedIn helper for recruiter outreach. Uses its own Chrome profile (data/linkedin-profile), signed in once by the applicant.

It only ever:
  - searches people (for the draft step),
  - sends connection requests WITHOUT a note to recruiters the applicant approved (status 'approved'),
  - sends the applicant's approved message to recruiters who accepted, and
  - reads their inbox to spot replies (it never replies).

Usage:
  python3 src/linkedin.py login                 # opens Chrome so you can sign in once
  python3 src/linkedin.py search "<query>"      # JSON list of {name, title, url}
  python3 src/linkedin.py profile "<url>"       # a person's headline, about, experience, education (for personalizing)
  python3 src/linkedin.py invite [--dry-run]    # send every approved request now
  python3 src/linkedin.py check  [--dry-run]    # accepts -> send message, replies -> notify (runs 9 AM, 1 PM, 7 PM)
Add --show to watch the browser.
"""
import fcntl
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import ROOT, now_iso  # noqa: E402
import me  # noqa: E402
import outreach  # noqa: E402

PROFILE = ROOT / "data" / "linkedin-profile"
BROWSER_LOCK = ROOT / "data" / ".linkedin-browser.lock"
BASE = "https://www.linkedin.com"
MAX_INVITES_PER_RUN = 15


class NeedLogin(Exception):
    pass


def pause(lo=2.5, hi=6.0):
    time.sleep(random.uniform(lo, hi))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def vanity(url):
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url)
    return m.group(1) if m else None


def first_name(name):
    return re.sub(r"\(.*?\)", "", name).split()[0] if name else ""


# ---------- browser ----------

def browser_lock(wait):
    BROWSER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    f = open(BROWSER_LOCK, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
    except BlockingIOError:
        f.close()
        return None
    return f


def launch(p, show):
    PROFILE.mkdir(parents=True, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE), channel="chrome", headless=not show, viewport={"width": 1280, "height": 900},
        ignore_default_args=["--enable-automation"], args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def goto(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    pause(2.5, 4.5)
    if re.search(r"/(login|checkpoint|authwall|uas/login)", page.url):
        raise NeedLogin(page.url)


# ---------- search ----------

SEARCH_JS = r"""() => {
  const seen = new Set(), out = [];
  for (const a of document.querySelectorAll('main a[href*="/in/"]')) {
    const url = a.href.split('?')[0];
    if (!/\/in\/[^/]+\/?$/.test(url) || seen.has(url)) continue;
    const box = a.closest('li') || a.closest('div[data-view-name]') || a.parentElement;
    const lines = (box ? box.innerText : '').split('\n').map(s => s.trim()).filter(Boolean);
    if (!lines.length || /mutual connection/.test(lines[0])) continue;
    seen.add(url);
    const name = lines[0].replace(/\s*•.*$/, '').trim();
    const rest = lines.slice(1).filter(s => !/^•?\s*(1st|2nd|3rd\+?)$/.test(s.replace(/^•\s*/, '')) && !/^•/.test(s));
    out.push({name, title: rest[0] || '', location: rest[1] || '', url: url.endsWith('/') ? url : url + '/'});
  }
  return out.slice(0, 10);
}"""


def cmd_search(page, query):
    from urllib.parse import quote
    goto(page, f"{BASE}/search/results/people/?keywords={quote(query)}")
    page.wait_for_selector('main a[href*="/in/"]', timeout=15000)
    print(json.dumps(page.evaluate(SEARCH_JS), indent=1, ensure_ascii=False))


# ---------- invites ----------

def send_invite(page, person, dry):
    """Returns 'requested', 'blocked' or raises."""
    v = vanity(person["url"])
    goto(page, f"{BASE}/preload/custom-invite/?vanityName={v}")
    dialog = page.locator('[role="dialog"]').first
    dialog.wait_for(timeout=15000)
    text = dialog.inner_text()
    if first_name(person["name"]).lower() not in text.lower():
        raise RuntimeError(f"invite dialog didn't name {person['name']}: {text[:120]!r}")
    if re.search(r"enter their email|email to connect", text, re.I):
        dialog.get_by_role("button", name=re.compile("dismiss|close", re.I)).first.click()
        return "blocked"
    send = dialog.get_by_role("button", name="Send without a note")
    if dry:
        log("  [dry run] would click Send without a note for", person["name"])
        return "requested"
    send.click()
    pause(2, 4)
    return "requested"


def run_invites(page, dry):
    sent = []
    for _ in range(MAX_INVITES_PER_RUN):
        approved = [p for p in outreach.load().get("people", []) if p.get("status") == "approved"
                    and p.get("invite_attempts", 0) < 2]
        if not approved:
            break
        person = approved[0]
        log("inviting", person["name"], f"({person['company']})")
        try:
            result = send_invite(page, person, dry)
        except NeedLogin:
            raise
        except Exception as ex:
            log("  failed:", ex)
            if not dry:
                outreach.set_fields(person["url"], invite_attempts=person.get("invite_attempts", 0) + 1,
                                    last_error=f"{outreach.today()}: invite failed: {str(ex)[:160]}")
            if dry:
                break
            continue
        if dry:
            break
        if result == "blocked":
            outreach.set_fields(person["url"], status="blocked", note="Profile only accepts requests from people who know their email.")
        else:
            outreach.set_fields(person["url"], status="requested", requested_at=outreach.today())
            sent.append(person)
        pause(4, 9)
    return sent


# ---------- accepts, messages, replies ----------

DEGREE_JS = r"""() => {
  const t = (document.querySelector('main') || document.body).innerText.slice(0, 600);
  const labels = [...document.querySelectorAll('[aria-label]')].map(e => e.getAttribute('aria-label'));
  const pending = labels.some(l => /^Pending, click to withdraw/i.test(l));
  const first = /·\s*1st\b/.test(t) || labels.some(l => /1st degree connection/i.test(l));
  return {pending, first};
}"""


def open_profile(page, url):
    """Profile pages: the name is an h2 now and the top card loads after the shell, so wait for the degree line."""
    goto(page, url)
    page.wait_for_function("() => /·\\s*(1st|2nd|3rd)|Pending|Connect|Message/.test((document.querySelector('main')||{}).innerText||'')",
                           timeout=20000)
    pause(1, 2)


PROFILE_JS = r"""() => (document.querySelector('main') || document.body).innerText
  .replace(/\n{2,}/g, '\n').split('\n').filter(l => !/^(Message|Follow|Connect|More|Pending|Show all.*|…see more|Contact info|·)$/.test(l.trim()))
  .join('\n').slice(0, 3500)"""


def cmd_profile(page, url):
    open_profile(page, url)
    for _ in range(5):  # experience / education load as you scroll
        page.mouse.wheel(0, 2500)
        pause(0.8, 1.5)
    text = page.evaluate(PROFILE_JS)
    # Drop the "Activity" feed (their reposts); keep headline, about, experience, education.
    text = re.sub(r"\nActivity\n.*?(?=\n(Experience|Education|Skills|Licenses)\n|$)", "\n", text, flags=re.S)
    print(text[:3000])


def connection_state(page, person):
    open_profile(page, person["url"])
    s = page.evaluate(DEGREE_JS)
    if s["first"]:
        return "accepted"
    if s["pending"]:
        return "pending"
    # The pending link sometimes lives in the "More" menu; the sent-invitations page is the fallback check.
    return "unknown"


def send_message(page, person, dry):
    """Opens a chat from the profile and sends the approved message. Returns True if sent (or would be)."""
    open_profile(page, person["url"])
    btn = page.locator("main").get_by_role("button", name=re.compile(r"^Message", re.I)).first
    if not btn.count():
        btn = page.locator("main").get_by_role("link", name=re.compile(r"^Message", re.I)).first
    btn.click()
    pause(2.5, 4)
    box = page.locator('div.msg-form__contenteditable[contenteditable="true"]').last
    box.wait_for(timeout=15000)
    convo = page.locator(".msg-overlay-conversation-bubble, .msg-convo-wrapper, main").last
    header = convo.inner_text()[:400]
    if first_name(person["name"]).lower() not in header.lower():
        raise RuntimeError(f"chat window isn't with {person['name']}")
    if convo.locator(".msg-s-event-listitem").count() > 0:
        raise RuntimeError("conversation already has messages; not sending")
    if dry:
        log("  [dry run] would send:", person["message"][:80], "...")
        return True
    box.click()
    page.keyboard.insert_text(person["message"])
    pause(1, 2)
    convo.locator("button.msg-form__send-button, button[type=submit]").first.click()
    pause(2.5, 4)
    if person["message"][:40] not in convo.inner_text():
        raise RuntimeError("message didn't show up after sending")
    try:
        convo.locator('button[aria-label^="Close your conversation"], button[aria-label^="Close your draft"]').first.click(timeout=3000)
    except Exception:
        pass
    return True


INBOX_JS = r"""() => [...document.querySelectorAll('li.msg-conversation-listitem, li[class*="conversation-listitem"]')].map(li => li.innerText.replace(/\s+\n/g, '\n').trim()).slice(0, 60)"""


def inbox_items(page):
    goto(page, f"{BASE}/messaging/")
    page.wait_for_selector('li[class*="conversation-listitem"]', timeout=20000)
    pause(1, 2)
    return page.evaluate(INBOX_JS)


def find_reply(items, person):
    """Returns the snippet if the latest message in their conversation is from them, else None."""
    name = re.sub(r"\(.*?\)", "", person["name"]).strip()
    for it in items:
        if name.split()[0].lower() in it.lower() and (name.split()[-1].lower().rstrip(".") in it.lower()):
            lines = [line for line in it.split("\n") if line.strip()]
            snippet = next((line for line in lines[1:] if ":" in line or len(line) > 25), lines[-1] if lines else "")
            if re.match(r"^\s*You:", snippet):
                return None
            if person.get("message", "")[:30] and person["message"][:30] in snippet:
                return None
            return snippet.split(":", 1)[-1].strip() if ":" in snippet else snippet.strip()
    return None


def cmd_check(page, dry):
    report = {"accepted": [], "replied": [], "pending": 0, "errors": []}
    # 1. Recruiters for any new applications (backup for the apply hook) and any approved requests.
    if not dry:
        started = outreach.draft_for_new_applications()
        if started:
            log("drafting recruiters for:", ", ".join(started))
    report["invited"] = [p["name"] for p in run_invites(page, dry)]

    people = outreach.load().get("people", [])
    # 2. Accepts -> send the approved message.
    for person in [p for p in people if p.get("status") == "requested"]:
        try:
            state = connection_state(page, person)
        except NeedLogin:
            raise
        except Exception as ex:
            report["errors"].append(f"{person['name']}: {str(ex)[:100]}")
            continue
        log(person["name"], "->", state)
        if state == "pending" or state == "unknown":
            report["pending"] += 1
            continue
        try:
            send_message(page, person, dry)
            if not dry:
                outreach.set_fields(person["url"], status="messaged", messaged_at=outreach.today())
            report["accepted"].append(f"{person['name']} ({person['company']})")
        except NeedLogin:
            raise
        except Exception as ex:
            # Status 'accepted' (not 'requested') so a half-sent message is never sent twice; the applicant sees the error.
            report["errors"].append(f"message to {person['name']}: {str(ex)[:120]}")
            if not dry:
                outreach.set_fields(person["url"], status="accepted", last_error=f"{outreach.today()}: {str(ex)[:160]}")
        pause(4, 8)

    # 3. Replies.
    waiting = [p for p in outreach.load().get("people", []) if p.get("status") == "messaged"]
    if waiting:
        try:
            items = inbox_items(page)
            for person in waiting:
                snippet = find_reply(items, person)
                if snippet:
                    report["replied"].append(f"{person['name']} ({person['company']}): {snippet[:120]}")
                    if not dry:
                        outreach.set_fields(person["url"], status="replied", replied_at=outreach.today(), reply=snippet[:500])
        except NeedLogin:
            raise
        except Exception as ex:
            report["errors"].append(f"inbox: {str(ex)[:120]}")

    long_pending = [p["name"] for p in people if p.get("status") == "requested" and p.get("requested_at")
                    and (time.time() - time.mktime(time.strptime(p["requested_at"], "%Y-%m-%d"))) > 21 * 86400]
    report["long_pending"] = long_pending
    if not dry:
        with outreach.editing() as d:
            d["last_check"] = {"at": now_iso(), **report}
    log("report:", json.dumps(report, indent=1, ensure_ascii=False))

    bits = []
    if report["replied"]:
        bits.append(f"{len(report['replied'])} recruiter{'s' if len(report['replied']) != 1 else ''} replied: "
                    + ", ".join(r.split(' (')[0] for r in report["replied"]))
    if report["accepted"]:
        bits.append(f"messaged {len(report['accepted'])} who accepted")
    if report["errors"]:
        bits.append(f"{len(report['errors'])} problem(s), see review page")
    if bits and not dry:
        outreach.notify("LinkedIn outreach", "; ".join(bits))


def main():
    from playwright.sync_api import sync_playwright
    if not me.outreach_enabled(me.prefs()):
        sys.exit('Recruiter outreach is off. To use it, set "recruiter_outreach": true in profile/preferences.json '
                 "(automating LinkedIn is against its user agreement; you take that risk).")
    args = sys.argv[1:]
    show = "--show" in args
    dry = "--dry-run" in args
    args = [a for a in args if a not in ("--show", "--dry-run")]
    if not args or args[0] not in ("login", "search", "profile", "invite", "check"):
        sys.exit(__doc__)
    cmd = args[0]
    # invite: if another run already holds the browser, it will pick up new approvals itself.
    lock = browser_lock(wait=cmd != "invite")
    if lock is None:
        log("another LinkedIn run is active; it will send this approval")
        return
    with sync_playwright() as p:
        ctx, page = launch(p, show or cmd == "login")
        try:
            if cmd == "login":
                page.goto(f"{BASE}/login")
                print("Sign in to LinkedIn in the Chrome window. It closes by itself once you're on your feed.", flush=True)
                page.wait_for_url(re.compile(r"linkedin\.com/(feed|in/|mynetwork)"), timeout=10 * 60 * 1000)
                pause(2, 3)
                print("Signed in. You won't need to do this again.")
            elif cmd == "search":
                cmd_search(page, " ".join(args[1:]))
            elif cmd == "profile":
                cmd_profile(page, args[1])
            elif cmd == "invite":
                sent = run_invites(page, dry)
                if sent and not dry:
                    outreach.notify("LinkedIn outreach", "Request sent to " + ", ".join(p["name"] for p in sent))
            else:
                cmd_check(page, dry)
        except NeedLogin:
            msg = "LinkedIn signed you out. Run: python3 src/linkedin.py login"
            log(msg)
            if not dry:
                with outreach.editing() as d:
                    d["last_check"] = {"at": now_iso(), "errors": [msg]}
                outreach.notify("LinkedIn outreach", msg)
            sys.exit(2)
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
