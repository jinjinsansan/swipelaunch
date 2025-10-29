"""
X (Twitter) API v2 Client
OAuth 2.0認証とツイート投稿・検証機能
"""

import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class XAPIError(Exception):
    """X API関連のエラー"""
    pass


class XAPIClient:
    """
    X API v2 クライアント
    
    使用するエンドポイント:
    - POST /2/tweets - ツイート投稿
    - GET /2/tweets/:id - ツイート取得
    - GET /2/users/me - ユーザー情報取得
    """
    
    BASE_URL = "https://api.twitter.com/2"
    
    def __init__(self, access_token: str):
        """
        Args:
            access_token: OAuth 2.0 アクセストークン
        """
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    async def post_tweet(self, text: str) -> Dict[str, Any]:
        """
        ツイートを投稿
        
        Args:
            text: ツイート本文（280文字以内）
        
        Returns:
            {
                "tweet_id": "1234567890",
                "text": "ツイート本文",
                "created_at": "2024-10-28T12:00:00.000Z"
            }
        
        Raises:
            XAPIError: API呼び出し失敗時
        """
        if len(text) > 280:
            raise XAPIError("ツイートは280文字以内にしてください")
        
        url = f"{self.BASE_URL}/tweets"
        payload = {"text": text}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=self.headers)
                
                if response.status_code == 201:
                    data = response.json()
                    tweet_data = data.get("data", {})
                    return {
                        "tweet_id": tweet_data.get("id"),
                        "text": tweet_data.get("text"),
                        "created_at": datetime.utcnow().isoformat()
                    }
                elif response.status_code == 401:
                    raise XAPIError("認証エラー: アクセストークンが無効です")
                elif response.status_code == 403:
                    raise XAPIError("権限エラー: ツイート投稿権限がありません")
                elif response.status_code == 429:
                    raise XAPIError("レート制限: しばらく時間をおいてから再度お試しください")
                else:
                    error_msg = response.json().get("detail", "ツイート投稿に失敗しました")
                    raise XAPIError(f"X API エラー ({response.status_code}): {error_msg}")
        
        except httpx.TimeoutException:
            raise XAPIError("X API タイムアウト: ネットワーク接続を確認してください")
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")
    
    async def verify_tweet(self, tweet_id: str, expected_url: str) -> bool:
        """
        ツイートの存在と内容を検証
        
        Args:
            tweet_id: ツイートID
            expected_url: ツイートに含まれているべきURL
        
        Returns:
            bool: 検証成功ならTrue
        
        Raises:
            XAPIError: API呼び出し失敗時
        """
        url = f"{self.BASE_URL}/tweets/{tweet_id}"
        params = {
            "tweet.fields": "text,created_at,entities"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=self.headers)
                
                if response.status_code == 200:
                    data = response.json()
                    tweet_data = data.get("data", {})
                    tweet_text = tweet_data.get("text", "")
                    
                    # URLが含まれているか確認
                    if expected_url in tweet_text:
                        logger.info(f"ツイート検証成功: tweet_id={tweet_id}")
                        return True
                    else:
                        # entitiesのURLsもチェック
                        entities = tweet_data.get("entities", {})
                        urls = entities.get("urls", [])
                        for url_obj in urls:
                            expanded_url = url_obj.get("expanded_url", "")
                            if expected_url in expanded_url:
                                logger.info(f"ツイート検証成功 (entities): tweet_id={tweet_id}")
                                return True
                        
                        logger.warning(f"ツイートにURLが含まれていません: tweet_id={tweet_id}")
                        return False
                
                elif response.status_code == 404:
                    logger.warning(f"ツイートが見つかりません: tweet_id={tweet_id}")
                    return False
                elif response.status_code == 401:
                    raise XAPIError("認証エラー: アクセストークンが無効です")
                else:
                    error_msg = response.json().get("detail", "ツイート検証に失敗しました")
                    raise XAPIError(f"X API エラー ({response.status_code}): {error_msg}")
        
        except httpx.TimeoutException:
            raise XAPIError("X API タイムアウト")
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")
    
    async def get_user_info(self) -> Dict[str, Any]:
        """
        認証済みユーザーの情報を取得
        
        Returns:
            {
                "x_user_id": "1234567890",
                "x_username": "example_user",
                "account_created_at": "2010-01-01T00:00:00.000Z",
                "followers_count": 1000,
                "is_verified": False
            }
        
        Raises:
            XAPIError: API呼び出し失敗時
        """
        url = f"{self.BASE_URL}/users/me"
        params = {
            "user.fields": "created_at,public_metrics,verified"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=self.headers)
                
                if response.status_code == 200:
                    data = response.json()
                    user_data = data.get("data", {})
                    public_metrics = user_data.get("public_metrics", {})
                    
                    return {
                        "x_user_id": user_data.get("id"),
                        "x_username": user_data.get("username"),
                        "account_created_at": user_data.get("created_at"),
                        "followers_count": public_metrics.get("followers_count", 0),
                        "is_verified": user_data.get("verified", False)
                    }
                
                elif response.status_code == 401:
                    raise XAPIError("認証エラー: アクセストークンが無効です")
                else:
                    error_msg = response.json().get("detail", "ユーザー情報取得に失敗しました")
                    raise XAPIError(f"X API エラー ({response.status_code}): {error_msg}")
        
        except httpx.TimeoutException:
            raise XAPIError("X API タイムアウト")
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")


