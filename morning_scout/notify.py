"""Delivery channels: ntfy push notifications and Gmail SMTP."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import requests

NTFY_SERVER = "https://ntfy.sh"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
_TIMEOUT = 30


def send_ntfy(
    topic: str, title: str, message: str, *, priority: int = 3, tags: list[str] | None = None
) -> None:
    """Publish a Markdown notification to an ntfy topic.

    The JSON publishing endpoint is used so that the title and body can contain
    any Unicode (HTTP headers cannot).
    """
    response = requests.post(
        NTFY_SERVER,
        json={
            "topic": topic,
            "title": title,
            "message": message,
            "markdown": True,
            "priority": priority,
            "tags": tags or ["sunrise"],
        },
        timeout=_TIMEOUT,
    )
    response.raise_for_status()


def send_email(
    *,
    sender: str,
    app_password: str,
    recipient: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """Send a multipart (plain text + HTML) e-mail through Gmail using an app password."""
    message = EmailMessage()
    message["From"] = f"Morning Scout <{sender}>"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=_TIMEOUT) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(message)
