from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from supabase import Client


def load_billing_profile(supabase: Client, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a persisted billing profile for the given user."""

    try:
        response = (
            supabase
            .table("billing_profiles")
            .select(
                "full_name, email, phone_number, postal_code, prefecture, city, "
                "address_line1, address_line2, company_name, country_code"
            )
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception:  # pragma: no cover - defensive fallback
        return None

    data = response.data if response else None
    if not data:
        return None

    return {
        "full_name": _normalize_str(data.get("full_name")),
        "email": _normalize_str(data.get("email")),
        "phone_number": _normalize_str(data.get("phone_number")),
        "postal_code": _normalize_str(data.get("postal_code")),
        "prefecture": _normalize_str(data.get("prefecture")),
        "city": _normalize_str(data.get("city")),
        "address_line1": _normalize_str(data.get("address_line1")),
        "address_line2": _normalize_str(data.get("address_line2")),
        "company_name": _normalize_str(data.get("company_name")),
        "country_code": _normalize_str(data.get("country_code")),
    }


def build_payer_details(
    user_record: Dict[str, Any],
    billing_profile: Optional[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    """Compose payer payload fields for ONE.lat checkout requests."""

    email = _normalize_str(user_record.get("email"))
    username = _normalize_str(user_record.get("username"))

    if billing_profile:
        email = billing_profile.get("email") or email
        full_name = billing_profile.get("full_name")
        phone_number = billing_profile.get("phone_number")
    else:
        full_name = None
        phone_number = None

    first_name, last_name = _split_name(full_name)

    if not first_name:
        first_name = username or (email.split("@", 1)[0] if email else None)

    return {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": phone_number,
    }


def _split_name(full_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not full_name:
        return None, None

    normalized = full_name.strip()
    if not normalized:
        return None, None

    parts = normalized.split()
    if len(parts) == 1:
        return parts[0], None

    first = parts[0]
    last = " ".join(parts[1:])
    return first, last


def _normalize_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)
