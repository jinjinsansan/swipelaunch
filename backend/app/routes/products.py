from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings
from app.models.product import (
    ProductCreateRequest,
    ProductUpdateRequest,
    ProductResponse,
    ProductListResponse,
    ProductPurchaseRequest,
    ProductPurchaseResponse,
    ProductWithSellerResponse,
    PublicProductListResponse
)
from typing import Optional
import jwt

router = APIRouter(prefix="/products", tags=["products"])
security = HTTPBearer()

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

def get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    """トークンから現在のユーザーIDを取得"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
            )
        return user_id
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました"
        )

def get_current_user(credentials: HTTPAuthorizationCredentials) -> dict:
    """トークンから現在のユーザー情報を取得"""
    user_id = get_current_user_id(credentials)
    supabase = get_supabase()
    
    user_response = supabase.table("users").select("*").eq("id", user_id).single().execute()
    
    if not user_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ユーザーが見つかりません"
        )
    
    return user_response.data

@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    商品作成（Seller専用）
    
    - **lp_id**: 関連するLP ID（オプション）
    - **title**: 商品タイトル
    - **description**: 商品説明
    - **price_in_points**: ポイント価格
    - **stock_quantity**: 在庫数（nullで無制限）
    - **is_available**: 販売可能か
    """
    try:
        user = get_current_user(credentials)
        
        # Sellerのみ作成可能
        if user.get("user_type") != "seller":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="商品はSellerのみ作成できます"
            )
        
        supabase = get_supabase()
        
        # LP IDが指定されている場合、自分のLPか確認
        if data.lp_id:
            lp_response = supabase.table("landing_pages").select("id").eq("id", data.lp_id).eq("seller_id", user["id"]).single().execute()
            
            if not lp_response.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="指定されたLPが見つかりません"
                )
        
        # 商品作成
        product_data = {
            "seller_id": user["id"],
            "lp_id": data.lp_id,
            "title": data.title,
            "description": data.description,
            "price_in_points": data.price_in_points,
            "stock_quantity": data.stock_quantity,
            "is_available": data.is_available
        }
        
        response = supabase.table("products").insert(product_data).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="商品作成に失敗しました"
            )
        
        return ProductResponse(**response.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"商品作成エラー: {str(e)}"
        )

