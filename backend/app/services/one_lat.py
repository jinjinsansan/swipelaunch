"""
ONE.lat Payment Gateway API Client
決済処理とWebhook通知を処理するクライアント
"""
import httpx
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from app.config import settings

logger = logging.getLogger(__name__)


class OneLatClient:
    """ONE.lat API クライアント"""
    
    def __init__(self):
        self.base_url = settings.one_lat_api_base_url
        self.api_key = settings.one_lat_api_key
        self.api_secret = settings.one_lat_api_secret
        self.checkout_base_url = settings.one_lat_checkout_base_url
        
    def _get_headers(self) -> Dict[str, str]:
        """API認証ヘッダーを取得"""
        return {
            "x-api-key": self.api_key,
            "x-api-secret": self.api_secret,
            "Content-Type": "application/json"
        }
    
    async def create_checkout_preference(
        self,
        amount: float,
        currency: str,
        title: str,
        external_id: str,
        webhook_url: str,
        success_url: str,
        error_url: str,
        payer_email: Optional[str] = None,
        payer_name: Optional[str] = None,
        payer_last_name: Optional[str] = None,
        payer_phone: Optional[str] = None,
        expiration_minutes: int = 15,
        preference_type: str = "PAYMENT",
        payment_link_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Checkout Preferenceを作成
        
        Args:
            amount: 金額（0.1〜3000 USD）
            currency: 通貨コード（USD, COP, など）
            title: 商品説明
            external_id: 外部ID（一意である必要がある）
            webhook_url: Webhook通知先URL
            success_url: 決済成功時のリダイレクト先
            error_url: 決済失敗時のリダイレクト先
            payer_email: 購入者メールアドレス
            payer_name: 購入者名
            payer_last_name: 購入者姓
            payer_phone: 購入者電話番号
            expiration_minutes: 有効期限（分）
            
        Returns:
            Checkout Preference情報（checkout_url含む）
        """
        expiration_date = (datetime.utcnow() + timedelta(minutes=expiration_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        payload: Dict[str, Any] = {
            "type": preference_type,
            "title": title,
            "origin": "API",
            "external_id": external_id,
            "expiration_date": expiration_date,
            "custom_urls": {
                "status_changes_webhook": webhook_url,
                "success_payment_redirect": success_url,
                "error_payment_redirect": error_url
            },
        }

        if preference_type.upper() == "SUBSCRIPTION":
            if not payment_link_id:
                raise ValueError("payment_link_id is required for subscription checkout preferences")
            payload["payment_link_id"] = payment_link_id
        else:
            payload["amount"] = amount
            payload["currency"] = currency
        
        # Payerの情報を追加（オプション）
        if payer_email or payer_name:
            payer_data = {}
            if payer_email:
                payer_data["email"] = payer_email
            if payer_name:
                payer_data["first_name"] = payer_name
            if payer_last_name:
                payer_data["last_name"] = payer_last_name
            if payer_phone:
                payer_data["phone_number"] = payer_phone
            payload["payer"] = payer_data
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/checkout_preferences",
                    headers=self._get_headers(),
                    json=payload
                )
                
                response.raise_for_status()
                data = response.json()
                
                logger.info(f"✅ Checkout Preference created: {data.get('id')}")
                return data
                
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ ONE.lat API Error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"ONE.lat API Error: {e.response.text}")
        except Exception as e:
            logger.error(f"❌ Failed to create checkout preference: {str(e)}")
            raise
    
    async def get_payment_order(self, payment_order_id: str) -> Dict[str, Any]:
        """
        Payment Order詳細を取得
        
        Args:
            payment_order_id: Payment Order ID
            
        Returns:
            Payment Order情報
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/v1/payment_orders/{payment_order_id}",
                    headers=self._get_headers()
                )
                
                response.raise_for_status()
                data = response.json()
                
                logger.info(f"✅ Payment Order retrieved: {payment_order_id} - Status: {data.get('status')}")
                return data
                
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ ONE.lat API Error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"ONE.lat API Error: {e.response.text}")
        except Exception as e:
            logger.error(f"❌ Failed to get payment order: {str(e)}")
            raise

    async def get_recurrent_payment(self, recurrent_payment_id: str) -> Dict[str, Any]:
        """Retrieve recurrent payment details."""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/v1/recurrent_payments/{recurrent_payment_id}",
                    headers=self._get_headers(),
                )

                response.raise_for_status()
                data = response.json()
                logger.info(
                    "✅ Recurrent payment retrieved",
                    extra={"recurrent_payment_id": recurrent_payment_id, "status": data.get("status")},
                )
                return data

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ ONE.lat API Error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"ONE.lat API Error: {e.response.text}")
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"❌ Failed to get recurrent payment: {str(e)}")
            raise

    async def cancel_recurrent_payment(self, recurrent_payment_id: str, deleted_by: str = "merchant") -> Dict[str, Any]:
        """Cancel an active recurrent payment."""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{self.base_url}/v1/recurrent_payments/{recurrent_payment_id}",
                    headers=self._get_headers(),
                    params={"deleted_by": deleted_by},
                )

                response.raise_for_status()
                data = response.json()
                logger.info(
                    "✅ Recurrent payment cancelled",
                    extra={"recurrent_payment_id": recurrent_payment_id},
                )
                return data

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ ONE.lat API Error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"ONE.lat API Error: {e.response.text}")
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"❌ Failed to cancel recurrent payment: {str(e)}")
            raise


# シングルトンインスタンス
one_lat_client = OneLatClient()
