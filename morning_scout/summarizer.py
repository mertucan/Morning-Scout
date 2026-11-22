"""Turning new items into a short Markdown digest with Gemini, with a no-AI fallback.

Google Search grounding is intentionally *not* used: the model must only
summarise the sources we hand it (and grounding is not on the free tier).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from morning_scout.messages import messages_for, system_prompt
from morning_scout.models import Item, PageChange

log = logging.getLogger(__name__)

MAX_SNIPPET_CHARS = 400


class SummaryError(Exception):
    """The LLM call failed or returned nothing usable."""


def build_prompt(items: list[Item], changes: list[PageChange]) -> str:
    """Render the new material as a plain-text source list for the LLM."""
    parts: list[str] = []
    for topic, topic_items in _group_by_topic(items).items():
        parts.append(f"## Konu / Topic: {topic}")
        for item in topic_items:
            parts.append(f"- Başlık: {item.title}\n  URL: {item.url}")
            if item.snippet:
                parts.append(f"  Özet: {item.snippet[:MAX_SNIPPET_CHARS]}")
    if changes:
        parts.append("## Değişen sayfalar / Changed pages")
        for change in changes:
            parts.append(f"- Sayfa: {change.name}\n  URL: {change.url}\n  Fark:\n{change.diff}")
    return "\n".join(parts)


def summarize_with_gemini(
    items: list[Item],
    changes: list[PageChange],
    *,
    api_key: str,
    model: str,
    language: str,
) -> str:
    """Ask Gemini for a grouped digest. Raises :class:`SummaryError` on any failure."""
    if not api_key:
        raise SummaryError("GEMINI_API_KEY is not set")

    # Imported lazily: the SDK is heavy and not needed for tests or dry fallbacks.
    from google import genai
    from google.genai import types

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=build_prompt(items, changes),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt(language),
                temperature=0.2,
                max_output_tokens=4096,
            ),
        )
        text = (response.text or "").strip()
    except Exception as exc:  # the SDK raises many unrelated types; treat all as "failed"
        raise SummaryError(f"Gemini request failed: {type(exc).__name__}") from exc
    if not text:
        raise SummaryError("Gemini returned an empty response")
    return text


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
