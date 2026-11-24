"""Sending email for password resets.

If SMTP is configured (EXLEX_SMTP_HOST, EXLEX_SMTP_PORT, EXLEX_SMTP_USER, EXLEX_SMTP_PASSWORD, EXLEX_SMTP_FROM) the message is sent for real.
If not, it is only queued for an administrator to read, and the state says nothing was sent: the system never claims to have emailed.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def configured() -> bool:
    return bool(os.environ.get("EXLEX_SMTP_HOST") and os.environ.get("EXLEX_SMTP_FROM"))


def send(to: str, subject: str, body: str) -> str:
    """Returns the state to record: "sent" or "failed: ..." (queued-only is decided by the caller when not configured())."""
    host, port = os.environ["EXLEX_SMTP_HOST"], int(os.environ.get("EXLEX_SMTP_PORT", "587"))
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.environ["EXLEX_SMTP_FROM"], to, subject
    msg.set_content(body)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls(context=ssl.create_default_context())
        with server:
            if os.environ.get("EXLEX_SMTP_USER"):
                server.login(os.environ["EXLEX_SMTP_USER"], os.environ.get("EXLEX_SMTP_PASSWORD", ""))
            server.send_message(msg)
        return "sent"
    except Exception as e:  # noqa: BLE001 - the reason is shown to the administrator
        return f"failed: {type(e).__name__}"
