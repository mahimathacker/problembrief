"""Email the brief via Resend. No-op if RESEND_API_KEY is unset."""
from __future__ import annotations

import httpx

import config


def send_email(subject: str, body: str) -> bool:
    if not config.RESEND_API_KEY:
        print("  - email: skipped (set RESEND_API_KEY — see README 'Email setup')")
        return False
    if not config.EMAIL_TO:
        print("  ! email: RESEND_API_KEY is set but EMAIL_TO is empty")
        return False
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
            json={
                "from": config.EMAIL_FROM,
                "to": [config.EMAIL_TO],
                "subject": subject,
                "text": body,
            },
            timeout=20,
        )
        r.raise_for_status()
        print(f"  - email: sent to {config.EMAIL_TO}")
        return True
    except Exception as e:
        print(f"  ! email send failed: {e}")
        return False
