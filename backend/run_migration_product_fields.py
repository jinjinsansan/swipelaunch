#!/usr/bin/env python3
"""
Add redirect_url and thanks_lp_id columns to products table
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

# .env ファイルから設定を読み込む
load_dotenv()

def run_migration():
    """製品テーブルに購入後リダイレクトフィールドを追加"""
    
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        print("❌ SUPABASE_URL と SUPABASE_KEY が .env ファイルに設定されていません")
        return
    
    print("🔄 マイグレーションを実行中...\n")
    print(f"Supabase URL: {supabase_url}\n")
    
    # Supabase クライアント作成
    supabase: Client = create_client(supabase_url, supabase_key)
    
    # マイグレーションSQL
    migration_sql = """
    -- Add post-purchase redirect fields to products table
    ALTER TABLE products
    ADD COLUMN IF NOT EXISTS redirect_url TEXT,
    ADD COLUMN IF NOT EXISTS thanks_lp_id UUID REFERENCES landing_pages(id) ON DELETE SET NULL;
    """
    
    try:
        # Note: Supabase Python client doesn't directly support raw SQL execution
        # You need to run this SQL in Supabase Dashboard SQL Editor
        
        print("📝 以下のSQLをSupabase DashboardのSQL Editorで実行してください:\n")
        print("="*80)
        print(migration_sql)
        print("="*80)
        print("\nまたは、Supabase CLIを使用:")
        print("supabase db execute -f migrations/add_product_post_purchase_fields.sql\n")
        
        # Try to verify if columns exist by querying a product
        try:
            response = supabase.table("products").select("*").limit(1).execute()
            if response.data and len(response.data) > 0:
                product = response.data[0]
                has_redirect = 'redirect_url' in product
                has_thanks_lp = 'thanks_lp_id' in product
                
                print("\n現在のカラム状態:")
                print(f"  redirect_url: {'✅ 存在' if has_redirect else '❌ 存在しない'}")
                print(f"  thanks_lp_id: {'✅ 存在' if has_thanks_lp else '❌ 存在しない'}")
                
                if has_redirect and has_thanks_lp:
                    print("\n✅ カラムは既に存在します！マイグレーション完了")
                else:
                    print("\n⚠️  カラムがまだ存在しません。上記のSQLを実行してください。")
            else:
                print("\n⚠️  製品テーブルにデータがないため、カラムの存在を確認できません")
        except Exception as e:
            print(f"\n⚠️  カラムチェック中にエラー: {str(e)}")
    
    except Exception as e:
        print(f"❌ エラー: {str(e)}")

if __name__ == "__main__":
    run_migration()
