"""Utility functions for sending emails via Mailgun."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailgunRecipient:
    email: str
    name: Optional[str] = None


def is_configured() -> bool:
    return bool(settings.mailgun_api_key and settings.mailgun_domain)


def _chunk(items: Sequence[MailgunRecipient], size: int) -> Iterable[Sequence[MailgunRecipient]]:
    if size <= 0:
        size = 200
    for index in range(0, len(items), size):
        yield items[index : index + size]


def send_bulk_email(
    *,
    subject: str,
    text: Optional[str],
    html: Optional[str],
    recipients: Sequence[MailgunRecipient],
    sender_email: str,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> List[str]:
    """Send a bulk email to multiple recipients via Mailgun.

    Returns a list of email addresses that were accepted by Mailgun.
    """

    if not is_configured():
        logger.warning("Mailgun is not configured; skipping email send")
        return []

    if not subject or not sender_email:
        logger.warning("Mailgun send skipped due to missing subject or sender email")
        return []

    if not recipients:
        return []

    base_url = settings.mailgun_base_url.rstrip("/")
    endpoint = f"{base_url}/{settings.mailgun_domain}/messages"
    auth = ("api", settings.mailgun_api_key)

    accepted: List[str] = []

    headers = {"Accept": "application/json"}
    timeout = settings.mailgun_request_timeout or 10.0

    with httpx.Client(timeout=timeout, headers=headers) as client:
        for batch in _chunk(list(recipients), settings.mailgun_max_batch_size or 200):
            to_field: List[str] = []
            recipient_variables = {}
            for recipient in batch:
                email = recipient.email.strip()
                if not email:
                    continue
                if recipient.name:
                    to_field.append(f"{recipient.name} <{email}>")
                    recipient_variables[email] = {"name": recipient.name}
                else:
                    to_field.append(email)
            if not to_field:
                continue

            data = {
                "from": f"{sender_name} <{sender_email}>" if sender_name else sender_email,
                "to": to_field,
                "subject": subject,
            }
            if text:
                data["text"] = text
            if html:
                data["html"] = html
            if reply_to:
                data["h:Reply-To"] = reply_to
            if recipient_variables:
                data["recipient-variables"] = json.dumps(recipient_variables, ensure_ascii=False)

            try:
                resp = client.post(endpoint, auth=auth, data=data)
            except httpx.HTTPError as exc:  # pragma: no cover - network failure
                logger.exception("Mailgun request failed: %s", exc)
                continue

            if resp.status_code >= 400:
                logger.error(
                    "Mailgun rejected request (status=%s, body=%s)",
                    resp.status_code,
                    resp.text,
                )
                continue

            accepted.extend([item.email for item in batch if item.email.strip()])

    return accepted
