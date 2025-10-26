from fastapi import APIRouter, HTTPException, status, Query
from supabase import create_client, Client
from app.config import settings
from app.models.landing_page import LPDetailResponse, LPStepResponse, CTAResponse
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

router = APIRouter(prefix="/public", tags=["public"])

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

class ViewRecordRequest(BaseModel):
    session_id: Optional[str] = None


class StepViewRequest(BaseModel):
    step_id: str
    session_id: Optional[str] = None


class CTAClickRequest(BaseModel):
    cta_id: Optional[str] = None
    step_id: Optional[str] = None
    session_id: Optional[str] = None

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
        
        return LPDetailResponse(
            **lp_data,
            steps=steps,
            ctas=ctas,
            public_url=public_url
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
