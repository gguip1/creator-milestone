"""Record every shot of docs/demo-script.md as per-segment browser footage.

Dry run against the local fake (no PayPal pages, no AI calls):
    (cd ../backend && uv run python -m scripts.dev_fake_paypal --judge --port 8765)
    uv run python record.py --base-url http://127.0.0.1:8765

Final take against the hosted demo (PayPal sandbox pages recorded for real):
    DEMO_BUYER_EMAIL=... DEMO_BUYER_PASSWORD=... uv run python record.py --live --base-url https://creator-milestone.onrender.com

Output: raw/<shot>-<n>.webm plus raw/manifest.json (segments, idle spans to trim, cut spans to remove)
and raw/run.json (invoice number, flags). Nothing secret is written, printed or kept.
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from urllib.parse import urlparse

import httpx
from playwright.sync_api import Locator, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

from common import RAW, SANDBOX_HOST, ensure_dirs

DESKTOP = {"width": 1920, "height": 1080}
PHONE = {"width": 390, "height": 844}
WAIT = 90_000  # ms: explicit wait ceiling for AI and PayPal round trips
LOCAL_HOSTS = {"127.0.0.1", "localhost"}

CURSOR_JS = """
(() => {
  const mk = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.style.cssText = 'position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;' +
      'transform:translate(-100px,-100px);transition:none;';
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 26 26"><path d="M3 2 L3 20 L8 15.5 L11.5 23 L14.5 21.7 L11 14.3 L18 14 Z" ' +
      'fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    const ring = document.createElement('div'); ring.id = '__ring';
    ring.style.cssText = 'position:fixed;left:0;top:0;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;' +
      'border:3px solid #ff9f1c;z-index:2147483646;pointer-events:none;opacity:0;';
    document.documentElement.appendChild(ring);
    let last = null; try { last = JSON.parse(sessionStorage.getItem('__cur')); } catch (e) {}
    if (last) c.style.transform = `translate(${last.x}px,${last.y}px)`;
    addEventListener('mousemove', e => {
      c.style.transform = `translate(${e.clientX}px,${e.clientY}px)`;
      try { sessionStorage.setItem('__cur', JSON.stringify({x: e.clientX, y: e.clientY})); } catch (x) {}
    }, true);
    addEventListener('mousedown', e => {
      ring.style.left = e.clientX + 'px'; ring.style.top = e.clientY + 'px';
      ring.animate([{opacity: 1, transform: 'scale(.4)'}, {opacity: 0, transform: 'scale(1.5)'}], {duration: 450});
    }, true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', mk); else mk();
})();
"""

SPOT_JS = """
(el, on) => {
  if (!on) { document.querySelectorAll('[data-spot]').forEach(e => { e.style.outline = ''; e.style.outlineOffset = ''; e.removeAttribute('data-spot'); }); return; }
  let n = el, limit = 6;
  const sec = el.closest('section, article') || document.body;
  const target = sec.getBoundingClientRect().width * 0.6;
  while (limit-- > 0 && n.parentElement && n.getBoundingClientRect().width < target && n.parentElement !== sec) n = n.parentElement;
  n.setAttribute('data-spot', '1');
  n.style.outline = '3px solid #ff9f1c'; n.style.outlineOffset = '4px';
}
"""


def die(msg: str) -> None:
    sys.exit(f"record.py: {msg}")


class Seg:
    """One recorded page: a cursor that glides, explicit waits, and trim marks."""

    def __init__(self, rec: "Recorder", shot: str, kind: str, page: Page, app: bool) -> None:
        self.rec, self.shot, self.kind, self.page, self.app = rec, shot, kind, page, app
        self.t0 = time.monotonic()
        self.x, self.y = (PHONE if kind == "phone" else DESKTOP)["width"] / 2, 300
        self.idle_spans: list[list[float]] = []
        self.cut_spans: list[list[float]] = []
        self.start_at = 0.0
        self.flags: dict = {}
        self.marks: list[tuple[str, float | None]] = [(shot, None)]  # (shot, start time) of each part

    def split(self, shot: str) -> None:
        """From here on the footage belongs to the next shot (same recording, sliced by the editor)."""
        self.marks.append((shot, self.now()))

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def open(self, url: str, ready: Locator | str) -> None:
        """Navigate, wait for a visible landmark, then start the usable footage a moment before it."""
        self.page.goto(url, wait_until="domcontentloaded")
        loc = self.page.locator(ready) if isinstance(ready, str) else ready
        loc.first.wait_for(state="visible", timeout=WAIT)
        self.page.mouse.move(self.x, self.y)
        self.start_at = max(0.0, self.now() - 0.3)

    def hold(self, seconds: float) -> None:
        self.page.wait_for_timeout(seconds * 1000)
        if self.app:
            self.rec.guard_secrets(self.page)

    @contextmanager
    def idle(self):
        """A wait that adds nothing to watch (AI, PayPal). The editor shortens it and marks the cut."""
        a = self.now()
        yield
        self.idle_spans.append([a, self.now()])

    @contextmanager
    def cut(self):
        """Footage that must not appear in the video at all."""
        a = self.now()
        yield
        self.cut_spans.append([a, self.now()])

    def glide(self, x: float, y: float, dur: float = 0.9) -> None:
        n = max(10, int(dur * 40))
        for i in range(1, n + 1):
            t = i / n
            e = t * t * (3 - 2 * t)
            self.page.mouse.move(self.x + (x - self.x) * e, self.y + (y - self.y) * e)
            self.page.wait_for_timeout(dur * 1000 / n)
        self.x, self.y = x, y

    def point(self, loc: Locator, dur: float = 0.9) -> None:
        first = loc.first
        first.wait_for(state="visible", timeout=WAIT)
        first.scroll_into_view_if_needed()
        box = first.bounding_box()
        if box:
            self.glide(box["x"] + min(box["width"] / 2, 220), box["y"] + box["height"] / 2, dur)

    def click(self, loc: Locator) -> None:
        self.point(loc)
        self.hold(0.3)
        loc.first.click()
        self.hold(0.4)

    def scroll_to(self, loc: Locator, block: str = "center") -> None:
        loc.first.wait_for(state="visible", timeout=WAIT)
        loc.first.evaluate(f"el => el.scrollIntoView({{behavior: 'smooth', block: '{block}'}})")
        self.hold(1.1)

    def spotlight(self, loc: Locator, seconds: float = 2.2) -> None:
        self.scroll_to(loc)
        self.point(loc, 0.7)
        loc.first.evaluate(SPOT_JS, True)
        self.hold(seconds)
        loc.first.evaluate(SPOT_JS, False)


class Recorder:
    def __init__(self, pw, base_url: str, live: bool, headed: bool) -> None:
        self.base = base_url.rstrip("/")
        self.live = live
        host = urlparse(self.base).hostname
        if not live and host not in LOCAL_HOSTS:
            die("a dry run only targets the local fake runner; pass --live for a hosted take")
        self.browser = pw.chromium.launch(headless=not headed, args=["--force-device-scale-factor=1"])
        self.state: dict | None = None
        self.manifest: list[dict] = []
        self.run: dict = {"mode": "live" if live else "dry", "base_url": self.base, "cached_analysis": False}
        self.counter: dict[str, int] = {}
        self.tmp = RAW / "tmp"
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.secrets = [os.environ[k] for k in ("DEMO_BUYER_PASSWORD",) if live and os.environ.get(k)]

    def guard_secrets(self, page: Page) -> None:
        if not self.secrets:
            return
        try:
            text = page.inner_text("body", timeout=2000)
        except Exception:  # noqa: BLE001
            return
        if any(s and s in text for s in self.secrets):
            die("the buyer password is visible on an app page; stop and fix the app text before recording")

    def new_context(self, kind: str, record: bool, state: dict | None):
        size = PHONE if kind == "phone" else DESKTOP
        kw: dict = {"viewport": size, "device_scale_factor": 1, "locale": "en-US"}
        if record:
            kw.update(record_video_dir=str(self.tmp), record_video_size=size)
        if state:
            kw["storage_state"] = state
        ctx = self.browser.new_context(**kw)
        ctx.add_init_script(CURSOR_JS)
        ctx.set_default_timeout(WAIT)
        return ctx

    def _save(self, seg: Seg, ctx, shot: str, extra: dict | None = None) -> None:
        vpath = seg.page.video.path()
        seg.page.close()
        ctx.close()
        n = self.counter[shot] = self.counter.get(shot, 0) + 1
        dest = RAW / f"{shot.lower()}-{n}.webm"
        shutil.move(vpath, dest)
        for i, (name, t) in enumerate(seg.marks):
            a = seg.start_at if t is None else t
            b = seg.marks[i + 1][1] if i + 1 < len(seg.marks) else None
            inside = lambda sp: sp[0] >= a - 0.01 and (b is None or sp[1] <= b + 0.01)  # noqa: E731
            self.manifest.append({
                "shot": name, "kind": seg.kind, "file": dest.name, "in": a, "out": b,
                "idle": [sp for sp in seg.idle_spans if inside(sp)], "cut": [sp for sp in seg.cut_spans if inside(sp)],
                **seg.flags, **(extra or {}),
            })

    @contextmanager
    def segment(self, shot: str, kind: str = "desktop", fresh: bool = False, save: bool = True):
        ctx = self.new_context(kind, True, None if fresh else self.state)
        page = ctx.new_page()
        seg = Seg(self, shot, kind, page, app=True)
        yield seg
        if save:
            self.state = ctx.storage_state()
        self._save(seg, ctx, shot)

    @contextmanager
    def silent(self):
        """Setup steps that never appear in the video (no recording)."""
        ctx = self.new_context("desktop", False, self.state)
        page = ctx.new_page()
        page.set_default_timeout(WAIT)
        yield page
        self.state = ctx.storage_state()
        ctx.close()


# ----------------------------------------------------------------------------- app flow

def check_cached(seg: Seg, rec: Recorder) -> None:
    if seg.page.get_by_text("Cached analysis").first.is_visible():
        seg.flags["cached"] = True
        rec.run["cached_analysis"] = True
        print(f"  note: {seg.shot} shows 'Cached analysis'." + (" RE-RECORD for the live take." if rec.live else " Expected on the fake runner."))


def shot_s2(rec: Recorder) -> str:
    with rec.segment("S2", fresh=True) as s:
        s.open(rec.base + "/", s.page.get_by_role("button", name="Try the demo"))
        s.scroll_to(s.page.get_by_text("Sandbox only", exact=False).last, "end")
        s.hold(2.0)
        s.scroll_to(s.page.get_by_role("button", name="Try the demo"), "center")
        s.click(s.page.get_by_role("button", name="Try the demo"))
        s.page.wait_for_url(re.compile(r"/projects/[0-9a-f]+/intake"))
        s.page.get_by_role("button", name="Use example message").wait_for(state="visible")
        s.hold(1.0)
        pid = re.search(r"/projects/([0-9a-f]+)", s.page.url)[1]
    return pid


def shot_s3_s4(rec: Recorder, pid: str) -> str:
    """S3 and S4 are one recording: the analysis lives in the page, so the fields are filled in place."""
    with rec.segment("S3") as s:
        s.open(f"{rec.base}/projects/{pid}/intake", s.page.get_by_role("button", name="Use example message"))
        s.click(s.page.get_by_role("button", name="Use example message"))
        s.click(s.page.get_by_role("button", name="Analyze"))
        with s.idle():
            s.page.get_by_text("Revisions: not confirmed").first.wait_for(state="visible", timeout=WAIT)
        check_cached(s, rec)
        s.spotlight(s.page.get_by_text("Revisions: not confirmed"), 2.6)
        s.spotlight(s.page.get_by_text("Usage rights: unknown"), 1.6)
        s.spotlight(s.page.get_by_text("Client email: unknown"), 1.6)
        s.scroll_to(s.page.get_by_text("Clarifying reply draft"), "start")
        s.hold(1.5)
        s.scroll_to(s.page.get_by_text("한국어", exact=False), "center")
        s.hold(2.5)
        s.split("S4")
        s.scroll_to(s.page.get_by_role("button", name="Fill example values"), "center")
        s.click(s.page.get_by_role("button", name="Fill example values"))
        s.spotlight(s.page.get_by_label("Revisions included"), 1.2)
        accept = s.page.get_by_role("button", name=re.compile(r"^Accept scope v1"))
        s.click(accept)
        s.page.wait_for_url(re.compile(r"/projects/[0-9a-f]+/?$"))
        s.page.get_by_text("You accepted scope v1").first.wait_for(state="visible")
        s.hold(2.0)
        href = client_href(s.page)
    with rec.segment("S4", "phone", fresh=True, save=False) as p:
        p.open(rec.base + href, p.page.get_by_role("button", name=re.compile(r"^Accept scope v1")))
        p.hold(1.5)
        p.click(p.page.get_by_role("button", name=re.compile(r"^Accept scope v1")))
        p.page.get_by_text("You accepted scope v1").first.wait_for(state="visible")
        p.hold(2.5)
    with rec.segment("S4") as s:
        s.open(f"{rec.base}/projects/{pid}", s.page.get_by_text("Milestones", exact=True).first)
        s.hold(3.0)
    return href


def client_href(page: Page) -> str:
    href = page.get_by_role("link", name="Open", exact=True).first.get_attribute("href")
    if not href or not href.startswith("/c/"):
        die("client page link not found on the project screen")
    return href


def preroll_revisions(rec: Recorder, pid: str) -> None:
    """Both revisions are used in the sketch round; log them off camera so Scope Guard bills the third."""
    with rec.silent() as page:
        page.goto(f"{rec.base}/projects/{pid}")
        for n in (1, 2):
            page.get_by_role("button", name="Log a revision").first.click()
            page.get_by_text(f"{n} of 2 used").first.wait_for(state="visible")


def shot_s1(rec: Recorder, pid: str, href: str) -> None:
    with rec.segment("S1") as s:
        s.open(f"{rec.base}/projects/{pid}/messages/new", s.page.get_by_role("button", name="Use example message"))
        s.click(s.page.get_by_role("button", name="Use example message"))
        s.click(s.page.get_by_role("button", name="Check against scope"))
        with s.idle():
            s.page.get_by_text("Change order total").first.wait_for(state="visible", timeout=WAIT)
        check_cached(s, rec)
        s.page.get_by_text("Exceeds limit: 2/2 revisions used").first.wait_for(state="visible")
        s.scroll_to(s.page.get_by_text("Scope Guard result"), "start")
        s.hold(1.2)
        s.spotlight(s.page.get_by_text("add a second outfit"), 2.4)
        s.spotlight(s.page.get_by_text("Exceeds limit: 2/2 revisions used"), 2.6)
        s.spotlight(s.page.get_by_text("I might use it on merch later"), 2.4)
        s.spotlight(s.page.get_by_text("Change order total"), 2.0)
    with rec.segment("S1") as s:
        s.open(f"{rec.base}/projects/{pid}", s.page.locator("article[aria-label='Change order #1: bill two extras']"))
        card = s.page.locator("article[aria-label='Change order #1: bill two extras']")
        s.spotlight(card, 1.6)
        s.click(card.get_by_role("button", name="Approve"))
        card.first.wait_for(state="hidden")  # the proposal card leaves once the client is asked
        s.hold(1.2)
    with rec.segment("S1", "phone", fresh=True, save=False) as p:
        p.open(rec.base + href, p.page.get_by_role("button", name="Approve change order"))
        p.hold(1.5)
        p.click(p.page.get_by_role("button", name="Approve change order"))
        p.page.get_by_text("You approved change order #1").first.wait_for(state="visible")
        p.hold(2.0)


def shot_s5(rec: Recorder, pid: str) -> dict:
    out: dict = {}
    with rec.segment("S5") as s:
        s.open(f"{rec.base}/projects/{pid}", s.page.locator("article[aria-label='Bill change order #1']"))
        bill = s.page.locator("article[aria-label='Bill change order #1']")
        s.spotlight(bill, 3.0)  # recipient, two lines, $100.00 total
        s.click(bill.get_by_role("button", name="Approve"))
        send = s.page.locator("article[aria-label='Send this invoice?']")
        with s.idle():
            send.first.wait_for(state="visible", timeout=WAIT)
        s.hold(1.5)
        s.click(send.get_by_role("button", name="Send invoice"))
        link = s.page.get_by_role("link", name="Open PayPal invoice")
        with s.idle():
            link.first.wait_for(state="visible", timeout=WAIT)
        out["payer_link"] = link.first.get_attribute("href")
        body = s.page.inner_text("main")
        m = re.search(r"CM-[0-9a-f]+-[0-9a-f]+-\d+", body)
        if not m:
            die("invoice number not found on the project screen after sending")
        out["invoice_number"] = m[0]
        s.scroll_to(s.page.get_by_text(m[0]).first, "center")
        s.hold(3.0)
    return out


def check_payer_link(link: str | None) -> str:
    u = urlparse(link or "")
    if u.scheme != "https" or u.hostname != SANDBOX_HOST:
        die(f"payer link host is {u.hostname!r}, not {SANDBOX_HOST}; refusing to open it")
    return link


# ----------------------------------------------------------------------------- PayPal (live only)

def assert_sandbox(page: Page) -> None:
    host = urlparse(page.url).hostname
    if host != SANDBOX_HOST:
        die(f"on {host!r}, not {SANDBOX_HOST}; refusing to enter anything")


def paypal_login(page: Page, email: str, password: str) -> None:
    """Sign in on the sandbox. Values are never printed; failures report only where it stopped."""
    assert_sandbox(page)
    page.locator("#email").fill(email)
    if page.locator("#btnNext").is_visible():
        page.locator("#btnNext").click()
    page.locator("#password").wait_for(state="visible")
    assert_sandbox(page)
    page.locator("#password").fill(password)
    page.locator("#btnLogin").click()


def buyer_state(rec: Recorder, email: str, password: str) -> dict:
    """Log in once in an unrecorded, in-memory context, so the login is never on camera."""
    ctx = rec.new_context("desktop", False, None)
    page = ctx.new_page()
    try:
        page.goto(f"https://{SANDBOX_HOST}/signin", wait_until="domcontentloaded")
        paypal_login(page, email, password)
        page.wait_for_url(lambda u: "signin" not in u, timeout=WAIT)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        die(f"sandbox buyer pre-login failed ({type(exc).__name__}); watch for a verification prompt")
    state = ctx.storage_state()
    ctx.close()
    return state


def shots_s6_s7(rec: Recorder, link: str, number: str) -> None:
    email, password = os.environ.get("DEMO_BUYER_EMAIL"), os.environ.get("DEMO_BUYER_PASSWORD")
    if not email or not password:
        die("live mode needs DEMO_BUYER_EMAIL and DEMO_BUYER_PASSWORD in the environment")
    link = check_payer_link(link)
    state = buyer_state(rec, email, password)
    ctx = rec.new_context("desktop", True, state)  # a clean private window that is already signed in
    page = ctx.new_page()
    seg = Seg(rec, "S6", "desktop", page, app=False)
    page.goto(link, wait_until="domcontentloaded")
    assert_sandbox(page)
    page.get_by_text(number).first.wait_for(state="visible", timeout=WAIT)
    text = page.inner_text("body")
    for needle in ("100.00", "80.00", "20.00"):
        if needle not in text:
            die(f"the PayPal invoice page does not show {needle}; not the invoice from S5")
    seg.start_at = max(0.0, seg.now() - 0.3)
    page.mouse.move(seg.x, seg.y)
    seg.hold(3.0)
    terms = re.search(r"terms and conditions", text, re.I) and re.search(r"scope v2|version 2|v2", text, re.I)
    rec.run["terms_visible_on_paypal_page"] = bool(terms)
    if not terms:
        print("  WARNING: note/terms not found on the PayPal page. Cut the last sentence of S6 and its caption.")
    for part in ("terms", "note"):
        loc = page.get_by_text(re.compile(rf"{part}", re.I)).last
        if loc.count():
            seg.scroll_to(loc, "center")
            seg.hold(2.2)
    seg.scroll_to(page.get_by_text(number).first, "center")
    seg.hold(2.5)
    split_t = seg.now()
    seg.start_s7 = split_t
    # S7: pay the same invoice.
    pay = page.get_by_role("button", name=re.compile(r"^pay( now)?$", re.I)).or_(
        page.get_by_role("link", name=re.compile(r"^pay( now)?$", re.I)))
    seg.click(pay)
    cut_from: float | None = None
    deadline = time.monotonic() + 120
    done = re.compile(r"(you('ve| have)? paid|payment (was )?(sent|successful|complete)|thank you|payment receipt)", re.I)
    step = re.compile(r"^(pay now|complete purchase|continue|pay)$", re.I)
    while time.monotonic() < deadline:
        assert_sandbox(page)
        if page.locator("#password").is_visible() or page.locator("#email").is_visible():
            # The pre-login did not carry over. Log in here, off camera in the edit.
            cut_from = seg.now()
            paypal_login(page, email, password)
            page.locator("#password").wait_for(state="hidden", timeout=WAIT)
            seg.cut_spans.append([cut_from, seg.now() + 0.4])
            continue
        if done.search(page.inner_text("body")):
            break
        btn = page.get_by_role("button", name=step).first
        try:
            btn.wait_for(state="visible", timeout=6000)
            seg.click(btn)
        except PWTimeout:
            page.wait_for_timeout(1000)
    else:
        shot = RAW / "debug-paypal.png"
        page.screenshot(path=str(shot))
        die(f"PayPal confirmation not reached in 120 s; screenshot at {shot}. Do the payment by hand and re-record S8 only.")
    seg.hold(4.0)
    if "100.00" not in page.inner_text("body"):
        print("  WARNING: $100.00 not visible on the confirmation page; check S7 by eye.")
    end_t = seg.now()
    vpath = page.video.path()
    page.close()
    ctx.close()
    dest = RAW / "paypal-1.webm"
    shutil.move(vpath, dest)
    cuts = seg.cut_spans
    rec.manifest.append({"shot": "S6", "kind": "desktop", "file": dest.name, "in": seg.start_at, "out": split_t,
                         "idle": [], "cut": [], "app": False})
    rec.manifest.append({"shot": "S7", "kind": "desktop", "file": dest.name, "in": split_t, "out": end_t,
                         "idle": [], "cut": cuts, "app": False})


def placeholders(rec: Recorder, number: str) -> None:
    for shot in ("S6", "S7"):
        rec.manifest.append({"shot": shot, "kind": "placeholder", "text": "PayPal page recorded in live take",
                             "sub": f"Invoice {number} (fake runner)", "file": None, "in": 0, "out": None, "idle": [], "cut": []})


def shot_s8(rec: Recorder, pid: str) -> None:
    if not rec.live:
        httpx.post(rec.base + "/dev/pay", timeout=10).raise_for_status()  # fake runner only: the buyer "pays"
    with rec.segment("S8") as s:
        s.open(f"{rec.base}/projects/{pid}", s.page.get_by_text("Change orders").first)
        s.scroll_to(s.page.get_by_text("Change orders").first, "start")
        refresh = s.page.get_by_role("button", name="Check PayPal now")
        if refresh.count():
            s.click(refresh.first)
        with s.idle():
            s.page.get_by_text("Paid via PayPal").first.wait_for(state="visible", timeout=WAIT)
        s.hold(2.0)
        s.spotlight(s.page.get_by_text("Paid via PayPal").first, 2.2)
        s.spotlight(s.page.get_by_text(re.compile(r"Status read from PayPal: Paid via PayPal")).first, 3.0)
        s.scroll_to(s.page.locator("#activity-h"), "start")
        s.hold(3.0)


def shot_s9(rec: Recorder) -> None:
    with rec.segment("S9") as s:
        s.open(rec.base + "/", s.page.get_by_text("Who it is for", exact=True))
        s.scroll_to(s.page.get_by_text("Who it is for", exact=True), "start")
        s.hold(6.5)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--live", action="store_true", help="final take: record the PayPal sandbox pages")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    ensure_dirs()
    for f in RAW.glob("*.webm"):
        f.unlink()
    with sync_playwright() as pw:
        rec = Recorder(pw, args.base_url, args.live, args.headed)
        try:
            print("S2 landing"); pid = shot_s2(rec)
            print("S3/S4 intake, both accept"); href = shot_s3_s4(rec, pid)
            print("setup: revisions used up (not recorded)"); preroll_revisions(rec, pid)
            print("S1 change order"); shot_s1(rec, pid, href)
            print("S5 invoice created and sent"); info = shot_s5(rec, pid)
            rec.run.update(invoice_number=info["invoice_number"], project_id=pid)
            if args.live:
                print("S6/S7 PayPal sandbox"); shots_s6_s7(rec, info["payer_link"], info["invoice_number"])
            else:
                print("S6/S7 skipped (placeholders)"); placeholders(rec, info["invoice_number"])
            print("S8 read back"); shot_s8(rec, pid)
            print("S9 landing"); shot_s9(rec)
        finally:
            rec.browser.close()
    (RAW / "manifest.json").write_text(json.dumps(rec.manifest, indent=2))
    (RAW / "run.json").write_text(json.dumps(rec.run, indent=2))
    shutil.rmtree(rec.tmp, ignore_errors=True)
    print(f"done: {len(rec.manifest)} segments, invoice {rec.run['invoice_number']}")


if __name__ == "__main__":
    main()
