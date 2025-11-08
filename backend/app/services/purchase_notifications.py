from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from supabase import Client

from app.config import settings
from app.services import mailgun
from app.services.mailgun import MailgunRecipient
from app.utils.locale import normalize_locale, DEFAULT_LOCALE

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


def _format_points(points: Optional[int], locale: str) -> Optional[str]:
    if points is None:
        return None
    try:
        points_int = int(points)
    except (TypeError, ValueError):
        return None
    if points_int <= 0:
        return None
    return f"{points_int:,}ポイント" if locale == "ja" else f"{points_int:,} points"


def _is_valid_uuid(candidate: Optional[str]) -> bool:
    if not candidate or not isinstance(candidate, str):
        return False
    try:
        UUID(candidate)
    except (ValueError, TypeError):
        return False
    return True


CONTENT_TYPE_LABELS = {
    "ja": {
        "NOTE": "NOTE",
        "PRODUCT": "プロダクト",
        "SALON": "サロン",
        "SUBSCRIPTION": "サブスクリプション",
    },
    "en": {
        "NOTE": "NOTE",
        "PRODUCT": "Product",
        "SALON": "Salon",
        "SUBSCRIPTION": "Subscription",
    },
}


PURCHASE_EMAIL_TEXT = {
    "ja": {
        "subject": "ご購入ありがとうございます：{title}",
        "greeting": "ご購入ありがとうございました。",
        "content": "ご購入コンテンツ: 「{title}」 ({content_type})",
        "quantity": "数量: {quantity}",
        "seller": "販売者: {seller}",
        "payment": "お支払い内容: {summary}",
        "contact": "デジタルコンテンツの詳細については、販売者へ直接お問い合わせください。",
        "footer": [
            "――――――――――――――――――",
            "D-swipe",
            "info@dlogicai.com",
            "公式LINE: https://lin.ee/lYIZWhd",
        ],
        "sender_name": "D-swipe事務局",
    },
    "en": {
        "subject": "Thank you for your purchase: {title}",
        "greeting": "Thank you for your purchase.",
        "content": "Purchased content: \"{title}\" ({content_type})",
        "quantity": "Quantity: {quantity}",
        "seller": "Seller: {seller}",
        "payment": "Payment details: {summary}",
        "contact": "If you have any questions about this digital content, please contact the seller directly.",
        "footer": [
            "――――――――――――――――――",
            "D-swipe",
            "info@dlogicai.com",
            "Official LINE: https://lin.ee/lYIZWhd",
        ],
        "sender_name": "D-swipe Support",
    },
}


SELLER_EMAIL_TEXT = {
    "ja": {
        "subject": "【販売報告】{title}",
        "intro": "以下のコンテンツが購入されました。",
        "content": "コンテンツ: 「{title}」 ({content_type})",
        "quantity": "数量: {quantity}",
        "buyer": "購入者: {buyer}",
        "payment_method": "決済方法: {method}",
        "payment": "お支払い内容: {summary}",
        "purchased_at": "購入日時: {timestamp}",
        "footer": [
            "",
            "――――――――――――――――――",
            "D-swipe",
            "info@dlogicai.com",
            "公式LINE: https://lin.ee/lYIZWhd",
        ],
        "sender_name": "D-swipe事務局",
    },
    "en": {
        "subject": "Sales notification: {title}",
        "intro": "The following content has been purchased.",
        "content": "Content: \"{title}\" ({content_type})",
        "quantity": "Quantity: {quantity}",
        "buyer": "Buyer: {buyer}",
        "payment_method": "Payment method: {method}",
        "payment": "Payment details: {summary}",
        "purchased_at": "Purchase time: {timestamp}",
        "footer": [
            "",
            "――――――――――――――――――",
            "D-swipe",
            "info@dlogicai.com",
            "Official LINE: https://lin.ee/lYIZWhd",
        ],
        "sender_name": "D-swipe Support",
    },
}


