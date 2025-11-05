from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import logging
from http import HTTPStatus

import requests
from postgrest.exceptions import APIError

from supabase import Client

from app.config import get_supabase_client, settings
from app.models.platform_settings import (
    PlatformPaymentSettings,
    PlatformPaymentSettingsUpdateRequest,
)

SETTINGS_TABLE = "platform_settings"

KEY_EXCHANGE_RATE = "exchange_rate_usd_jpy"
KEY_SPREAD = "exchange_rate_spread_jpy"
KEY_FEE_PERCENT = "platform_fee_percent"

_CACHE_TTL = timedelta(minutes=5)
_cache: Optional[PlatformPaymentSettings] = None
_cache_expiry: Optional[datetime] = None

logger = logging.getLogger(__name__)

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS platform_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID REFERENCES users(id)
);

CREATE OR REPLACE FUNCTION trg_platform_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS platform_settings_updated_at ON platform_settings;
CREATE TRIGGER platform_settings_updated_at
BEFORE UPDATE ON platform_settings
FOR EACH ROW
EXECUTE PROCEDURE trg_platform_settings_updated_at();

INSERT INTO platform_settings (key, value)
VALUES
    ('exchange_rate_usd_jpy', to_jsonb({default_rate})),
    ('exchange_rate_spread_jpy', to_jsonb({default_spread})),
    ('platform_fee_percent', to_jsonb({default_fee}))
