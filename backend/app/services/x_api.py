"""
X (Twitter) API v2 Client
OAuth 2.0認証とツイート投稿・検証機能
"""

import asyncio
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
    
    async def get_tweet(self, tweet_id: str) -> Dict[str, Any]:
        """ツイート詳細を取得"""
        url = f"{self.BASE_URL}/tweets/{tweet_id}"
        params = {
            "tweet.fields": "text,author_id,created_at",
            "expansions": "author_id",
            "user.fields": "username"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=self.headers)

            if response.status_code == 200:
                payload = response.json()
                tweet_data = payload.get("data")
                if not tweet_data:
                    raise XAPIError("ツイート情報の取得に失敗しました")

                author_id = tweet_data.get("author_id")
                author_username = None
                includes = payload.get("includes", {})
                users = includes.get("users") or []
                if author_id:
                    for user in users:
                        if user.get("id") == author_id:
                            author_username = user.get("username")
                            break

                tweet_url = None
                if author_username:
                    tweet_url = f"https://x.com/{author_username}/status/{tweet_data.get('id')}"

                return {
                    "tweet_id": tweet_data.get("id"),
                    "text": tweet_data.get("text"),
                    "author_id": author_id,
                    "author_username": author_username,
                    "created_at": tweet_data.get("created_at"),
                    "tweet_url": tweet_url,
                }

            if response.status_code == 404:
                raise XAPIError("ツイートが見つかりませんでした")
            if response.status_code == 401:
                raise XAPIError("認証エラー: アクセストークンが無効です")

            error_msg = response.json().get("detail", "ツイート取得に失敗しました")
            raise XAPIError(f"X API エラー ({response.status_code}): {error_msg}")

        except httpx.TimeoutException:
            raise XAPIError("X API タイムアウト")
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")

    async def retweet(self, user_id: str, tweet_id: str) -> Dict[str, Any]:
        """指定ツイートをリツイート"""
        url = f"{self.BASE_URL}/users/{user_id}/retweets"
        payload = {"tweet_id": tweet_id}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=self.headers)

            if response.status_code in (200, 201):
                data = response.json().get("data", {})
                if data.get("retweeted") is True:
                    return {"retweeted": True}
                raise XAPIError("リツイートに失敗しました")

            if response.status_code == 403:
                raise XAPIError("権限エラー: このツイートをリツイートできません")
            if response.status_code == 404:
                raise XAPIError("ツイートが見つかりませんでした")
            if response.status_code == 401:
                raise XAPIError("認証エラー: アクセストークンが無効です")
            if response.status_code == 429:
                reset_at = response.headers.get("x-rate-limit-reset")
                if reset_at:
                    try:
                        reset_time = datetime.fromtimestamp(int(reset_at))
                        raise XAPIError(f"レート制限: {reset_time.isoformat()} までお待ちください")
                    except ValueError:
                        pass
                raise XAPIError("レート制限: しばらく時間をおいてから再試行してください")

            error_msg = response.json().get("detail", "リツイートに失敗しました")
            raise XAPIError(f"X API エラー ({response.status_code}): {error_msg}")

        except httpx.TimeoutException:
            raise XAPIError("X API タイムアウト")
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")

    async def _fetch_recent_tweets(self, user_id: str, max_results: int = 20) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/users/{user_id}/tweets"
        params = {
            "max_results": max_results,
            "tweet.fields": "created_at,referenced_tweets",
            "exclude": "replies",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=self.headers)
        except httpx.TimeoutException:
            raise XAPIError("X API タイムアウト")
        except httpx.HTTPError as e:
            raise XAPIError(f"ネットワークエラー: {str(e)}")

        if response.status_code == 200:
            return response.json()
        if response.status_code == 401:
            raise XAPIError("認証エラー: アクセストークンが無効です")
        if response.status_code == 404:
            raise XAPIError("ユーザーが見つかりませんでした")
        if response.status_code == 429:
            raise XAPIError("レート制限: 後でもう一度お試しください")

        error_msg = response.json().get("detail", "ユーザータイムラインの取得に失敗しました")
        raise XAPIError(f"X API エラー ({response.status_code}): {error_msg}")

    async def find_retweet(
        self,
        user_id: str,
        target_tweet_id: str,
        max_results: int = 20,
    ) -> Optional[Dict[str, Any]]:
        """ユーザータイムラインから指定ツイートのリツイートを探索"""
        try:
            payload = await self._fetch_recent_tweets(user_id, max_results=max_results)
        except XAPIError as exc:
            logger.warning("Failed to fetch recent tweets for verification: %s", exc)
            return None

        for tweet in payload.get("data", []) or []:
            for reference in tweet.get("referenced_tweets", []) or []:
                if reference.get("type") == "retweeted" and reference.get("id") == target_tweet_id:
                    return {
                        "retweet_id": tweet.get("id"),
                        "created_at": tweet.get("created_at"),
                    }
        return None

    async def verify_retweet(
        self,
        user_id: str,
        target_tweet_id: str,
        attempts: int = 3,
        delay_seconds: float = 2.0,
    ) -> Optional[Dict[str, Any]]:
        """指定ツイートがユーザーによってリツイートされたか確認"""
        for attempt in range(attempts):
            retweet_info = await self.find_retweet(user_id, target_tweet_id)
            if retweet_info:
                return retweet_info
            if attempt < attempts - 1:
                await asyncio.sleep(delay_seconds)
        return None

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
