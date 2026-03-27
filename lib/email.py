"""
Brevo (Sendinblue) transactional email sender.
"""

import json
import urllib.request
import urllib.error

from lib.config import BREVO_API_KEY, BREVO_SENDER_EMAIL, BREVO_SENDER_NAME


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send a transactional email via Brevo API. Returns True on success."""
    if not BREVO_API_KEY:
        return False

    payload = json.dumps({
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
    }).encode()

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": BREVO_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 201
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False
