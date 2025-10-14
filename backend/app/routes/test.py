from fastapi import APIRouter, HTTPException
from supabase import create_client, Client
from app.config import settings

router = APIRouter(prefix="/test", tags=["test"])

def get_supabase() -> Client:
    """Supabaseクライアント取得"""
    return create_client(settings.supabase_url, settings.supabase_key)

@router.get("/config")
async def test_config():
    """設定確認（デバッグ用）"""
    return {
        "supabase_url": settings.supabase_url,
        "supabase_key_length": len(settings.supabase_key) if settings.supabase_key else 0,
        "supabase_key_preview": settings.supabase_key[:20] + "..." if settings.supabase_key else "NOT SET",
        "api_host": settings.api_host,
        "api_port": settings.api_port,
        "frontend_url": settings.frontend_url
    }

@router.get("/supabase")
async def test_supabase_connection():
    """Supabase接続テスト"""
    try:
        supabase = get_supabase()
        
        # テーブル一覧を取得
        response = supabase.table('users').select("*").limit(1).execute()
        
        return {
            "status": "success",
            "message": "Supabase接続成功！",
            "supabase_url": settings.supabase_url,
            "tables_accessible": True
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Supabase接続エラー: {str(e)}"
        )

@router.get("/database-tables")
async def list_database_tables():
    """データベーステーブル一覧取得"""
    try:
        supabase = get_supabase()
        
        tables = [
            "users",
            "landing_pages",
            "lp_steps",
            "lp_ctas",
            "products",
            "point_transactions",
            "lp_analytics",
            "ab_tests"
        ]
        
        table_status = {}
        for table in tables:
            try:
                response = supabase.table(table).select("count").limit(1).execute()
                table_status[table] = "✅ OK"
            except Exception as e:
                table_status[table] = f"❌ Error: {str(e)}"
        
        return {
            "status": "success",
            "total_tables": len(tables),
            "tables": table_status
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"テーブル確認エラー: {str(e)}"
        )
