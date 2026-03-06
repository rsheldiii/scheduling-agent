from __future__ import annotations

import logging

from twilio.rest import Client as TwilioClient

from .secrets import get_secret

logger = logging.getLogger(__name__)

_client: TwilioClient | None = None
_phone_from: str | None = None


def send_sms(to: str, body: str, client: TwilioClient | None = None) -> str:
    """Send an SMS message via Twilio. Returns the message SID.

    If *client* is provided it will be cached for future calls. Otherwise a
    client is created from environment variables on the first invocation.
    """
    global _client, _phone_from

    if client is not None:
        _client = client
    if _client is None:
        account_sid = get_secret("twilio_account_sid", "TWILIO_ACCOUNT_SID")
        auth_token = get_secret("twilio_auth_token", "TWILIO_AUTH_TOKEN")
        if not account_sid or not auth_token:
            raise RuntimeError("Twilio credentials not configured for SMS")
        _client = TwilioClient(account_sid, auth_token)

    if _phone_from is None:
        _phone_from = get_secret("twilio_phone_from", "PHONE_NUMBER_FROM") or ""
    if not _phone_from:
        raise RuntimeError("PHONE_NUMBER_FROM not configured for SMS")

    message = _client.messages.create(from_=_phone_from, to=to, body=body)
    sid: str = str(message.sid)
    logger.info("SMS sent to %s: sid=%s", to, sid)
    return sid