class XOAuthClient:
    """
    X OAuth 2.0 認証クライアント
    """
    
    AUTH_URL = "https://twitter.com/i/oauth2/authorize"
    TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
    
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
    
    def get_authorization_url(self, state: str, code_challenge: str) -> str:
        """
        OAuth認証URLを生成
        
        Args:
            state: CSRF対策用のランダム文字列
            code_challenge: PKCE用のチャレンジコード
        
        Returns:
            認証URL
        """
        scopes = ["tweet.read", "tweet.write", "users.read", "offline.access"]
        scope_str = " ".join(scopes)
        
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": scope_str,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{self.AUTH_URL}?{query_string}"
    
    async def exchange_code_for_token(
        self, 
        code: str, 
        code_verifier: str
    ) -> Dict[str, Any]:
        """
        認証コードをアクセストークンに交換
        
        Args:
            code: 認証コード
            code_verifier: PKCE用のverifier
        
        Returns:
            {
                "access_token": "...",
                "refresh_token": "...",
                "expires_in": 7200
            }
        
        Raises:
            XAPIError: トークン取得失敗時
        """
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
            "client_id": self.client_id
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.TOKEN_URL,
                    data=payload,
                    auth=(self.client_id, self.client_secret)
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    error_msg = response.json().get("error_description", "トークン取得失敗")
                    raise XAPIError(f"OAuth エラー: {error_msg}")
        
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")
    
    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        リフレッシュトークンで新しいアクセストークンを取得
        
        Args:
            refresh_token: リフレッシュトークン
        
        Returns:
            新しいトークン情報
        
        Raises:
            XAPIError: トークン更新失敗時
        """
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.TOKEN_URL,
                    data=payload,
                    auth=(self.client_id, self.client_secret)
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    error_msg = response.json().get("error_description", "トークン更新失敗")
                    raise XAPIError(f"OAuth エラー: {error_msg}")
        
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")
    
    async def create_repost(self, tweet_id: str) -> Dict[str, Any]:
        """
        指定のツイートをリポスト（RT）する
        
        Args:
            tweet_id: リポストするツイートID
        
        Returns:
            {"retweeted": True}
        
        Raises:
            XAPIError: API呼び出し失敗時
        """
        # まずユーザーIDを取得
        user_info = await self.get_user_info()
        user_id = user_info.get("x_user_id")
        
        url = f"{self.BASE_URL}/users/{user_id}/retweets"
        payload = {"tweet_id": tweet_id}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload
                )
                
                if response.status_code in [200, 201]:
                    return {"retweeted": True, "tweet_id": tweet_id}
                else:
                    error_data = response.json()
                    error_msg = error_data.get("detail", "リポスト失敗")
                    raise XAPIError(f"リポストエラー: {error_msg}")
        
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")
    
    async def check_user_retweeted(self, tweet_id: str, user_id: str) -> bool:
        """
        指定のユーザーが指定のツイートをリポストしているか確認
        
        Args:
            tweet_id: チェックするツイートID
            user_id: チェックするユーザーのX ID
        
        Returns:
            True: リポスト済み, False: 未リポスト
        
        Raises:
            XAPIError: API呼び出し失敗時
        """
        # X API v2: GET /2/tweets/:id/retweeted_by
        url = f"{self.BASE_URL}/tweets/{tweet_id}/retweeted_by"
        params = {"max_results": 100}  # 最大100件まで
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=self.headers)
                
                if response.status_code == 200:
                    data = response.json()
                    retweeters = data.get("data", [])
                    
                    # ユーザーIDがリポストしたユーザーリストに含まれているかチェック
                    for user in retweeters:
                        if user.get("id") == user_id:
                            return True
                    
                    return False
                else:
                    # エラーの場合はFalseを返す（寛容）
                    return False
        
        except httpx.HTTPError:
            # ネットワークエラーの場合もFalseを返す（寛容）
            return False
