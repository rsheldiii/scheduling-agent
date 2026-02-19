from __future__ import annotations

import logging
import os

from twilio.rest import Client as TwilioClient

logger = logging.getLogger(__name__)


def send_sms(to: str, body: str) -> str:
    """Send an SMS message via Twilio. Returns the message SID."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    phone_from = os.getenv("PHONE_NUMBER_FROM")

    if not all([account_sid, auth_token, phone_from]):
        raise RuntimeError("Twilio credentials not configured for SMS")

    client = TwilioClient(account_sid, auth_token)
    message = client.messages.create(from_=phone_from, to=to, body=body)
    logger.info("SMS sent to %s: sid=%s", to, message.sid)
    return message.sid
