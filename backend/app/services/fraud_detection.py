"""
NOTEシェア不正検知システム
短時間大量シェア、同一IP、疑わしいアカウントパターンを検出
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
from supabase import Client
import logging

logger = logging.getLogger(__name__)


class FraudDetector:
    """不正シェア検知"""
    
    # 閾値設定
    RAPID_SHARE_THRESHOLD = 10  # 1時間以内の最大シェア数
    RAPID_SHARE_WINDOW_HOURS = 1
    
    MIN_ACCOUNT_AGE_DAYS = 7  # Xアカウント最小年齢（日）
    MIN_FOLLOWERS_COUNT = 10  # 最小フォロワー数
    
    def __init__(self, supabase: Client):
        self.supabase = supabase
    
    async def check_rapid_shares(self, user_id: str) -> bool:
        """
        短時間大量シェアチェック
        
        Args:
            user_id: ユーザーID
        
        Returns:
            True: 疑わしい（閾値超過）
        """
        time_threshold = datetime.utcnow() - timedelta(hours=self.RAPID_SHARE_WINDOW_HOURS)
        
        try:
            response = self.supabase.table("note_shares").select("id").eq(
                "user_id", user_id
            ).gte(
                "shared_at", time_threshold.isoformat()
            ).execute()
            
            share_count = len(response.data) if response.data else 0
            
            if share_count >= self.RAPID_SHARE_THRESHOLD:
                logger.warning(
                    f"Rapid shares detected: user_id={user_id}, "
                    f"count={share_count} in {self.RAPID_SHARE_WINDOW_HOURS}h"
                )
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Failed to check rapid shares: {e}")
            return False
    
    async def check_ip_pattern(self, ip_address: str) -> bool:
        """
        同一IPパターンチェック
        
        Args:
            ip_address: IPアドレス
        
        Returns:
            True: 疑わしい（複数アカウントから同一IP）
        """
        if not ip_address:
            return False
        
        try:
            # 過去24時間以内に同じIPから複数の異なるユーザーがシェアしているか
            time_threshold = datetime.utcnow() - timedelta(hours=24)
            
            response = self.supabase.table("note_shares").select(
                "user_id"
            ).eq(
                "ip_address", ip_address
            ).gte(
                "shared_at", time_threshold.isoformat()
            ).execute()
            
            if response.data:
                unique_users = set(item["user_id"] for item in response.data)
                if len(unique_users) >= 3:  # 3人以上
                    logger.warning(
                        f"Suspicious IP pattern: ip={ip_address}, "
                        f"unique_users={len(unique_users)}"
                    )
                    return True
            
            return False
        
        except Exception as e:
            logger.error(f"Failed to check IP pattern: {e}")
            return False
    
    async def check_account_age(self, account_created_at: Optional[str]) -> bool:
        """
        Xアカウント年齢チェック
        
        Args:
            account_created_at: アカウント作成日時（ISO形式）
        
        Returns:
            True: 疑わしい（作成から規定日数未満）
        """
        if not account_created_at:
            return False
        
        try:
            created_date = datetime.fromisoformat(account_created_at.replace('Z', '+00:00'))
            account_age_days = (datetime.utcnow() - created_date.replace(tzinfo=None)).days
            
            if account_age_days < self.MIN_ACCOUNT_AGE_DAYS:
                logger.warning(
                    f"New account detected: age={account_age_days} days "
                    f"(threshold={self.MIN_ACCOUNT_AGE_DAYS})"
                )
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Failed to check account age: {e}")
            return False
    
    async def check_followers_count(self, followers_count: int) -> bool:
        """
        フォロワー数チェック
        
        Args:
            followers_count: フォロワー数
        
        Returns:
            True: 疑わしい（フォロワー数が極端に少ない）
        """
        if followers_count < self.MIN_FOLLOWERS_COUNT:
            logger.warning(
                f"Low followers count: {followers_count} "
                f"(threshold={self.MIN_FOLLOWERS_COUNT})"
            )
            return True
        
        return False
    
    async def calculate_fraud_score(self, share_data: Dict[str, Any]) -> Tuple[int, str]:
        """
        不正スコア計算
        
        Args:
            share_data: {
                "user_id": str,
                "ip_address": str,
                "account_created_at": str,
                "followers_count": int,
                "is_verified": bool
            }
        
        Returns:
            (score: 0-100, severity: "low"|"medium"|"high")
        """
        score = 0
        reasons = []
        
        # 1. 短時間大量シェア: +40点
        if await self.check_rapid_shares(share_data.get("user_id", "")):
            score += 40
            reasons.append("rapid_shares")
        
        # 2. 同一IPパターン: +30点
        if await self.check_ip_pattern(share_data.get("ip_address", "")):
            score += 30
            reasons.append("same_ip")
        
        # 3. アカウント年齢: +20点
        if await self.check_account_age(share_data.get("account_created_at")):
            score += 20
            reasons.append("new_account")
        
        # 4. フォロワー数: +10点
        if await self.check_followers_count(share_data.get("followers_count", 0)):
            score += 10
            reasons.append("low_followers")
        
        # 5. X認証バッジなし（軽減要素）: 既に他で考慮
        
        # スコアに基づく重要度判定
        if score >= 50:
            severity = "high"
        elif score >= 30:
            severity = "medium"
        else:
            severity = "low"
        
        logger.info(
            f"Fraud score calculated: score={score}, severity={severity}, "
            f"reasons={reasons}"
        )
        
        return (score, severity)
    
    async def create_alert(
        self,
        alert_type: str,
        note_share_id: str,
        note_id: str,
        user_id: str,
        severity: str,
        description: str
    ) -> Optional[Dict[str, Any]]:
        """
        不正アラート生成
        
        Args:
            alert_type: アラートタイプ
            note_share_id: シェアID
            note_id: NOTE ID
            user_id: ユーザーID
            severity: 重要度
            description: 説明
        
        Returns:
            作成されたアラート情報
        """
        try:
            alert_data = {
                "alert_type": alert_type,
                "note_share_id": note_share_id,
                "note_id": note_id,
                "user_id": user_id,
                "severity": severity,
                "description": description,
                "resolved": False
            }
            
            response = self.supabase.table("share_fraud_alerts").insert(
                alert_data
            ).execute()
            
            if response.data:
                logger.warning(
                    f"Fraud alert created: type={alert_type}, "
                    f"severity={severity}, note_share_id={note_share_id}"
                )
                return response.data[0] if isinstance(response.data, list) else response.data
            
            return None
        
        except Exception as e:
            logger.error(f"Failed to create fraud alert: {e}")
            return None
    
    async def should_block_reward(self, fraud_score: int) -> bool:
        """
        不正スコアに基づいてポイント報酬をブロックすべきか判定
        
        Args:
            fraud_score: 不正スコア (0-100)
        
        Returns:
            True: 報酬をブロック（要手動承認）
        """
        # スコア50以上は報酬を保留
        return fraud_score >= 50
