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
