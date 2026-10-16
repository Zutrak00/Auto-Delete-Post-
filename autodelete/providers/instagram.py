"""Instagram through the user's own logged-in browser: free, no developer account needed."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator

from ..models import Post, parse_time
from .base import Field, Provider, ProviderError

BASE = os.environ.get("AUTODELETE_INSTAGRAM_BASE", "https://www.instagram.com")

MORE_OPTIONS = re.compile(
    r"^\s*(More options|Más opciones|Plus d.options|Weitere Optionen|Mais opções|Altre opzioni|Meer opties|"
    r"Diğer seçenekler|Więcej opcji|Другие параметры)\s*$", re.I)
DELETE_LABEL = re.compile(r"^\s*(Delete|Eliminar|Supprimer|Löschen|Excluir|Elimina|Verwijderen|Sil|Usuń|Удалить)\s*$", re.I)
GONE_TEXT = re.compile(r"isn.t available|page may have been removed|no está disponible", re.I)


class InstagramProvider(Provider):
    key = "instagram"
    name = "Instagram"
    ease = "easy"
    ease_note = "Free: log in once in a browser window. Deletes slowly to stay safe."
    browser = True
    fields = [Field("username", "Your Instagram username", help="Without the @")]
    setup_help = (
        "Free, no developer account needed. After saving, click 'Open login window' and log in to Instagram as "
        "usual. To avoid tripping Instagram's spam checks, the app deletes at most 30 posts per run with a pause "
        "of about 25 seconds between each."
    )
    login_url = f"{BASE}/accounts/login/"
    delete_delay = 25.0
    max_per_run = 30

    def __init__(self, credentials: dict, profile: Path, archive: list[dict] | None = None, **kwargs):
        super().__init__(credentials, **kwargs)
        self.profile = profile
        self.username = self.cred("username").lstrip("@")

    @staticmethod
    def is_logged_in(context) -> dict | None:
        from ..browser import cookie

        if not cookie(context, BASE, "sessionid"):
            return None
        return {"user_id": cookie(context, BASE, "ds_user_id") or ""}

    # --- session ---------------------------------------------------------------------------
    def login(self) -> None:
        from ..browser import open_browser

        self._session = open_browser(self.profile, headless=True, start_url=BASE + "/")
        self.context, self.page = self._session.__enter__()
        info = self.is_logged_in(self.context)
        if not info:
            self.close()
            raise ProviderError("You're logged out of Instagram. On the dashboard, click 'Log in again'.")
        self.user_id = info["user_id"] or self.cred("user_id")

    def close(self) -> None:
        session, self._session = getattr(self, "_session", None), None
        if session:
            session.__exit__(None, None, None)

    # --- listing ---------------------------------------------------------------------------
    def iter_posts(self) -> Iterator[Post]:
        from ..browser import ResponseCollector, scroll_until_done

        seen: dict[str, Post] = {}
        collector = ResponseCollector(self.page, lambda url: "/api/" in url or "/graphql" in url)

        def collect() -> int:
            before = len(seen)
            for payload in collector.drain():
                for p in parse_posts(payload, self.username, self.user_id):
                    seen.setdefault(p.id, p)
            return len(seen) - before

        self.page.goto(f"{BASE}/{self.username}/", wait_until="domcontentloaded")
        self.page.wait_for_timeout(3000)
        collector.embedded_json()  # the first posts are often embedded in the page itself
        scroll_until_done(self.page, collect, pause=2.0)
        yield from seen.values()

    # --- deleting --------------------------------------------------------------------------
    def delete(self, post: Post) -> None:
        from playwright.sync_api import Error as PlaywrightError

        page = self.page
        try:
            page.goto(post.url, wait_until="domcontentloaded")
            more = page.locator("main").get_by_role("button", name=MORE_OPTIONS).first
            try:
                more.wait_for(timeout=15000)
            except PlaywrightError:
                if GONE_TEXT.search(page.locator("body").inner_text(timeout=5000)):
                    return  # already deleted
                raise ProviderError("Couldn't find the post's menu")
            more.click()
            page.get_by_role("dialog").last.get_by_role("button", name=DELETE_LABEL).click()
            # A second dialog asks "Delete post?"
            confirm = page.get_by_role("dialog").last.get_by_role("button", name=DELETE_LABEL)
            confirm.click()
            confirm.wait_for(state="hidden", timeout=15000)
        except PlaywrightError as exc:
            self._save_debug(post)
            raise ProviderError(f"Browser step failed: {str(exc).splitlines()[0]}") from None
        except ProviderError:
            self._save_debug(post)
            raise

    def _save_debug(self, post: Post) -> None:
        try:
            folder = self.profile.parent.parent / "debug"
            folder.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(folder / f"instagram-{post.id}.png"))
        except Exception:  # noqa: BLE001 - debugging aid only
            pass


def parse_posts(payload, username: str, user_id: str = "") -> list[Post]:
    """Find this user's posts in any Instagram web API response or embedded page data."""
    from ..browser import walk

    posts = []
    for d in walk(payload):
        if not isinstance(d.get("code"), str) or not isinstance(d.get("taken_at"), (int, float)):
            continue
        owner = d.get("user") or d.get("owner") or {}
        owner_id = str(owner.get("pk") or owner.get("id") or "")
        if (owner.get("username") or "").lower() != username.lower() and not (user_id and owner_id == str(user_id)):
            continue
        caption = d.get("caption") or {}
        posts.append(Post(
            id=d["code"],
            created_at=parse_time(d["taken_at"]),
            text=caption.get("text", "") if isinstance(caption, dict) else "",
            url=f"{BASE}/p/{d['code']}/",
            likes=int(d.get("like_count") or 0),
            pinned=bool(d.get("timeline_pinned_user_ids")),
            kind="post",
        ))
    return posts
