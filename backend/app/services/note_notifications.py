from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from supabase import Client

from app.config import settings
from app.services import mailgun, operator_messages
from app.services.followers import list_followers, fetch_creator
from app.services.mailgun import MailgunRecipient

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_price(note: Dict[str, object]) -> str:
    parts: List[str] = []
    if note.get("allow_point_purchase") and note.get("price_points"):
        try:
            parts.append(f"{int(note.get('price_points')):,} pt")
        except Exception:  # pragma: no cover - defensive
            parts.append("ポイント決済")
    if note.get("allow_jpy_purchase") and note.get("price_jpy"):
        try:
            parts.append(f"¥{int(note.get('price_jpy')):,}")
        except Exception:  # pragma: no cover
            parts.append("日本円決済")
    if parts:
        return " / ".join(parts)
    return "無料"


def _build_subject(display_name: str, note_title: str) -> str:
    base_name = display_name or "クリエイター"
    return f"【D-swipe】{base_name}さんの新着SWipeコラム: {note_title}"


def _build_bodies(display_name: str, note_title: str, note_excerpt: Optional[str], note_url: str, price_text: str) -> Dict[str, str]:
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

    text_body = "\n".join(lines)

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
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to notify followers for note %s", note_row.get("id"))


def _handle_note_published(client: Client, note_row: Dict[str, object]) -> None:
    note_id = note_row.get("id")
    creator_id = note_row.get("author_id")
    slug = note_row.get("slug")

    if not note_id or not creator_id or not slug:
        return

    followers = list_followers(client, creator_id)
    if not followers:
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
    if not creator:
        logger.info("Creator %s not found when sending note notification", creator_id)
        return

    display_name = (creator.get("display_name") or creator.get("username") or "クリエイター") if isinstance(creator, dict) else "クリエイター"
    note_title = str(note_row.get("title") or "新着ノート")
    note_excerpt = note_row.get("excerpt") if isinstance(note_row.get("excerpt"), str) else None
    frontend_base = settings.frontend_url.rstrip("/") if settings.frontend_url else "https://d-swipe.com"
    note_url = f"{frontend_base}/notes/{slug}"
    price_text = _format_price(note_row)

    body_payload = _build_bodies(display_name, note_title, note_excerpt, note_url, price_text)
    subject = _build_subject(display_name, note_title)

    message_insert = (
        client
        .table("operator_messages")
        .insert(
            {
                "title": subject,
                "body_text": body_payload["text"],
                "body_html": body_payload["html"],
                "category": "note_publication",
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
                "related_note_id": note_id,
                "related_creator_id": creator_id,
                "metadata": {
                    "note_slug": slug,
                    "note_url": note_url,
                },
            }
        )
        .execute()
    )

    if not message_insert.data:
        logger.warning("Failed to insert operator message for note %s", note_id)
        return

    message_row = message_insert.data[0]
    message_id = message_row.get("id")
    if not message_id:
        return

    follower_ids = [row.get("follower_id") for row in followers if row.get("follower_id")]
    follower_ids = [fid for fid in follower_ids if isinstance(fid, str)]
    if not follower_ids:
        return

    client.table("operator_message_segments").insert(
        {
            "message_id": message_id,
            "segment_type": "user_ids",
            "segment_payload": {"user_ids": follower_ids},
        }
    ).execute()

    operator_messages.dispatch_message(message_id, client=client)

    email_opt_in_ids = [
        row.get("follower_id")
        for row in followers
        if row.get("notify_email", True) and isinstance(row.get("follower_id"), str)
    ]
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
        if not isinstance(email, str) or not email.strip():
            continue
        normalized_email = email.strip().lower()
        email_to_user[normalized_email] = contact.get("id")
        name = contact.get("display_name") or contact.get("username") or None
        recipients.append(MailgunRecipient(email=normalized_email, name=name))

    if not recipients:
        return

    if settings.mailgun_default_from_email:
        sender_email = settings.mailgun_default_from_email
    elif settings.mailgun_domain:
        sender_email = f"no-reply@{settings.mailgun_domain}"
    else:
        sender_email = "no-reply@d-swipe.com"

    sender_name = settings.mailgun_default_from_name or "D-swipe 運営"

    accepted = mailgun.send_bulk_email_async(
        subject=subject,
        text=body_payload["text"],
        html=body_payload["html"],
        recipients=recipients,
        sender_email=sender_email,
        sender_name=sender_name,
        reply_to=settings.mailgun_default_reply_to,
    )

    if not accepted:
        logger.info("Mailgun did not accept any recipients for note %s notification", note_id)
        return

    accepted_lower = {email.lower() for email in accepted}
    accepted_user_ids = [uid for email, uid in email_to_user.items() if email in accepted_lower and isinstance(uid, str)]
    if not accepted_user_ids:
        return

    now_iso = _now_iso()
    client.table("operator_message_recipients").update({"email_sent_at": now_iso}).eq("message_id", message_id).in_("user_id", accepted_user_ids).execute()
    client.table("creator_followers").update({"last_notified_at": now_iso}).eq("creator_id", creator_id).in_("follower_id", accepted_user_ids).execute()
