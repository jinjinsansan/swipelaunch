from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

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
) -> None:
    """Deliver a thank-you message to the buyer inbox via operator messages."""

    if not buyer_id or not hasattr(supabase, "table"):
        return

    try:
        buyer_email: Optional[str] = None
        buyer_name: Optional[str] = None

        buyer_resp = (
            supabase
            .table("users")
            .select("email, display_name, username")
            .eq("id", buyer_id)
            .maybe_single()
            .execute()
        )
        buyer_row = getattr(buyer_resp, "data", None) or None
        if buyer_row:
            buyer_email = (buyer_row.get("email") or "").strip() or None
            buyer_name = buyer_row.get("display_name") or buyer_row.get("username") or None

        seller_name: Optional[str] = None
        if seller_id:
            seller_resp = (
                supabase
                .table("users")
                .select("display_name, username")
                .eq("id", seller_id)
                .maybe_single()
                .execute()
            )
            seller_row = getattr(seller_resp, "data", None) or None
            if seller_row:
                seller_name = seller_row.get("display_name") or seller_row.get("username")

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
        message_row = getattr(message_resp, "data", None)
        if not message_row:
            raise RuntimeError("operator_messages insert did not return a row")

        message_id = message_row[0]["id"] if isinstance(message_row, list) else message_row.get("id")
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

        if buyer_email and mailgun.is_configured() and settings.mailgun_default_from_email:
            try:
                mailgun.send_bulk_email_async(
                    subject=message_title,
                    text=body_text,
                    html=None,
                    recipients=[MailgunRecipient(email=buyer_email, name=buyer_name)],
                    sender_email=settings.mailgun_default_from_email,
                    sender_name=settings.mailgun_default_from_name,
                    reply_to=settings.mailgun_default_reply_to,
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
