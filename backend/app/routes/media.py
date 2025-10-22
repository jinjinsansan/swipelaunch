from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.services.storage import storage
from app.services.image_processor import image_processor
from typing import Optional, Literal

from app.utils.auth import decode_access_token

router = APIRouter(prefix="/media", tags=["media"])
security = HTTPBearer()

def get_current_user_id(credentials: HTTPAuthorizationCredentials) -> str:
    """トークンから現在のユーザーIDを取得"""
    try:
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

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    media_type: Literal["image", "video"] = Form("image"),
    optimize: bool = Form(True),
    max_width: Optional[int] = Form(None),
    max_height: Optional[int] = Form(None),
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    メディアファイルをアップロード
    
    - **file**: アップロードするファイル
    - **media_type**: メディアタイプ（image または video）
    - **optimize**: 画像最適化を行うか（デフォルト: true）
    - **max_width**: 最大幅（オプション）
    - **max_height**: 最大高さ（オプション）
    
    Returns:
        アップロードされたファイルのURL
    """
    try:
        user_id = get_current_user_id(credentials)
        
        # ファイルサイズチェック（10MB制限）
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        
        # ファイルを読み込む
        file_content = await file.read()
        
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="ファイルサイズが大きすぎます（最大10MB）"
            )
        
        # Content-Type取得
        content_type = file.content_type or "application/octet-stream"
        
        # 画像の場合の処理
        if media_type == "image":
            # 画像バリデーション
            if not image_processor.validate_image(file_content):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="無効な画像ファイルです"
                )
            
            # 画像情報取得
            image_info = image_processor.get_image_info(file_content)
            
            # 最適化
            if optimize:
                # ファイル拡張子から出力フォーマットを決定
                if file.filename:
                    ext = file.filename.lower().split('.')[-1]
                    if ext in ['jpg', 'jpeg']:
                        output_format = 'JPEG'
                    elif ext == 'png':
                        output_format = 'PNG'
                    elif ext == 'webp':
                        output_format = 'WEBP'
                    else:
                        output_format = 'JPEG'  # デフォルト
                else:
                    output_format = 'JPEG'
                
                file_content, content_type = image_processor.optimize_image(
                    file_content,
                    max_width=max_width,
                    max_height=max_height,
                    output_format=output_format
                )
                
                # ファイル名の拡張子を変更
                if file.filename:
                    base_name = '.'.join(file.filename.split('.')[:-1])
                    file.filename = f"{base_name}.{output_format.lower()}"
        
        elif media_type == "video":
            # 動画の場合はContent-Typeチェックのみ
            if not content_type.startswith("video/"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="無効な動画ファイルです"
                )
        
        # R2にアップロード
        folder = f"{media_type}s/{user_id}"  # images/user_id または videos/user_id
        file_url = storage.upload_file(
            file_content=file_content,
            file_name=file.filename or "unnamed",
            content_type=content_type,
            folder=folder
        )
        
        return {
            "url": file_url,
            "content_type": content_type,
            "size": len(file_content),
            "filename": file.filename,
            "media_type": media_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"メディアアップロードエラー: {str(e)}"
        )

@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    url: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    メディアファイルを削除
    
    - **url**: 削除するファイルのURL
    """
    try:
        user_id = get_current_user_id(credentials)
        
        # URLに自分のuser_idが含まれているか確認（セキュリティチェック）
        if f"/{user_id}/" not in url:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="このファイルを削除する権限がありません"
            )
        
        # ファイル存在確認
        if not storage.file_exists(url):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ファイルが見つかりません"
            )
        
        # 削除実行
        success = storage.delete_file(url)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ファイルの削除に失敗しました"
            )
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"メディア削除エラー: {str(e)}"
        )
