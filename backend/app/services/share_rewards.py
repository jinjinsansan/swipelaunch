"""
NOTEシェア報酬システム
インフォプレナーへの即時ポイント付与
"""

from typing import Dict, Any, Optional
from supabase import Client
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ShareRewardService:
    """シェア報酬管理"""
    
    def __init__(self, supabase: Client):
        self.supabase = supabase
    
    async def get_current_reward_rate(self) -> int:
        """
        現在の報酬レート取得
        
        Returns:
            1シェアあたりのポイント数
        """
        try:
            response = self.supabase.table("share_reward_settings").select(
                "points_per_share"
            ).order(
                "updated_at", desc=True
            ).limit(1).execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]["points_per_share"]
            
            # デフォルト: 1P
            return 1
        
        except Exception as e:
            logger.error(f"Failed to get reward rate: {e}")
            return 1
    
    async def grant_share_reward(
        self,
        author_id: str,
        note_id: str,
        shared_by_user_id: str,
        points_amount: int,
        share_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        シェア報酬を即時付与
        
        Args:
            author_id: 著者ID（報酬受取人）
            note_id: NOTE ID
            shared_by_user_id: シェアしたユーザーID
            points_amount: 付与ポイント数
            share_id: シェアレコードID
        
        Returns:
            トランザクション情報
        """
        try:
            # 1. point_transactionsレコード作成
            transaction_data = {
                "user_id": author_id,
                "transaction_type": "note_share_reward",
                "amount": points_amount,
                "related_note_id": note_id,
                "description": f"NOTEシェア報酬（シェアユーザー: {shared_by_user_id}）"
            }
            
            transaction_response = self.supabase.table("point_transactions").insert(
                transaction_data
            ).execute()
            
            if not transaction_response.data:
                raise Exception("Failed to create point transaction")
            
            # 2. users.point_balance を更新
            # 現在の残高を取得
            user_response = self.supabase.table("users").select(
                "point_balance"
            ).eq(
                "id", author_id
            ).single().execute()
            
            if not user_response.data:
                raise Exception(f"User not found: {author_id}")
            
            current_balance = user_response.data.get("point_balance", 0) or 0
            new_balance = current_balance + points_amount
            
            # 残高更新
            update_response = self.supabase.table("users").update({
                "point_balance": new_balance
            }).eq(
                "id", author_id
            ).execute()
            
            if not update_response.data:
                raise Exception("Failed to update user point balance")
            
            # 3. note_shares の points_rewarded フラグを更新
            self.supabase.table("note_shares").update({
                "points_rewarded": True,
                "points_amount": points_amount
            }).eq(
                "id", share_id
            ).execute()
            
            logger.info(
                f"Share reward granted: author_id={author_id}, "
                f"points={points_amount}, note_id={note_id}, "
                f"new_balance={new_balance}"
            )
            
            transaction_record = (
                transaction_response.data[0] 
                if isinstance(transaction_response.data, list) 
                else transaction_response.data
            )
            
            return {
                "transaction_id": transaction_record.get("id"),
                "author_id": author_id,
                "points_granted": points_amount,
                "new_balance": new_balance,
                "note_id": note_id
            }
        
        except Exception as e:
            logger.error(f"Failed to grant share reward: {e}")
            return None
    
    async def update_reward_rate(
        self,
        new_rate: int,
        updated_by_user_id: str
    ) -> bool:
        """
        報酬レート更新（管理者専用）
        
        Args:
            new_rate: 新しいレート（1シェア = N ポイント）
            updated_by_user_id: 更新者の管理者ID
        
        Returns:
            成功: True
        """
        if new_rate < 0:
            logger.error(f"Invalid reward rate: {new_rate}")
            return False
        
        try:
            # 新しい設定レコードを追加（履歴として残す）
            setting_data = {
                "points_per_share": new_rate,
                "updated_by": updated_by_user_id
            }
            
            response = self.supabase.table("share_reward_settings").insert(
                setting_data
            ).execute()
            
            if response.data:
                logger.info(
                    f"Reward rate updated: new_rate={new_rate}, "
                    f"updated_by={updated_by_user_id}"
                )
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Failed to update reward rate: {e}")
            return False
    
    async def get_reward_history(self, limit: int = 10) -> list:
        """
        報酬レート変更履歴取得
        
        Args:
            limit: 取得件数
        
        Returns:
            変更履歴リスト
        """
        try:
            response = self.supabase.table("share_reward_settings").select(
                "id, points_per_share, updated_by, updated_at"
            ).order(
                "updated_at", desc=True
            ).limit(limit).execute()
            
            return response.data if response.data else []
        
        except Exception as e:
            logger.error(f"Failed to get reward history: {e}")
            return []