ON CONFLICT (key) DO NOTHING;
"""


def _execute_sql(sql: str) -> None:
    if not settings.supabase_url:
        raise RuntimeError("Supabase URL not configured")

    api_key = settings.supabase_service_role_key or settings.supabase_key
    if not api_key:
        raise RuntimeError(
            "Supabase service role key is not configured."
            " Set SUPABASE_SERVICE_ROLE_KEY or run the migration SQL manually."
        )

    url = f"{settings.supabase_url.rstrip('/')}/sql/v1"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"query": sql}

    response = requests.post(url, headers=headers, json=payload, timeout=15)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:  # pragma: no cover - network failure
        status = response.status_code
        if status in {HTTPStatus.NOT_FOUND, HTTPStatus.METHOD_NOT_ALLOWED}:
            raise RuntimeError(
                "Supabase SQL API is unavailable. Ensure the project allows SQL API access or run "
                "migrations/20251105_add_platform_settings.sql manually via Supabase CLI or dashboard."
            ) from exc

        if status == HTTPStatus.UNAUTHORIZED:
            raise RuntimeError(
                "Supabase service role key is invalid. Please update SUPABASE_SERVICE_ROLE_KEY."
            ) from exc

        logger.exception("Failed to execute SQL for platform settings bootstrap")
        raise RuntimeError(f"SQL bootstrap failed: {exc}") from exc


def _bootstrap_settings_table() -> None:
    sql = BOOTSTRAP_SQL.format(
        default_rate=settings.default_exchange_rate_usd_jpy,
        default_spread=settings.default_exchange_spread_jpy,
        default_fee=settings.default_platform_fee_percent,
    )
    _execute_sql(sql)


def _as_float(value: object, fallback: float) -> float:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict) and "value" in value:
        return _as_float(value.get("value"), fallback)
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _load_settings(client: Client) -> PlatformPaymentSettings:
    keys = [KEY_EXCHANGE_RATE, KEY_SPREAD, KEY_FEE_PERCENT]
    try:
        response = (
            client
            .table(SETTINGS_TABLE)
            .select("key, value, updated_at, updated_by")
            .in_("key", keys)
            .execute()
        )
    except APIError as exc:  # pragma: no cover - depends on Supabase state
        message = getattr(exc, "message", "") or str(exc)
        if "platform_settings" not in message:
            raise

        logger.warning("platform_settings table missing; attempting bootstrap")
        try:
            _bootstrap_settings_table()
        except RuntimeError as bootstrap_exc:
            logger.error("Platform settings bootstrap failed: %s", bootstrap_exc)
            return PlatformPaymentSettings(
                exchange_rate_usd_jpy=settings.default_exchange_rate_usd_jpy,
                spread_jpy=settings.default_exchange_spread_jpy,
                platform_fee_percent=settings.default_platform_fee_percent,
                updated_at=None,
                updated_by=None,
            )

        try:
            response = (
                client
                .table(SETTINGS_TABLE)
                .select("key, value, updated_at, updated_by")
                .in_("key", keys)
                .execute()
            )
        except APIError as retry_exc:
            logger.error("Failed to read platform_settings after bootstrap: %s", retry_exc)
            return PlatformPaymentSettings(
                exchange_rate_usd_jpy=settings.default_exchange_rate_usd_jpy,
                spread_jpy=settings.default_exchange_spread_jpy,
                platform_fee_percent=settings.default_platform_fee_percent,
                updated_at=None,
                updated_by=None,
            )

    rows: Dict[str, Dict[str, object]] = {}
    for row in response.data or []:
        rows[str(row["key"])] = row

    exchange_rate = _as_float(rows.get(KEY_EXCHANGE_RATE, {}).get("value"), settings.default_exchange_rate_usd_jpy)
    spread = _as_float(rows.get(KEY_SPREAD, {}).get("value"), settings.default_exchange_spread_jpy)
    fee_percent = _as_float(rows.get(KEY_FEE_PERCENT, {}).get("value"), settings.default_platform_fee_percent)

    latest_row = max(
        (row for row in rows.values() if row.get("updated_at")),
        default=None,
        key=lambda row: row.get("updated_at"),
    )

    updated_at = None
    updated_by = None
    if latest_row:
        updated_at = latest_row.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                updated_at = None
        updated_by = latest_row.get("updated_by")

    return PlatformPaymentSettings(
        exchange_rate_usd_jpy=exchange_rate,
        spread_jpy=spread,
        platform_fee_percent=fee_percent,
        updated_at=updated_at,
        updated_by=str(updated_by) if updated_by else None,
    )


def get_platform_settings(force_refresh: bool = False, client: Optional[Client] = None) -> PlatformPaymentSettings:
    global _cache, _cache_expiry

    now = datetime.now(timezone.utc)
    if not force_refresh and _cache and _cache_expiry and now < _cache_expiry:
        return _cache

    client = client or get_supabase_client()
    settings_obj = _load_settings(client)
    _cache = settings_obj
    _cache_expiry = now + _CACHE_TTL
    return settings_obj


def clear_platform_settings_cache() -> None:
    global _cache, _cache_expiry
    _cache = None
    _cache_expiry = None


def update_platform_settings(
    payload: PlatformPaymentSettingsUpdateRequest,
    actor_id: Optional[str],
    client: Optional[Client] = None,
) -> PlatformPaymentSettings:
    client = client or get_supabase_client()
    now_iso = datetime.now(timezone.utc).isoformat()

    entries = [
        {
            "key": KEY_EXCHANGE_RATE,
            "value": payload.exchange_rate_usd_jpy,
            "updated_at": now_iso,
            "updated_by": actor_id,
        },
        {
            "key": KEY_SPREAD,
            "value": payload.spread_jpy,
            "updated_at": now_iso,
            "updated_by": actor_id,
        },
        {
            "key": KEY_FEE_PERCENT,
            "value": payload.platform_fee_percent,
            "updated_at": now_iso,
            "updated_by": actor_id,
        },
    ]

    try:
        client.table(SETTINGS_TABLE).upsert(entries).execute()
    except APIError as exc:  # pragma: no cover - depends on Supabase state
        message = getattr(exc, "message", "") or str(exc)
        if "platform_settings" not in message:
            raise

        logger.warning("platform_settings table missing during update; attempting bootstrap")
        try:
            _bootstrap_settings_table()
        except RuntimeError as bootstrap_exc:
            logger.error("Platform settings bootstrap failed during update: %s", bootstrap_exc)
            raise RuntimeError(
                "決済設定テーブルが存在しないため更新に失敗しました。"
                " Supabase Dashboard で migrations/20251105_add_platform_settings.sql を実行するか、"
                "SUPABASE_SERVICE_ROLE_KEY を設定してください。"
            ) from bootstrap_exc

        client.table(SETTINGS_TABLE).upsert(entries).execute()

    clear_platform_settings_cache()
    return get_platform_settings(client=client)
