"""
NOTEシェアシステムのテスト
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

# テスト対象のサービス
from app.services.fraud_detection import FraudDetector
from app.services.share_rewards import ShareRewardService
from app.services.x_api import XAPIClient, XOAuthClient, XAPIError


class TestFraudDetector:
    """不正検知システムのテスト"""
    
    @pytest.fixture
    def mock_supabase(self):
        """モックSupabaseクライアント"""
        mock = MagicMock()
        return mock
    
    @pytest.fixture
    def fraud_detector(self, mock_supabase):
        """FraudDetectorインスタンス"""
        return FraudDetector(mock_supabase)
    
    @pytest.mark.asyncio
    async def test_check_rapid_shares_normal(self, fraud_detector, mock_supabase):
        """正常範囲のシェア数（疑わしくない）"""
        # 1時間以内に5件のシェア（閾値10未満）
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
            {"id": f"share_{i}"} for i in range(5)
        ]
        
        result = await fraud_detector.check_rapid_shares("user123")
        
        assert result is False  # 疑わしくない
    
    @pytest.mark.asyncio
    async def test_check_rapid_shares_suspicious(self, fraud_detector, mock_supabase):
        """短時間大量シェア（疑わしい）"""
        # 1時間以内に15件のシェア（閾値10以上）
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
            {"id": f"share_{i}"} for i in range(15)
        ]
        
        result = await fraud_detector.check_rapid_shares("user123")
        
        assert result is True  # 疑わしい
    
    @pytest.mark.asyncio
    async def test_check_account_age_old_account(self, fraud_detector):
        """古いアカウント（疑わしくない）"""
        # 1年前に作成されたアカウント
        old_date = "2023-10-01T00:00:00Z"
        
        result = await fraud_detector.check_account_age(old_date)
        
        assert result is False  # 疑わしくない
    
    @pytest.mark.asyncio
    async def test_check_account_age_new_account(self, fraud_detector):
        """新しいアカウント（疑わしい）"""
        # 3日前に作成されたアカウント
        recent_date = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        
        result = await fraud_detector.check_account_age(recent_date)
        
        assert result is True  # 疑わしい
    
    @pytest.mark.asyncio
    async def test_check_followers_count_normal(self, fraud_detector):
        """フォロワー数が十分（疑わしくない）"""
        result = await fraud_detector.check_followers_count(100)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_check_followers_count_suspicious(self, fraud_detector):
        """フォロワー数が少ない（疑わしい）"""
        result = await fraud_detector.check_followers_count(5)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_calculate_fraud_score_clean(self, fraud_detector, mock_supabase):
        """正常なシェア（低スコア）"""
        # すべてのチェックをパス
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = []
        
        share_data = {
            "user_id": "user123",
            "ip_address": "192.168.1.1",
            "account_created_at": "2020-01-01T00:00:00Z",
            "followers_count": 500,
            "is_verified": True
        }
        
        score, severity = await fraud_detector.calculate_fraud_score(share_data)
        
        assert score < 30  # LOWスコア
        assert severity == "low"
    
    @pytest.mark.asyncio
    async def test_calculate_fraud_score_suspicious(self, fraud_detector, mock_supabase):
        """疑わしいシェア（高スコア）"""
        # 短時間大量シェア + 新アカウント + 低フォロワー
        mock_supabase.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
            {"id": f"share_{i}"} for i in range(15)
        ]
        
        share_data = {
            "user_id": "user123",
            "ip_address": "192.168.1.1",
            "account_created_at": datetime.now(timezone.utc).isoformat(),
            "followers_count": 3,
            "is_verified": False
        }
        
        score, severity = await fraud_detector.calculate_fraud_score(share_data)
        
        assert score >= 50  # HIGHスコア
        assert severity == "high"


class TestShareRewardService:
    """ポイント報酬システムのテスト"""
    
    @pytest.fixture
    def mock_supabase(self):
        mock = MagicMock()
        return mock
    
    @pytest.fixture
    def reward_service(self, mock_supabase):
        return ShareRewardService(mock_supabase)
    
    @pytest.mark.asyncio
    async def test_get_current_reward_rate(self, reward_service, mock_supabase):
        """現在の報酬レート取得"""
        mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"points_per_share": 5}
        ]
        
        rate = await reward_service.get_current_reward_rate()
        
        assert rate == 5
    
    @pytest.mark.asyncio
    async def test_get_current_reward_rate_default(self, reward_service, mock_supabase):
        """報酬レート未設定時のデフォルト値"""
        mock_supabase.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        
        rate = await reward_service.get_current_reward_rate()
        
        assert rate == 1  # デフォルト
    
    @pytest.mark.asyncio
    async def test_grant_share_reward_success(self, reward_service, mock_supabase):
        """ポイント報酬付与の成功"""
        # トランザクション作成成功
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "tx123"}
        ]
        
        # ユーザー残高取得
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "point_balance": 100
        }
        
        # 残高更新成功
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            {"id": "user123", "point_balance": 105}
        ]
        
        result = await reward_service.grant_share_reward(
            author_id="author123",
            note_id="note456",
            shared_by_user_id="user789",
            points_amount=5,
            share_id="share999"
        )
        
        assert result is not None
        assert result["points_granted"] == 5
        assert result["new_balance"] == 105


class TestXAPIClient:
    """X API クライアントのテスト"""
    
    @pytest.fixture
    def x_client(self):
        return XAPIClient("fake_access_token")
    
    @pytest.mark.asyncio
    async def test_post_tweet_success(self, x_client):
        """ツイート投稿成功"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "data": {
                    "id": "1234567890",
                    "text": "Test tweet"
                }
            }
            
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            result = await x_client.post_tweet("Test tweet")
            
            assert result["tweet_id"] == "1234567890"
            assert result["text"] == "Test tweet"
    
    @pytest.mark.asyncio
    async def test_post_tweet_too_long(self, x_client):
        """ツイートが長すぎる場合のエラー"""
        long_tweet = "a" * 281
        
        with pytest.raises(XAPIError, match="280文字以内"):
            await x_client.post_tweet(long_tweet)
    
    @pytest.mark.asyncio
    async def test_post_tweet_unauthorized(self, x_client):
        """認証エラー"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 401
            
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            with pytest.raises(XAPIError, match="認証エラー"):
                await x_client.post_tweet("Test")
    
    @pytest.mark.asyncio
    async def test_get_tweet_success(self, x_client):
        """ツイート詳細取得成功"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "id": "1111",
                    "text": "Official tweet",
                    "author_id": "author123",
                    "created_at": "2024-10-29T00:00:00Z"
                },
                "includes": {
                    "users": [
                        {"id": "author123", "username": "author_user"}
                    ]
                }
            }

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            result = await x_client.get_tweet("1111")

            assert result["tweet_id"] == "1111"
            assert result["author_username"] == "author_user"
            assert result["tweet_url"] == "https://x.com/author_user/status/1111"

    @pytest.mark.asyncio
    async def test_get_tweet_not_found(self, x_client):
        """ツイート取得で404"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            with pytest.raises(XAPIError, match="ツイートが見つかりません"):
                await x_client.get_tweet("9999")

    @pytest.mark.asyncio
    async def test_retweet_success(self, x_client):
        """リツイート成功"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"retweeted": True}}

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await x_client.retweet("user123", "tweet456")

            assert result["retweeted"] is True

    @pytest.mark.asyncio
    async def test_retweet_rate_limit(self, x_client):
        """リツイートでレート制限"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {"x-rate-limit-reset": "1700000000"}
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(XAPIError, match="レート制限"):
                await x_client.retweet("user123", "tweet456")

    @pytest.mark.asyncio
    async def test_verify_retweet_success(self, x_client):
        """リツイート検証成功"""
        with patch.object(XAPIClient, "_fetch_recent_tweets", new=AsyncMock(return_value={
            "data": [
                {
                    "id": "retweet789",
                    "referenced_tweets": [
                        {"type": "retweeted", "id": "tweet456"}
                    ],
                    "created_at": "2024-10-29T12:00:00Z"
                }
            ]
        })):
            result = await x_client.verify_retweet("user123", "tweet456")

            assert result is not None
            assert result["retweet_id"] == "retweet789"

    @pytest.mark.asyncio
    async def test_verify_retweet_not_found(self, x_client):
        """リツイート検証失敗"""
        with patch.object(XAPIClient, "_fetch_recent_tweets", new=AsyncMock(return_value={"data": []})):
            with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
                result = await x_client.verify_retweet("user123", "tweet456", attempts=2, delay_seconds=0.1)

            assert result is None

    @pytest.mark.asyncio
    async def test_verify_tweet_success(self, x_client):
        """ツイート検証成功（URLを含む）"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "id": "1234567890",
                    "text": "Check out this NOTE https://d-swipe.com/notes/example-slug"
                }
            }
            
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            result = await x_client.verify_tweet("1234567890", "https://d-swipe.com/notes/example-slug")
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_verify_tweet_no_url(self, x_client):
        """ツイート検証失敗（URLが含まれていない）"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "id": "1234567890",
                    "text": "Just a regular tweet without the URL"
                }
            }
            
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            result = await x_client.verify_tweet("1234567890", "https://d-swipe.com/notes/example-slug")
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_verify_tweet_not_found(self, x_client):
        """ツイートが見つからない"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            result = await x_client.verify_tweet("9999999999", "https://d-swipe.com/notes/example-slug")
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_get_user_info_success(self, x_client):
        """ユーザー情報取得成功"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "id": "123456",
                    "username": "test_user",
                    "created_at": "2020-01-01T00:00:00.000Z",
                    "verified": True,
                    "public_metrics": {
                        "followers_count": 1000
                    }
                }
            }
            
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
            
            result = await x_client.get_user_info()
            
            assert result["x_user_id"] == "123456"
            assert result["x_username"] == "test_user"
            assert result["followers_count"] == 1000
            assert result["is_verified"] is True


class TestXOAuthClient:
    """X OAuth クライアントのテスト"""
    
    @pytest.fixture
    def oauth_client(self):
        return XOAuthClient(
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uri="https://example.com/callback"
        )
    
    def test_get_authorization_url(self, oauth_client):
        """OAuth認証URL生成"""
        url = oauth_client.get_authorization_url("random_state", "challenge_code")
        
        assert "https://twitter.com/i/oauth2/authorize" in url
        assert "client_id=test_client_id" in url
        assert "state=random_state" in url
        assert "code_challenge=challenge_code" in url
        assert "scope=" in url
    
    @pytest.mark.asyncio
    async def test_exchange_code_for_token_success(self, oauth_client):
        """認証コードをトークンに交換（成功）"""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "expires_in": 7200
            }
            
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            result = await oauth_client.exchange_code_for_token("auth_code", "verifier")
            
            assert result["access_token"] == "new_access_token"
            assert result["refresh_token"] == "new_refresh_token"
            assert result["expires_in"] == 7200


# テスト実行時の設定
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
