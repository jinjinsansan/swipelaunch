from fastapi import APIRouter, HTTPException, status, Query, Header
from supabase import create_client, Client
from app.config import settings
from app.models.landing_page import LPDetailResponse, LPStepResponse, CTAResponse, LinkedSalonInfo
from app.models.required_actions import (
    EmailSubmitRequest,
    LineConfirmRequest,
    ActionCompletionResponse,
    RequiredActionInfo,
    RequiredActionsStatusResponse
)
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.constants.subscription_plans import SUBSCRIPTION_PLANS, get_subscription_plan, get_subscription_plan_by_id
from app.models.salons import (
    SalonPublicListItem,
    SalonPublicListResponse,
    SalonPublicOwner,
    SalonPublicPlan,
    SalonPublicResponse,
)
from app.utils.auth import decode_access_token

router = APIRouter(prefix="/public", tags=["public"])

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)


def _build_linked_salon_info(supabase: Client, salon_id: Optional[str]) -> Optional[LinkedSalonInfo]:
    if not salon_id:
        return None

    try:
        salon_response = (
            supabase
            .table("salons")
            .select("id, title, thumbnail_url, owner_id, is_active")
            .eq("id", salon_id)
            .execute()
        )

        salon_data = salon_response.data
        
        if not salon_data or len(salon_data) == 0:
            return None
        
        salon_data = salon_data[0]
        if salon_data.get("is_active") is False:
            return None
    except Exception:
        return None

    owner_username: Optional[str] = None
    owner_id = salon_data.get("owner_id")
    if owner_id:
        try:
            owner_response = (
                supabase
                .table("users")
                .select("username")
                .eq("id", owner_id)
                .execute()
            )
            if owner_response.data and len(owner_response.data) > 0:
                owner_username = owner_response.data[0].get("username")
        except Exception:
            pass

    return LinkedSalonInfo(
        id=salon_data.get("id"),
        title=salon_data.get("title") or "",
        thumbnail_url=salon_data.get("thumbnail_url"),
        owner_username=owner_username,
        public_path=f"/salons/{salon_data.get('id')}/public",
    )

class ViewRecordRequest(BaseModel):
    session_id: Optional[str] = None


class StepViewRequest(BaseModel):
    step_id: str
    session_id: Optional[str] = None


class CTAClickRequest(BaseModel):
    cta_id: Optional[str] = None
    step_id: Optional[str] = None
    session_id: Optional[str] = None


class PublicUserProfileResponse(BaseModel):
    username: str
    bio: Optional[str] = None
    sns_url: Optional[str] = None
    line_url: Optional[str] = None
    profile_image_url: Optional[str] = None