@router.get("", response_model=ProductListResponse)
async def get_products(
    is_available: Optional[bool] = Query(None, description="販売可能フィルター"),
    lp_id: Optional[str] = Query(None, description="LP IDでフィルター"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    自分の商品一覧取得（Seller専用）
    
    - **is_available**: 販売可能フィルター
    - **lp_id**: LP IDでフィルター
    - **limit**: 取得件数
    - **offset**: オフセット
    """
    try:
        user = get_current_user(credentials)
        
        # Sellerのみ取得可能
        if user.get("user_type") != "seller":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="商品一覧はSellerのみ取得できます"
            )
        
        supabase = get_supabase()
        
        # クエリ構築
        query = supabase.table("products").select("*").eq("seller_id", user["id"])
        
        if is_available is not None:
            query = query.eq("is_available", is_available)
        
        if lp_id:
            query = query.eq("lp_id", lp_id)
        
        # 件数取得
        count_response = query.execute()
        total = len(count_response.data) if count_response.data else 0
        
        # データ取得（ページネーション）
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = query.execute()
        
        products = [ProductResponse(**product) for product in response.data] if response.data else []
        
        return ProductListResponse(
            data=products,
            total=total,
            limit=limit,
            offset=offset
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"商品一覧取得エラー: {str(e)}"
        )

@router.get("/public", response_model=PublicProductListResponse)
async def get_public_products(
    sort: str = Query("latest", description="ソート順: 'popular' (人気順) または 'latest' (新着順)"),
    limit: int = Query(5, ge=1, le=50),
    offset: int = Query(0, ge=0),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """
    全ての販売中商品を取得（認証必須、全ユーザー可能）
    
    - **sort**: 'popular' (total_salesでソート) または 'latest' (created_atでソート)
    - **limit**: 取得件数（デフォルト: 5）
    - **offset**: オフセット
    
    Returns:
        販売者情報を含む商品一覧
    """
    try:
        # 認証チェック（BuyerもSellerもOK）
        user = get_current_user(credentials)
        supabase = get_supabase()
        
        # 販売中の商品を取得（seller情報をJOIN）
        query = """
            SELECT 
                p.id,
                p.seller_id,
                u.username as seller_username,
                p.lp_id,
                p.title,
                p.description,
                p.price_in_points,
                p.stock_quantity,
                p.is_available,
                p.total_sales,
                p.created_at,
                p.updated_at
            FROM products p
            INNER JOIN users u ON p.seller_id = u.id
            WHERE p.is_available = true
        """
        
        # ソート順を決定
        if sort == "popular":
            query += " ORDER BY p.total_sales DESC, p.created_at DESC"
        else:  # latest
            query += " ORDER BY p.created_at DESC"
        
        query += f" LIMIT {limit} OFFSET {offset}"
        
        # RPC実行
        response = supabase.rpc('exec_sql', {'query': query}).execute()
        
        if response.data is None:
            # RPC関数が存在しない場合は通常のクエリで代替
            products_response = supabase.table("products").select("*, seller:users!seller_id(username)").eq("is_available", True)
            
            if sort == "popular":
                products_response = products_response.order("total_sales", desc=True).order("created_at", desc=True)
            else:
                products_response = products_response.order("created_at", desc=True)
            
            products_response = products_response.range(offset, offset + limit - 1).execute()
            
            products = []
            for product in (products_response.data or []):
                seller_data = product.get("seller", {})
                products.append(ProductWithSellerResponse(
                    id=product["id"],
                    seller_id=product["seller_id"],
                    seller_username=seller_data.get("username", "Unknown"),
                    lp_id=product.get("lp_id"),
                    title=product["title"],
                    description=product.get("description"),
                    price_in_points=product["price_in_points"],
                    stock_quantity=product.get("stock_quantity"),
                    is_available=product["is_available"],
                    total_sales=product.get("total_sales", 0),
                    created_at=product["created_at"],
                    updated_at=product["updated_at"]
                ))
            
            # 総数取得
            count_response = supabase.table("products").select("id", count="exact").eq("is_available", True).execute()
            total = count_response.count or 0
        else:
            products = [ProductWithSellerResponse(**p) for p in response.data]
            # 総数取得
            count_response = supabase.table("products").select("id", count="exact").eq("is_available", True).execute()
            total = count_response.count or 0
        
        return PublicProductListResponse(
            data=products,
            total=total,
            limit=limit,
            offset=offset
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"公開商品一覧取得エラー: {str(e)}"
        )

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    商品詳細取得
    """
    try:
        user_id = get_current_user_id(credentials)
        supabase = get_supabase()
        
        # 商品取得
        product_response = supabase.table("products").select("*").eq("id", product_id).single().execute()
        
        if not product_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="商品が見つかりません"
            )
        
        product = product_response.data
        
        # 自分の商品か確認（Sellerの場合）
        if product["seller_id"] != user_id:
            # 他人の商品は公開されている場合のみ閲覧可能
            if not product.get("is_available"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="この商品を閲覧する権限がありません"
                )
        
        return ProductResponse(**product)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"商品詳細取得エラー: {str(e)}"
        )

