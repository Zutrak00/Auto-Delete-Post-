"""Drives a real browser for networks with no free API (X, Instagram).

The user logs in once in a visible window; the browser profile (cookies) is kept in the app's data folder so later
runs work in the background. We prefer a Chromium-based browser already installed on the computer (Chrome, Edge,
Brave, Vivaldi, Opera, Chromium) and only download Chromium if none is available.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .providers.base import ProviderError

log = logging.getLogger("autodelete")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def profile_dir(data_dir: Path, account_id: int) -> Path:
    return data_dir / "browser-profiles" / f"account-{account_id}"


@contextmanager
def open_browser(profile: Path, headless: bool = True, start_url: str | None = None):
    """Yield (context, page) for a persistent browser profile. Only one user of a profile at a time."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    key = str(profile)
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        raise ProviderError("This account's browser is busy (a login window or another run is open). Try again shortly.")
    try:
        profile.mkdir(parents=True, exist_ok=True)
        _use_persistent_browser_folder()  # must be set before Playwright's driver starts
        with sync_playwright() as pw:
            context = _launch(pw, profile, headless, PlaywrightError)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(20000)
                if start_url:
                    page.goto(start_url, wait_until="domcontentloaded")
                yield context, page
            finally:
                try:
                    context.close()
                except PlaywrightError:
                    pass
    finally:
        lock.release()


# Chromium-based browsers Playwright can drive, besides Chrome and Edge (found through Playwright's channels).
# Safari and the regular Firefox can't be automated this way.
_MAC_APPS = ["Brave Browser", "Vivaldi", "Chromium", "Opera", "Google Chrome Beta", "Google Chrome Canary"]
_WINDOWS_EXES = [  # relative to Program Files, Program Files (x86) or %LOCALAPPDATA%
    "BraveSoftware/Brave-Browser/Application/brave.exe",
    "Vivaldi/Application/vivaldi.exe",
    "Chromium/Application/chrome.exe",
    "Programs/Opera/opera.exe",
    "Opera/opera.exe",
]
_LINUX_COMMANDS = ["brave-browser", "brave", "vivaldi-stable", "vivaldi", "chromium", "chromium-browser", "opera"]


def other_browsers() -> list[str]:
    """Paths of installed Chromium-based browsers other than Chrome and Edge."""
    if sys.platform == "darwin":
        found = []
        for name in _MAC_APPS:
            for apps in (Path("/Applications"), Path.home() / "Applications"):
                exe = apps / f"{name}.app" / "Contents" / "MacOS" / name
                if exe.is_file():
                    found.append(str(exe))
                    break
        return found
    if sys.platform == "win32":
        roots = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        return [str(Path(root) / rel) for rel in _WINDOWS_EXES for root in roots
                if root and (Path(root) / rel).is_file()]
    return [path for path in (shutil.which(cmd) for cmd in _LINUX_COMMANDS) if path]


def _launch(pw, profile: Path, headless: bool, error_cls):
    options = dict(headless=headless, args=LAUNCH_ARGS, locale="en-US", viewport={"width": 1200, "height": 900})
    custom = os.environ.get("AUTODELETE_BROWSER_PATH")
    if custom:
        return pw.chromium.launch_persistent_context(str(profile), executable_path=custom, **options)
    channels = ["msedge", "chrome"] if sys.platform == "win32" else ["chrome", "msedge"]
    attempts = [dict(channel=c) for c in channels] + [dict(executable_path=p) for p in other_browsers()]
    for attempt in attempts:
        try:
            return pw.chromium.launch_persistent_context(str(profile), **attempt, **options)
        except error_cls as exc:
            log.debug("Browser %s didn't start: %s", attempt, str(exc).splitlines()[0] if str(exc) else exc)
    # No usable browser installed: use Playwright's own Chromium, downloading it once if needed.
    try:
        return pw.chromium.launch_persistent_context(str(profile), **options)
    except error_cls:
        log.info("Downloading Chromium (one time, about 150 MB)...")
        install_chromium()
        return pw.chromium.launch_persistent_context(str(profile), **options)