def _extract_user_id(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    token = authorization.strip()
    if not token:
        return None
    if " " in token:
        scheme, value = token.split(" ", 1)
        if scheme.lower() != "bearer":
            value = token
        else:
            token = value
    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    user_id = payload.get("sub") if isinstance(payload, dict) else None
    return user_id if isinstance(user_id, str) else None


SALON_FILTER_PRICE_BRACKETS = {
    "under_1000": (0, 1000),
    "1000_3000": (1000, 3000),
    "3000_5000": (3000, 5000),
    "over_5000": (5000, None),
}


def _resolve_public_plan(supabase: Client, subscription_plan_id: Optional[str]) -> SalonPublicPlan:
    plan_id = str(subscription_plan_id or "")
    
    # Try to find plan by ID first (ONE.lat subscription_plan_id)
    cached_plan = get_subscription_plan_by_id(plan_id)
    if cached_plan:
        return SalonPublicPlan(
            key=cached_plan.key,
            label=cached_plan.label,
            points=cached_plan.points,
            usd_amount=cached_plan.usd_amount,
            subscription_plan_id=cached_plan.subscription_plan_id,
        )
    
    # Fallback: try to find by plan_key (for legacy data)
    cached_plan = get_subscription_plan(plan_id)
    if cached_plan:
        return SalonPublicPlan(
            key=cached_plan.key,
            label=cached_plan.label,
            points=cached_plan.points,
            usd_amount=cached_plan.usd_amount,
            subscription_plan_id=cached_plan.subscription_plan_id,
        )

    fallback_key = "custom"
    fallback_label = "プラン情報未設定"
    fallback_points = 0
    fallback_usd = 0.0

    if plan_id:
        try:
            response = (
                supabase
                .table("subscription_plans")
                .select("plan_key, label, points_per_cycle, usd_amount, points")
                .eq("id", plan_id)
                .single()
                .execute()
            )
            record = response.data or {}
            if record:
                fallback_key = record.get("plan_key") or fallback_key
                fallback_label = record.get("label") or fallback_label
                points_value = record.get("points_per_cycle") or record.get("points")
                if isinstance(points_value, (int, float)):
                    fallback_points = int(points_value)
                usd_value = record.get("usd_amount")
                if isinstance(usd_value, (int, float)):
                    fallback_usd = float(usd_value)
        except Exception:
            # フォールバック情報が取得できない場合でも静かに続行
            pass

    return SalonPublicPlan(
        key=fallback_key,
        label=fallback_label,
        points=fallback_points,
        usd_amount=fallback_usd,
        subscription_plan_id=plan_id,
    )


@router.get("/salons/{salon_id}", response_model=SalonPublicResponse)
async def get_public_salon_detail(salon_id: str, authorization: Optional[str] = Header(default=None)):
    """公開サロン詳細を取得（認証任意）。"""

    supabase = get_supabase()
    salon_response = (
        supabase
        .table("salons")
        .select("id, owner_id, title, description, thumbnail_url, subscription_plan_id, is_active, created_at, updated_at")
        .eq("id", salon_id)
        .single()
        .execute()
    )

    salon_record = salon_response.data
    if not salon_record or not bool(salon_record.get("is_active", False)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")

    plan_payload = _resolve_public_plan(supabase, salon_record.get("subscription_plan_id"))

    owner_response = (
        supabase
        .table("users")
        .select("id, username, profile_image_url")
        .eq("id", salon_record.get("owner_id"))
        .single()
        .execute()
    )
    owner_record = owner_response.data
    if not owner_record or not owner_record.get("username"):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="サロンオーナー情報が取得できません")

    member_count_resp = (
        supabase
        .table("salon_memberships")
        .select("id", count="exact")
        .eq("salon_id", salon_id)
        .eq("status", "ACTIVE")
        .execute()
    )
    member_count = getattr(member_count_resp, "count", 0) or 0

    viewer_id = _extract_user_id(authorization)
    is_member = False
    membership_status: Optional[str] = None

    if viewer_id:
        if viewer_id == owner_record.get("id"):
            is_member = True
            membership_status = "OWNER"
        else:
            membership_resp = (
                supabase
                .table("salon_memberships")
                .select("status")
                .eq("salon_id", salon_id)
                .eq("user_id", viewer_id)
                .limit(1)
                .execute()
            )
            for membership in membership_resp.data or []:
                status_value = str(membership.get("status", "")).upper() or None
                membership_status = status_value
                if status_value == "ACTIVE":
                    is_member = True
                    break

    owner = SalonPublicOwner(
        id=owner_record.get("id"),
        username=owner_record.get("username"),
        display_name=owner_record.get("display_name"),
        profile_image_url=owner_record.get("profile_image_url"),
    )

    return SalonPublicResponse(
        id=salon_record.get("id"),
        title=salon_record.get("title", ""),
        description=salon_record.get("description"),
        thumbnail_url=salon_record.get("thumbnail_url"),
        is_active=bool(salon_record.get("is_active", False)),
        owner=owner,
        plan=plan_payload,
        member_count=member_count,
        is_member=is_member,
        membership_status=membership_status,
        created_at=salon_record.get("created_at"),
        updated_at=salon_record.get("updated_at"),
    )


@router.get("/salons", response_model=SalonPublicListResponse)
async def list_public_salons(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    category: Optional[str] = Query(None, description="カテゴリフィルタ"),
    price_range: Optional[str] = Query(None, description="価格帯フィルタ (under_1000 / 1000_3000 / 3000_5000 / over_5000)"),
    seller_username: Optional[str] = Query(None, description="販売者（オーナー）ユーザー名で絞り込み"),
    sort: Optional[str] = Query("new", description="ソートキー (new / popular)"),
):
    supabase = get_supabase()

    query = (
        supabase
        .table("salons")
        .select("id, owner_id, title, description, thumbnail_url, subscription_plan_id, created_at")
        .eq("is_active", True)
    )

    if category:
        query = query.eq("category", category)

    if seller_username:
        owner_resp = (
            supabase
            .table("users")
            .select("id")
            .eq("username", seller_username)
            .single()
            .execute()
        )
        owner_id = owner_resp.data.get("id") if owner_resp.data else None
        if not owner_id:
            return SalonPublicListResponse(data=[], total=0, limit=limit, offset=offset)
        query = query.eq("owner_id", owner_id)

    if price_range:
        bracket = SALON_FILTER_PRICE_BRACKETS.get(price_range)
        if bracket:
            min_points, max_points = bracket
            allowed_ids = [
                plan.subscription_plan_id
                for plan in SUBSCRIPTION_PLANS
                if (min_points is None or plan.points >= min_points)
                and (max_points is None or plan.points < max_points)
            ]
            if allowed_ids:
                query = query.in_("subscription_plan_id", allowed_ids)
            else:
                return SalonPublicListResponse(data=[], total=0, limit=limit, offset=offset)

    response = query.execute()
    rows = response.data or []

    salon_ids = [row.get("id") for row in rows if row.get("id")]
    owner_ids = {row.get("owner_id") for row in rows if row.get("owner_id")}

    owners: dict[str, dict[str, Optional[str]]] = {}
    if owner_ids:
        owners_resp = (
            supabase
            .table("users")
            .select("id, username, profile_image_url")
            .in_("id", list(owner_ids))
            .execute()
        )
        for record in owners_resp.data or []:
            owners[str(record.get("id"))] = {
                "username": record.get("username"),
                "display_name": record.get("display_name"),
                "profile_image_url": record.get("profile_image_url"),
            }

    member_counts: dict[str, int] = {}
    if salon_ids:
        memberships_resp = (
            supabase
            .table("salon_memberships")
            .select("salon_id, status")
            .in_("salon_id", salon_ids)
            .execute()
        )
        for membership in memberships_resp.data or []:
            if str(membership.get("status", "")).upper() != "ACTIVE":
                continue
            salon_id = membership.get("salon_id")
            if salon_id:
                member_counts[salon_id] = member_counts.get(salon_id, 0) + 1

    items: List[SalonPublicListItem] = []
    for row in rows:
        owner = owners.get(str(row.get("owner_id")))
        if not owner or not owner.get("username"):
            continue

        plan_payload = _resolve_public_plan(supabase, row.get("subscription_plan_id"))

        items.append(
            SalonPublicListItem(
                id=row.get("id"),
                title=row.get("title", ""),
                description=row.get("description"),
                thumbnail_url=row.get("thumbnail_url"),
                category=None,  # Category field removed from salons table
                owner_username=owner.get("username", ""),
                owner_display_name=owner.get("display_name"),
                owner_profile_image_url=owner.get("profile_image_url"),
                plan_label=plan_payload.label,
                plan_points=plan_payload.points,
                plan_usd_amount=plan_payload.usd_amount,
                created_at=row.get("created_at"),
            )
        )

    if sort == "popular":
        items.sort(key=lambda item: member_counts.get(item.id, 0), reverse=True)
    else:
        items.sort(key=lambda item: item.created_at, reverse=True)

    total = len(items)
    paged_items = items[offset : offset + limit]

    return SalonPublicListResponse(data=paged_items, total=total, limit=limit, offset=offset)


@router.get("/users/{username}", response_model=PublicUserProfileResponse)
async def get_public_user_profile(username: str):
    """公開プロフィール情報を取得"""
    try:
        supabase = get_supabase()

        user_response = (
            supabase
            .table("users")
            .select("username, bio, sns_url, line_url, profile_image_url")
            .eq("username", username)
            .single()
            .execute()
        )

        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません"
            )

        return PublicUserProfileResponse(**user_response.data)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ユーザープロフィール取得エラー: {str(e)}"
        )

