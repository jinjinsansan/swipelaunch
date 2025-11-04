from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from supabase import Client

from app.config import settings
from app.services import mailgun
from app.services.mailgun import MailgunRecipient

logger = logging.getLogger(__name__)


def _format_currency_jpy(amount: Optional[int]) -> Optional[str]:
    if amount is None:
        return None
    try:
        amount_int = int(amount)
    except (TypeError, ValueError):
        return None
    if amount_int <= 0:
        return None
    return f"¥{amount_int:,}"


def _format_points(points: Optional[int]) -> Optional[str]:
    if points is None:
        return None
    try:
        points_int = int(points)
    except (TypeError, ValueError):
        return None
    if points_int <= 0:
        return None
    return f"{points_int:,}ポイント"


def _is_valid_uuid(candidate: Optional[str]) -> bool:
    if not candidate or not isinstance(candidate, str):
        return False
    try:
        UUID(candidate)
    except (ValueError, TypeError):
        return False
    return True


def send_purchase_notification(
    supabase: Client,
    *,
    buyer_id: str,
    content_title: str,
    content_type: str,
    seller_id: Optional[str] = None,
    amount_jpy: Optional[int] = None,
    points: Optional[int] = None,
    quantity: Optional[int] = None,
    extra_lines: Optional[Sequence[str]] = None,

) -> Optional[str]:
    """Deliver a thank-you message to the buyer inbox via operator messages.

    Returns ``True`` when the inbox notification was created successfully, otherwise ``False``.
    """

    if not buyer_id or not hasattr(supabase, "table"):
        return None

    try:
        buyer_email: Optional[str] = None
        buyer_name: Optional[str] = None

        buyer_resp = (
            supabase
            .table("users")
            .select("email, username")
            .eq("id", buyer_id)
            .maybe_single()
            .execute()
        )
        buyer_row = getattr(buyer_resp, "data", None) or None
        if buyer_row:
            buyer_email = (buyer_row.get("email") or "").strip() or None
            buyer_name = buyer_row.get("username") or None

        seller_name: Optional[str] = None
        if seller_id and _is_valid_uuid(seller_id):
            seller_resp = (
                supabase
                .table("users")
                .select("username")
                .eq("id", seller_id)
                .maybe_single()
                .execute()
            )
            seller_row = getattr(seller_resp, "data", None) or None
            if seller_row:
                seller_name = seller_row.get("username")

        currency_text = _format_currency_jpy(amount_jpy)
        points_text = _format_points(points)

        payment_parts = [value for value in (currency_text, points_text) if value]
        payment_summary = " / ".join(payment_parts) if payment_parts else None

        now_iso = datetime.now(timezone.utc).isoformat()

        lines = [
            "ご購入ありがとうございました。",
            f"ご購入コンテンツ: 「{content_title}」 ({content_type})",
        ]

        if quantity and quantity > 1:
            lines.append(f"数量: {quantity}")

        if seller_name:
            lines.append(f"販売者: {seller_name}")

        if payment_summary:
            lines.append(f"お支払い内容: {payment_summary}")

        if extra_lines:
            lines.extend(extra_lines)

        lines.append("デジタルコンテンツの詳細については、販売者へ直接お問い合わせください。")
        lines.append("")
        lines.extend(
            [
                "――――――――――――――――――",
                "D-swipe",
                "info@dlogicai.com",
                "公式LINE: https://lin.ee/lYIZWhd",
            ]
        )

        body_text = "\n".join(lines)
        message_title = f"ご購入ありがとうございます：{content_title}"

        message_payload = {
            "title": message_title,
            "body_text": body_text,
            "body_html": None,
            "category": "purchase",
            "priority": "normal",
            "status": "sent",
            "send_at": now_iso,
            "created_by": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "admin_hidden": False,
            "admin_archived_at": None,
        }

        message_resp = supabase.table("operator_messages").insert(message_payload).execute()
        message_data = getattr(message_resp, "data", None)
        if not message_data:
            raise RuntimeError("operator_messages insert did not return a row")

        message_obj = message_data[0] if isinstance(message_data, list) else message_data
        message_id = message_obj.get("id") if isinstance(message_obj, dict) else None
        if not message_id:
            raise RuntimeError("operator_messages insert missing id")

        recipient_payload = {
            "message_id": message_id,
            "user_id": buyer_id,
            "delivery_status": "delivered",
            "archived": False,
            "read_at": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        supabase.table("operator_message_recipients").insert(recipient_payload).execute()

        sender_email = settings.mailgun_default_from_email
        if not sender_email and settings.mailgun_domain:
            sender_email = f"no-reply@{settings.mailgun_domain}"

        sender_name = settings.mailgun_default_from_name or "D-swipe事務局"
        reply_to = settings.mailgun_default_reply_to or "info@dlogicai.com"

        if buyer_email and mailgun.is_configured() and sender_email:
            try:
                accepted = mailgun.send_bulk_email_async(
                    subject=message_title,
                    text=body_text,
                    html=None,
                    recipients=[MailgunRecipient(email=buyer_email, name=buyer_name)],
                    sender_email=sender_email,
                    sender_name=sender_name,
                    reply_to=reply_to,
                )
                if accepted:
                    (
                        supabase
                        .table("operator_message_recipients")
                        .update({"email_sent_at": datetime.now(timezone.utc).isoformat()})
                        .eq("message_id", message_id)
                        .eq("user_id", buyer_id)
                        .execute()
                    )
            except Exception as mail_exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to enqueue purchase notification email",
                    extra={
                        "buyer_id": buyer_id,
                        "buyer_email": buyer_email,
                        "error": str(mail_exc),
                    },
                )

        return message_id

    except Exception as exc:  # pragma: no cover - logging only
        logger.warning(
            "Failed to send purchase notification",
            extra={
                "buyer_id": buyer_id,
                "content_title": content_title,
                "content_type": content_type,
                "error": str(exc),
            },
        )
        return None
