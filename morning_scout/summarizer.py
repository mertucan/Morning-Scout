"""Turning new items into a cited, bullet-point Markdown digest with Gemini.

Google Search grounding is intentionally *not* used: the model must only
summarise the sources we hand it (and grounding is not on the free tier).
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from morning_scout.messages import messages_for, system_prompt
from morning_scout.models import Item, PageChange
from morning_scout.privacy import describe_error

log = logging.getLogger(__name__)

MAX_SNIPPET_CHARS = 400
MAX_SOURCE_TITLE_CHARS = 110
RETRY_DELAYS = (10.0, 30.0)  # seconds; absorbed by the wait for send_time
# Generous: "thinking" models spend part of the output budget before answering.
MAX_OUTPUT_TOKENS = 16_384
# Busy models can take minutes; give up on one attempt after this and retry/fall back.
REQUEST_TIMEOUT_MS = 180_000


class SummaryError(Exception):
    """The LLM call failed or returned nothing usable."""


@dataclass(frozen=True)
class Source:
    """A citable source shown to the model as ``S<n>``."""

    title: str
    url: str


def build_prompt(
    items: list[Item],
    changes: list[PageChange],
    focus: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, Source]]:
    """Render the new material as a numbered source list for the LLM.

    URLs are replaced by short ids (``S1``, ``S2``...). The model cites ids and
    :func:`render_digest` puts the real links back afterwards, so the model
    cannot mangle or invent URLs, and long redirect links don't waste tokens.
    ``focus`` maps a topic to a filter instruction shown under its heading.

    Returns:
        The prompt text and the ``{id: Source}`` mapping.
    """
    focus = focus or {}
    sources: dict[str, Source] = {}
    parts: list[str] = []
    for topic, topic_items in _group_by_topic(items).items():
        parts.append(f"## Konu / Topic: {topic}")
        if focus.get(topic):
            parts.append(f"Odak (yalnızca bu konu) / Focus (this topic only): {focus[topic]}")
        for item in topic_items:
            source_id = f"S{len(sources) + 1}"
            sources[source_id] = Source(item.title, item.url)
            parts.append(f"- [{source_id}] {item.title}")
            if item.snippet:
                parts.append(f"  {item.snippet[:MAX_SNIPPET_CHARS]}")
    if changes:
        parts.append("## Değişen sayfalar / Changed pages")
        for change in changes:
            source_id = f"S{len(sources) + 1}"
            sources[source_id] = Source(change.name, change.url)
            parts.append(f"- [{source_id}] {change.name}")
            if change.focus:
                parts.append(f"  Odak (yalnızca bu sayfa) / Focus (this page only): {change.focus}")
            parts.append(f"  Fark / Diff:\n{change.diff}")
    return "\n".join(parts), sources


def parse_digest(raw: str) -> list[dict[str, Any]]:
    """Validate the model's JSON answer and return its sections.

    Raises:
        ValueError: if the answer is not the expected shape.
    """
    data = json.loads(raw)
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list):
        raise ValueError("response has no 'sections' list")
    return [s for s in sections if isinstance(s, dict) and s.get("bullets")]


def render_digest(sections: list[dict[str, Any]], sources: dict[str, Source], language: str) -> str:
    """Turn the model's sections into Markdown with numbered citations.

    Every topic gets its own numbering: bullets cite ``[1]``, ``[2]``... (each a
    link to the source) and a numbered "Sources" list closes the topic.
    Citations of ids that were never offered to the model are dropped.
    """
    heading = messages_for(language)["sources_heading"]
    blocks: list[str] = []
    for section in sections:
        numbers: dict[str, int] = {}  # source id -> number within this topic
        bullets: list[str] = []
        for bullet in section.get("bullets", []):
            text = " ".join(str(bullet.get("text", "")).split())
            if not text:
                continue
            cites = []
            for raw_id in bullet.get("sources", []):
                source_id = str(raw_id).strip().strip("[]").upper()
                if source_id not in sources:
                    continue
                number = numbers.setdefault(source_id, len(numbers) + 1)
                cites.append(f"[[{number}]]({sources[source_id].url})")
            bullets.append(f"- {_md_escape(text)} {' '.join(dict.fromkeys(cites))}".rstrip())
        if not bullets:
            continue
        lines = [f"### {_md_escape(str(section.get('topic', '')).strip())}", "", *bullets]
        if numbers:
            lines += ["", f"**{heading}**", ""]
            lines += [
                f"{number}. [{_md_escape(shorten(sources[source_id].title))}]"
                f"({sources[source_id].url})"
                for source_id, number in numbers.items()
            ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


DIGEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "sources": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["text", "sources"],
                        },
                    },
                },
                "required": ["topic", "bullets"],
            },
        }
    },
    "required": ["sections"],
}


def summarize_with_gemini(
    items: list[Item],
    changes: list[PageChange],
    *,
    api_key: str,
    models: list[str],
    language: str,
    focus: Mapping[str, str] | None = None,
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

    prompt, sources = build_prompt(items, changes, focus)

    def call(model: str) -> str:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt(language),
                temperature=0.2,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",
                response_json_schema=DIGEST_SCHEMA,
            ),
        )
        # Invalid JSON raises here and counts as a failure of this model.
        return render_digest(parse_digest(response.text or ""), sources, language)

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
            return text
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
        lines.extend(f"- [{_md_escape(shorten(item.title))}]({item.url})" for item in topic_items)
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


def shorten(text: str, limit: int = MAX_SOURCE_TITLE_CHARS) -> str:
    """Cut long titles (social media posts use the whole caption) at a word boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip(" ,.;:-–—\"'") + "…"


def _md_escape(text: str) -> str:
    return text.replace("[", "(").replace("]", ")")
