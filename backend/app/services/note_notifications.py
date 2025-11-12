from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from supabase import Client

from app.config import settings
from app.services import mailgun, operator_messages
from app.services.followers import fetch_creator, list_followers
from app.services.mailgun import MailgunRecipient

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frontend_base() -> str:
    return settings.frontend_url.rstrip("/") if settings.frontend_url else "https://d-swipe.com"


def _creator_display_name(creator: Optional[Dict[str, Any]]) -> str:
    if not isinstance(creator, dict):
        return "クリエイター"
    for key in ("display_name", "username", "name"):
        value = creator.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return "クリエイター"


def _is_email_opt_in(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"true", "t", "1", "yes", "y"}
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


def _collect_followers(client: Client, creator_id: str) -> Tuple[List[Dict[str, object]], List[str], List[str]]:
    followers = list_followers(client, creator_id)
    if not followers:
        return [], [], []

    follower_ids: List[str] = []
    email_opt_in_ids: List[str] = []

    for row in followers:
        follower_id = row.get("follower_id")
        if not isinstance(follower_id, str):
            continue
        follower_ids.append(follower_id)
        if _is_email_opt_in(row.get("notify_email")):
            email_opt_in_ids.append(follower_id)

    return followers, follower_ids, email_opt_in_ids


def _send_follow_notification(
    client: Client,
    *,
    creator_id: str,
    follower_ids: List[str],
    email_opt_in_ids: List[str],
    subject: str,
    body_text: str,
    body_html: Optional[str],
    category: str,
    metadata: Dict[str, Any],
    related_note_id: Optional[str] = None,
    related_product_id: Optional[str] = None,
) -> None:
    if not follower_ids:
        return

    payload: Dict[str, Any] = {
        "title": subject,
        "body_text": body_text,
        "body_html": body_html,
        "category": category,
        "priority": "normal",
        "status": "draft",
        "send_at": _now_iso(),
        "created_by": creator_id,
        "send_email": False,
        "email_subject": subject,
        "email_from_name": settings.mailgun_default_from_name,
        "email_from_address": settings.mailgun_default_from_email,
        "email_reply_to": settings.mailgun_default_reply_to,
        "automated": True,
        "related_creator_id": creator_id,
        "metadata": metadata or {},
    }
    if related_note_id:
        payload["related_note_id"] = related_note_id
    if related_product_id:
        payload["related_product_id"] = related_product_id

    message_insert = client.table("operator_messages").insert(payload).execute()
    if not getattr(message_insert, "data", None):
        logger.warning("Failed to insert operator message for category %s", category)
        return

    message_row = message_insert.data[0]
    message_id = message_row.get("id") if isinstance(message_row, dict) else None
    if not isinstance(message_id, str):
        return

    client.table("operator_message_segments").insert(
        {
            "message_id": message_id,
            "segment_type": "user_ids",
            "segment_payload": {"user_ids": follower_ids},
        }
    ).execute()

    operator_messages.dispatch_message(message_id, client=client)

    if not email_opt_in_ids or not mailgun.is_configured():
        return

    contacts_resp = (
        client
        .table("users")
        .select("id, email, display_name, username")
        .in_("id", email_opt_in_ids)
        .execute()
    )
    contacts = contacts_resp.data or []
    if not contacts:
        return

    recipients: List[MailgunRecipient] = []
    email_to_user: Dict[str, str] = {}

    for contact in contacts:
        email = contact.get("email")
        if not isinstance(email, str):
            continue
        normalized = email.strip().lower()
        if not normalized:
            continue
        user_id = contact.get("id")
        if isinstance(user_id, str):
            email_to_user[normalized] = user_id
        name = contact.get("display_name") or contact.get("username") or None
        recipients.append(MailgunRecipient(email=normalized, name=name))

    if not recipients:
        return

    sender_email = settings.mailgun_default_from_email
    if not sender_email and settings.mailgun_domain:
        sender_email = f"no-reply@{settings.mailgun_domain}"
    if not sender_email:
        sender_email = "no-reply@d-swipe.com"

    sender_name = settings.mailgun_default_from_name or "D-swipe 運営"

    accepted = mailgun.send_bulk_email_async(
        subject=subject,
        text=body_text,
        html=body_html,
        recipients=recipients,
        sender_email=sender_email,
        sender_name=sender_name,
        reply_to=settings.mailgun_default_reply_to,
    )

    if not accepted and recipients:
        accepted = mailgun.send_bulk_email(
            subject=subject,
            text=body_text,
            html=body_html,
            recipients=recipients,
            sender_email=sender_email,
            sender_name=sender_name,
            reply_to=settings.mailgun_default_reply_to,
        )

    if not accepted:
        logger.info("Mailgun did not accept any recipients for category %s", category)
        return

    accepted_lower = {email.lower() for email in accepted}
    accepted_user_ids = [
        user_id
        for email, user_id in email_to_user.items()
        if email in accepted_lower and isinstance(user_id, str)
    ]
    if not accepted_user_ids:
        return

    now_iso = _now_iso()
    client.table("operator_message_recipients").update({"email_sent_at": now_iso}).eq("message_id", message_id).in_("user_id", accepted_user_ids).execute()
    client.table("creator_followers").update({"last_notified_at": now_iso}).eq("creator_id", creator_id).in_("follower_id", accepted_user_ids).execute()


