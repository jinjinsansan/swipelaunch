from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# 商品作成リクエスト
class ProductCreateRequest(BaseModel):
    lp_id: Optional[str] = Field(None, description="関連するLP ID（オプション）")
    title: str = Field(..., min_length=1, max_length=255, description="商品タイトル")
    description: Optional[str] = Field(None, description="商品説明")
    price_in_points: int = Field(..., ge=0, description="ポイント価格")
    stock_quantity: Optional[int] = Field(None, ge=0, description="在庫数（nullで無制限）")
    is_available: bool = Field(default=True, description="販売可能か")
    redirect_url: Optional[str] = Field(None, description="購入完了後のリダイレクトURL（外部URL）")
    thanks_lp_id: Optional[str] = Field(None, description="購入完了後のサンクスページLP ID（サイト内）")

# 商品更新リクエスト
class ProductUpdateRequest(BaseModel):
    lp_id: Optional[str] = None
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    price_in_points: Optional[int] = Field(None, ge=0)
    stock_quantity: Optional[int] = Field(None, ge=0)
    is_available: Optional[bool] = None
    redirect_url: Optional[str] = None
    thanks_lp_id: Optional[str] = None

# 商品レスポンス
class ProductResponse(BaseModel):
    id: str
    seller_id: str
    lp_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    price_in_points: int
    stock_quantity: Optional[int] = None
    is_available: bool
    total_sales: int = 0
    redirect_url: Optional[str] = None
    thanks_lp_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# 商品一覧レスポンス
class ProductListResponse(BaseModel):
    data: List[ProductResponse]
    total: int
    limit: int
    offset: int

# 商品購入リクエスト
class ProductPurchaseRequest(BaseModel):
    quantity: int = Field(default=1, ge=1, description="購入数量")

# 商品購入レスポンス
class ProductPurchaseResponse(BaseModel):
    purchase_id: str
    product_id: str
    product_title: str
    quantity: int
    total_points: int
    remaining_points: int
    purchased_at: datetime
    redirect_url: Optional[str] = None
    thanks_lp_id: Optional[str] = None
