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


def send_report(to_email, subject, body_text, pdf_bytes, filename, body_html=None):
    """Send one email with a PDF attachment. Raises on failure.
    body_text is the plain-text fallback; body_html (optional) is the rich version."""
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
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    return True


def report_email_body(pharmacy_id, area, period_label, monthly=False):
    """Return (plain_text, html) for a MedShare report email, branded like a
    proper statement message. period_label e.g. 'June 2026'."""
    intro = ("Please find attached your monthly MedShare pharmacy report."
             if monthly else
             "Please find attached your MedShare pharmacy report.")
    plain = (
        f"Dear {pharmacy_id} ({area}),\n\n"
        f"MEDSHARE PHARMACY REPORT — {period_label}\n\n"
        f"{intro}\n\n"
        "The attached PDF summarises your current stock value, stock at risk of expiry, "
        "your best-selling drugs, redistribution activity, and value lost to expiry. "
        "All figures are generated directly from the MedShare platform at the time of sending.\n\n"
        "You can also view this dashboard at any time, or download the report on demand, "
        "by signing in to the MedShare app.\n\n"
        "Thank you for being part of the MedShare network.\n\n"
        "— The MedShare Team\n"
        "This is an automated message; please do not reply to this email."
    )
    html = f"""\
<!DOCTYPE html><html><body style="margin:0;padding:0;background:#F4F1EA;font-family:Segoe UI,Arial,sans-serif;color:#0C211D;">
  <div style="max-width:600px;margin:0 auto;background:#FFFFFF;border:1px solid #D8D1C4;border-radius:14px;overflow:hidden;">
    <div style="background:#0F6E5C;padding:22px 28px;">
      <div style="font-family:Georgia,serif;font-size:24px;font-weight:600;color:#FFFFFF;">MedShare</div>
      <div style="font-size:12px;color:#CFE7DF;letter-spacing:.04em;margin-top:2px;">Inter-pharmacy redistribution network</div>
    </div>
    <div style="padding:26px 28px;">
      <p style="margin:0 0 14px;">Dear <strong>{pharmacy_id}</strong> ({area}),</p>
      <p style="margin:0 0 6px;font-weight:600;text-decoration:underline;">MedShare Pharmacy Report — {period_label}</p>
      <p style="margin:14px 0;">{intro}</p>
      <p style="margin:14px 0;">The attached PDF summarises your current <strong>stock value</strong>,
        <strong>stock at risk of expiry</strong>, your <strong>best-selling drugs</strong>,
        <strong>redistribution activity</strong>, and <strong>value lost to expiry</strong>.
        All figures are generated directly from the MedShare platform at the time of sending.</p>
      <p style="margin:14px 0;">You can also view this dashboard at any time, or download the report on demand,
        by signing in to the MedShare app.</p>
      <p style="margin:18px 0 0;">Thank you for being part of the MedShare network.</p>
      <p style="margin:6px 0 0;color:#3D544D;">— The MedShare Team</p>
    </div>
    <div style="background:#F1F5F3;padding:14px 28px;font-size:12px;color:#5E6F69;border-top:1px solid #D8D1C4;">
      This is an automated message; please do not reply to this email.
    </div>
  </div>
</body></html>"""
    return plain, html