PAYMENT_METHOD_LABELS = {
    "ja": {
        "points": "ポイント決済",
        "yen": "日本円決済",
        "mixed": "円 + ポイント決済",
        "subscription": "サブスクリプション",
        "other": "その他",
    },
    "en": {
        "points": "Point payment",
        "yen": "JPY payment",
        "mixed": "Mixed (JPY + points)",
        "subscription": "Subscription",
        "other": "Other",
    },
}


def _localize_content_type(content_type: Optional[str], locale: str) -> str:
    if not content_type:
        return "Content" if locale == "en" else "コンテンツ"
    key = str(content_type).upper()
    labels = CONTENT_TYPE_LABELS.get(locale) or CONTENT_TYPE_LABELS[DEFAULT_LOCALE]
    return labels.get(key, key)


def _normalize_payment_method(raw_value: Optional[str]) -> str:
    if not raw_value:
        return "other"
    value = str(raw_value).strip().lower()
    if "ポイント" in raw_value:
        return "points"
    if "円" in raw_value:
        if "ポイント" in raw_value:
            return "mixed"
        return "yen"
    if "point" in value:
        return "points"
    if any(keyword in value for keyword in ("yen", "jpy")):
        return "yen"
    if "subscription" in value:
        return "subscription"
    if "mixed" in value:
        return "mixed"
    return "other"


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
    """Deliver a localized thank-you message to the buyer inbox via operator messages."""

    if not buyer_id or not hasattr(supabase, "table"):
        return None

    try:
        buyer_email: Optional[str] = None
        buyer_name: Optional[str] = None
        buyer_locale: str = DEFAULT_LOCALE

        buyer_resp = (
            supabase
            .table("users")
            .select("email, username, preferred_locale")
            .eq("id", buyer_id)
            .maybe_single()
            .execute()
        )
        buyer_row = getattr(buyer_resp, "data", None) or None
        if buyer_row:
            buyer_email = (buyer_row.get("email") or "").strip() or None
            buyer_name = buyer_row.get("username") or None
            buyer_locale = normalize_locale(buyer_row.get("preferred_locale"))

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
        points_text = _format_points(points, buyer_locale)

        payment_parts = [value for value in (currency_text, points_text) if value]
        payment_summary = " / ".join(payment_parts) if payment_parts else None

        now_iso = datetime.now(timezone.utc).isoformat()
        translations = PURCHASE_EMAIL_TEXT.get(buyer_locale) or PURCHASE_EMAIL_TEXT[DEFAULT_LOCALE]
        content_type_label = _localize_content_type(content_type, buyer_locale)

        lines = [
            translations["greeting"],
            translations["content"].format(title=content_title, content_type=content_type_label),
        ]

        if quantity and quantity > 1:
            lines.append(translations["quantity"].format(quantity=quantity))

        if seller_name:
            lines.append(translations["seller"].format(seller=seller_name))

        if payment_summary:
            lines.append(translations["payment"].format(summary=payment_summary))

        if extra_lines:
            lines.extend(extra_lines)

        lines.append(translations["contact"])
        lines.append("")
        lines.extend(translations["footer"])

        body_text = "\n".join(lines)
        message_title = translations["subject"].format(title=content_title)

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

        default_sender_name = translations["sender_name"]
        sender_name = settings.mailgun_default_from_name or default_sender_name
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