def _use_persistent_browser_folder() -> None:
    """In the packaged app Playwright looks for its Chromium inside the app's temporary unpack folder, which is
    deleted on exit, while `install` puts it in the user's cache. Point both at the usual cache folder."""
    if not getattr(sys, "frozen", False) or os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    home = Path.home()
    if sys.platform == "win32":
        cache = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    elif sys.platform == "darwin":
        cache = home / "Library" / "Caches"
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cache / "ms-playwright")


def install_chromium() -> None:
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    driver = compute_driver_executable()
    cmd = list(driver) if isinstance(driver, (tuple, list)) else [str(driver)]
    result = subprocess.run([*cmd, "install", "chromium"], env=get_driver_env(), capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("Chromium download failed: %s", (result.stderr or result.stdout).strip()[-500:])
        raise ProviderError("Couldn't find a Chromium-based browser (Chrome, Edge, Brave, Vivaldi, Opera), and "
                            "downloading one failed. Install one of them and try again.")


# --- login window ------------------------------------------------------------------

LOGIN_STATES: dict[int, dict] = {}


def start_login(account_id: int, profile: Path, login_url: str, is_logged_in: Callable,
                on_success: Callable[[dict], None], timeout: float = 600) -> None:
    """Open a visible browser at the login page in the background and watch for the user to finish logging in."""
    state = LOGIN_STATES[account_id] = {"status": "opening", "message": ""}

    def run():
        try:
            with open_browser(profile, headless=False, start_url=login_url) as (context, page):
                state["status"] = "waiting"
                deadline = time.time() + timeout
                while time.time() < deadline:
                    info = is_logged_in(context)
                    if info is not None:
                        time.sleep(2)  # let the site finish writing its cookies
                        on_success(info)
                        state["status"] = "ok"
                        return
                    if not context.pages:  # user closed the window
                        break
                    time.sleep(1)
                state.update(status="failed", message="The login window was closed before you finished logging in.")
        except Exception as exc:  # noqa: BLE001 - shown to the user
            log.warning("Login window failed: %s", exc)
            state.update(status="failed", message=str(exc).splitlines()[0] if str(exc) else "Login failed.")

    threading.Thread(target=run, daemon=True, name=f"login-{account_id}").start()


def cookie(context, url: str, name: str) -> str | None:
    for c in context.cookies(url):
        if c["name"] == name and c.get("value"):
            return c["value"]
    return None


# --- reading data the site loads ---------------------------------------------------------

class ResponseCollector:
    """Collects JSON the page loads (API calls and embedded JSON) so we can read posts without fragile scraping."""

    def __init__(self, page, url_filter: Callable[[str], bool]):
        self.page = page
        self.url_filter = url_filter
        self.payloads: list = []
        page.on("response", self._on_response)

    def _on_response(self, response) -> None:
        if not self.url_filter(response.url):
            return
        try:
            if "json" in (response.headers.get("content-type") or ""):
                self.payloads.append(response.json())
        except Exception:  # noqa: BLE001 - some responses have no body (redirects, aborted)
            pass

    def embedded_json(self) -> None:
        for text in self.page.locator('script[type="application/json"]').all_text_contents():
            try:
                self.payloads.append(json.loads(text))
            except ValueError:
                pass

    def drain(self) -> list:
        items, self.payloads = self.payloads, []
        return items


def walk(obj) -> Iterator[dict]:
    """Every dict nested anywhere inside a JSON value."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def scroll_until_done(page, collect: Callable[[], int], max_scrolls: int = 400, patience: int = 6,
                      pause: float = 1.5) -> None:
    """Scroll to the bottom repeatedly until no new posts show up for `patience` scrolls."""
    idle = 0
    for _ in range(max_scrolls):
        new = collect()
        idle = 0 if new else idle + 1
        if idle >= patience:
            return
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(int(pause * 1000))
