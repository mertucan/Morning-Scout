"""Turning new items into a short Markdown digest with Gemini, with a no-AI fallback.

Google Search grounding is intentionally *not* used: the model must only
summarise the sources we hand it (and grounding is not on the free tier).
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable

from morning_scout.messages import messages_for, system_prompt
from morning_scout.models import Item, PageChange
from morning_scout.privacy import describe_error

log = logging.getLogger(__name__)

MAX_SNIPPET_CHARS = 400
RETRY_DELAYS = (10.0, 30.0)  # seconds; absorbed by the wait for send_time
# Generous: "thinking" models spend part of the output budget before answering.
MAX_OUTPUT_TOKENS = 16_384
# Busy models can take minutes; give up on one attempt after this and retry/fall back.
REQUEST_TIMEOUT_MS = 180_000
_SOURCE_LINK_RE = re.compile(r"\[([^\]]+)\]\(\s*\[?(S\d+)\]?\s*\)", re.IGNORECASE)


class SummaryError(Exception):
    """The LLM call failed or returned nothing usable."""


def build_prompt(items: list[Item], changes: list[PageChange]) -> tuple[str, dict[str, str]]:
    """Render the new material as a numbered source list for the LLM.

    URLs are replaced by short ids (``S1``, ``S2``...). The model cites ids and
    :func:`resolve_sources` puts the real links back afterwards, so the model
    cannot mangle or invent URLs, and long redirect links don't waste tokens.

    Returns:
        The prompt text and the ``{id: url}`` mapping.
    """
    sources: dict[str, str] = {}
    parts: list[str] = []
    for topic, topic_items in _group_by_topic(items).items():
        parts.append(f"## Konu / Topic: {topic}")
        for item in topic_items:
            source_id = f"S{len(sources) + 1}"
            sources[source_id] = item.url
            parts.append(f"- [{source_id}] {item.title}")
            if item.snippet:
                parts.append(f"  {item.snippet[:MAX_SNIPPET_CHARS]}")
    if changes:
        parts.append("## Değişen sayfalar / Changed pages")
        for change in changes:
            source_id = f"S{len(sources) + 1}"
            sources[source_id] = change.url
            parts.append(f"- [{source_id}] {change.name}\n  Fark / Diff:\n{change.diff}")
    return "\n".join(parts), sources


def resolve_sources(text: str, sources: dict[str, str]) -> str:
    """Replace ``(S3)`` link targets with real URLs; drop links to unknown ids."""

    def replace(match: re.Match[str]) -> str:
        label, source_id = match.group(1), match.group(2).upper()
        url = sources.get(source_id)
        return f"[{label}]({url})" if url else ""

    return _SOURCE_LINK_RE.sub(replace, text)


def summarize_with_gemini(
    items: list[Item],
    changes: list[PageChange],
    *,
    api_key: str,
    models: list[str],
    language: str,
) -> str:
    """Ask Gemini for a grouped digest, trying each model in turn.

    Each model gets a few retries for transient errors; if it still fails (e.g.
    "high demand" on a popular model), the next model is tried.

    Raises:
        SummaryError: when every model failed or returned nothing.
    """
    if not api_key:
        raise SummaryError("GEMINI_API_KEY is not set")

    # Imported lazily: the SDK is heavy and not needed for tests or dry fallbacks.
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS)
    )

    prompt, sources = build_prompt(items, changes)

    def call(model: str) -> str:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt(language),
                temperature=0.2,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        return (response.text or "").strip()

    last_error: Exception | None = None
    for model in dict.fromkeys(models):  # unique, in order
        try:
            text = with_retries(lambda model=model: call(model), delays=RETRY_DELAYS)
        except Exception as exc:  # the SDK raises many unrelated types; treat all as "failed"
            log.warning("Gemini: model %s failed (%s)", model, describe_error(exc))
            last_error = exc
            continue
        if text:
            log.info("Gemini: summary created with %s", model)
            return resolve_sources(text, sources)
        log.warning("Gemini: model %s returned an empty response", model)
    if last_error is not None:
        raise SummaryError(f"Gemini request failed: {type(last_error).__name__}") from last_error
    raise SummaryError("Gemini returned an empty response")


def with_retries[T](
    call: Callable[[], T],
    delays: tuple[float, ...] = RETRY_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``call``, retrying after each delay when it fails with a transient error.

    Free-tier Gemini regularly answers 503 ("model overloaded") or 429 for a
    short while; those are worth waiting for. Anything else fails immediately.
    """
    for attempt, delay in enumerate((*delays, None), start=1):
        try:
            return call()
        except Exception as exc:
            if delay is None or not is_transient(exc):
                raise
            log.info(
                "Gemini: attempt %d failed (%s); retrying in %.0f s",
                attempt,
                describe_error(exc),
                delay,
            )
            sleep(delay)
    raise AssertionError("unreachable")


def is_transient(exc: BaseException) -> bool:
    """True for rate limiting (429) and server-side (5xx) API errors."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return isinstance(code, int) and (code == 429 or 500 <= code < 600)


def fallback_summary(items: list[Item], changes: list[PageChange], language: str) -> str:
    """Plain "title + link" Markdown list used when the LLM is unavailable."""
    msg = messages_for(language)
    lines = [msg["fallback_note"], ""]
    for topic, topic_items in _group_by_topic(items).items():
        lines.append(f"### {topic}")
        lines.extend(f"- [{_md_escape(item.title)}]({item.url})" for item in topic_items)
        lines.append("")
    if changes:
        lines.append(f"### {msg['section_pages']}")
        lines.extend(f"- [{_md_escape(change.name)}]({change.url})" for change in changes)
    return "\n".join(lines).strip()


def _group_by_topic(items: list[Item]) -> dict[str, list[Item]]:
    grouped: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        grouped[item.topic].append(item)
    return dict(grouped)


def _md_escape(text: str) -> str:
    return text.replace("[", "(").replace("]", ")")