@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    data: ProductUpdateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    商品更新（Seller専用）
    """
    try:
        user = get_current_user(credentials)
        
        # Sellerのみ更新可能
        if user.get("user_type") != "seller":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="商品はSellerのみ更新できます"
            )
        
        supabase = get_supabase()
        
        # 商品存在確認と所有者チェック
        product_response = supabase.table("products").select("*").eq("id", product_id).eq("seller_id", user["id"]).single().execute()
        
        if not product_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="商品が見つかりません"
            )
        
        # 更新データ準備
        update_data = data.model_dump(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="更新するデータがありません"
            )
        
        # LP IDが指定されている場合、自分のLPか確認
        if "lp_id" in update_data and update_data["lp_id"]:
            lp_response = supabase.table("landing_pages").select("id").eq("id", update_data["lp_id"]).eq("seller_id", user["id"]).single().execute()
            
            if not lp_response.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="指定されたLPが見つかりません"
                )
        
        # 更新
        response = supabase.table("products").update(update_data).eq("id", product_id).execute()
        
        return ProductResponse(**response.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"商品更新エラー: {str(e)}"
        )

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    商品削除（Seller専用）
    """
    try:
        user = get_current_user(credentials)
        
        # Sellerのみ削除可能
        if user.get("user_type") != "seller":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="商品はSellerのみ削除できます"
            )
        
        supabase = get_supabase()
        
        # 商品存在確認と所有者チェック
        product_response = supabase.table("products").select("id").eq("id", product_id).eq("seller_id", user["id"]).single().execute()
        
        if not product_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="商品が見つかりません"
            )
        
        # 削除
        supabase.table("products").delete().eq("id", product_id).execute()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"商品削除エラー: {str(e)}"
        )

@router.post("/{product_id}/purchase", response_model=ProductPurchaseResponse, status_code=status.HTTP_201_CREATED)
async def purchase_product(
    product_id: str,
    data: ProductPurchaseRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    商品購入
    
    - **product_id**: 購入する商品のID
    - **quantity**: 購入数量（デフォルト: 1）
    """
    try:
        user = get_current_user(credentials)
        supabase = get_supabase()
        
        # 商品情報取得
        product_response = supabase.table("products").select("*").eq("id", product_id).single().execute()
        
        if not product_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="商品が見つかりません"
            )
        
        product = product_response.data
        
        # 販売可能かチェック
        if not product.get("is_available"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="この商品は現在販売されていません"
            )
        
        # 在庫チェック
        if product.get("stock_quantity") is not None:
            if product["stock_quantity"] < data.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"在庫不足です（在庫: {product['stock_quantity']}）"
                )
        
        # 必要ポイント計算
        total_points = product["price_in_points"] * data.quantity
        current_balance = user.get("point_balance", 0)
        
        # ポイント残高チェック
        if current_balance < total_points:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ポイントが不足しています（必要: {total_points}、残高: {current_balance}）"
            )
        
        # ポイント消費
        new_balance = current_balance - total_points
        supabase.table("users").update({"point_balance": new_balance}).eq("id", user["id"]).execute()
        
        # 在庫を減らす（在庫管理がある場合）
        if product.get("stock_quantity") is not None:
            new_stock = product["stock_quantity"] - data.quantity
            supabase.table("products").update({"stock_quantity": new_stock}).eq("id", product_id).execute()
        
        # 販売数を増やす
        new_sales = product.get("total_sales", 0) + data.quantity
        supabase.table("products").update({"total_sales": new_sales}).eq("id", product_id).execute()
        
        # トランザクション記録
        transaction_data = {
            "user_id": user["id"],
            "transaction_type": "product_purchase",
            "amount": -total_points,  # マイナス値で記録
            "related_product_id": product_id,
            "description": f"{product['title']} x{data.quantity}を購入しました"
        }
        
        transaction_response = supabase.table("point_transactions").insert(transaction_data).execute()
        
        if not transaction_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="トランザクション記録に失敗しました"
            )
        
        transaction = transaction_response.data[0]
        
        # thanks_lp_idからslugを取得
        thanks_lp_slug = None
        if product.get("thanks_lp_id"):
            thanks_lp_response = supabase.table("landing_pages").select("slug").eq("id", product["thanks_lp_id"]).single().execute()
            if thanks_lp_response.data:
                thanks_lp_slug = thanks_lp_response.data.get("slug")
        
        return ProductPurchaseResponse(
            purchase_id=transaction["id"],
            product_id=product_id,
            product_title=product["title"],
            quantity=data.quantity,
            total_points=total_points,
            remaining_points=new_balance,
            purchased_at=transaction["created_at"],
            redirect_url=product.get("redirect_url"),
            thanks_lp_slug=thanks_lp_slug
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"商品購入エラー: {str(e)}"
        )
