"""X (Twitter) through the user's own logged-in browser: free, no developer account needed."""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ..models import Post, parse_time
from .base import Field, Provider, ProviderError

BASE = os.environ.get("AUTODELETE_X_BASE", "https://x.com")
X_TIME = "%a %b %d %H:%M:%S %z %Y"  # "Wed Oct 10 20:19:24 +0000 2018"

# The Delete menu item has no stable id, so match its label (X follows the account language).
DELETE_LABEL = re.compile(
    r"^\s*(Delete|Eliminar|Supprimer|Löschen|Excluir|Elimina|Verwijderen|Sil|Usuń|Удалить|削除|삭제|删除|刪除)\s*$", re.I)
GONE_TEXT = re.compile(r"doesn.t exist|was deleted|isn.t available|no longer available", re.I)


class XBrowserProvider(Provider):
    key = "x"
    name = "X (Twitter)"
    ease = "easy"
    ease_note = "Free: log in once in a browser window."
    browser = True
    fields = [Field("username", "Your X username", help="Without the @, e.g. jack")]
    setup_help = (
        "Free, no developer account needed. After saving, click 'Open login window' and log in to X as usual. "
        "To clean up more than your latest ~3,200 posts, also import your X archive (Settings → Your account → "
        "Download an archive of your data)."
    )
    login_url = f"{BASE}/i/flow/login"
    delete_delay = 4.0
    max_per_run = 300

    def __init__(self, credentials: dict, profile: Path, archive: list[dict] | None = None, **kwargs):
        super().__init__(credentials, **kwargs)
        self.profile = profile
        self.archive = archive or []
        self.username = self.cred("username").lstrip("@")

    @staticmethod
    def is_logged_in(context) -> dict | None:
        from ..browser import cookie

        if not cookie(context, BASE, "auth_token"):
            return None
        twid = cookie(context, BASE, "twid") or ""  # "u%3D12345" -> "12345"
        return {"user_id": twid.split("%3D")[-1].split("=")[-1].strip('"')}

    # --- session ---------------------------------------------------------------------------
    def login(self) -> None:
        from ..browser import open_browser

        self._session = open_browser(self.profile, headless=True, start_url=BASE + "/home")
        self.context, self.page = self._session.__enter__()
        info = self.is_logged_in(self.context)
        if not info:
            self.close()
            raise ProviderError("You're logged out of X. On the dashboard, click 'Log in again'.")
        self.user_id = info["user_id"] or self.cred("user_id")

    def close(self) -> None:
        session, self._session = getattr(self, "_session", None), None
        if session:
            session.__exit__(None, None, None)

    # --- listing ---------------------------------------------------------------------------
    def iter_posts(self) -> Iterator[Post]:
        from ..browser import ResponseCollector, scroll_until_done

        seen: dict[str, Post] = {}
        pinned: set[str] = set()
        collector = ResponseCollector(self.page, lambda url: "/i/api/graphql/" in url)

        def collect() -> int:
            before = len(seen)
            for payload in collector.drain():
                posts, pins = parse_timeline(payload, self.user_id, self.username)
                pinned.update(pins)
                for p in posts:
                    seen.setdefault(p.id, p)
            return len(seen) - before

        # X's profile splits posts, replies, reposts and media into tabs: read every tab the profile shows.
        def open_tab(path: str) -> None:
            self.page.goto(BASE + path, wait_until="domcontentloaded")
            self.page.wait_for_timeout(3000)

        open_tab(f"/{self.username}")
        tabs = self._profile_tabs()  # before scrolling, while the tab bar is on screen
        scroll_until_done(self.page, collect)
        for tab in tabs:
            open_tab(tab)
            scroll_until_done(self.page, collect)
        for post in seen.values():
            post.pinned = post.id in pinned
            yield post
        # The live timeline stops after a few thousand posts; the archive covers the rest.
        for item in self.archive:
            if item["id"] not in seen:
                yield archive_item_to_post(item, self.username, pinned)

    def _profile_tabs(self) -> list[str]:
        """Paths of the profile's other tabs (Replies, Reposts, Media...), read from the page, minus Likes."""
        from playwright.sync_api import Error as PlaywrightError

        prefix = f"/{self.username}/".lower()
        try:
            hrefs = self.page.locator('nav a[role="tab"]').evaluate_all("els => els.map(e => e.getAttribute('href'))")
        except PlaywrightError:
            hrefs = []
        tabs = [h for h in dict.fromkeys(hrefs) if h and h.lower().startswith(prefix)
                and not h.lower().endswith("/likes")]
        return tabs or [f"/{self.username}/with_replies", f"/{self.username}/media"]

    # --- deleting --------------------------------------------------------------------------
    def delete(self, post: Post) -> None:
        from playwright.sync_api import Error as PlaywrightError

        page = self.page
        try:
            page.goto(f"{BASE}/{self.username}/status/{post.id}", wait_until="domcontentloaded")
            if post.kind == "repost":
                self._undo_repost()
                return
            # Exact match on the timestamp link: a short old ID can be a prefix of a newer one in the same thread.
            article = page.locator(f'article[data-testid="tweet"]:has(a[href$="/status/{post.id}"] time)').first
            try:
                article.wait_for(timeout=15000)
            except PlaywrightError:
                if self._gone():
                    return  # already deleted
                raise ProviderError("Couldn't find the post on the page")
            article.locator('[data-testid="caret"]').first.click()
            item = page.locator('[role="menuitem"]').filter(has_text=DELETE_LABEL).first
            if not item.count():
                page.keyboard.press("Escape")
                raise ProviderError("No 'Delete' option in the post menu (is this post yours?)")
            item.click()
            confirm = page.locator('[data-testid="confirmationSheetConfirm"]')
            confirm.click()
            confirm.wait_for(state="hidden", timeout=15000)
        except PlaywrightError as exc:
            self._save_debug(post)
            raise ProviderError(f"Browser step failed: {str(exc).splitlines()[0]}") from None
        except ProviderError:
            self._save_debug(post)
            raise

    def _undo_repost(self) -> None:
        from playwright.sync_api import Error as PlaywrightError

        button = self.page.locator('[data-testid="unretweet"]').first
        try:
            button.wait_for(timeout=15000)
        except PlaywrightError:
            return  # not reposted any more, or the original was deleted
        button.click()
        self.page.locator('[data-testid="unretweetConfirm"]').click()

    def _gone(self) -> bool:
        try:
            return bool(GONE_TEXT.search(self.page.locator("body").inner_text(timeout=5000)))
        except Exception:  # noqa: BLE001
            return False

    def _save_debug(self, post: Post) -> None:
        try:
            folder = self.profile.parent.parent / "debug"
            folder.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(folder / f"x-{post.id}.png"))
        except Exception:  # noqa: BLE001 - debugging aid only
            pass


