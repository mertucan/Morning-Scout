"""Formatting the digest for each channel: a short ntfy push and a full HTML e-mail."""

from __future__ import annotations

import html
import re

import markdown

from morning_scout.messages import messages_for

# ntfy turns messages above 4,096 bytes into attachments; stay well below.
NTFY_MAX_BYTES = 3000
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

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

    Long digests are cut at a line boundary with a pointer to the e-mail, which
    always carries the complete text.
    """
    text = summary_md.strip()
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


def email_html(summary_md: str, title: str, language: str) -> str:
    """Full digest as a self-contained HTML e-mail with clickable links."""
    # Neutralise raw HTML from the LLM output; Markdown links are kept intact.
    safe_md = summary_md.replace("<", "&lt;")
    body = markdown.markdown(safe_md, extensions=["sane_lists"])
    body = body.replace("<a href=", '<a style="color:#2563eb;" target="_blank" href=')
    return _EMAIL_TEMPLATE.format(
        title=html.escape(title),
        body=body,
        footer=html.escape(messages_for(language)["footer"]),
    )


def email_text(summary_md: str) -> str:
    """Plain-text alternative: Markdown links become ``text (url)``."""
    return _LINK_RE.sub(r"\1 (\2)", summary_md).strip() + "\n"
