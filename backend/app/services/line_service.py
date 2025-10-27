import hmac
import hashlib
import base64
import logging
from typing import Optional, Dict, Any
import httpx
from datetime import datetime, timezone

from app.config import settings, get_supabase_client
from app.models.line import LINEUserProfile

logger = logging.getLogger(__name__)

class LINEService:
    """LINE Messaging API サービス"""
    
    LINE_API_BASE = "https://api.line.me/v2"
    CHANNEL_ACCESS_TOKEN = "HUxJxjtHptIwQBxQqt70iCJIm/Xwz27zMWcSON4c3oS6Nt+I3TcP7K6Iql4YiQs8DlRddJGVli8b7mIF84zcZmK7Tr7Mt7bo9jyqOe7iWWNAGBGzrORER80V7Cnd5dpA4hLGdD8kEaY2aQrxUAwmegdB04t89/1O/w1cDnyilFU="
    CHANNEL_SECRET = "e3c0e09aaa0389b3d6836381a4924883"
    
    @staticmethod
    def verify_signature(body: bytes, signature: str) -> bool:
        """
        LINE Webhookの署名を検証
        
        Args:
            body: リクエストボディ（バイト列）
            signature: X-Line-Signatureヘッダーの値
        
        Returns:
            署名が正しければTrue
        """
        try:
            hash_digest = hmac.new(
                LINEService.CHANNEL_SECRET.encode('utf-8'),
                body,
                hashlib.sha256
            ).digest()
            
            expected_signature = base64.b64encode(hash_digest).decode('utf-8')
            
            is_valid = hmac.compare_digest(signature, expected_signature)
            
            if is_valid:
                logger.info("✅ LINE signature verified")
            else:
                logger.warning("❌ LINE signature verification failed")
            
            return is_valid
        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False
    
    @staticmethod
    async def get_user_profile(line_user_id: str) -> Optional[LINEUserProfile]:
        """
        LINE ユーザープロフィールを取得
        
        Args:
            line_user_id: LINEユーザーID
        
        Returns:
            ユーザープロフィール、または取得失敗時はNone
        """
        try:
            url = f"{LINEService.LINE_API_BASE}/bot/profile/{line_user_id}"
            headers = {
                "Authorization": f"Bearer {LINEService.CHANNEL_ACCESS_TOKEN}"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                
                profile_data = response.json()
                logger.info(f"✅ Retrieved LINE profile for user: {line_user_id}")
                
                return LINEUserProfile(**profile_data)
        
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error getting LINE profile: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error getting LINE profile: {e}")
            return None
    
    @staticmethod
    async def get_bonus_settings() -> Optional[Dict[str, Any]]:
        """
        現在のLINEボーナス設定を取得
        
        Returns:
            設定データ、または取得失敗時はNone
        """
        try:
            supabase = get_supabase_client()
            response = supabase.table('line_bonus_settings').select('*').limit(1).execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]
            
            return None
        except Exception as e:
            logger.error(f"Error getting bonus settings: {e}")
            return None
    
    @staticmethod
    async def find_user_by_line_id(line_user_id: str) -> Optional[str]:
        """
        LINE IDから既存のユーザーIDを検索
        
        Args:
            line_user_id: LINEユーザーID
        
        Returns:
            ユーザーID、または見つからない場合はNone
        """
        try:
            supabase = get_supabase_client()
            response = supabase.table('line_connections').select('user_id').eq('line_user_id', line_user_id).limit(1).execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]['user_id']
            
            return None
        except Exception as e:
            logger.error(f"Error finding user by LINE ID: {e}")
            return None
    
    @staticmethod
    async def create_line_connection(
        user_id: str,
        line_user_id: str,
        display_name: Optional[str] = None,
        picture_url: Optional[str] = None,
        status_message: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        LINE連携を作成
        
        Args:
            user_id: ユーザーID
            line_user_id: LINEユーザーID
            display_name: 表示名
            picture_url: プロフィール画像URL
            status_message: ステータスメッセージ
        
        Returns:
            作成された連携データ、または失敗時はNone
        """
        try:
            supabase = get_supabase_client()
            
            connection_data = {
                'user_id': user_id,
                'line_user_id': line_user_id,
                'display_name': display_name,
                'picture_url': picture_url,
                'status_message': status_message,
                'connected_at': datetime.now(timezone.utc).isoformat(),
                'bonus_awarded': False
            }
            
            response = supabase.table('line_connections').insert(connection_data).execute()
            
            if response.data and len(response.data) > 0:
                logger.info(f"✅ LINE connection created for user: {user_id}")
                return response.data[0]
            
            return None
        except Exception as e:
            logger.error(f"Error creating LINE connection: {e}")
            return None
    
    @staticmethod
    async def award_bonus_points(user_id: str, line_user_id: str) -> bool:
        """
        LINE連携ボーナスポイントを付与
        
        Args:
            user_id: ユーザーID
            line_user_id: LINEユーザーID
        
        Returns:
            成功時True、失敗時False
        """
        try:
            supabase = get_supabase_client()
            
            # ボーナス設定を取得
            settings = await LINEService.get_bonus_settings()
            if not settings or not settings.get('is_enabled'):
                logger.warning("LINE bonus is disabled or settings not found")
                return False
            
            bonus_points = settings.get('bonus_points', 300)
            
            # 既にボーナスを受け取っているかチェック
            connection_check = supabase.table('line_connections').select('bonus_awarded').eq('user_id', user_id).limit(1).execute()
            
            if connection_check.data and len(connection_check.data) > 0:
                if connection_check.data[0].get('bonus_awarded'):
                    logger.warning(f"Bonus already awarded for user: {user_id}")
                    return False
            
            # ポイントを付与
            user_response = supabase.table('users').select('point_balance').eq('id', user_id).limit(1).execute()
            
            if not user_response.data or len(user_response.data) == 0:
                logger.error(f"User not found: {user_id}")
                return False
            
            current_balance = user_response.data[0].get('point_balance', 0)
            new_balance = current_balance + bonus_points
            
            # ユーザーのポイント残高を更新
            supabase.table('users').update({
                'point_balance': new_balance
            }).eq('id', user_id).execute()
            
            # ポイント取引履歴を記録
            supabase.table('point_transactions').insert({
                'user_id': user_id,
                'amount': bonus_points,
                'transaction_type': 'bonus',
                'description': f'LINE公式アカウント連携ボーナス',
                'status': 'completed'
            }).execute()
            
            # LINE連携にボーナス付与を記録
            supabase.table('line_connections').update({
                'bonus_awarded': True,
                'bonus_points': bonus_points,
                'bonus_awarded_at': datetime.now(timezone.utc).isoformat()
            }).eq('line_user_id', line_user_id).execute()
            
            logger.info(f"✅ Awarded {bonus_points} points to user: {user_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error awarding bonus points: {e}")
            return False
    
    @staticmethod
    async def send_reply_message(reply_token: str, message_text: str) -> bool:
        """
        LINEにリプライメッセージを送信
        
        Args:
            reply_token: リプライトークン
            message_text: メッセージ本文
        
        Returns:
            成功時True
        """
        try:
            url = f"{LINEService.LINE_API_BASE}/bot/message/reply"
            headers = {
                "Authorization": f"Bearer {LINEService.CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "replyToken": reply_token,
                "messages": [
                    {
                        "type": "text",
                        "text": message_text
                    }
                ]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                
                logger.info("✅ Reply message sent successfully")
                return True
        
        except Exception as e:
            logger.error(f"Error sending reply message: {e}")
            return False
