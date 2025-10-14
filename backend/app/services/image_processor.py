from PIL import Image
import io
from typing import Tuple, Optional

class ImageProcessor:
    """画像処理サービス"""
    
    def __init__(self):
        self.max_width = 2000  # 最大幅
        self.max_height = 2000  # 最大高さ
        self.jpeg_quality = 85  # JPEG品質
        self.webp_quality = 80  # WebP品質
    
    def optimize_image(
        self,
        image_bytes: bytes,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        output_format: str = "JPEG"
    ) -> Tuple[bytes, str]:
        """
        画像を最適化
        
        Args:
            image_bytes: 元の画像データ
            max_width: 最大幅（デフォルト: 2000）
            max_height: 最大高さ（デフォルト: 2000）
            output_format: 出力フォーマット（JPEG, PNG, WEBP）
        
        Returns:
            (最適化された画像データ, Content-Type)
        """
        try:
            # 画像を開く
            image = Image.open(io.BytesIO(image_bytes))
            
            # RGBに変換（透明度がある場合は背景を白に）
            if image.mode in ('RGBA', 'LA', 'P'):
                if output_format.upper() == 'JPEG':
                    # JPEGは透明度をサポートしないので、白背景に変換
                    background = Image.new('RGB', image.size, (255, 255, 255))
                    if image.mode == 'P':
                        image = image.convert('RGBA')
                    background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                    image = background
            
            # リサイズ
            max_w = max_width or self.max_width
            max_h = max_height or self.max_height
            
            if image.width > max_w or image.height > max_h:
                image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            
            # 出力
            output = io.BytesIO()
            output_format = output_format.upper()
            
            if output_format == 'JPEG':
                image.save(output, format='JPEG', quality=self.jpeg_quality, optimize=True)
                content_type = 'image/jpeg'
            elif output_format == 'PNG':
                image.save(output, format='PNG', optimize=True)
                content_type = 'image/png'
            elif output_format == 'WEBP':
                image.save(output, format='WEBP', quality=self.webp_quality)
                content_type = 'image/webp'
            else:
                # デフォルトはJPEG
                image.save(output, format='JPEG', quality=self.jpeg_quality, optimize=True)
                content_type = 'image/jpeg'
            
            output.seek(0)
            return output.read(), content_type
            
        except Exception as e:
            raise Exception(f"画像処理エラー: {str(e)}")
    
    def validate_image(self, image_bytes: bytes) -> bool:
        """
        画像が有効かチェック
        
        Args:
            image_bytes: 画像データ
        
        Returns:
            有効ならTrue
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image.verify()
            return True
        except Exception:
            return False
    
    def get_image_info(self, image_bytes: bytes) -> dict:
        """
        画像情報を取得
        
        Args:
            image_bytes: 画像データ
        
        Returns:
            画像情報（幅、高さ、フォーマット）
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            return {
                "width": image.width,
                "height": image.height,
                "format": image.format,
                "mode": image.mode,
                "size_bytes": len(image_bytes)
            }
        except Exception as e:
            raise Exception(f"画像情報取得エラー: {str(e)}")

# シングルトンインスタンス
image_processor = ImageProcessor()
