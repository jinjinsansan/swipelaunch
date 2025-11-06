from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from fastapi import HTTPException, status

ROLE_PRIORITY: Dict[str, int] = {
    "manager": 1,
    "owner": 2,
}


@dataclass
class TeamContext:
    team_id: str
    owner_id: str
    role: str


def _role_priority(role: Optional[str]) -> int:
    if not role:
        return 0
    return ROLE_PRIORITY.get(role, ROLE_PRIORITY.get("manager", 0))


def _fetch_team_rows(supabase, team_ids: Sequence[str]) -> Dict[str, Dict[str, str]]:
    if not team_ids:
        return {}

    response = (
        supabase
        .table("teams")
        .select("id, owner_user_id")
        .in_("id", list(dict.fromkeys(team_ids)))
        .execute()
    )
    rows = response.data or []
    return {row.get("id"): row for row in rows if row.get("id")}


def _fetch_memberships(supabase, user_id: str) -> List[TeamContext]:
    memberships_resp = (
        supabase
        .table("team_members")
        .select("team_id, role, status")
        .eq("user_id", user_id)
        .execute()
    )

    membership_rows = memberships_resp.data or []
    active_rows = [row for row in membership_rows if (row.get("status") or "active") == "active"]
    team_map = _fetch_team_rows(supabase, [row.get("team_id") for row in active_rows if row.get("team_id")])

    contexts: List[TeamContext] = []
    for row in active_rows:
        team_id = row.get("team_id")
        if not team_id:
            continue
        team = team_map.get(team_id)
        owner_id = (team or {}).get("owner_user_id")
        if not owner_id:
            continue
        role = row.get("role") or "manager"
        contexts.append(TeamContext(team_id=team_id, owner_id=owner_id, role=role))

    # Ensure owner membership exists even if team_members not populated yet
    owner_team_resp = (
        supabase
        .table("teams")
        .select("id, owner_user_id")
        .eq("owner_user_id", user_id)
        .maybe_single()
        .execute()
    )
    owner_team = getattr(owner_team_resp, "data", None) or None
    if owner_team:
        team_id = owner_team.get("id")
        if team_id and all(ctx.team_id != team_id for ctx in contexts):
            contexts.append(TeamContext(team_id=team_id, owner_id=user_id, role="owner"))

    return contexts


def _select_context_for_team(
    contexts: Iterable[TeamContext],
    team_id: Optional[str],
    owner_id: Optional[str],
) -> Optional[TeamContext]:
    contexts = list(contexts)

    if team_id:
        for ctx in contexts:
            if ctx.team_id == team_id:
                return ctx
        return None

    if owner_id:
        for ctx in contexts:
            if ctx.owner_id == owner_id:
                return ctx
        return None

    if len(contexts) == 1:
        return contexts[0]

    owner_contexts = [ctx for ctx in contexts if ctx.role == "owner"]
    if len(owner_contexts) == 1:
        return owner_contexts[0]

    return None


def _require_role(context: Optional[TeamContext], required_role: str) -> TeamContext:
    if not context:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="チーム権限がありません")

    if _role_priority(context.role) < _role_priority(required_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="操作権限が不足しています")

    return context


def resolve_team_context(
    supabase,
    user_id: str,
    *,
    required_role: str = "manager",
    team_id: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> TeamContext:
    """Resolve team context for the acting user.

    If ``team_id`` or ``owner_id`` are provided, attempt to locate a matching membership.
    Otherwise, attempt to infer a unique membership. Raises HTTP 400 when ambiguous.
    """

    contexts = _fetch_memberships(supabase, user_id)
    context = _select_context_for_team(contexts, team_id=team_id, owner_id=owner_id)

    if not context:
        if team_id or owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="対象チームが見つかりません")
        if not contexts:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="有効なチームに所属していません")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="複数のチームに所属しているためチームIDの指定が必要です")

    normalized_role = required_role if required_role in ROLE_PRIORITY else "manager"
    return _require_role(context, normalized_role)


def ensure_owner_access(
    supabase,
    actor_user_id: str,
    owner_user_id: str,
    *,
    required_role: str,
) -> TeamContext:
    """Ensure the acting user has the required role for the team owned by ``owner_user_id``."""

    if actor_user_id == owner_user_id:
        return TeamContext(team_id=_ensure_owner_team_id(supabase, owner_user_id), owner_id=owner_user_id, role="owner")

    contexts = _fetch_memberships(supabase, actor_user_id)
    context = _select_context_for_team(contexts, team_id=None, owner_id=owner_user_id)
    return _require_role(context, required_role)


def _ensure_owner_team_id(supabase, owner_user_id: str) -> str:
    response = (
        supabase
        .table("teams")
        .select("id")
        .eq("owner_user_id", owner_user_id)
        .maybe_single()
        .execute()
    )
    team = getattr(response, "data", None) or None
    team_id: Optional[str] = None
    if isinstance(team, dict):
        team_id = team.get("id")
    if not team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="チームが見つかりません")
    return team_id


def get_accessible_owner_ids(
    supabase,
    user_id: str,
    *,
    minimum_role: str = "manager",
) -> List[str]:
    contexts = _fetch_memberships(supabase, user_id)
    normalized_role = minimum_role if minimum_role in ROLE_PRIORITY else "manager"
    return [ctx.owner_id for ctx in contexts if _role_priority(ctx.role) >= _role_priority(normalized_role)]


def assert_manager_or_owner(
    supabase,
    actor_user_id: str,
    owner_user_id: str,
) -> TeamContext:
    return ensure_owner_access(supabase, actor_user_id, owner_user_id, required_role="manager")


def assert_editor_or_owner(
    supabase,
    actor_user_id: str,
    owner_user_id: str,
) -> TeamContext:
    return ensure_owner_access(supabase, actor_user_id, owner_user_id, required_role="manager")


def assert_viewer(
    supabase,
    actor_user_id: str,
    owner_user_id: str,
) -> TeamContext:
    return ensure_owner_access(supabase, actor_user_id, owner_user_id, required_role="manager")


def assert_owner(
    supabase,
    actor_user_id: str,
    owner_user_id: str,
) -> TeamContext:
    return ensure_owner_access(supabase, actor_user_id, owner_user_id, required_role="owner")


def list_team_memberships(supabase, user_id: str) -> List[TeamContext]:
    return _fetch_memberships(supabase, user_id)
