from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator

import requests

from ..models import Post

USER_AGENT = "auto-delete-post/0.1 (self-hosted)"


class ProviderError(Exception):
    pass


@dataclass
class Field:
    name: str
    label: str
    secret: bool = False
    required: bool = True
    default: str = ""
    help: str = ""


class Provider:
    """Base class for a social network connector.

    Subclasses list their posts newest-first via ``iter_posts`` and remove one with
    ``delete``. If a provider refreshes its tokens it puts the new values in
    ``updated_credentials`` so the caller can save them.
    """

    key: str = ""
    name: str = ""
    fields: list[Field] = []
    setup_help: str = ""
    # Seconds to wait between deletes so we stay under rate limits.
    delete_delay: float = 1.0

    def __init__(self, credentials: dict, session: requests.Session | None = None):
        self.credentials = {k: (v or "").strip() if isinstance(v, str) else v for k, v in credentials.items()}
        missing = [f.label for f in self.fields if f.required and not self.credentials.get(f.name)]
        if missing:
            raise ProviderError(f"Missing: {', '.join(missing)}")
        self.http = session or requests.Session()
        self.http.headers.setdefault("User-Agent", USER_AGENT)
        self.updated_credentials: dict = {}

    def cred(self, name: str) -> str:
        value = self.credentials.get(name)
        if value:
            return value
        for f in self.fields:
            if f.name == name:
                return f.default
        return ""

    # --- to implement -----------------------------------------------------
    def login(self) -> None:
        """Authenticate / verify credentials. Called once before listing."""

    def iter_posts(self) -> Iterator[Post]:
        raise NotImplementedError

    def delete(self, post: Post) -> None:
        raise NotImplementedError

    # --- helpers ----------------------------------------------------------
    def request(self, method: str, url: str, retries: int = 3, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        for attempt in range(retries + 1):
            resp = self.http.request(method, url, **kwargs)
            if resp.status_code == 429 and attempt < retries:
                wait = _retry_after(resp)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise ProviderError(f"{self.name}: {method} {url} -> {resp.status_code} {resp.text[:300]}")
            return resp
        raise ProviderError(f"{self.name}: rate limited")  # pragma: no cover


def _retry_after(resp: requests.Response) -> float:
    header = resp.headers.get("Retry-After")
    if header and header.isdigit():
        return min(float(header), 900)
    reset = resp.headers.get("x-rate-limit-reset") or resp.headers.get("X-RateLimit-Reset")
    if reset and reset.replace(".", "").isdigit():
        value = float(reset)
        # Some APIs send an epoch timestamp, others seconds-until-reset.
        wait = value - time.time() if value > 1e9 else value
        return max(1.0, min(wait, 900))
    return 30.0