def send_seller_purchase_notification(
    supabase: Client,
    *,
    seller_id: Optional[str],
    content_title: str,
    content_type: str,
    buyer_id: Optional[str] = None,
    amount_jpy: Optional[int] = None,
    points: Optional[int] = None,
    quantity: Optional[int] = None,
    payment_method: Optional[str] = None,
    purchased_at: Optional[datetime] = None,
    extra_lines: Optional[Sequence[str]] = None,
) -> Optional[str]:
    if not seller_id or not _is_valid_uuid(seller_id):
        return None

    try:
        seller_resp = (
            supabase
            .table("users")
            .select("email, username, preferred_locale")
            .eq("id", seller_id)
            .maybe_single()
            .execute()
        )
        seller_row = getattr(seller_resp, "data", None) or None
        if not seller_row:
            return None

        seller_email: Optional[str] = (seller_row.get("email") or "").strip() or None
        seller_name: Optional[str] = seller_row.get("username") or None
        seller_locale = normalize_locale(seller_row.get("preferred_locale"))

        buyer_name: Optional[str] = None
        if buyer_id and _is_valid_uuid(buyer_id):
            buyer_resp = (
                supabase
                .table("users")
                .select("username")
                .eq("id", buyer_id)
                .maybe_single()
                .execute()
            )
            buyer_row = getattr(buyer_resp, "data", None) or None
            if buyer_row:
                buyer_name = buyer_row.get("username") or None

        currency_text = _format_currency_jpy(amount_jpy)
        points_text = _format_points(points, seller_locale)
        payment_parts = [value for value in (currency_text, points_text) if value]
        payment_summary = " / ".join(payment_parts) if payment_parts else None

        now_iso = datetime.now(timezone.utc).isoformat()
        purchased_at_text = (
            purchased_at.isoformat()
            if isinstance(purchased_at, datetime)
            else now_iso
        )

        translations = SELLER_EMAIL_TEXT.get(seller_locale) or SELLER_EMAIL_TEXT[DEFAULT_LOCALE]
        content_type_label = _localize_content_type(content_type, seller_locale)
        normalized_payment_method = _normalize_payment_method(payment_method)
        payment_method_label = PAYMENT_METHOD_LABELS.get(seller_locale, PAYMENT_METHOD_LABELS[DEFAULT_LOCALE]).get(
            normalized_payment_method,
            PAYMENT_METHOD_LABELS[DEFAULT_LOCALE][normalized_payment_method],
        )

        lines = [
            translations["intro"],
            translations["content"].format(title=content_title, content_type=content_type_label),
        ]

        if quantity and quantity > 1:
            lines.append(translations["quantity"].format(quantity=quantity))

        if buyer_name:
            lines.append(translations["buyer"].format(buyer=buyer_name))

        if payment_method_label:
            lines.append(translations["payment_method"].format(method=payment_method_label))

        if payment_summary:
            lines.append(translations["payment"].format(summary=payment_summary))

        lines.append(translations["purchased_at"].format(timestamp=purchased_at_text))

        if extra_lines:
            lines.extend(extra_lines)

        lines.extend(translations["footer"])

        body_text = "\n".join(lines)
        message_title = translations["subject"].format(title=content_title)

        message_payload = {
            "title": message_title,
            "body_text": body_text,
            "body_html": None,
            "category": "sales",
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
            "user_id": seller_id,
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

        default_sender_name = translations["sender_name"]
        sender_name = settings.mailgun_default_from_name or default_sender_name
        reply_to = settings.mailgun_default_reply_to or "info@dlogicai.com"

        if seller_email and mailgun.is_configured() and sender_email:
            try:
                accepted = mailgun.send_bulk_email_async(
                    subject=message_title,
                    text=body_text,
                    html=None,
                    recipients=[MailgunRecipient(email=seller_email, name=seller_name)],
                    sender_email=sender_email,
                    sender_name=sender_name,
                    reply_to=reply_to,
                )
                if accepted:
                    (
                        supabase
                        .table("operator_message_recipients")
                        .update({
                            "email_sent_at": datetime.now(timezone.utc).isoformat(),
                        })
                        .eq("message_id", message_id)
                        .eq("user_id", seller_id)
                        .execute()
                    )
            except Exception as mail_exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to enqueue seller purchase notification email",
                    extra={
                        "seller_id": seller_id,
                        "seller_email": seller_email,
                        "error": str(mail_exc),
                    },
                )

        return message_id

    except Exception as exc:  # pragma: no cover - logging only
        logger.warning(
            "Failed to send seller purchase notification",
            extra={
                "seller_id": seller_id,
                "content_title": content_title,
                "content_type": content_type,
                "error": str(exc),
            },
        )
        return None