def _format_note_price(note: Dict[str, object]) -> str:
    parts: List[str] = []
    if note.get("allow_point_purchase") and note.get("price_points"):
        try:
            parts.append(f"{int(note.get('price_points')):,} pt")
        except Exception:
            parts.append("ポイント決済")
    if note.get("allow_jpy_purchase") and note.get("price_jpy"):
        try:
            parts.append(f"¥{int(note.get('price_jpy')):,}")
        except Exception:
            parts.append("日本円決済")
    if parts:
        return " / ".join(parts)
    return "無料"


def _build_note_subject(display_name: str, note_title: str) -> str:
    base_name = display_name or "クリエイター"
    return f"【D-swipe】{base_name}さんの新着SWipeコラム: {note_title}"


def _build_note_bodies(display_name: str, note_title: str, note_excerpt: Optional[str], note_url: str, price_text: str) -> Dict[str, str]:
    intro = f"{display_name}さんが新しいSWipeコラム『{note_title}』を公開しました。"
    lines = [intro, f"価格: {price_text}"]
    if note_excerpt:
        lines.append("")
        lines.append(note_excerpt)
    lines.append("")
    lines.append(f"コラムを読む: {note_url}")
    lines.append("")
    lines.append("－－－－－－－－－－－－")
    lines.append("このメールは D-swipe 運営から自動送信されています。")

    text_body = "\\n".join(lines)

    html_parts = [
        f"<p>{intro}</p>",
        f"<p><strong>価格:</strong> {price_text}</p>",
    ]
    if note_excerpt:
        html_parts.append(f"<p>{note_excerpt}</p>")
    html_parts.append(f'<p><a href="{note_url}" target="_blank" rel="noopener noreferrer">コラムを読む</a></p>')
    html_parts.append("<hr />")
    html_parts.append("<p>このメールは D-swipe 運営から自動送信されています。</p>")

    return {
        "text": text_body,
        "html": "".join(html_parts),
    }


def handle_note_published(client: Client, note_row: Dict[str, object]) -> None:
    try:
        _handle_note_published(client, note_row)
    except Exception:
        logger.exception("Failed to notify followers for note %s", note_row.get("id"))