@router.get("/{slug}", response_model=LPDetailResponse)
async def get_public_lp(
    slug: str,
    track_view: bool = Query(False, description="閲覧数をトラッキングし、ビューイベントを記録するか"),
    session_id: Optional[str] = Query(None, description="ビューイベントに紐づけるセッションID"),
):
    """
    公開LP取得（認証不要）
    
    - **slug**: LPのスラッグ
    
    Returns:
        LP詳細情報（ステップとCTA含む）
    """
    try:
        supabase = get_supabase()
        
        # スラッグでLP取得（公開中のみ、ユーザー情報をJOIN）
        lp_response = supabase.table("landing_pages").select("*, owner:users!seller_id(username, email)").eq("slug", slug).eq("status", "published").single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません。まだ公開されていないか、URLが間違っています。"
            )
        
        lp_data = lp_response.data
        lp_id = lp_data["id"]
        
        # ステップ取得・フィルタリング
        steps_response = supabase.table("lp_steps").select("*").eq("lp_id", lp_id).order("step_order").execute()
        steps = []
        if steps_response.data:
            for step in steps_response.data:
                # block_typeを正規化：content_dataから抽出を試みる
                if not step.get("block_type"):
                    step["block_type"] = (step.get("content_data") or {}).get("block_type")
                
                # ステップの有効性をチェック
                block_type = step.get("block_type")
                image_url = step.get("image_url")
                
                # 有効なblock_type: 空でない文字列
                has_valid_block = isinstance(block_type, str) and len(block_type.strip()) > 0
                # 有効なimage_url: 空でない文字列
                has_valid_image = isinstance(image_url, str) and len(image_url.strip()) > 0
                
                # block_typeか image_urlのいずれかが有効なステップのみを追加
                if has_valid_block or has_valid_image:
                    steps.append(LPStepResponse(**step))
        
        has_sticky_cta = any(
            isinstance(step.block_type, str) and step.block_type.strip() == "sticky-cta-1"
            for step in steps
        )
        if has_sticky_cta and not lp_data.get("floating_cta"):
            lp_data["floating_cta"] = True

        # CTA取得
        ctas_response = supabase.table("lp_ctas").select("*").eq("lp_id", lp_id).execute()
        ctas = [CTAResponse(**cta) for cta in ctas_response.data] if ctas_response.data else []

        if track_view:
            should_track_view = True
            if session_id:
                existing_view = (
                    supabase
                    .table("lp_event_logs")
                    .select("id")
                    .eq("lp_id", lp_id)
                    .eq("event_type", "view")
                    .eq("session_id", session_id)
                    .limit(1)
                    .execute()
                )
                if existing_view.data:
                    should_track_view = False

            if should_track_view:
                current_views = lp_data.get("total_views", 0)
                updated = supabase.table("landing_pages").update({"total_views": current_views + 1}).eq("id", lp_id).execute()
                if updated.data:
                    lp_data["total_views"] = updated.data[0].get("total_views", current_views + 1)
                else:
                    lp_data["total_views"] = current_views + 1

                analytics_data = {
                    "lp_id": lp_id,
                    "event_type": "view",
                    "session_id": session_id,
                    "user_agent": None,
                    "ip_address": None,
                }
                supabase.table("lp_event_logs").insert(analytics_data).execute()

        # 公開URL生成
        public_url = f"{settings.frontend_url}/{lp_data['slug']}"

        linked_salon = _build_linked_salon_info(supabase, lp_data.get("salon_id"))
        
        return LPDetailResponse(
            **lp_data,
            steps=steps,
            ctas=ctas,
            public_url=public_url,
            linked_salon=linked_salon
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LP取得エラー: {str(e)}"
        )

