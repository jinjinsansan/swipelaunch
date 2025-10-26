from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# ポイント購入リクエスト
class PointPurchaseRequest(BaseModel):
    amount: int = Field(..., ge=100, description="購入するポイント数（最低100ポイント）")

# ポイント購入レスポンス
class PointPurchaseResponse(BaseModel):
    transaction_id: str
    amount: int
    new_balance: int
    purchased_at: datetime

# ポイント残高レスポンス
class PointBalanceResponse(BaseModel):
    user_id: str
    username: str
    point_balance: int
    last_updated: datetime

# トランザクションレスポンス
class TransactionResponse(BaseModel):
    id: str
    user_id: str
    transaction_type: str
    amount: int
    related_product_id: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

# トランザクション一覧レスポンス
class TransactionListResponse(BaseModel):
    data: List[TransactionResponse]
    total: int
    limit: int
    offset: int
    transaction_type_filter: Optional[str] = None

# JPYC決済リクエスト
class JPYCPurchaseRequest(BaseModel):
    points_amount: int = Field(..., ge=100, description="購入するポイント数（最低100ポイント）")
    from_address: str = Field(..., min_length=42, max_length=42, description="ユーザーのウォレットアドレス")
    chain_id: int = Field(..., description="ブロックチェーンID（1: Ethereum, 137: Polygon, 43114: Avalanche）")
    nonce: str = Field(..., min_length=66, max_length=66, description="EIP-3009 nonce")
    signature_v: int = Field(..., ge=0, le=255, description="署名のv値")
    signature_r: str = Field(..., min_length=66, max_length=66, description="署名のr値")
    signature_s: str = Field(..., min_length=66, max_length=66, description="署名のs値")
    valid_after: int = Field(..., ge=0, description="有効開始時刻（unix timestamp）")
    valid_before: int = Field(..., ge=0, description="有効終了時刻（unix timestamp）")

# JPYC決済レスポンス
class JPYCPurchaseResponse(BaseModel):
    transaction_id: str
    status: str
    points_amount: int
    jpyc_amount: int
    from_address: str
    to_address: str
    chain_id: int
    estimated_confirmation_time: int = Field(..., description="予想確認時間（秒）")

# JPYCトランザクションステータス
class JPYCTransactionStatus(BaseModel):
    transaction_id: str
    status: str
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None
    points_amount: int
    jpyc_amount: int
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
