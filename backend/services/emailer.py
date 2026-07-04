import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from backend.config import settings

log = logging.getLogger(__name__)


def send_fraud_alert(case: dict) -> None:
    if not settings.gmail_user or not settings.gmail_app_password:
        log.warning("Email not configured — skipping alert")
        return

    subject = f"🚨 FRAUD ALERT [{case['confidence']}] — {case['currency']} {case['amount']:,.2f}"

    reasons_html = "".join(f"<li>{r}</li>" for r in case.get("reasons", []))

    filings = []
    if case.get("ctr_required"):
        filings.append("CTR filing required")
    if case.get("sar_recommended"):
        filings.append("SAR recommended")
    filing_html = (
        f'<div style="background:#fffbeb;border:1px solid #fde68a;padding:12px;border-radius:8px;margin-bottom:16px;">'
        f'<strong style="color:#92400e;">Regulatory: {" · ".join(filings)}</strong></div>'
        if filings else ""
    )

    if case.get("sanctions_hit"):
        subject = f"⛔ OFAC SANCTIONS MATCH — {case['currency']} {case['amount']:,.2f} — BLOCK & REVIEW"
        filing_html = (
            f'<div style="background:#fef2f2;border:1px solid #fecaca;border-left:4px solid #f87171;'
            f'color:#7f1d1d;padding:14px;border-radius:8px;margin-bottom:16px;">'
            f'<strong>OFAC SANCTIONS MATCH — transaction must be blocked or rejected and reported to OFAC.</strong>'
            f'<div style="margin-top:6px;font-size:13px;color:#b91c1c;">{case.get("sanctions_detail", "")}</div></div>'
        ) + filing_html

    body = f"""
    <html><body style="font-family: Arial, sans-serif; color: #1a1a1a;">
      <div style="background:#fee2e2;border-left:4px solid #dc2626;padding:16px;border-radius:8px;margin-bottom:16px;">
        <h2 style="margin:0;color:#dc2626;">Fraudulent Transaction Flagged</h2>
      </div>

      <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
        <tr><td style="padding:8px;color:#6b7280;width:160px;">Account</td><td style="padding:8px;font-weight:600;">{case['account_id']}</td></tr>
        <tr style="background:#f9fafb;"><td style="padding:8px;color:#6b7280;">Amount</td><td style="padding:8px;font-weight:600;">{case['currency']} {case['amount']:,.2f}</td></tr>
        <tr><td style="padding:8px;color:#6b7280;">Direction</td><td style="padding:8px;">{case['direction']}</td></tr>
        <tr style="background:#f9fafb;"><td style="padding:8px;color:#6b7280;">Counterparty</td><td style="padding:8px;">{case.get('counterparty_name', 'N/A')} ({case.get('counterparty_account', 'N/A')})</td></tr>
        <tr><td style="padding:8px;color:#6b7280;">Channel</td><td style="padding:8px;">{case.get('channel', 'N/A')}</td></tr>
        <tr style="background:#f9fafb;"><td style="padding:8px;color:#6b7280;">Fraud Type</td><td style="padding:8px;color:#dc2626;font-weight:600;">{case.get('fraud_type', 'N/A')}</td></tr>
        <tr><td style="padding:8px;color:#6b7280;">Confidence</td><td style="padding:8px;font-weight:600;">{case['confidence']}</td></tr>
        <tr style="background:#f9fafb;"><td style="padding:8px;color:#6b7280;">Case ID</td><td style="padding:8px;font-family:monospace;font-size:12px;">{case['id']}</td></tr>
      </table>

      {filing_html}

      <div style="background:#fef2f2;border:1px solid #fecaca;padding:16px;border-radius:8px;margin-bottom:16px;">
        <h3 style="margin:0 0 8px 0;color:#dc2626;">Why this was flagged:</h3>
        <ul style="margin:0;padding-left:20px;">{reasons_html}</ul>
      </div>

      <p style="color:#6b7280;font-size:13px;">{case.get('ai_summary', '')}</p>

      <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;">
      <p style="color:#9ca3af;font-size:12px;">FMS — Fraud Monitoring System · AI-assisted analysis</p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.gmail_user
    msg["To"] = settings.alert_email or settings.gmail_user
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.gmail_user, settings.gmail_app_password)
            server.sendmail(settings.gmail_user, msg["To"], msg.as_string())
        log.info(f"Fraud alert email sent for case {case['id']}")
    except Exception as e:
        log.error(f"Failed to send email alert: {e}")