@router.post("/{slug}/step-view", status_code=status.HTTP_204_NO_CONTENT)
async def record_step_view(slug: str, data: StepViewRequest):
    """
    ステップ閲覧を記録
    
    - **slug**: LPのスラッグ
    - **step_id**: 閲覧したステップのID
    - **session_id**: セッションID（オプション）
    """
    try:
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("slug", slug).eq("status", "published").single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        lp_id = lp_response.data["id"]
        
        # ステップ存在確認
        step_response = supabase.table("lp_steps").select("step_views").eq("id", data.step_id).eq("lp_id", lp_id).single().execute()
        
        if not step_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ステップが見つかりません"
            )
        
        if data.session_id:
            existing_event = (
                supabase
                .table("lp_event_logs")
                .select("id")
                .eq("lp_id", lp_id)
                .eq("step_id", data.step_id)
                .eq("event_type", "step_view")
                .eq("session_id", data.session_id)
                .limit(1)
                .execute()
            )
            if existing_event.data:
                return None

        # ステップの閲覧数を+1
        current_views = step_response.data.get("step_views", 0)
        supabase.table("lp_steps").update({"step_views": current_views + 1}).eq("id", data.step_id).execute()
        
        # lp_event_logsテーブルに記録
        analytics_data = {
            "lp_id": lp_id,
            "step_id": data.step_id,
            "event_type": "step_view",
            "session_id": data.session_id,
        }
        supabase.table("lp_event_logs").insert(analytics_data).execute()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ステップ閲覧記録エラー: {str(e)}"
        )

