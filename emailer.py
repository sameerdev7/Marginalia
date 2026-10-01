"""Outbound email. One function, stdlib only.

With SMTP_HOST unset (local dev, tests) nothing is sent — the message is
written to the log instead, so the reset link can be copied from the server
console. Sending runs from a FastAPI BackgroundTask, so the request that
triggered it never waits on (or fails because of) the mail server.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from config import settings

logger = logging.getLogger("athenaeum.email")


def _send_sync(msg: EmailMessage) -> None:
    if settings.smtp_port == 465:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    with server:
        if settings.smtp_port != 465 and settings.smtp_starttls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
        server.send_message(msg)


async def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if not settings.smtp_host:
        logger.warning("SMTP not configured — would have sent to %s:\n%s\n%s", to, subject, text)
        return

    try:
        # smtplib blocks; keep it off the event loop.
        await asyncio.to_thread(_send_sync, msg)
    except Exception:
        # A background task has no caller to report to; log and move on.
        logger.exception("Failed to send email to %s", to)


def password_reset_email(link: str, minutes: int) -> tuple[str, str, str]:
    subject = "Reset your Athenaeum password"
    text = (
        "Someone asked to reset the password for your Athenaeum account.\n\n"
        f"Choose a new one here (the link works once, for {minutes} minutes):\n{link}\n\n"
        "If this wasn't you, ignore this email — your password is unchanged."
    )
    html = f"""\
<div style="font-family:Georgia,serif;max-width:480px;margin:auto;padding:24px;color:#2a2116">
  <h2 style="letter-spacing:.12em;color:#a97a1e;margin:0 0 16px">ATHENAEUM</h2>
  <p>Someone asked to reset the password for your account.</p>
  <p><a href="{link}" style="display:inline-block;background:#dcb056;color:#1d1409;
     padding:12px 22px;border-radius:999px;text-decoration:none;font-weight:bold">Choose a new password</a></p>
  <p style="font-size:13px;color:#6c5f47">The link works once and expires in {minutes} minutes.
  If this wasn't you, ignore this email — your password is unchanged.</p>
</div>"""
    return subject, text, html
