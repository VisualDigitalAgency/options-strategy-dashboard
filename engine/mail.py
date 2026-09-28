"""Outgoing email (issue #45): sign-up verification codes, for now.

MAIL_BACKEND picks how mail leaves:
  - `resend`: the Resend HTTP API. Needs RESEND_API_KEY.
  - `smtp`:   any SMTP server. SMTP_HOST, SMTP_PORT (587, STARTTLS; 465 is implicit TLS),
              SMTP_USER, SMTP_PASS.
  - `log`:    the default. Nothing is sent; the message is written to the log. For dev and tests.
MAIL_FROM is the sender, e.g. `Theta Desk <no-reply@example.com>`. Secrets use the same
NAME_FILE-or-env-var lookup as the DB passwords (settings.secret).

Transient failures (network, timeouts, HTTP 429/5xx, SMTP 4xx) are retried a few times.
send() then raises MailError, and the caller records it in the audit log for the admin.
"""

import json
import logging
import os
import smtplib
import ssl
import time
import urllib.error
import urllib.request
from email.message import EmailMessage

from . import settings

log = logging.getLogger(__name__)

TRIES = 3
TIMEOUT = 10
RESEND_URL = "https://api.resend.com/emails"


class MailError(Exception):
    pass


class _Transient(Exception):
    pass


def backend() -> str:
    return (os.environ.get("MAIL_BACKEND") or "log").strip().lower()


def _sender() -> str:
    return os.environ.get("MAIL_FROM") or "Theta Desk <no-reply@theta.local>"


def _resend(to: str, subject: str, text: str) -> None:
    key = settings.secret("RESEND_API_KEY")
    if not key:
        raise MailError("RESEND_API_KEY is not set")
    body = json.dumps({"from": _sender(), "to": [to], "subject": subject, "text": text}).encode()
    req = urllib.request.Request(RESEND_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "theta-desk"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT):
            return
    except urllib.error.HTTPError as e:
        detail = e.read(300).decode(errors="replace")
        if e.code == 429 or e.code >= 500:
            raise _Transient(f"Resend HTTP {e.code}: {detail}") from e
        raise MailError(f"Resend HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _Transient(f"Resend unreachable: {e}") from e


def _smtp(to: str, subject: str, text: str) -> None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise MailError("SMTP_HOST is not set")
    port = int(os.environ.get("SMTP_PORT") or 587)
    user, password = os.environ.get("SMTP_USER"), settings.secret("SMTP_PASS")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = _sender(), to, subject
    msg.set_content(text)
    ctx = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT)
            server.starttls(context=ctx)
        with server:
            if user:
                server.login(user, password or "")
            server.send_message(msg)
    except smtplib.SMTPResponseException as e:
        if 400 <= e.smtp_code < 500:
            raise _Transient(f"SMTP {e.smtp_code}") from e
        raise MailError(f"SMTP {e.smtp_code}: {e.smtp_error[:200]!r}") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise MailError("SMTP refused the recipient") from e
    except (smtplib.SMTPException, OSError) as e:
        raise _Transient(f"SMTP: {e}") from e


def send(to: str, subject: str, text: str) -> None:
    """Sends one plain-text email, or raises MailError."""
    kind = backend()
    if kind == "log":
        log.info("mail (log backend) to=%s subject=%r\n%s", to, subject, text)
        return
    fn = {"resend": _resend, "smtp": _smtp}.get(kind)
    if fn is None:
        raise MailError(f"Unknown MAIL_BACKEND {kind!r}")
    for attempt in range(1, TRIES + 1):
        try:
            return fn(to, subject, text)
        except _Transient as e:
            log.warning("mail failed (try %d/%d): %s", attempt, TRIES, e)
            if attempt == TRIES:
                raise MailError(str(e)) from e
            time.sleep(attempt)