@router.post("/{slug}/step-exit", status_code=status.HTTP_204_NO_CONTENT)
async def record_step_exit(slug: str, data: StepViewRequest):
    """
    ステップ離脱を記録
    
    - **slug**: LPのスラッグ
    - **step_id**: 離脱したステップのID
    - **session_id**: セッションID（オプション）
    """
    try:
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("slug", slug).eq("status", "published").single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        lp_id = lp_response.data["id"]
        
        # ステップ存在確認
        step_response = supabase.table("lp_steps").select("step_exits").eq("id", data.step_id).eq("lp_id", lp_id).single().execute()
        
        if not step_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ステップが見つかりません"
            )
        
        if data.session_id:
            existing_event = (
                supabase
                .table("lp_event_logs")
                .select("id")
                .eq("lp_id", lp_id)
                .eq("step_id", data.step_id)
                .eq("event_type", "step_exit")
                .eq("session_id", data.session_id)
                .limit(1)
                .execute()
            )
            if existing_event.data:
                return None

        # ステップの離脱数を+1
        current_exits = step_response.data.get("step_exits", 0)
        supabase.table("lp_steps").update({"step_exits": current_exits + 1}).eq("id", data.step_id).execute()
        
        # lp_event_logsテーブルに記録
        analytics_data = {
            "lp_id": lp_id,
            "step_id": data.step_id,
            "event_type": "step_exit",
            "session_id": data.session_id,
        }
        supabase.table("lp_event_logs").insert(analytics_data).execute()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ステップ離脱記録エラー: {str(e)}"
        )

@router.post("/{slug}/cta-click", status_code=status.HTTP_204_NO_CONTENT)
async def record_cta_click(slug: str, data: CTAClickRequest):
    """
    CTAクリックを記録
    
    - **slug**: LPのスラッグ
    - **cta_id**: クリックされたCTAのID（存在しない場合は省略可）
    - **step_id**: CTAが配置されているステップID（cta_idが無い場合に必須）
    - **session_id**: セッションID（オプション）
    """
    try:
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id, total_cta_clicks").eq("slug", slug).eq("status", "published").single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        lp_id = lp_response.data["id"]
        
        resolved_cta_id: Optional[str] = None
        resolved_step_id: Optional[str] = data.step_id

        if data.cta_id:
            cta_response = (
                supabase
                .table("lp_ctas")
                .select("id, step_id, click_count")
                .eq("id", data.cta_id)
                .eq("lp_id", lp_id)
                .single()
                .execute()
            )

            if not cta_response.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="CTAが見つかりません"
                )

            resolved_cta_id = cta_response.data.get("id")
            if not resolved_step_id:
                resolved_step_id = cta_response.data.get("step_id")

            current_clicks = cta_response.data.get("click_count", 0)
            supabase.table("lp_ctas").update({"click_count": current_clicks + 1}).eq("id", resolved_cta_id).execute()

        elif resolved_step_id:
            step_check = (
                supabase
                .table("lp_steps")
                .select("id")
                .eq("id", resolved_step_id)
                .eq("lp_id", lp_id)
                .single()
                .execute()
            )
            if not step_check.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="ステップが見つかりません"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cta_id もしくは step_id のいずれかを指定してください"
            )

        if data.session_id:
            duplicate_query = (
                supabase
                .table("lp_event_logs")
                .select("id")
                .eq("lp_id", lp_id)
                .eq("event_type", "cta_click")
                .eq("session_id", data.session_id)
            )
            if resolved_cta_id:
                duplicate_query = duplicate_query.eq("cta_id", resolved_cta_id)
            if resolved_step_id:
                duplicate_query = duplicate_query.eq("step_id", resolved_step_id)

            duplicate_event = duplicate_query.limit(1).execute()
            if duplicate_event.data:
                return None

        current_total_clicks = lp_response.data.get("total_cta_clicks", 0)
        supabase.table("landing_pages").update({"total_cta_clicks": current_total_clicks + 1}).eq("id", lp_id).execute()

        analytics_data = {
            "lp_id": lp_id,
            "cta_id": resolved_cta_id,
            "step_id": resolved_step_id,
            "event_type": "cta_click",
            "session_id": data.session_id,
        }
        supabase.table("lp_event_logs").insert(analytics_data).execute()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CTAクリック記録エラー: {str(e)}"
        )

