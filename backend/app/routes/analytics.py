from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings
from app.models.analytics import (
    LPAnalyticsResponse,
    StepFunnelData,
    CTAClickData,
    EventLogResponse,
    EventLogListResponse
)
from typing import Optional
from datetime import datetime

from app.utils.auth import decode_access_token

router = APIRouter(prefix="/lp", tags=["analytics"])
security = HTTPBearer()

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

def get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    """トークンから現在のユーザーIDを取得"""
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
            )
        return user_id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました"
        )

@router.get("/{lp_id}/analytics", response_model=LPAnalyticsResponse)
async def get_lp_analytics(
    lp_id: str,
    date_from: Optional[str] = Query(None, description="開始日 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="終了日 (YYYY-MM-DD)"),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    LP統計取得
    
    - **lp_id**: LP ID
    - **date_from**: 開始日（オプション）
    - **date_to**: 終了日（オプション）
    
    Returns:
        LP統計情報（閲覧数、クリック数、ファネル分析）
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認と所有者チェック
        lp_response = supabase.table("landing_pages").select("*").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        lp_data = lp_response.data
        
        # ステップ情報取得
        steps_response = supabase.table("lp_steps").select("*").eq("lp_id", lp_id).order("step_order").execute()
        steps = steps_response.data if steps_response.data else []
        
        # ステップファネル計算
        step_funnel = []
        for i, step in enumerate(steps):
            step_views = max(0, step.get("step_views", 0))
            step_exits = max(0, step.get("step_exits", 0))
            
            # 次のステップへの遷移率を計算
            if i < len(steps) - 1:
                next_step_views = max(0, steps[i + 1].get("step_views", 0))
                conversion_rate = (next_step_views / step_views * 100) if step_views > 0 else 0
            else:
                # 最後のステップはCTAクリック率
                cta_clicks = max(0, lp_data.get("total_cta_clicks", 0))
                conversion_rate = (cta_clicks / step_views * 100) if step_views > 0 else 0
            
            # conversion_rateを0-100の範囲にクランプ
            conversion_rate = max(0.0, min(100.0, conversion_rate))
            
            step_funnel.append(StepFunnelData(
                step_id=step["id"],
                step_order=step["step_order"],
                step_views=step_views,
                step_exits=step_exits,
                conversion_rate=round(conversion_rate, 2)
            ))
        
        # CTA別クリック数取得
        ctas_response = supabase.table("lp_ctas").select("id, step_id, cta_type, click_count").eq("lp_id", lp_id).execute()
        cta_lookup = {cta["id"]: cta for cta in (ctas_response.data or [])}

        cta_events_query = (
            supabase
            .table("lp_event_logs")
            .select("cta_id, step_id")
            .eq("lp_id", lp_id)
            .eq("event_type", "cta_click")
        )

        if date_from:
            cta_events_query = cta_events_query.gte("created_at", date_from)
        if date_to:
            cta_events_query = cta_events_query.lte("created_at", date_to)

        cta_events_response = cta_events_query.execute()

        aggregated_cta: dict[str, dict] = {}
        for event in (cta_events_response.data or []):
            event_cta_id = event.get("cta_id")
            event_step_id = event.get("step_id")
            key = event_cta_id or f"step:{event_step_id or 'unknown'}"
            entry = aggregated_cta.setdefault(key, {
                "cta_id": event_cta_id,
                "step_id": event_step_id,
                "cta_type": None,
                "click_count": 0,
            })
            entry["click_count"] += 1

        for cta_id, cta in cta_lookup.items():
            entry = aggregated_cta.get(cta_id)
            if entry:
                entry["cta_type"] = entry.get("cta_type") or cta.get("cta_type")
                if entry.get("step_id") is None:
                    entry["step_id"] = cta.get("step_id")
            else:
                aggregated_cta[cta_id] = {
                    "cta_id": cta_id,
                    "step_id": cta.get("step_id"),
                    "cta_type": cta.get("cta_type"),
                    "click_count": cta.get("click_count", 0) if not date_from and not date_to else 0,
                }

        for value in aggregated_cta.values():
            if not value.get("cta_type"):
                value["cta_type"] = "inferred"

        cta_clicks_raw = sorted(aggregated_cta.values(), key=lambda item: item.get("click_count", 0), reverse=True)
        cta_clicks = [CTAClickData(**item) for item in cta_clicks_raw]
        
        # ユニークセッション数を計算（session_idが記録されている場合）
        events_query = supabase.table("lp_event_logs").select("session_id").eq("lp_id", lp_id).eq("event_type", "view")
        
        if date_from:
            events_query = events_query.gte("created_at", date_from)
        if date_to:
            events_query = events_query.lte("created_at", date_to)
        
        events_response = events_query.execute()
        
        # ユニークセッション数（session_idが記録されている場合のみ）
        sessions = set()
        if events_response.data:
            for event in events_response.data:
                if event.get("session_id"):
                    sessions.add(event["session_id"])
        
        total_sessions = len(sessions) if sessions else lp_data.get("total_views", 0)
        
        # CTA変換率計算
        total_views = lp_data.get("total_views", 0)
        total_cta_clicks = lp_data.get("total_cta_clicks", 0)
        cta_conversion_rate = (total_cta_clicks / total_views * 100) if total_views > 0 else 0
        
        # 期間のパース
        period_start = datetime.fromisoformat(date_from) if date_from else None
        period_end = datetime.fromisoformat(date_to) if date_to else None
        
        return LPAnalyticsResponse(
            lp_id=lp_data["id"],
            title=lp_data["title"],
            slug=lp_data["slug"],
            status=lp_data["status"],
            total_views=total_views,
            total_cta_clicks=total_cta_clicks,
            total_sessions=total_sessions,
            cta_conversion_rate=round(cta_conversion_rate, 2),
            step_funnel=step_funnel,
            cta_clicks=cta_clicks,
            period_start=period_start,
            period_end=period_end
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析データ取得エラー: {str(e)}"
        )

@router.get("/{lp_id}/events", response_model=EventLogListResponse)
async def get_lp_events(
    lp_id: str,
    event_type: Optional[str] = Query(None, description="イベントタイプでフィルター"),
    date_from: Optional[str] = Query(None, description="開始日時 (ISO 8601)"),
    date_to: Optional[str] = Query(None, description="終了日時 (ISO 8601)"),
    limit: int = Query(50, ge=1, le=500, description="取得件数"),
    offset: int = Query(0, ge=0, description="オフセット"),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    イベントログ取得
    
    - **lp_id**: LP ID
    - **event_type**: イベントタイプでフィルター（view, step_view, step_exit, cta_click）
    - **date_from**: 開始日時（ISO 8601形式）
    - **date_to**: 終了日時（ISO 8601形式）
    - **limit**: 取得件数（デフォルト: 50、最大: 500）
    - **offset**: オフセット（デフォルト: 0）
    
    Returns:
        イベントログのリスト
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認と所有者チェック
        lp_response = supabase.table("landing_pages").select("id").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        # クエリ構築
        query = supabase.table("lp_event_logs").select("*").eq("lp_id", lp_id)
        
        # フィルター適用
        if event_type:
            query = query.eq("event_type", event_type)
        
        if date_from:
            query = query.gte("created_at", date_from)
        
        if date_to:
            query = query.lte("created_at", date_to)
        
        # 件数取得（フィルター適用後）
        count_response = query.execute()
        total = len(count_response.data) if count_response.data else 0
        
        # データ取得（ページネーション + 降順）
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()
        
        events = [EventLogResponse(**event) for event in response.data] if response.data else []
        
        # 期間のパース
        period_start = datetime.fromisoformat(date_from) if date_from else None
        period_end = datetime.fromisoformat(date_to) if date_to else None
        
        return EventLogListResponse(
            data=events,
            total=total,
            limit=limit,
            offset=offset,
            event_type_filter=event_type,
            date_from=period_start,
            date_to=period_end
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"イベントログ取得エラー: {str(e)}"
        )
