"""URL normalisation and hashing used for duplicate detection."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only track the click and never change the content.
_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
    "oc",
}
_TRACKING_PREFIXES = ("utm_",)
_DEFAULT_PORTS = {"http": 80, "https": 443}
_KEY_LENGTH = 16  # 64 bits of SHA-256: plenty for a few thousand entries


def normalize_url(url: str) -> str:
    """Return a canonical form of ``url`` so that trivially different links match.

    - lower-cases scheme and host, drops ``www.`` and default ports
    - upgrades ``http`` to ``https``
    - removes the fragment and tracking parameters (``utm_*``, ``fbclid``...)
    - sorts the remaining query parameters
    - strips a trailing slash from the path
    """
    parts = urlsplit(url.strip())
    original_scheme = parts.scheme.lower() or "https"
    scheme = "https" if original_scheme == "http" else original_scheme

    host = (parts.hostname or "").lower()
    host = host.removeprefix("www.")
    port = parts.port
    if port and port != _DEFAULT_PORTS.get(original_scheme):
        host = f"{host}:{port}"

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS and not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or ""
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def url_key(url: str) -> str:
    """Short stable hash of the normalised URL."""
    return short_hash("u:" + normalize_url(url))


def title_key(title: str) -> str:
    """Short stable hash of a headline, ignoring case, punctuation and publisher suffix.

    Google News titles look like ``"Headline - Publisher"``; the same story can
    arrive with different redirect URLs, so the headline is a second dedup key.
    """
    text = title.rsplit(" - ", 1)[0] if " - " in title else title
    text = re.sub(r"[\W_]+", " ", text.casefold()).strip()
    return short_hash("t:" + text)


def short_hash(value: str) -> str:
    """Truncated SHA-256 hex digest used for compact, non-reversible keys."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_KEY_LENGTH]
