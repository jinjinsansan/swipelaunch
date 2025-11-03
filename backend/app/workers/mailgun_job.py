"""RQ worker functions for Mailgun delivery."""

from __future__ import annotations

import logging
from typing import List, Optional

from app.services.mailgun import MailgunRecipient, deliver_bulk_email_sync

logger = logging.getLogger(__name__)


def deliver_mailgun_message(
    *,
    subject: str,
    text: Optional[str] = None,
    html: Optional[str] = None,
    recipients: List[dict],
    sender_email: str,
    sender_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    objects = [MailgunRecipient(**data) for data in recipients]
    deliver_bulk_email_sync(
        subject=subject,
        text=text,
        html=html,
        recipients=objects,
        sender_email=sender_email,
        sender_name=sender_name,
        reply_to=reply_to,
    )