# --- parsing -------------------------------------------------------------------------------

def parse_x_time(value: str) -> datetime:
    try:
        return datetime.strptime(value, X_TIME)
    except ValueError:
        return parse_time(value)


def parse_timeline(payload, user_id: str, username: str) -> tuple[list[Post], set[str]]:
    """Find this user's posts in any X web API response."""
    from ..browser import walk

    posts, pinned = [], set()
    for d in walk(payload):
        legacy = d.get("legacy")
        if not isinstance(legacy, dict):
            continue
        if "pinned_tweet_ids_str" in legacy and str(d.get("rest_id")) == str(user_id):
            pinned.update(legacy.get("pinned_tweet_ids_str") or [])
        if not {"id_str", "created_at", "full_text"} <= legacy.keys():
            continue
        if str(legacy.get("user_id_str")) != str(user_id):
            continue
        posts.append(Post(
            id=legacy["id_str"],
            created_at=parse_x_time(legacy["created_at"]),
            text=legacy.get("full_text", ""),
            url=f"https://x.com/{username}/status/{legacy['id_str']}",
            likes=int(legacy.get("favorite_count") or 0),
            reposts=int(legacy.get("retweet_count") or 0),
            kind=_kind(legacy),
        ))
    return posts, pinned


def _kind(tweet: dict) -> str:
    if "retweeted_status_result" in tweet or tweet.get("full_text", "").startswith("RT @"):
        return "repost"
    if tweet.get("in_reply_to_status_id_str"):
        return "reply"
    return "post"


def parse_archive(source, filename: str = "") -> list[dict]:
    """Read posts from an X archive (.zip) or its data/tweets.js file. ``source`` is bytes or a file object."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    files: list[str] = []
    if filename.lower().endswith(".js"):
        files.append(source.read().decode("utf-8"))
    else:
        try:
            archive = zipfile.ZipFile(source)
        except zipfile.BadZipFile:
            raise ValueError("That isn't a zip file. Choose the archive .zip you downloaded from X.")
        names = [n for n in archive.namelist() if re.search(r"(^|/)data/tweets?(-part\d+)?\.js$", n)]
        if not names:
            raise ValueError("No posts found in that file. Make sure it's the archive from X (it contains data/tweets.js).")
        files.extend(archive.read(n).decode("utf-8") for n in names)

    items = []
    for text in files:
        body = text[text.index("["):] if "[" in text else "[]"  # strip "window.YTD.tweets.part0 = "
        for entry in json.loads(body):
            t = entry.get("tweet", entry)
            items.append({
                "id": t["id_str"],
                "created_at": parse_x_time(t["created_at"]).isoformat(),
                "text": t.get("full_text", ""),
                "likes": int(t.get("favorite_count") or 0),
                "kind": _kind(t),
            })
    return items


def archive_item_to_post(item: dict, username: str, pinned: set[str]) -> Post:
    return Post(
        id=item["id"],
        created_at=parse_time(item["created_at"]),
        text=item.get("text", ""),
        url=f"https://x.com/{username}/status/{item['id']}",
        likes=item.get("likes", 0),
        pinned=item["id"] in pinned,
        kind=item.get("kind", "post"),
        extra={"from_archive": True},
    )
