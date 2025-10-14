# SwipeLaunch - Swipe型LP作成プラットフォーム

スワイプ型のランディングページを簡単に作成・公開できるプラットフォームです。

## 機能

### 認証・ユーザー管理
- JWT認証
- Seller/Buyer ロール管理
- ポイントベースの決済システム

### LP作成・管理
- LP作成・編集・削除・公開
- スワイプステップ管理（縦/横スワイプ対応）
- CTA配置と管理
- メディアアップロード（Cloudflare R2）

### 分析機能
- LP閲覧数カウント
- ステップファネル分析
- CTAクリック追跡
- イベントログ記録

### 商品・決済
- 商品管理（在庫管理付き）
- ポイント購入・消費
- トランザクション履歴

### 必須アクション
- メールアドレス収集
- LINE友達追加ゲート

## 技術スタック

### バックエンド
- FastAPI (Python)
- Supabase (PostgreSQL + Auth)
- Cloudflare R2 (画像ストレージ)
- Pillow (画像最適化)

### フロントエンド（予定）
- Next.js
- TypeScript
- Tailwind CSS
- Swiper.js

## セットアップ

### 前提条件
- Python 3.10+
- Supabaseアカウント
- Cloudflare R2アカウント

### インストール

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 環境変数設定

`.env.example`をコピーして`.env`を作成し、必要な値を設定してください。

```bash
cp .env.example .env
```

### データベースセットアップ

Supabase SQL Editorで以下のSQLファイルを実行：

1. `database_setup.sql` - 基本テーブル作成
2. `add_event_log_table.sql` - イベントログテーブル作成
3. `add_required_actions_tables.sql` - 必須アクションテーブル作成

### 起動

```bash
uvicorn app.main:app --reload
```

API: http://localhost:8000
Swagger UI: http://localhost:8000/docs

## API エンドポイント

- 認証API: 4エンドポイント
- LP管理API: 13エンドポイント
- メディアAPI: 2エンドポイント
- 公開API: 7エンドポイント
- 分析API: 2エンドポイント
- 商品管理API: 6エンドポイント
- ポイントシステムAPI: 4エンドポイント
- テストAPI: 2エンドポイント

**合計: 40エンドポイント**

詳細は`/docs`で確認できます。

## デプロイ

### Render

1. GitHubにプッシュ
2. Renderで新しいWeb Serviceを作成
3. 環境変数を設定
4. デプロイ

## ライセンス

Proprietary
