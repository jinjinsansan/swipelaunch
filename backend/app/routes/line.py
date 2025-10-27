from fastapi import APIRouter, Depends, HTTPException, Request, Header
from typing import Optional
import logging

from app.models.line import (
    LINEWebhookRequest,
    LineConnectionResponse,
    LineBonusSettingsResponse,
    LineBonusSettingsUpdate,
    LineLinkStatusResponse
)
from app.services.line_service import LINEService
from app.routes.auth import get_current_user
from app.config import get_supabase_client

router = APIRouter(prefix="/line", tags=["LINE Integration"])
logger = logging.getLogger(__name__)

@router.post("/webhook")
async def line_webhook(
    request: Request,
    x_line_signature: Optional[str] = Header(None)
):
    """
    LINE Webhook エンドポイント
    
    LINE公式アカウントにユーザーが友達追加した際に呼び出される
    """
    try:
        # リクエストボディを取得
        body = await request.body()
        
        # 署名検証
        if not x_line_signature:
            logger.error("Missing X-Line-Signature header")
            raise HTTPException(status_code=400, detail="Missing signature")
        
        if not LINEService.verify_signature(body, x_line_signature):
            logger.error("Invalid LINE signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # JSONパース
        webhook_data = await request.json()
        webhook_request = LINEWebhookRequest(**webhook_data)
        
        logger.info(f"📩 Received LINE webhook with {len(webhook_request.events)} events")
        
        # イベント処理
        for event in webhook_request.events:
            logger.info(f"Processing event type: {event.type}")
            
            # フォローイベント（友達追加）
            if event.type == "follow":
                line_user_id = event.source.get('userId')
                
                if not line_user_id:
                    logger.warning("No userId in follow event")
                    continue
                
                logger.info(f"👤 User followed: {line_user_id}")
                
                # ユーザープロフィール取得
                profile = await LINEService.get_user_profile(line_user_id)
                
                # 既存ユーザーを検索
                existing_user_id = await LINEService.find_user_by_line_id(line_user_id)
                
                if existing_user_id:
                    logger.info(f"✅ Existing user found: {existing_user_id}")
                    
                    # ボーナスポイント付与
                    bonus_awarded = await LINEService.award_bonus_points(existing_user_id, line_user_id)
                    
                    if bonus_awarded and event.replyToken:
                        settings = await LINEService.get_bonus_settings()
                        bonus_points = settings.get('bonus_points', 300) if settings else 300
                        
                        await LINEService.send_reply_message(
                            event.replyToken,
                            f"🎉 D-swipeに友達追加ありがとうございます！\n{bonus_points}ポイントをプレゼントしました！"
                        )
                else:
                    logger.info(f"ℹ️ New LINE user (not yet registered in D-swipe): {line_user_id}")
                    
                    # D-swipeに未登録のユーザー
                    if event.replyToken:
                        await LINEService.send_reply_message(
                            event.replyToken,
                            "🎉 D-swipeに友達追加ありがとうございます！\n\nD-swipeアカウントと連携すると300ポイントプレゼント🎁\n\nhttps://d-swipe.com からアカウント登録・ログインしてください！"
                        )
            
            # アンフォローイベント
            elif event.type == "unfollow":
                line_user_id = event.source.get('userId')
                logger.info(f"👋 User unfollowed: {line_user_id}")
        
        return {"status": "ok"}
    
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status", response_model=LineLinkStatusResponse)
async def get_line_link_status(current_user: dict = Depends(get_current_user)):
    """
    現在のユーザーのLINE連携状態とボーナス情報を取得
    """
    try:
        user_id = current_user['id']
        supabase = get_supabase_client()
        
        # ボーナス設定を取得
        settings = await LINEService.get_bonus_settings()
        settings_response = LineBonusSettingsResponse(**settings) if settings else None
        
        # LINE連携状態を取得
        connection_response = supabase.table('line_connections').select('*').eq('user_id', user_id).limit(1).execute()
        
        connection = None
        is_connected = False
        
        if connection_response.data and len(connection_response.data) > 0:
            connection_data = connection_response.data[0]
            connection = LineConnectionResponse(**connection_data)
            is_connected = True
        
        return LineLinkStatusResponse(
            is_connected=is_connected,
            bonus_settings=settings_response,
            connection=connection
        )
    
    except Exception as e:
        logger.error(f"Error getting LINE link status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/link")
async def link_line_account(
    line_user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    LINE アカウントを手動で連携
    
    ※ 通常はWebhookで自動連携されるが、手動連携も可能にする
    """
    try:
        user_id = current_user['id']
        
        # 既に連携済みかチェック
        supabase = get_supabase_client()
        existing = supabase.table('line_connections').select('*').eq('user_id', user_id).limit(1).execute()
        
        if existing.data and len(existing.data) > 0:
            raise HTTPException(status_code=400, detail="Already linked to LINE")
        
        # LINEユーザープロフィール取得
        profile = await LINEService.get_user_profile(line_user_id)
        
        if not profile:
            raise HTTPException(status_code=404, detail="LINE user not found")
        
        # LINE連携を作成
        connection = await LINEService.create_line_connection(
            user_id=user_id,
            line_user_id=profile.userId,
            display_name=profile.displayName,
            picture_url=profile.pictureUrl,
            status_message=profile.statusMessage
        )
        
        if not connection:
            raise HTTPException(status_code=500, detail="Failed to create LINE connection")
        
        # ボーナスポイント付与
        await LINEService.award_bonus_points(user_id, line_user_id)
        
        return {"status": "success", "message": "LINE account linked successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error linking LINE account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bonus-settings", response_model=LineBonusSettingsResponse)
async def get_bonus_settings():
    """
    LINEボーナス設定を取得（公開API）
    """
    try:
        settings = await LINEService.get_bonus_settings()
        
        if not settings:
            raise HTTPException(status_code=404, detail="Settings not found")
        
        return LineBonusSettingsResponse(**settings)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting bonus settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/bonus-settings", response_model=LineBonusSettingsResponse)
async def update_bonus_settings(
    update_data: LineBonusSettingsUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    LINEボーナス設定を更新（管理者のみ）
    """
    try:
        # 管理者チェック
        if current_user.get('user_type') != 'admin':
            raise HTTPException(status_code=403, detail="Admin access required")
        
        supabase = get_supabase_client()
        
        # 現在の設定を取得
        current_settings = await LINEService.get_bonus_settings()
        
        if not current_settings:
            raise HTTPException(status_code=404, detail="Settings not found")
        
        # 更新データを準備
        update_dict = update_data.dict(exclude_unset=True)
        
        if not update_dict:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # 設定を更新
        response = supabase.table('line_bonus_settings').update(update_dict).eq('id', current_settings['id']).execute()
        
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=500, detail="Failed to update settings")
        
        logger.info(f"✅ LINE bonus settings updated by admin: {current_user['id']}")
        
        return LineBonusSettingsResponse(**response.data[0])
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating bonus settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
