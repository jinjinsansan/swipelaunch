from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from app.config import settings
from pydantic import BaseModel
from typing import Optional, List
import jwt

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBearer()

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

def get_current_user(credentials: HTTPAuthorizationCredentials) -> dict:
    """トークンから現在のユーザー情報を取得"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無効なトークンです"
            )
        
        supabase = get_supabase()
        user_response = supabase.table("users").select("*").eq("id", user_id).single().execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ユーザーが見つかりません"
            )
        
        return user_response.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="トークンの検証に失敗しました"
        )

def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """管理者権限チェック"""
    user = get_current_user(credentials)
    
    # 管理者メールアドレスのホワイトリスト
    ADMIN_EMAILS = [
        "admin@swipelaunch.com",
        "goldbenchan@gmail.com",
        "kusanokiyoshi1@gmail.com"
    ]
    
    # 管理者フラグをチェック（usersテーブルにis_adminカラムがある想定）
    # または特定のメールアドレスをハードコード
    if not user.get("is_admin") and user.get("email") not in ADMIN_EMAILS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理者権限が必要です"
        )
    
    return user

# リクエスト・レスポンスモデル
class GrantPointsRequest(BaseModel):
    user_id: str
    amount: int
    description: Optional[str] = "管理者によるポイント付与"

class GrantPointsResponse(BaseModel):
    transaction_id: str
    user_id: str
    username: str
    amount: int
    new_balance: int
    description: str
    granted_at: str

class UserSearchResponse(BaseModel):
    id: str
    username: str
    email: str
    user_type: str
    point_balance: int
    created_at: str

class UserListResponse(BaseModel):
    data: List[UserSearchResponse]
    total: int

@router.post("/points/grant", response_model=GrantPointsResponse)
async def grant_points(
    data: GrantPointsRequest,
    admin: dict = Depends(require_admin)
):
    """
    管理者がユーザーにポイントを付与
    
    - **user_id**: ポイントを付与するユーザーID
    - **amount**: 付与するポイント数（マイナスも可能）
    - **description**: 付与理由
    """
    try:
        supabase = get_supabase()
        
        # ユーザー情報取得
        user_response = supabase.table("users").select("username, point_balance").eq("id", data.user_id).single().execute()
        
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定されたユーザーが見つかりません"
            )
        
        user = user_response.data
        current_balance = user.get("point_balance", 0)
        new_balance = current_balance + data.amount
        
        # マイナス残高を許可しない
        if new_balance < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ポイント残高がマイナスになります（現在: {current_balance}、変更: {data.amount}）"
            )
        
        # ポイント残高を更新
        supabase.table("users").update({"point_balance": new_balance}).eq("id", data.user_id).execute()
        
        # トランザクション記録
        transaction_data = {
            "user_id": data.user_id,
            "transaction_type": "admin_grant",
            "amount": data.amount,
            "description": f"{data.description} (管理者: {admin['username']})"
        }
        
        transaction_response = supabase.table("point_transactions").insert(transaction_data).execute()
        
        if not transaction_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="トランザクション記録に失敗しました"
            )
        
        transaction = transaction_response.data[0]
        
        return GrantPointsResponse(
            transaction_id=transaction["id"],
            user_id=data.user_id,
            username=user["username"],
            amount=data.amount,
            new_balance=new_balance,
            description=data.description,
            granted_at=transaction["created_at"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ポイント付与エラー: {str(e)}"
        )

@router.get("/users/search", response_model=UserListResponse)
async def search_users(
    query: Optional[str] = Query(None, description="ユーザー名またはメールアドレスで検索"),
    user_type: Optional[str] = Query(None, description="ユーザータイプでフィルター（seller/buyer）"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(require_admin)
):
    """
    ユーザー検索（管理者専用）
    
    - **query**: ユーザー名またはメールアドレスで検索
    - **user_type**: ユーザータイプでフィルター
    - **limit**: 取得件数
    - **offset**: オフセット
    """
    try:
        supabase = get_supabase()
        
        # クエリ構築
        db_query = supabase.table("users").select("id, username, email, user_type, point_balance, created_at")
        
        if query:
            # username または email で検索（部分一致）
            db_query = db_query.or_(f"username.ilike.%{query}%,email.ilike.%{query}%")
        
        if user_type:
            db_query = db_query.eq("user_type", user_type)
        
        # 件数取得
        count_response = db_query.execute()
        total = len(count_response.data) if count_response.data else 0
        
        # データ取得（ページネーション）
        db_query = db_query.order("created_at", desc=True).range(offset, offset + limit - 1)
        response = db_query.execute()
        
        users = [UserSearchResponse(**user) for user in response.data] if response.data else []
        
        return UserListResponse(
            data=users,
            total=total
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ユーザー検索エラー: {str(e)}"
        )
