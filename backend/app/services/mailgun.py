"""Utility functions for sending emails via Mailgun."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

from app.config import settings
from app.services import task_queue

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

    return deliver_bulk_email_sync(
        subject=subject,
        text=text,
        html=html,
        recipients=recipients,
        sender_email=sender_email,
        sender_name=sender_name,
        reply_to=reply_to,
    )


def send_bulk_email_async(
    *,
    subject: str,
    text: Optional[str],
    html: Optional[str],
    recipients: Sequence[MailgunRecipient],
    sender_email: str,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> List[str]:
    if task_queue.enqueue_mailgun_send(
        {
            "subject": subject,
            "text": text,
            "html": html,
            "recipients": [recipient.__dict__ for recipient in recipients],
            "sender_email": sender_email,
            "sender_name": sender_name,
            "reply_to": reply_to,
        }
    ):
        return [recipient.email for recipient in recipients if recipient.email.strip()]

    return deliver_bulk_email_sync(
        subject=subject,
        text=text,
        html=html,
        recipients=recipients,
        sender_email=sender_email,
        sender_name=sender_name,
        reply_to=reply_to,
    )


def deliver_bulk_email_sync(
    *,
    subject: str,
    text: Optional[str],
    html: Optional[str],
    recipients: Sequence[MailgunRecipient],
    sender_email: str,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> List[str]:
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
            base_payload: Dict[str, Any] = {
                "from": f"{sender_name} <{sender_email}>" if sender_name else sender_email,
                "subject": subject,
            }
            if text:
                base_payload["text"] = text
            if html:
                base_payload["html"] = html
            if reply_to:
                base_payload["h:Reply-To"] = reply_to

            for recipient in batch:
                email = recipient.email.strip()
                if not email:
                    continue
                data = dict(base_payload)
                data["to"] = [f"{recipient.name} <{email}>" if recipient.name else email]
                if recipient.name:
                    data["recipient-variables"] = json.dumps({email: {"name": recipient.name}}, ensure_ascii=False)

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

                accepted.append(email)

    return accepted
