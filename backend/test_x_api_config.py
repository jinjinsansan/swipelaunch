"""
X API設定テストスクリプト
環境変数が正しく読み込まれているか確認
"""

import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("X API設定確認")
print("=" * 60)

# 環境変数チェック
x_client_id = os.getenv("X_API_CLIENT_ID")
x_client_secret = os.getenv("X_API_CLIENT_SECRET")
x_bearer_token = os.getenv("X_API_BEARER_TOKEN")
x_callback_url = os.getenv("X_OAUTH_CALLBACK_URL")

print("\n✓ 環境変数の読み込み:")
print(f"  X_API_CLIENT_ID: {'✅ 設定済み' if x_client_id else '❌ 未設定'}")
print(f"  X_API_CLIENT_SECRET: {'✅ 設定済み' if x_client_secret else '❌ 未設定'}")
print(f"  X_API_BEARER_TOKEN: {'✅ 設定済み' if x_bearer_token else '❌ 未設定'}")
print(f"  X_OAUTH_CALLBACK_URL: {x_callback_url if x_callback_url else '❌ 未設定'}")

if all([x_client_id, x_client_secret, x_bearer_token, x_callback_url]):
    print("\n✅ すべての環境変数が設定されています")
    print("\n次のステップ:")
    print("1. バックエンドサーバーを再起動してください")
    print("2. フロントエンドから X 連携をテストしてください")
    print("3. 管理者パネル (/admin/share-management) で統計を確認してください")
else:
    print("\n❌ 一部の環境変数が未設定です")
    print("   .env ファイルを確認してください")

print("\n" + "=" * 60)
