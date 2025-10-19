from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings
from app.models.landing_page import (
    LPCreateRequest,
    LPUpdateRequest,
    LPResponse,
    LPDetailResponse,
    LPListResponse,
    StepCreateRequest,
    StepUpdateRequest,
    LPStepResponse,
    CTACreateRequest,
    CTAUpdateRequest,
    CTAResponse
)
from typing import Optional, List, Dict
import re
import secrets
import jwt

router = APIRouter(prefix="/lp", tags=["landing_pages"])
security = HTTPBearer()

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

def get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    """トークンから現在のユーザーIDを取得"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
            )
        return user_id
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました"
        )

def normalize_slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        value = secrets.token_hex(3)
    return value[:100]

def generate_unique_slug(supabase: Client, base_slug: str) -> str:
    slug = base_slug
    for _ in range(10):
        existing = supabase.table("landing_pages").select("id").eq("slug", slug).execute()
        if not existing.data:
            return slug
        suffix = secrets.token_hex(2)
        trimmed = base_slug[: (100 - len(suffix) - 1)] if len(base_slug) + len(suffix) + 1 > 100 else base_slug
        slug = f"{trimmed}-{suffix}"
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="スラッグの生成に失敗しました"
    )

@router.post("", response_model=LPResponse, status_code=status.HTTP_201_CREATED)
async def create_lp(
    data: LPCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    LP作成
    
    - **title**: LPタイトル
    - **slug**: URL用スラッグ（一意）
    - **swipe_direction**: vertical（縦）または horizontal（横）
    - **is_fullscreen**: 全画面表示するか
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        normalized_slug = normalize_slug(data.slug)

        existing_response = supabase.table("landing_pages").select("*").eq("slug", normalized_slug).execute()

        if existing_response.data:
            existing_lp = existing_response.data[0]
            if existing_lp.get("seller_id") == user_id:
                update_payload = {
                    "title": data.title,
                    "swipe_direction": data.swipe_direction,
                    "is_fullscreen": data.is_fullscreen,
                    "show_swipe_hint": data.show_swipe_hint,
                    "fullscreen_media": data.fullscreen_media,
                    "floating_cta": data.floating_cta,
                    "product_id": data.product_id,
                    "meta_title": data.meta_title,
                    "meta_description": data.meta_description,
                    "meta_image_url": data.meta_image_url,
                    "meta_site_name": data.meta_site_name,
                    "custom_theme_hex": data.custom_theme_hex,
                    "custom_theme_shades": data.custom_theme_shades,
                }
                updated = supabase.table("landing_pages").update(update_payload).eq("id", existing_lp["id"]).execute()
                if not updated.data:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="既存LPの更新に失敗しました"
                    )
                return LPResponse(**updated.data[0])
            normalized_slug = generate_unique_slug(supabase, normalized_slug)
        
        # LP作成
        lp_data = {
            "seller_id": user_id,
            "title": data.title,
            "slug": normalized_slug,
            "swipe_direction": data.swipe_direction,
            "is_fullscreen": data.is_fullscreen,
            "status": "draft",
            "product_id": data.product_id,
            "show_swipe_hint": data.show_swipe_hint,
            "fullscreen_media": data.fullscreen_media,
            "floating_cta": data.floating_cta,
            "meta_title": data.meta_title,
            "meta_description": data.meta_description,
            "meta_image_url": data.meta_image_url,
            "meta_site_name": data.meta_site_name,
            "custom_theme_hex": data.custom_theme_hex,
            "custom_theme_shades": data.custom_theme_shades,
        }
        
        response = supabase.table("landing_pages").insert(lp_data).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LP作成に失敗しました"
            )
        
        return LPResponse(**response.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LP作成エラー: {str(e)}"
        )

@router.get("", response_model=LPListResponse)
async def get_lps(
    status_filter: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    自分のLP一覧取得
    
    - **status**: フィルター（draft, published, archived）
    - **limit**: 取得件数（デフォルト: 20）
    - **offset**: オフセット（デフォルト: 0）
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # クエリ構築
        query = supabase.table("landing_pages").select("*").eq("seller_id", user_id)
        
        if status_filter:
            query = query.eq("status", status_filter)
        
        # 件数取得（フィルター適用後）
        count_response = query.execute()
        total = len(count_response.data) if count_response.data else 0
        
        # データ取得（ページネーション）
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()
        
        lps = [LPResponse(**lp) for lp in response.data] if response.data else []
        
        return LPListResponse(
            data=lps,
            total=total,
            limit=limit,
            offset=offset
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LP一覧取得エラー: {str(e)}"
        )

@router.get("/{lp_id}", response_model=LPDetailResponse)
async def get_lp(
    lp_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    LP詳細取得（ステップとCTA含む）
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP取得
        lp_response = supabase.table("landing_pages").select("*").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        lp_data = lp_response.data
        
        # ステップ取得
        steps_response = supabase.table("lp_steps").select("*").eq("lp_id", lp_id).order("step_order").execute()
        steps = []
        if steps_response.data:
            for step in steps_response.data:
                if not step.get("block_type"):
                    step["block_type"] = (step.get("content_data") or {}).get("block_type")
                steps.append(LPStepResponse(**step))
        
        # CTA取得
        ctas_response = supabase.table("lp_ctas").select("*").eq("lp_id", lp_id).execute()
        ctas = [CTAResponse(**cta) for cta in ctas_response.data] if ctas_response.data else []
        
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
            detail=f"LP詳細取得エラー: {str(e)}"
        )

@router.put("/{lp_id}", response_model=LPResponse)
async def update_lp(
    lp_id: str,
    data: LPUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    LP更新
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("*").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        # 更新データ準備
        update_data = data.model_dump(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="更新するデータがありません"
            )
        
        # 更新
        response = supabase.table("landing_pages").update(update_data).eq("id", lp_id).execute()
        
        return LPResponse(**response.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LP更新エラー: {str(e)}"
        )

@router.delete("/{lp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lp(
    lp_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    LP削除
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        # 削除（カスケード削除でステップとCTAも削除される）
        supabase.table("landing_pages").delete().eq("id", lp_id).execute()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LP削除エラー: {str(e)}"
        )

@router.post("/{lp_id}/publish", response_model=LPResponse)
async def publish_lp(
    lp_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    LP公開
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("*").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        # 公開
        response = supabase.table("landing_pages").update({"status": "published"}).eq("id", lp_id).execute()
        
        return LPResponse(**response.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LP公開エラー: {str(e)}"
        )

@router.post("/{lp_id}/duplicate", response_model=LPDetailResponse, status_code=status.HTTP_201_CREATED)
async def duplicate_lp(
    lp_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """既存LPを複製してドラフトとして作成"""
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()

        # 元のLPを取得（本人のもののみ）
        lp_response = supabase.table("landing_pages").select("*").eq("id", lp_id).eq("seller_id", user_id).single().execute()

        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )

        original_lp = lp_response.data

        # 新しいスラッグとタイトルを生成
        base_slug = f"{original_lp.get('slug', '')}-copy" if original_lp.get("slug") else secrets.token_hex(3)
        new_slug = generate_unique_slug(supabase, base_slug)

        original_title = original_lp.get("title") or "コピーLP"
        new_title = f"{original_title} (コピー)"
        if len(new_title) > 255:
            new_title = new_title[:255]

        # 新しいLPレコードを作成
        new_lp_data = {
            "seller_id": user_id,
            "title": new_title,
            "slug": new_slug,
            "swipe_direction": original_lp.get("swipe_direction", "vertical"),
            "is_fullscreen": original_lp.get("is_fullscreen", False),
            "status": "draft",
            "product_id": None,
            "show_swipe_hint": original_lp.get("show_swipe_hint", False),
            "fullscreen_media": original_lp.get("fullscreen_media", False),
            "floating_cta": original_lp.get("floating_cta", False),
            "meta_title": original_lp.get("meta_title"),
            "meta_description": original_lp.get("meta_description"),
            "meta_image_url": original_lp.get("meta_image_url"),
            "meta_site_name": original_lp.get("meta_site_name"),
            "custom_theme_hex": original_lp.get("custom_theme_hex"),
            "custom_theme_shades": original_lp.get("custom_theme_shades"),
            "total_views": 0,
            "total_cta_clicks": 0,
        }

        insert_response = supabase.table("landing_pages").insert(new_lp_data).execute()

        if not insert_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LPの複製に失敗しました"
            )

        new_lp = insert_response.data[0]
        new_lp_id = new_lp["id"]

        # ステップを複製
        steps_response = supabase.table("lp_steps").select("*").eq("lp_id", lp_id).order("step_order").execute()
        old_step_ids: List[str] = []
        new_steps_payload: List[dict] = []

        for step in steps_response.data or []:
            old_step_ids.append(step["id"])
            new_steps_payload.append({
                "lp_id": new_lp_id,
                "step_order": step.get("step_order", 0),
                "image_url": step.get("image_url"),
                "video_url": step.get("video_url"),
                "animation_type": step.get("animation_type"),
                "block_type": step.get("block_type"),
                "content_data": step.get("content_data"),
                "step_views": 0,
                "step_exits": 0,
            })

        step_id_map: Dict[str, str] = {}
        inserted_steps: List[dict] = []

        if new_steps_payload:
            new_steps_response = supabase.table("lp_steps").insert(new_steps_payload).execute()
            inserted_steps = new_steps_response.data or []
            if len(inserted_steps) != len(old_step_ids):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="ステップの複製に失敗しました"
                )
            for old_id, new_step in zip(old_step_ids, inserted_steps):
                step_id_map[old_id] = new_step["id"]

        # CTAを複製
        ctas_response = supabase.table("lp_ctas").select("*").eq("lp_id", lp_id).execute()
        new_ctas_payload: List[dict] = []

        for cta in ctas_response.data or []:
            original_step_id = cta.get("step_id")
            new_step_id = step_id_map.get(original_step_id) if original_step_id else None
            new_ctas_payload.append({
                "lp_id": new_lp_id,
                "step_id": new_step_id,
                "cta_type": cta.get("cta_type"),
                "button_image_url": cta.get("button_image_url"),
                "button_position": cta.get("button_position"),
                "link_url": cta.get("link_url"),
                "is_required": cta.get("is_required", False),
                "click_count": 0,
            })

        inserted_ctas: List[dict] = []
        if new_ctas_payload:
            new_ctas_response = supabase.table("lp_ctas").insert(new_ctas_payload).execute()
            inserted_ctas = new_ctas_response.data or []

        # 最新のLP情報を取得しレスポンスを組み立て
        latest_lp_response = supabase.table("landing_pages").select("*").eq("id", new_lp_id).single().execute()
        latest_lp = latest_lp_response.data or new_lp

        steps_for_response = inserted_steps if inserted_steps else []
        if not steps_for_response and new_steps_payload:
            # 返却が空の場合は再取得
            steps_refresh = supabase.table("lp_steps").select("*").eq("lp_id", new_lp_id).order("step_order").execute()
            steps_for_response = steps_refresh.data or []

        ctas_for_response = inserted_ctas if inserted_ctas else []
        if not ctas_for_response and new_ctas_payload:
            ctas_refresh = supabase.table("lp_ctas").select("*").eq("lp_id", new_lp_id).execute()
            ctas_for_response = ctas_refresh.data or []

        steps_models: List[LPStepResponse] = []
        for step in steps_for_response:
            if not step.get("block_type"):
                step["block_type"] = (step.get("content_data") or {}).get("block_type")
            steps_models.append(LPStepResponse(**step))

        cta_models = [CTAResponse(**cta) for cta in ctas_for_response]

        public_url = f"{settings.frontend_url}/{latest_lp.get('slug', new_slug)}"

        return LPDetailResponse(
            **latest_lp,
            steps=steps_models,
            ctas=cta_models,
            public_url=public_url
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LP複製エラー: {str(e)}"
        )

# ==================== ステップ管理 ====================

@router.post("/{lp_id}/steps", response_model=LPStepResponse, status_code=status.HTTP_201_CREATED)
async def create_step(
    lp_id: str,
    data: StepCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    LPステップ追加
    
    - **step_order**: ステップ順序（0から開始）
    - **image_url**: 画像URL（テンプレートブロックでは省略可）
    - **video_url**: 動画URL（オプション）
    - **animation_type**: アニメーションタイプ（オプション）
    - **block_type**: ブロックタイプ（例: countdown-1）
    - **content_data**: ブロックコンテンツ（JSON）
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認（自分のLPか確認）
        lp_response = supabase.table("landing_pages").select("id").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        # ステップ作成
        step_data = {
            "lp_id": lp_id,
            "step_order": data.step_order
        }

        optional_fields = data.model_dump(
            exclude_unset=True,
            exclude_none=True,
            exclude={"step_order"}
        )

        block_type = optional_fields.pop("block_type", None)
        content_data = optional_fields.get("content_data") or {}
        if block_type:
            content_data = dict(content_data)
            content_data["block_type"] = block_type
            # DB の block_type カラムにも保存する（重要！）
            step_data["block_type"] = block_type
        optional_fields["content_data"] = content_data

        step_data.update(optional_fields)

        if "image_url" not in step_data:
            step_data["image_url"] = ""
        
        response = supabase.table("lp_steps").insert(step_data).execute()

        error = getattr(response, "error", None)
        if error:
            message = getattr(error, "message", None)
            if isinstance(error, dict):
                message = error.get("message")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"ステップ作成に失敗しました: {message or str(error)}"
            )

        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ステップ作成に失敗しました"
            )

        created_step = response.data[0]
        if not created_step.get("block_type"):
            created_step["block_type"] = (created_step.get("content_data") or {}).get("block_type")

        return LPStepResponse(**created_step)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ステップ作成エラー: {str(e)}"
        )

@router.put("/{lp_id}/steps/{step_id}", response_model=LPStepResponse)
async def update_step(
    lp_id: str,
    step_id: str,
    data: StepUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    ステップ更新
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        # ステップ存在確認
        step_response = supabase.table("lp_steps").select("*").eq("id", step_id).eq("lp_id", lp_id).single().execute()
        
        if not step_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ステップが見つかりません"
            )
        
        # 更新データ準備
        update_data = data.model_dump(exclude_unset=True, exclude_none=True)

        block_type = update_data.pop("block_type", None)
        if block_type is not None:
            content_data = update_data.get("content_data") or step_response.data.get("content_data") or {}
            content_data = dict(content_data)
            content_data["block_type"] = block_type
            # DB の block_type カラムにも保存する（重要！）
            update_data["block_type"] = block_type
            update_data["content_data"] = content_data
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="更新するデータがありません"
            )
        
        # 更新
        response = supabase.table("lp_steps").update(update_data).eq("id", step_id).execute()

        error = getattr(response, "error", None)
        if error:
            message = getattr(error, "message", None)
            if isinstance(error, dict):
                message = error.get("message")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"ステップ更新に失敗しました: {message or str(error)}"
            )

        updated_step = response.data[0]
        if not updated_step.get("block_type"):
            updated_step["block_type"] = (updated_step.get("content_data") or {}).get("block_type")

        return LPStepResponse(**updated_step)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ステップ更新エラー: {str(e)}"
        )

@router.delete("/{lp_id}/steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_step(
    lp_id: str,
    step_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    ステップ削除
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        # ステップ削除
        supabase.table("lp_steps").delete().eq("id", step_id).eq("lp_id", lp_id).execute()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ステップ削除エラー: {str(e)}"
        )

# ==================== CTA管理 ====================

@router.post("/{lp_id}/ctas", response_model=CTAResponse, status_code=status.HTTP_201_CREATED)
async def create_cta(
    lp_id: str,
    data: CTACreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    CTA追加
    
    - **step_id**: 特定ステップに紐付ける場合のID（null=全体共通）
    - **cta_type**: link, form, product, newsletter, line
    - **button_image_url**: ボタン画像URL
    - **button_position**: top, bottom, floating
    - **link_url**: リンク先URL
    - **is_required**: 次へ進むのに必須か
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # LP存在確認
        lp_response = supabase.table("landing_pages").select("id").eq("id", lp_id).eq("seller_id", user_id).single().execute()
        
        if not lp_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LPが見つかりません"
            )
        
        # CTA作成
        cta_data = {
            "lp_id": lp_id,
            "step_id": data.step_id,
            "cta_type": data.cta_type,
            "button_image_url": data.button_image_url,
            "button_position": data.button_position,
            "link_url": data.link_url,
            "is_required": data.is_required
        }
        
        response = supabase.table("lp_ctas").insert(cta_data).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="CTA作成に失敗しました"
            )
        
        return CTAResponse(**response.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CTA作成エラー: {str(e)}"
        )

@router.put("/ctas/{cta_id}", response_model=CTAResponse)
async def update_cta(
    cta_id: str,
    data: CTAUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    CTA更新
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # CTA取得して、LPの所有者確認
        cta_response = supabase.table("lp_ctas").select("*, landing_pages!inner(seller_id)").eq("id", cta_id).single().execute()
        
        if not cta_response.data or cta_response.data.get("landing_pages", {}).get("seller_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="CTAが見つかりません"
            )
        
        # 更新データ準備
        update_data = data.model_dump(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="更新するデータがありません"
            )
        
        # 更新
        response = supabase.table("lp_ctas").update(update_data).eq("id", cta_id).execute()
        
        return CTAResponse(**response.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CTA更新エラー: {str(e)}"
        )

@router.delete("/ctas/{cta_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cta(
    cta_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    CTA削除
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # CTA取得して、LPの所有者確認
        cta_response = supabase.table("lp_ctas").select("*, landing_pages!inner(seller_id)").eq("id", cta_id).single().execute()
        
        if not cta_response.data or cta_response.data.get("landing_pages", {}).get("seller_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="CTAが見つかりません"
            )
        
        # 削除
        supabase.table("lp_ctas").delete().eq("id", cta_id).execute()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CTA削除エラー: {str(e)}"
        )
