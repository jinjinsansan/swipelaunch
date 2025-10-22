from pydantic_settings import BaseSettings
from typing import Optional
from supabase import create_client, Client

class Settings(BaseSettings):
    # Supabase
    supabase_url: str = "https://lvfmajyxrcvcfqtgornn.supabase.co"
    supabase_key: str = ""
    
    # Cloudflare R2
    cloudflare_r2_account_id: str = ""
    cloudflare_r2_access_key: str = ""
    cloudflare_r2_secret_key: str = ""
    cloudflare_r2_bucket_name: str = "swipelaunch-media"
    cloudflare_r2_public_url: str = ""
    
    # Redis
    redis_url: str = ""
    
    # App
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    frontend_url: str = "https://swipe.dlogicai.in"
    
    # Security
    jwt_secret: str = "your-super-secret-jwt-key-change-this-in-production"
    api_key: str = "your-api-key-for-internal-calls"
    access_token_expires_minutes: int = 60 * 24

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    
    # OpenAI
    openai_api_key: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = False

def get_settings():
    return Settings()

settings = Settings()

def get_supabase_client() -> Client:
    """Supabaseクライアントを取得"""
    return create_client(settings.supabase_url, settings.supabase_key)
