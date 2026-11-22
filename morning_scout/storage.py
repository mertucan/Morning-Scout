"""Where ``config.yaml`` and ``state.json`` live: a secret GitHub Gist or a local folder."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import requests

CONFIG_FILE = "config.yaml"
STATE_FILE = "state.json"
GITHUB_API = "https://api.github.com"
TOKEN_EXPIRATION_HEADER = "github-authentication-token-expiration"
_TIMEOUT = 30


def parse_token_expiration(value: str | None) -> datetime | None:
    """Parse GitHub's ``github-authentication-token-expiration`` header.

    The header is only sent for tokens that expire, e.g. ``"2027-02-20 21:14:46 UTC"``.
    """
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


class StorageError(Exception):
    """Reading or writing the data store failed. Messages never contain ids or content."""


class Storage(Protocol):
    """Minimal key/value file store."""

    def read(self, name: str) -> str | None:
        """Return the file's text, or ``None`` if it does not exist."""
        ...

    def write(self, name: str, content: str) -> None:
        """Create or replace the file."""
        ...


class LocalStorage:
    """Files in a local directory, for development (``--local`` / ``DATA_DIR``)."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def read(self, name: str) -> str | None:
        path = self.directory / name
        return path.read_text(encoding="utf-8") if path.exists() else None

    def write(self, name: str, content: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / name).write_text(content, encoding="utf-8")


class GistStorage:
    """Files inside a (secret) GitHub Gist, accessed through the REST API."""

    def __init__(self, gist_id: str, token: str, session: requests.Session | None = None) -> None:
        if not gist_id or not token:
            raise StorageError("GIST_ID and GIST_TOKEN must both be set")
        self._url = f"{GITHUB_API}/gists/{gist_id}"
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "morning-scout",
            }
        )
        self._files: dict[str, Any] | None = None
        self.token_expires_at: datetime | None = None

    def read(self, name: str) -> str | None:
        files = self._load()
        entry = files.get(name)
        if entry is None:
            return None
        if entry.get("truncated"):
            # The API inlines at most 1 MB per file; fetch the rest from raw_url.
            return self._request("GET", entry["raw_url"]).text
        return entry.get("content", "")

    def write(self, name: str, content: str) -> None:
        self._request("PATCH", self._url, json={"files": {name: {"content": content}}})
        if self._files is not None:
            self._files[name] = {"content": content, "truncated": False}

    def _load(self) -> dict[str, Any]:
        if self._files is None:
            response = self._request("GET", self._url)
            self.token_expires_at = parse_token_expiration(
                response.headers.get(TOKEN_EXPIRATION_HEADER)
            )
            self._files = response.json().get("files", {})
        return self._files

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            response = self._session.request(method, url, timeout=_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise StorageError(f"Gist {method} failed: {type(exc).__name__}") from None
        if response.status_code >= 400:
            hint = {
                401: "token is invalid or expired",
                403: "token lacks gist permission or rate limit hit",
                404: "gist not found or token cannot see it",
            }.get(response.status_code, "unexpected response")
            raise StorageError(f"Gist {method} failed: HTTP {response.status_code} ({hint})")
        return response
