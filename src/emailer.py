"""
Email helper — sends a PDF report to a pharmacy via SMTP.

Credentials are read from environment variables (used by the scheduled GitHub
Action) OR Streamlit secrets (used by the in-app button). Set these:

    SMTP_HOST      e.g. smtp.gmail.com
    SMTP_PORT      e.g. 587
    SMTP_USER      the sending account / username
    SMTP_PASSWORD  app password or API key
    SMTP_FROM      the From address shown to recipients (optional; defaults to SMTP_USER)

For Gmail, create an App Password (Google Account -> Security -> App passwords)
and use that as SMTP_PASSWORD; SMTP_HOST=smtp.gmail.com, SMTP_PORT=587.
For SendGrid, SMTP_HOST=smtp.sendgrid.net, SMTP_USER="apikey", SMTP_PASSWORD=<your key>.
"""
import os
import smtplib
from email.message import EmailMessage


def _cfg(key, default=None):
    """Read config from env first, then Streamlit secrets if available."""
    if key in os.environ:
        return os.environ[key]
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


def is_configured():
    return all(_cfg(k) for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD"))


def send_report(to_email, subject, body_text, pdf_bytes, filename):
    """Send one email with a PDF attachment. Raises on failure."""
    if not to_email:
        raise ValueError("No destination email address.")
    if not is_configured():
        raise RuntimeError("Email is not configured. Set SMTP_* secrets/env vars.")

    host = _cfg("SMTP_HOST")
    port = int(_cfg("SMTP_PORT", "587"))
    user = _cfg("SMTP_USER")
    pwd = _cfg("SMTP_PASSWORD")
    sender = _cfg("SMTP_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(body_text)
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    return True
