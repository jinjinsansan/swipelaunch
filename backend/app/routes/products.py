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
from typing import Optional, Dict, Any, List
import logging
import uuid
from datetime import datetime

from app.services.one_lat import one_lat_client
from app.utils.auth import decode_access_token

router = APIRouter(prefix="/products", tags=["products"])
security = HTTPBearer(auto_error=False)

JPY_TO_USD_RATE = 145.0


def _coerce_float(value: Optional[Any]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive conversion
        return None

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

def get_current_user_id(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    """トークンから現在のユーザーIDを取得"""
    try:
        if not credentials or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="認証情報が提供されていません"
            )

        token = credentials.credentials
        payload = decode_access_token(token)
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
            )
        return user_id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました"
        )

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials]) -> dict:
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
        
        product_type = data.product_type or "points"
        salon_record = None

        allow_point_purchase = data.allow_point_purchase
        allow_jpy_purchase = data.allow_jpy_purchase

        if not allow_point_purchase and not allow_jpy_purchase:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="少なくとも1つの決済方法を有効にしてください"
            )

        if product_type == "points":
            if allow_point_purchase and (data.price_in_points is None or data.price_in_points <= 0):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ポイント商品には price_in_points が必須です"
                )
            price_in_points = data.price_in_points or 0
        else:
            # オンラインサロン商品
            if not data.salon_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="サロン商品には salon_id が必須です"
                )
            salon_response = (
                supabase
                .table("salons")
                .select("id, owner_id, subscription_plan_id")
                .eq("id", data.salon_id)
                .single()
                .execute()
            )
            if not salon_response.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="指定されたサロンが見つかりません"
                )
            salon_record = salon_response.data
            if salon_record.get("owner_id") != user["id"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="このサロンに商品を紐付ける権限がありません"
                )
            price_in_points = 0
            # サロン商品はポイント販売不可に固定
            allow_point_purchase = False

        if allow_jpy_purchase and (data.price_jpy is None or data.price_jpy <= 0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="日本円決済を有効にするには price_jpy を設定してください"
            )

        product_data = {
            "seller_id": user["id"],
            "lp_id": data.lp_id,
            "title": data.title,
            "description": data.description,
            "price_in_points": price_in_points,
            "price_jpy": data.price_jpy,
            "allow_point_purchase": allow_point_purchase,
            "allow_jpy_purchase": allow_jpy_purchase,
            "tax_rate": data.tax_rate if data.tax_rate is not None else 10.0,
            "tax_inclusive": data.tax_inclusive,
            "stock_quantity": data.stock_quantity if product_type == "points" and allow_point_purchase else None,
            "is_available": data.is_available,
            "redirect_url": data.redirect_url,
            "thanks_lp_id": data.thanks_lp_id,
            "product_type": product_type,
            "salon_id": salon_record.get("id") if salon_record else None,
        }

        response = supabase.table("products").insert(product_data).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="商品作成に失敗しました"
            )
        product_row = response.data[0]

        if product_type == "salon":
            try:
                supabase.table("salon_products").insert(
                    {
                        "salon_id": salon_record.get("id"),
                        "product_id": product_row["id"],
                        "subscription_plan_id": salon_record.get("subscription_plan_id"),
                    }
                ).execute()
            except Exception as exc:
                logger = logging.getLogger(__name__)
                logger.warning("Failed to register salon product linkage", extra={"error": str(exc)})

        return ProductResponse(**product_row)
        
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
    product_type: Optional[str] = Query(None, description="商品タイプフィルター(points/salon)"),
    salon_id: Optional[str] = Query(None, description="サロンIDでフィルター"),
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

        if product_type:
            query = query.eq("product_type", product_type)

        if salon_id:
            query = query.eq("salon_id", salon_id)
        
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
    seller_username: Optional[str] = Query(None, description="販売者ユーザー名でフィルター"),
    lp_id: Optional[str] = Query(None, description="特定LPに紐づく商品でフィルター"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """
    全ての販売中商品を取得（認証不要）
    
    - **sort**: 'popular' (total_salesでソート) または 'latest' (created_atでソート)
    - **limit**: 取得件数（デフォルト: 5）
    - **offset**: オフセット
    - **seller_username**: 販売者ユーザー名でフィルター（オプション）
    
    Returns:
        販売者情報を含む商品一覧
    """
    try:
        if credentials and credentials.credentials:
            try:
                get_current_user(credentials)
            except HTTPException:
                raise
        supabase = get_supabase()

        def extract_thumbnail_from_step(step: Dict[str, Any]) -> Optional[str]:
            """ステップ情報から最適なサムネイル（画像または動画）URLを抽出"""
            media_candidates: List[Optional[str]] = []

            content_data = step.get("content_data") or {}
            if isinstance(content_data, dict):
                # 画像を最優先、次に動画
                media_candidates.extend([
                    content_data.get("backgroundImageUrl"),
                    content_data.get("background_image_url"),
                    content_data.get("imageUrl"),
                    content_data.get("image_url"),
                    content_data.get("thumbnailUrl"),
                    content_data.get("thumbnail_url"),
                    content_data.get("heroImage"),
                    content_data.get("hero_image"),
                    content_data.get("primaryImageUrl"),
                    content_data.get("primary_image_url"),
                    # 動画も候補に含める
                    content_data.get("backgroundVideoUrl"),
                    content_data.get("background_video_url"),
                    content_data.get("videoUrl"),
                    content_data.get("video_url"),
                ])

                nested_content = content_data.get("content")
                if isinstance(nested_content, dict):
                    media_candidates.extend([
                        nested_content.get("backgroundImageUrl"),
                        nested_content.get("background_image_url"),
                        nested_content.get("imageUrl"),
                        nested_content.get("image_url"),
                        nested_content.get("thumbnailUrl"),
                        nested_content.get("thumbnail_url"),
                        nested_content.get("heroImage"),
                        nested_content.get("hero_image"),
                        nested_content.get("backgroundVideoUrl"),
                        nested_content.get("background_video_url"),
                        nested_content.get("videoUrl"),
                        nested_content.get("video_url"),
                    ])
                elif isinstance(nested_content, list):
                    for item in nested_content:
                        if isinstance(item, dict):
                            candidate = (
                                item.get("imageUrl") or 
                                item.get("image_url") or 
                                item.get("thumbnailUrl") or 
                                item.get("thumbnail_url") or 
                                item.get("heroImage") or 
                                item.get("hero_image") or
                                item.get("backgroundVideoUrl") or
                                item.get("videoUrl")
                            )
                            if isinstance(candidate, str) and candidate.strip() and candidate.strip() != "/placeholder.jpg":
                                return candidate.strip()

            # image_urlもチェック（/placeholder.jpgは除外）
            image_url = step.get("image_url")
            if isinstance(image_url, str) and image_url.strip() and image_url.strip() != "/placeholder.jpg":
                media_candidates.append(image_url)

            # 有効なメディアURLを返す（/placeholder.jpgのみ除外）
            for candidate in media_candidates:
                if isinstance(candidate, str) and candidate.strip():
                    cleaned = candidate.strip()
                    if cleaned != "/placeholder.jpg":
                        return cleaned

            return None

        # seller_usernameが指定されている場合、seller_idを取得
        seller_id_filter = None
        if seller_username:
            user_response = supabase.table("users").select("id").eq("username", seller_username).single().execute()
            if not user_response.data:
                # 該当ユーザーが存在しない場合は空のレスポンスを返す
                return PublicProductListResponse(
                    data=[],
                    total=0,
                    limit=limit,
                    offset=offset
                )
            seller_id_filter = user_response.data["id"]

        # 販売中の商品を取得（seller情報をJOIN）
        products_response = supabase.table("products").select("*, seller:users!seller_id(username)").eq("is_available", True)

        if lp_id:
            products_response = products_response.eq("lp_id", lp_id)
        
        # seller_idでフィルタリング
        if seller_id_filter:
            products_response = products_response.eq("seller_id", seller_id_filter)

        # ソート順を決定
        if sort == "popular":
            products_response = products_response.order("total_sales", desc=True).order("created_at", desc=True)
        else:  # latest
            products_response = products_response.order("created_at", desc=True)

        # ページネーション
        products_response = products_response.range(offset, offset + limit - 1).execute()

        raw_products = products_response.data or []
        lp_ids = {product.get("lp_id") for product in raw_products if product.get("lp_id")}

        lp_metadata: Dict[str, Dict[str, Optional[str]]] = {}
        lp_thumbnails: Dict[str, Optional[str]] = {}

        if lp_ids:
            lp_id_list = list(lp_ids)
            # LPメタデータ取得
            lp_meta_response = supabase.table("landing_pages").select("id, slug, title, meta_image_url").in_("id", lp_id_list).execute()
            for lp in (lp_meta_response.data or []):
                lp_metadata[lp["id"]] = {
                    "slug": lp.get("slug"),
                    "title": lp.get("title"),
                    "meta_image_url": lp.get("meta_image_url"),
                }

            # LPステップからサムネイル候補取得
            steps_response = (
                supabase
                .table("lp_steps")
                .select("lp_id, image_url, content_data, block_type, step_order")
                .in_("lp_id", lp_id_list)
                .order("lp_id")
                .order("step_order")
                .execute()
            )

            for step in (steps_response.data or []):
                lp_id = step.get("lp_id")
                if not lp_id or lp_id in lp_thumbnails:
                    continue
                thumbnail = extract_thumbnail_from_step(step)
                if thumbnail:
                    lp_thumbnails[lp_id] = thumbnail

        # レスポンス構築
        products = []
        for product in raw_products:
            seller_data = product.get("seller", {})
            lp_id = product.get("lp_id")
            lp_info = lp_metadata.get(lp_id or "", {}) if lp_id else {}
            raw_meta_image = lp_info.get("meta_image_url") if lp_info else None
            meta_image = raw_meta_image.strip() if isinstance(raw_meta_image, str) and raw_meta_image.strip() else None
            thumbnail_url = lp_thumbnails.get(lp_id) if lp_id else None
            selected_thumbnail = thumbnail_url or meta_image
            if isinstance(selected_thumbnail, str):
                selected_thumbnail = selected_thumbnail.strip() or None

            products.append(ProductWithSellerResponse(
                id=product["id"],
                seller_id=product["seller_id"],
                seller_username=seller_data.get("username", "Unknown"),
                lp_id=lp_id,
                product_type=product.get("product_type", "points"),
                salon_id=product.get("salon_id"),
                lp_slug=lp_info.get("slug") if lp_info else None,
                lp_title=lp_info.get("title") if lp_info else None,
                lp_thumbnail_url=selected_thumbnail,
                hero_image_url=selected_thumbnail,
                meta_image_url=meta_image,
                title=product["title"],
                description=product.get("description"),
                price_in_points=int(product.get("price_in_points") or 0),
                price_jpy=product.get("price_jpy"),
                allow_point_purchase=bool(product.get("allow_point_purchase", True)),
                allow_jpy_purchase=bool(product.get("allow_jpy_purchase", False)),
                tax_rate=_coerce_float(product.get("tax_rate")),
                tax_inclusive=bool(product.get("tax_inclusive", True)),
                stock_quantity=product.get("stock_quantity"),
                is_available=product["is_available"],
                total_sales=product.get("total_sales", 0),
                created_at=product["created_at"],
                updated_at=product["updated_at"]
            ))
        
        # 総数取得
        count_query = supabase.table("products").select("id", count="exact").eq("is_available", True)
        if seller_id_filter:
            count_query = count_query.eq("seller_id", seller_id_filter)
        if lp_id:
            count_query = count_query.eq("lp_id", lp_id)
        count_response = count_query.execute()
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

        current_product = product_response.data
        
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

        new_product_type = update_data.get("product_type") or current_product.get("product_type", "points")
        salon_record = None

        if new_product_type not in {"points", "salon"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不正な商品タイプです")

        allow_point_purchase = update_data.get("allow_point_purchase")
        if allow_point_purchase is None:
            allow_point_purchase = bool(current_product.get("allow_point_purchase", True))
        allow_jpy_purchase = update_data.get("allow_jpy_purchase")
        if allow_jpy_purchase is None:
            allow_jpy_purchase = bool(current_product.get("allow_jpy_purchase", False))

        if not allow_point_purchase and not allow_jpy_purchase:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="少なくとも1つの決済方法を有効にしてください"
            )

        if new_product_type == "points":
            price = update_data.get("price_in_points", current_product.get("price_in_points"))
            if price is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ポイント商品には price_in_points が必要です"
                )
            update_data["price_in_points"] = price
            if not allow_point_purchase:
                update_data["price_in_points"] = 0
            if "stock_quantity" not in update_data:
                update_data["stock_quantity"] = current_product.get("stock_quantity") if allow_point_purchase else None
            if not allow_point_purchase:
                update_data["stock_quantity"] = None
            update_data["salon_id"] = None
        else:
            salon_id = update_data.get("salon_id") or current_product.get("salon_id")
            if not salon_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="サロン商品には salon_id が必要です"
                )
            salon_response = (
                supabase
                .table("salons")
                .select("id, owner_id, subscription_plan_id")
                .eq("id", salon_id)
                .single()
                .execute()
            )
            if not salon_response.data:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")
            salon_record = salon_response.data
            if salon_record.get("owner_id") != user["id"]:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="このサロンに紐付けできません")
            update_data["salon_id"] = salon_record.get("id")
            update_data["price_in_points"] = 0
            update_data["stock_quantity"] = None
            allow_point_purchase = False

        if allow_jpy_purchase:
            price_jpy = update_data.get("price_jpy")
            if price_jpy is None:
                price_jpy = current_product.get("price_jpy")
            if price_jpy is None or price_jpy <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="日本円決済を有効にするには price_jpy を設定してください"
                )
            update_data["price_jpy"] = price_jpy
        else:
            # 明示的に無効化する場合は価格をnullにできるようにする
            if "price_jpy" not in update_data:
                update_data["price_jpy"] = None

        update_data["allow_point_purchase"] = allow_point_purchase
        update_data["allow_jpy_purchase"] = allow_jpy_purchase
        response = supabase.table("products").update(update_data).eq("id", product_id).execute()

        updated_product = response.data[0]

        if new_product_type == "salon":
            salon_link_resp = (
                supabase
                .table("salon_products")
                .select("id")
                .eq("product_id", product_id)
                .limit(1)
                .execute()
            )
            if not salon_record:
                salon_lookup = (
                    supabase
                    .table("salons")
                    .select("id, subscription_plan_id")
                    .eq("id", update_data.get("salon_id"))
                    .single()
                    .execute()
                )
                salon_record = salon_lookup.data if salon_lookup.data else None
            if not salon_record:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="サロンが見つかりません")
            payload = {
                "salon_id": update_data.get("salon_id"),
                "subscription_plan_id": salon_record.get("subscription_plan_id"),
            }
            if salon_link_resp.data:
                supabase.table("salon_products").update(payload).eq("product_id", product_id).execute()
            else:
                payload.update({"product_id": product_id})
                supabase.table("salon_products").insert(payload).execute()
        else:
            supabase.table("salon_products").delete().eq("product_id", product_id).execute()

        return ProductResponse(**updated_product)
        
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
        
        # サロン連携削除
        supabase.table("salon_products").delete().eq("product_id", product_id).execute()

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

        if product.get("product_type", "points") == "salon":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="オンラインサロン商品はサブスクリプションから購入してください"
            )

        stock_quantity = product.get("stock_quantity")
        if stock_quantity is not None and stock_quantity < data.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"在庫不足です（在庫: {product['stock_quantity']}）"
            )

        payment_method = data.payment_method
        thanks_lp_slug: Optional[str] = None

        if payment_method == "points":
            if not product.get("allow_point_purchase", True):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="この商品はポイント決済に対応していません"
                )
            price_per_unit = int(product.get("price_in_points") or 0)
            total_points = price_per_unit * data.quantity
            current_balance = int(user.get("point_balance", 0))
            if current_balance < total_points:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"ポイントが不足しています（必要: {total_points}、残高: {current_balance}）"
                )

            new_balance = current_balance - total_points
            supabase.table("users").update({"point_balance": new_balance}).eq("id", user["id"]).execute()

            if stock_quantity is not None:
                new_stock = stock_quantity - data.quantity
                supabase.table("products").update({"stock_quantity": new_stock}).eq("id", product_id).execute()

            new_sales = (product.get("total_sales") or 0) + data.quantity
            supabase.table("products").update({"total_sales": new_sales}).eq("id", product_id).execute()

            transaction_data = {
                "user_id": user["id"],
                "transaction_type": "product_purchase",
                "amount": -total_points,
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
                payment_method="points",
                payment_status="completed",
                purchased_at=transaction["created_at"],
                redirect_url=product.get("redirect_url"),
                thanks_lp_slug=thanks_lp_slug
            )

        if payment_method != "yen":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="サポートされていない決済方法です"
            )

        if not product.get("allow_jpy_purchase"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="この商品は日本円決済に対応していません"
            )

        price_jpy = product.get("price_jpy")
        if price_jpy is None or price_jpy <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="price_jpy が設定されていません"
            )

        amount_jpy = int(price_jpy) * data.quantity
        amount_usd = round(amount_jpy / JPY_TO_USD_RATE, 2)
        external_id = f"product_yen_{product_id}_{uuid.uuid4().hex[:8]}"

        backend_url = settings.backend_public_url.rstrip("/")
        frontend_url = settings.frontend_url.rstrip("/")
        webhook_url = f"{backend_url}/api/webhooks/one-lat"
        success_url = f"{frontend_url}/orders/complete?external_id={external_id}"
        error_url = f"{frontend_url}/orders/error?external_id={external_id}"

        checkout_data = await one_lat_client.create_checkout_preference(
            amount=amount_usd,
            currency="USD",
            title=f"Product Purchase - {product['title']}",
            external_id=external_id,
            webhook_url=webhook_url,
            success_url=success_url,
            error_url=error_url,
            payer_email=user.get("email"),
            payer_name=user.get("username")
        )

        metadata = {
            "quantity": data.quantity,
            "unit_price_jpy": price_jpy,
            "thanks_lp_id": product.get("thanks_lp_id"),
            "redirect_url": product.get("redirect_url"),
            "lp_id": product.get("lp_id"),
        }

        order_payload = {
            "user_id": user["id"],
            "seller_id": product.get("seller_id"),
            "item_type": "product",
            "item_id": product_id,
            "payment_method": "yen",
            "currency": "JPY",
            "amount_jpy": amount_jpy,
            "tax_amount_jpy": 0,
            "status": "PENDING",
            "external_id": external_id,
            "checkout_preference_id": checkout_data.get("id"),
            "metadata": metadata,
        }

        order_response = supabase.table("payment_orders").insert(order_payload).execute()
        if not order_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="注文情報の作成に失敗しました"
            )

        order_row = order_response.data[0]

        if product.get("thanks_lp_id"):
            thanks_lp_response = supabase.table("landing_pages").select("slug").eq("id", product["thanks_lp_id"]).single().execute()
            if thanks_lp_response.data:
                thanks_lp_slug = thanks_lp_response.data.get("slug")

        return ProductPurchaseResponse(
            purchase_id=order_row["id"],
            product_id=product_id,
            product_title=product["title"],
            quantity=data.quantity,
            total_points=0,
            total_amount_jpy=amount_jpy,
            remaining_points=int(user.get("point_balance", 0)),
            payment_method="yen",
            payment_status="pending",
            purchased_at=datetime.utcnow(),
            redirect_url=product.get("redirect_url"),
            thanks_lp_slug=thanks_lp_slug,
            checkout_url=checkout_data.get("checkout_url"),
            external_id=external_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"商品購入エラー: {str(e)}"
        )
