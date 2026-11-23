"""Formatting the digest for each channel: a short ntfy push and a full HTML e-mail."""

from __future__ import annotations

import html
import re

import markdown

from morning_scout.messages import messages_for

# ntfy turns messages above 4,096 bytes into attachments; stay well below.
NTFY_MAX_BYTES = 3000
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_ANY_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CITATION_RE = re.compile(r"[ \t]*\[\[\d+\]\]\([^)]*\)")
_CITATION_HTML_RE = re.compile(r"(<a [^>]*>\[\d+\]</a>)")
_SOURCES_STYLE = "font-size:13px;color:#57534e;"

_EMAIL_TEMPLATE = """\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f5f5f4;">
<div style="max-width:640px;margin:0 auto;padding:24px;font-family:-apple-system,Segoe UI,\
Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.55;color:#1c1917;background:#ffffff;">
<h2 style="margin-top:0;">{title}</h2>
{body}
<hr style="border:none;border-top:1px solid #e7e5e4;margin:24px 0 12px;">
<p style="font-size:12px;color:#78716c;">{footer}</p>
</div></body></html>
"""


def ntfy_message(summary_md: str, language: str, max_bytes: int = NTFY_MAX_BYTES) -> str:
    """A compact push notification body.

    Citations, source lists and links are removed (news redirect URLs are
    hundreds of characters long and would crowd out the content); the e-mail
    carries them. Long digests are cut at a line boundary with a pointer to the
    e-mail.
    """
    text = strip_links(summary_md, messages_for(language)["sources_heading"]).strip()
    if len(text.encode("utf-8")) <= max_bytes:
        return text

    suffix = "\n\n" + messages_for(language)["read_more_in_mail"]
    budget = max_bytes - len(suffix.encode("utf-8"))
    kept: list[str] = []
    used = 0
    for line in text.splitlines():
        size = len(line.encode("utf-8")) + 1
        if used + size > budget:
            break
        kept.append(line)
        used += size
    if not kept:  # one enormous line: hard cut on a character boundary
        kept = [text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")]
    return "\n".join(kept).rstrip() + suffix


def strip_links(text: str, sources_heading: str) -> str:
    """Plain-text version for push: no citations, no source lists, links become their text."""
    kept: list[str] = []
    in_sources = False
    for line in text.splitlines():
        if line.strip() == f"**{sources_heading}**":
            in_sources = True
            continue
        if line.startswith("#"):
            in_sources = False
        if not in_sources:
            kept.append(line)
    text = _CITATION_RE.sub("", "\n".join(kept))
    text = _ANY_LINK_RE.sub(r"\1", text)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def email_html(summary_md: str, title: str, language: str) -> str:
    """Full digest as a self-contained HTML e-mail with clickable links.

    Numbered citations are shown as superscripts linking to the source, and
    each topic's source list is set in smaller, muted type.
    """
    # Neutralise raw HTML from the LLM output; Markdown links are kept intact.
    safe_md = summary_md.replace("<", "&lt;")
    body = markdown.markdown(safe_md, extensions=["sane_lists"])
    body = body.replace("<a href=", '<a style="color:#2563eb;" target="_blank" href=')
    body = _CITATION_HTML_RE.sub(r'<sup style="font-size:11px;">\1</sup>', body)
    heading = html.escape(messages_for(language)["sources_heading"])
    body = body.replace(
        f"<p><strong>{heading}</strong></p>\n<ol>",
        f'<p style="{_SOURCES_STYLE}margin-bottom:4px;"><strong>{heading}</strong></p>\n'
        f'<ol style="{_SOURCES_STYLE}margin-top:0;">',
    )
    return _EMAIL_TEMPLATE.format(
        title=html.escape(title),
        body=body,
        footer=html.escape(messages_for(language)["footer"]),
    )


def email_text(summary_md: str) -> str:
    """Plain-text alternative: Markdown links become ``text (url)``."""
    return _LINK_RE.sub(r"\1 (\2)", summary_md).strip() + "\n"
