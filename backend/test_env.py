#!/usr/bin/env python3
import os
from dotenv import load_dotenv

print("=== .env ファイル読み込みテスト ===\n")

# .envファイルを読み込む
load_dotenv()

print("1. 環境変数から取得:")
print(f"   SUPABASE_URL: {os.getenv('SUPABASE_URL')}")
print(f"   SUPABASE_KEY length: {len(os.getenv('SUPABASE_KEY', ''))}")
print()

print("2. .envファイルの内容:")
with open('.env', 'r') as f:
    for line in f:
        if 'SUPABASE' in line and not line.startswith('#'):
            # キーの値は最初の30文字のみ表示
            if '=' in line:
                key, value = line.split('=', 1)
                if 'KEY' in key:
                    print(f"   {key}={value[:30]}...")
                else:
                    print(f"   {line.strip()}")
print()

print("3. pydantic_settings で読み込み:")
from app.config import settings
print(f"   settings.supabase_url: {settings.supabase_url}")
print(f"   settings.supabase_key length: {len(settings.supabase_key)}")
print(f"   settings.supabase_key preview: {settings.supabase_key[:30]}...")