# ==================== 必須アクション ====================

@router.post("/{slug}/submit-email", response_model=ActionCompletionResponse, status_code=status.HTTP_201_CREATED)
async def submit_email(slug: str, data: EmailSubmitRequest):
    """
    メールアドレス登録
    
    - **slug**: LPのスラッグ
    - **email**: メールアドレス
    - **session_id**: セッションID（オプション）
    """
    try:
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("slug", slug).eq("status", "published").single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        lp_id = lp_response.data["id"]
        
        # メールアクションが設定されているか確認
        action_response = supabase.table("lp_required_actions").select("*").eq("lp_id", lp_id).eq("action_type", "email").execute()
        
        if not action_response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="このLPではメールアドレス登録は不要です"
            )
        
        action = action_response.data[0]
        
        # アクション完了記録
        completion_data = {
            "lp_id": lp_id,
            "action_id": action["id"],
            "session_id": data.session_id,
            "action_type": "email",
            "action_data": {"email": data.email}
        }
        
        completion_response = supabase.table("user_action_completions").insert(completion_data).execute()
        
        if not completion_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="アクション記録に失敗しました"
            )
        
        completion = completion_response.data[0]
        
        return ActionCompletionResponse(
            completion_id=completion["id"],
            action_type="email",
            completed_at=completion["completed_at"],
            message="メールアドレスが登録されました"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"メールアドレス登録エラー: {str(e)}"
        )

@router.post("/{slug}/confirm-line", response_model=ActionCompletionResponse, status_code=status.HTTP_201_CREATED)
async def confirm_line(slug: str, data: LineConfirmRequest):
    """
    LINE友達追加確認
    
    - **slug**: LPのスラッグ
    - **line_user_id**: LINE User ID（オプション）
    - **session_id**: セッションID（オプション）
    """
    try:
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("slug", slug).eq("status", "published").single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        lp_id = lp_response.data["id"]
        
        # LINEアクションが設定されているか確認
        action_response = supabase.table("lp_required_actions").select("*").eq("lp_id", lp_id).eq("action_type", "line").execute()
        
        if not action_response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="このLPではLINE友達追加は不要です"
            )
        
        action = action_response.data[0]
        
        # アクション完了記録
        completion_data = {
            "lp_id": lp_id,
            "action_id": action["id"],
            "session_id": data.session_id,
            "action_type": "line",
            "action_data": {"line_user_id": data.line_user_id} if data.line_user_id else {}
        }
        
        completion_response = supabase.table("user_action_completions").insert(completion_data).execute()
        
        if not completion_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="アクション記録に失敗しました"
            )
        
        completion = completion_response.data[0]
        
        return ActionCompletionResponse(
            completion_id=completion["id"],
            action_type="line",
            completed_at=completion["completed_at"],
            message="LINE友達追加が確認されました"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LINE友達追加確認エラー: {str(e)}"
        )

@router.get("/{slug}/required-actions", response_model=RequiredActionsStatusResponse)
async def get_required_actions_status(
    slug: str,
    session_id: Optional[str] = None
):
    """
    必須アクション状態取得
    
    - **slug**: LPのスラッグ
    - **session_id**: セッションID（オプション）
    
    Returns:
        必須アクションのリストと完了状態
    """
    try:
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("slug", slug).eq("status", "published").single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        lp_id = lp_response.data["id"]
        
        # 必須アクション取得
        actions_response = supabase.table("lp_required_actions").select("*").eq("lp_id", lp_id).eq("is_required", True).execute()
        
        required_actions = [RequiredActionInfo(**action) for action in actions_response.data] if actions_response.data else []
        
        # 完了したアクション取得（session_idで絞り込み）
        completed_actions = []
        if session_id and required_actions:
            completions_response = supabase.table("user_action_completions").select("action_id").eq("lp_id", lp_id).eq("session_id", session_id).execute()
            
            if completions_response.data:
                completed_actions = [comp["action_id"] for comp in completions_response.data]
        
        # 全て完了しているか
        all_completed = len(required_actions) > 0 and len(completed_actions) == len(required_actions)
        
        return RequiredActionsStatusResponse(
            lp_id=lp_id,
            session_id=session_id,
            required_actions=required_actions,
            completed_actions=completed_actions,
            all_completed=all_completed
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"必須アクション状態取得エラー: {str(e)}"
        )
