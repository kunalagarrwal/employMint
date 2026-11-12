"""Small Playwright helpers shared by every site: waiting, the panel, confirmation detection, launching Chrome."""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jobs import ROOT  # noqa: E402
from formjs import PANEL_JS  # noqa: E402

BROWSER_PROFILE = ROOT / "data" / "browser-profile"  # keeps your logins between runs; stays on this laptop

CONFIRM_TEXT = re.compile(
    r"application (has been |was |has )?(successfully )?(been )?(submitted|received)|thank(s| you) for (applying|your application|submitting)"
    r"|we(?:'ve| have) received your application|your application (has been|was) (sent|submitted|received)", re.I)

CONFIRM_URL = re.compile(r"confirmation|/thanks|thank-you|thank_you|submitted|success|jobTasks/completed", re.I)

def submitted(ctx):
    """Returns the URL once a tab shows a confirmation message and the form is gone or the URL changed."""
    for pg in ctx.pages:
        try:
            if pg.is_closed():
                continue
            text = pg.evaluate("() => document.body ? document.body.innerText.slice(0, 20000) : ''")
            form_gone = pg.evaluate("() => !document.querySelector('[data-em-q]')")
            if CONFIRM_TEXT.search(text) and (form_gone or CONFIRM_URL.search(pg.url)):
                return pg.url
        except Exception:
            continue  # page is mid-navigation
    return None

def launch_browser(p, action):
    """Visible Chrome with the applicant's saved logins. Panel buttons call window.employmintAction(...)."""
    import fcntl
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    lock = open(BROWSER_PROFILE.parent / ".browser-profile.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("Another application window is already open (the queue or Open application). Close it first.")
    action["_lock"] = lock  # held until this process exits
    ctx = p.chromium.launch_persistent_context(str(BROWSER_PROFILE), channel="chrome", headless=False,
                                               no_viewport=True, args=["--start-maximized"],
                                               ignore_default_args=["--no-sandbox", "--enable-automation"])
    def on_action(source, value):
        # Only the page itself (our panel or the Lever sheet), never an ad or embedded iframe on a job site.
        if source.get("frame") is not None and source["frame"].parent_frame is not None:
            return
        action["v"] = value
    ctx.expose_binding("employmintAction", on_action)
    return ctx

def settle(page, ms=1500):
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(ms)

def visible(page, sel):
    try:
        return page.locator(sel).first.is_visible()
    except Exception:
        return False

def show(page, items, filled, title, queue):
    panel = [items, filled, title, queue]
    try:
        page.evaluate(PANEL_JS, panel)
    except Exception:
        pass
    return panel

def wait_fields_stable(page, timeout_s=10):
    """Workday renders a step's fields over a few seconds; wait until the count stops changing."""
    last, same, end = -1, 0, time.time() + timeout_s
    while time.time() < end:
        try:
            n = page.locator('[data-automation-id^="formField-"], input:visible, textarea:visible').count()
        except Exception:
            n = -1
        same = same + 1 if n == last and n > 0 else 0
        if same >= 2:
            return
        last = n
        page.wait_for_timeout(700)

def wait_while(page, action, cond, timeout_s=1200):
    """Polls until cond() is False, a panel button is pressed, or time runs out. Returns the pressed action or None."""
    end = time.time() + timeout_s
    while time.time() < end:
        if action.get("v") and action["v"] != "manual":
            return action["v"]
        try:
            if not cond():
                return None
            page.wait_for_timeout(1500)
        except Exception:
            time.sleep(1.5)
    return None
