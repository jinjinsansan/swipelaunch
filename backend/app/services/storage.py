import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from app.config import settings
import uuid
from typing import Optional

class CloudflareR2Storage:
    """Cloudflare R2ストレージサービス"""
    
    def __init__(self):
        # Cloudflare R2はS3互換APIを使用
        self.s3_client = boto3.client(
            's3',
            endpoint_url=f'https://{settings.cloudflare_r2_account_id}.r2.cloudflarestorage.com',
            aws_access_key_id=settings.cloudflare_r2_access_key,
            aws_secret_access_key=settings.cloudflare_r2_secret_key,
            config=Config(signature_version='s3v4'),
            region_name='auto'
        )
        self.bucket_name = settings.cloudflare_r2_bucket_name
        self.public_url = settings.cloudflare_r2_public_url
    
    def upload_file(
        self,
        file_content: bytes,
        file_name: str,
        content_type: str,
        folder: str = "media"
    ) -> str:
        """
        ファイルをR2にアップロード
        
        Args:
            file_content: ファイルの内容（バイナリ）
            file_name: ファイル名
            content_type: Content-Type (例: image/jpeg)
            folder: フォルダ名（デフォルト: media）
        
        Returns:
            アップロードされたファイルのURL
        """
        try:
            # ユニークなファイル名を生成
            unique_id = str(uuid.uuid4())
            file_extension = file_name.split('.')[-1] if '.' in file_name else ''
            key = f"{folder}/{unique_id}.{file_extension}" if file_extension else f"{folder}/{unique_id}"
            
            # R2にアップロード
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file_content,
                ContentType=content_type
            )
            
            # 公開URLを生成
            file_url = f"{self.public_url}/{key}"
            
            return file_url
            
        except ClientError as e:
            raise Exception(f"R2アップロードエラー: {str(e)}")
    
    def delete_file(self, file_url: str) -> bool:
        """
        ファイルをR2から削除
        
        Args:
            file_url: ファイルのURL
        
        Returns:
            削除成功したらTrue
        """
        try:
            # URLからキーを抽出
            if self.public_url in file_url:
                key = file_url.replace(f"{self.public_url}/", "")
            else:
                # URLが正しくない場合
                return False
            
            # R2から削除
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=key
            )
            
            return True
            
        except ClientError as e:
            raise Exception(f"R2削除エラー: {str(e)}")
    
    def file_exists(self, file_url: str) -> bool:
        """
        ファイルがR2に存在するか確認
        
        Args:
            file_url: ファイルのURL
        
        Returns:
            存在すればTrue
        """
        try:
            # URLからキーを抽出
            if self.public_url in file_url:
                key = file_url.replace(f"{self.public_url}/", "")
            else:
                return False
            
            # ファイルの存在確認
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=key
            )
            
            return True
            
        except ClientError:
            return False

# シングルトンインスタンス
storage = CloudflareR2Storage()
