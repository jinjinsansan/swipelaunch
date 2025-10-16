#!/usr/bin/env python3
"""
既存の LP ステップで block_type が None のものを、content_data から抽出して DB に保存し直す
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

# .env ファイルから設定を読み込む
load_dotenv()

def migrate_block_types():
    """既存 DB データの block_type を正規化"""
    
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    supabase: Client = create_client(supabase_url, supabase_key)
    
    # SQL でバッチ更新
    print("🔄 SQL でバッチ更新を実行中...\n")
    
    sql_query = """
    UPDATE lp_steps
    SET block_type = content_data->>'block_type'
    WHERE block_type IS NULL 
      AND content_data IS NOT NULL 
      AND content_data->>'block_type' IS NOT NULL 
      AND trim(content_data->>'block_type') != '';
    """
    
    try:
        response = supabase.rpc("exec_sql", {"query": sql_query}).execute()
        print("⚠️ exec_sql RPC が使用できません。テーブル API で更新します...\n")
    except:
        pass
    
    # block_type が None のステップを全て取得
    response = supabase.table("lp_steps").select("id,lp_id,block_type,content_data").is_("block_type", "null").execute()
    
    if not response.data:
        print("✅ block_type が None のステップはありません")
        return
    
    total = len(response.data)
    print(f"📊 処理対象: {total} ステップ\n")
    
    updated_count = 0
    skipped_count = 0
    
    for step in response.data:
        step_id = step["id"]
        lp_id = step["lp_id"]
        content_data = step.get("content_data") or {}
        block_type_from_content = content_data.get("block_type")
        
        if isinstance(block_type_from_content, str) and len(block_type_from_content.strip()) > 0:
            # content_data から有効な block_type を抽出できた
            try:
                update_response = supabase.table("lp_steps").update({
                    "block_type": block_type_from_content
                }).eq("id", step_id).execute()
                
                if update_response.data:
                    print(f"✅ Updated: {step_id}")
                    print(f"   LP ID: {lp_id}")
                    print(f"   block_type: {block_type_from_content}\n")
                    updated_count += 1
                else:
                    print(f"⚠️ Failed to update: {step_id}\n")
                    skipped_count += 1
            except Exception as e:
                print(f"❌ Error updating {step_id}: {str(e)}\n")
                skipped_count += 1
        else:
            # content_data に block_type がない
            print(f"⚠️ Skipped: {step_id} (content_data に block_type がありません)\n")
            skipped_count += 1
    
    print(f"\n{'='*80}")
    print(f"📊 **マイグレーション完了**")
    print(f"  更新: {updated_count}/{total}")
    print(f"  スキップ: {skipped_count}/{total}")
    print(f"{'='*80}")

if __name__ == "__main__":
    migrate_block_types()
