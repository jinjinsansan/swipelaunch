from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
from supabase import create_client, Client

class Settings(BaseSettings):
    # Supabase
    supabase_url: str = "https://lvfmajyxrcvcfqtgornn.supabase.co"
    supabase_key: str = ""
    supabase_service_role_key: Optional[str] = Field(default=None, env="SUPABASE_SERVICE_ROLE_KEY")
    
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
    frontend_url: str = Field(default="https://d-swipe.com", env="FRONTEND_URL")
    backend_public_url: str = Field(default="https://swipelaunch-backend.onrender.com", env="BACKEND_PUBLIC_URL")
    default_exchange_rate_usd_jpy: float = Field(default=147.0, env="DEFAULT_EXCHANGE_RATE_USD_JPY")
    default_exchange_spread_jpy: float = Field(default=3.0, env="DEFAULT_EXCHANGE_SPREAD_JPY")
    default_platform_fee_percent: float = Field(default=10.0, env="DEFAULT_PLATFORM_FEE_PERCENT")
    account_share_invite_expiry_days: int = Field(default=7, env="ACCOUNT_SHARE_INVITE_EXPIRY_DAYS")
    
    # Security
    jwt_secret: str = "your-super-secret-jwt-key-change-this-in-production"
    api_key: str = "your-api-key-for-internal-calls"
    access_token_expires_minutes: int = 60 * 24
    operator_message_super_admin_emails: List[str] = Field(
        default_factory=lambda: [
            "goldbenchan@gmail.com",
            "kusanokiyoshi1@gmail.com",
        ],
        env="OPERATOR_MESSAGE_SUPER_ADMIN_EMAILS",
    )
    secret_memo_password: str = Field(default="kusano", env="SECRET_MEMO_PASSWORD")

    # Mailgun
    mailgun_api_key: Optional[str] = Field(default=None, env="MAILGUN_API_KEY")
    mailgun_domain: Optional[str] = Field(default=None, env="MAILGUN_DOMAIN")
    mailgun_base_url: str = Field(default="https://api.mailgun.net/v3", env="MAILGUN_BASE_URL")
    mailgun_default_from_name: Optional[str] = Field(default=None, env="MAILGUN_DEFAULT_FROM_NAME")
    mailgun_default_from_email: Optional[str] = Field(default=None, env="MAILGUN_DEFAULT_FROM_EMAIL")
    mailgun_default_reply_to: Optional[str] = Field(default=None, env="MAILGUN_DEFAULT_REPLY_TO")
    mailgun_request_timeout: float = Field(default=10.0, env="MAILGUN_REQUEST_TIMEOUT")
    mailgun_max_batch_size: int = Field(default=200, env="MAILGUN_MAX_BATCH_SIZE")

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    
    # OpenAI
    openai_api_key: Optional[str] = None
    
    # ONE.lat Payment Gateway
    one_lat_api_key: str = ""
    one_lat_api_secret: str = ""
    one_lat_api_base_url: str = "https://api.one.lat"
    one_lat_checkout_base_url: str = "https://one.lat/checkout"
    one_lat_plan_980_id: str = Field(default="1N7ZtYUvoEy5F4RDwn", env="ONE_LAT_PLAN_980_ID")
    one_lat_plan_1980_id: str = Field(default="Y6Dm9IXNUL4Jj1BuqP", env="ONE_LAT_PLAN_1980_ID")
    one_lat_plan_2980_id: str = Field(default="vE7JKQGEJE1bHd8Cj6", env="ONE_LAT_PLAN_2980_ID")
    one_lat_plan_4980_id: str = Field(default="dbTiCPa2593wT5vNEX", env="ONE_LAT_PLAN_4980_ID")
    one_lat_plan_9980_id: str = Field(default="uwBFYVO2g7JFQ2Dqnc", env="ONE_LAT_PLAN_9980_ID")
    
    # X (Twitter) API
    x_api_client_id: str = ""
    x_api_client_secret: str = ""
    x_api_bearer_token: str = ""
    x_oauth_callback_url: str = "https://swipelaunch-backend.onrender.com/api/auth/x/callback"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

def get_settings():
    return Settings()

settings = Settings()

def get_supabase_client() -> Client:
    """Supabaseクライアントを取得"""
    return create_client(settings.supabase_url, settings.supabase_key)