def _handle_note_published(client: Client, note_row: Dict[str, object]) -> None:
    note_id = note_row.get("id")
    creator_id = note_row.get("author_id")
    slug = note_row.get("slug")

    if not note_id or not creator_id or not slug:
        return

    followers, follower_ids, email_opt_in_ids = _collect_followers(client, creator_id)
    if not follower_ids:
        return

    existing = (
        client
        .table("operator_messages")
        .select("id")
        .eq("automated", True)
        .eq("related_note_id", note_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return

    creator = fetch_creator(client, creator_id)
    display_name = _creator_display_name(creator)
    note_title = str(note_row.get("title") or "新着SWipeコラム")
    note_excerpt = note_row.get("excerpt") if isinstance(note_row.get("excerpt"), str) else None
    note_url = f"{_frontend_base()}/notes/{slug}"
    price_text = _format_note_price(note_row)

    body_payload = _build_note_bodies(display_name, note_title, note_excerpt, note_url, price_text)
    subject = _build_note_subject(display_name, note_title)

    _send_follow_notification(
        client,
        creator_id=creator_id,
        follower_ids=follower_ids,
        email_opt_in_ids=email_opt_in_ids,
        subject=subject,
        body_text=body_payload["text"],
        body_html=body_payload["html"],
        category="note_publication",
        metadata={
            "type": "note_publication",
            "note_slug": slug,
            "note_url": note_url,
        },
        related_note_id=note_id,
    )


def _format_product_price(product: Dict[str, object]) -> Optional[str]:
    parts: List[str] = []
    if product.get("allow_point_purchase") and product.get("price_in_points"):
        try:
            parts.append(f"{int(product.get('price_in_points')):,} pt")
        except Exception:
            parts.append("ポイント決済")
    if product.get("allow_jpy_purchase") and product.get("price_jpy"):
        try:
            parts.append(f"¥{int(product.get('price_jpy')):,}")
        except Exception:
            parts.append("日本円決済")
    if not parts:
        return None
    return " / ".join(parts)


def _truncate(text: Optional[str], limit: int = 180) -> Optional[str]:
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"


def _build_lp_subject(display_name: str, lp_title: str) -> str:
    base_name = display_name or "クリエイター"
    return f"【D-swipe】{base_name}さんの新着LP: {lp_title}"


def _build_lp_bodies(
    display_name: str,
    lp_title: str,
    product_title: Optional[str],
    description: Optional[str],
    lp_url: str,
    price_text: Optional[str],
) -> Dict[str, str]:
    intro = f"{display_name}さんのLP『{lp_title}』がAllLPに掲載されました。"
    lines: List[str] = [intro]
    if product_title and product_title != lp_title:
        lines.append(f"商品名: {product_title}")
    if price_text:
        lines.append(f"価格: {price_text}")
    excerpt = _truncate(description)
    if excerpt:
        lines.append("")
        lines.append(excerpt)
    lines.append("")
    lines.append(f"LPを見る: {lp_url}")
    lines.append("")
    lines.append("－－－－－－－－－－－－")
    lines.append("このメールは D-swipe 運営から自動送信されています。")

    text_body = "\\n".join(lines)

    html_parts = [f"<p>{intro}</p>"]
    if product_title and product_title != lp_title:
        html_parts.append(f"<p><strong>商品名:</strong> {product_title}</p>")
    if price_text:
        html_parts.append(f"<p><strong>価格:</strong> {price_text}</p>")
    if excerpt:
        html_parts.append(f"<p>{excerpt}</p>")
    html_parts.append(f'<p><a href="{lp_url}" target="_blank" rel="noopener noreferrer">LPを見る</a></p>')
    html_parts.append("<hr />")
    html_parts.append("<p>このメールは D-swipe 運営から自動送信されています。</p>")

    return {
        "text": text_body,
        "html": "".join(html_parts),
    }


def _fetch_lp(client: Client, lp_id: str, cache: Optional[Dict[str, Optional[Dict[str, object]]]] = None) -> Optional[Dict[str, object]]:
    if cache is not None and lp_id in cache:
        return cache[lp_id]

    response = (
        client
        .table("landing_pages")
        .select("id, slug, title, status")
        .eq("id", lp_id)
        .single()
        .execute()
    )
    lp_data = response.data if response and getattr(response, "data", None) else None
    if cache is not None:
        cache[lp_id] = lp_data
    return lp_data


def _product_is_alllp_ready(
    product: Optional[Dict[str, object]],
    client: Client,
    cache: Optional[Dict[str, Optional[Dict[str, object]]]] = None,
) -> bool:
    if not product:
        return False
    product_type = str(product.get("product_type") or "points").lower()
    if product_type != "points":
        return False
    if not product.get("is_available"):
        return False
    lp_id = product.get("lp_id")
    if not isinstance(lp_id, str):
        return False
    lp_data = _fetch_lp(client, lp_id, cache)
    if not lp_data:
        return False
    return str(lp_data.get("status", "")).lower() == "published"


def handle_lp_product_listed(
    client: Client,
    product_row: Dict[str, object],
    previous_row: Optional[Dict[str, object]] = None,
) -> None:
    try:
        _handle_lp_product_listed(client, product_row, previous_row)
    except Exception:
        logger.exception(
            "Failed to notify followers for LP listing of product %s",
            product_row.get("id"),
        )


def _handle_lp_product_listed(
    client: Client,
    product_row: Dict[str, object],
    previous_row: Optional[Dict[str, object]] = None,
) -> None:
    product_id = product_row.get("id")
    creator_id = product_row.get("seller_id")
    if not isinstance(product_id, str) or not isinstance(creator_id, str):
        return

    cache: Dict[str, Optional[Dict[str, object]]] = {}
    if not _product_is_alllp_ready(product_row, client, cache):
        return

    lp_id = product_row.get("lp_id")
    if not isinstance(lp_id, str):
        return

    lp_data = _fetch_lp(client, lp_id, cache)
    if not lp_data or str(lp_data.get("status", "")).lower() != "published":
        return

    if previous_row and previous_row.get("lp_id") == lp_id:
        if _product_is_alllp_ready(previous_row, client, cache):
            return

    existing = (
        client
        .table("operator_messages")
        .select("id")
        .eq("automated", True)
        .eq("category", "lp_publication")
        .eq("related_product_id", product_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return

    followers, follower_ids, email_opt_in_ids = _collect_followers(client, creator_id)
    if not follower_ids:
        return

    creator = fetch_creator(client, creator_id)
    display_name = _creator_display_name(creator)

    slug = lp_data.get("slug") if isinstance(lp_data, dict) else None
    lp_url = f"{_frontend_base()}/view/{slug}" if isinstance(slug, str) and slug else f"{_frontend_base()}/products/{product_id}"

    lp_title = str(lp_data.get("title") or product_row.get("title") or "新着LP")
    product_title = product_row.get("title") if isinstance(product_row.get("title"), str) else None
    description = product_row.get("description") if isinstance(product_row.get("description"), str) else None
    price_text = _format_product_price(product_row)

    body_payload = _build_lp_bodies(display_name, lp_title, product_title, description, lp_url, price_text)
    subject = _build_lp_subject(display_name, lp_title)

    _send_follow_notification(
        client,
        creator_id=creator_id,
        follower_ids=follower_ids,
        email_opt_in_ids=email_opt_in_ids,
        subject=subject,
        body_text=body_payload["text"],
        body_html=body_payload["html"],
        category="lp_publication",
        metadata={
            "type": "lp_publication",
            "lp_id": lp_id,
            "lp_slug": slug,
            "lp_url": lp_url,
            "product_id": product_id,
        },
        related_product_id=product_id,
    )


def _format_salon_price(salon: Dict[str, object]) -> Optional[str]:
    parts: List[str] = []
    monthly_price = salon.get("monthly_price_jpy")
    if salon.get("allow_jpy_subscription") and isinstance(monthly_price, (int, float)):
        try:
            parts.append(f"¥{int(monthly_price):,}/月")
        except Exception:
            parts.append("日本円決済")
    if salon.get("allow_point_subscription") and salon.get("subscription_plan_id"):
        parts.append("ポイント決済対応")
    if not parts:
        return None
    return " / ".join(parts)


def _build_salon_subject(display_name: str, salon_title: str) -> str:
    base_name = display_name or "クリエイター"
    return f"【D-swipe】{base_name}さんのオンラインサロンが公開されました"


def _build_salon_bodies(
    display_name: str,
    salon_title: str,
    description: Optional[str],
    salon_url: str,
    price_text: Optional[str],
) -> Dict[str, str]:
    intro = f"{display_name}さんのオンラインサロン『{salon_title}』が公開されました。"
    lines: List[str] = [intro]
    if price_text:
        lines.append(f"参加費: {price_text}")
    excerpt = _truncate(description)
    if excerpt:
        lines.append("")
        lines.append(excerpt)
    lines.append("")
    lines.append(f"サロンをチェック: {salon_url}")
    lines.append("")
    lines.append("－－－－－－－－－－－－")
    lines.append("このメールは D-swipe 運営から自動送信されています。")

    text_body = "\\n".join(lines)

    html_parts = [f"<p>{intro}</p>"]
    if price_text:
        html_parts.append(f"<p><strong>参加費:</strong> {price_text}</p>")
    if excerpt:
        html_parts.append(f"<p>{excerpt}</p>")
    html_parts.append(f'<p><a href="{salon_url}" target="_blank" rel="noopener noreferrer">サロンをチェック</a></p>')
    html_parts.append("<hr />")
    html_parts.append("<p>このメールは D-swipe 運営から自動送信されています。</p>")

    return {
        "text": text_body,
        "html": "".join(html_parts),
    }


def handle_salon_published(
    client: Client,
    salon_row: Dict[str, object],
    previous_row: Optional[Dict[str, object]] = None,
) -> None:
    try:
        _handle_salon_published(client, salon_row, previous_row)
    except Exception:
        logger.exception("Failed to notify followers for salon %s", salon_row.get("id"))


def _handle_salon_published(
    client: Client,
    salon_row: Dict[str, object],
    previous_row: Optional[Dict[str, object]] = None,
) -> None:
    salon_id = salon_row.get("id")
    creator_id = salon_row.get("owner_id")
    if not isinstance(salon_id, str) or not isinstance(creator_id, str):
        return

    is_active_now = bool(salon_row.get("is_active", False))
    if not is_active_now:
        return

    if previous_row is not None and bool(previous_row.get("is_active", False)):
        return

    followers, follower_ids, email_opt_in_ids = _collect_followers(client, creator_id)
    if not follower_ids:
        return

    creator = fetch_creator(client, creator_id)
    display_name = _creator_display_name(creator)
    salon_title = str(salon_row.get("title") or "オンラインサロン")
    description = salon_row.get("description") if isinstance(salon_row.get("description"), str) else None
    price_text = _format_salon_price(salon_row)
    salon_url = f"{_frontend_base()}/salons/{salon_id}/public"

    body_payload = _build_salon_bodies(display_name, salon_title, description, salon_url, price_text)
    subject = _build_salon_subject(display_name, salon_title)

    _send_follow_notification(
        client,
        creator_id=creator_id,
        follower_ids=follower_ids,
        email_opt_in_ids=email_opt_in_ids,
        subject=subject,
        body_text=body_payload["text"],
        body_html=body_payload["html"],
        category="salon_publication",
        metadata={
            "type": "salon_publication",
            "salon_id": salon_id,
            "salon_url": salon_url,
        },
    )
