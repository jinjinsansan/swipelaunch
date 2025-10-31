#!/usr/bin/env python3
"""
無効な公式シェア投稿を無効化するスクリプト
tweet_id: 1983483722386350559 が存在しないため無効化
"""

import sys
sys.path.insert(0, '/mnt/e/dev/Cusor/lp/backend')

from app.config import settings
from supabase import create_client

supabase = create_client(settings.supabase_url, settings.supabase_key)

# 無効な公式投稿を無効化
tweet_id = "1983483722386350559"

print(f"Searching for official post with tweet_id: {tweet_id}")

# 該当レコードを検索
response = supabase.table("official_share_posts").select("*").eq("tweet_id", tweet_id).execute()

if response.data:
    print(f"Found {len(response.data)} record(s)")
    for record in response.data:
        print(f"  - ID: {record['id']}")
        print(f"  - Note ID: {record['note_id']}")
        print(f"  - Tweet URL: {record['tweet_url']}")
        print(f"  - Is Active: {record['is_active']}")
    
    # 無効化
    print("\nDeactivating...")
    update_response = supabase.table("official_share_posts").update({
        "is_active": False
    }).eq("tweet_id", tweet_id).execute()
    
    print(f"✅ Successfully deactivated {len(update_response.data)} record(s)")
    print("\nNow users will see the tweet posting option instead of repost option.")
else:
    print("No records found with that tweet_id")
