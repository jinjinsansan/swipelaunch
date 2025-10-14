# SwipeLaunch 開発環境セットアップガイド

## 目次
1. [前提条件](#前提条件)
2. [Supabase設定](#supabase設定)
3. [Cloudflare R2設定](#cloudflare-r2設定)
4. [Upstash Redis設定](#upstash-redis設定)
5. [フロントエンド環境構築](#フロントエンド環境構築)
6. [バックエンド環境構築](#バックエンド環境構築)
7. [ローカル開発開始](#ローカル開発開始)
8. [トラブルシューティング](#トラブルシューティング)

---

## 前提条件

### 必要なソフトウェア

| ソフトウェア | バージョン | インストール方法 |
|-------------|-----------|----------------|
| Node.js | 18.x 以上 | [nodejs.org](https://nodejs.org/) |
| Python | 3.11 以上 | [python.org](https://www.python.org/) |
| Git | 最新版 | [git-scm.com](https://git-scm.com/) |
| pnpm (推奨) | 最新版 | `npm install -g pnpm` |

### インストール確認

```bash
# Node.js
node --version  # v18.0.0 以上

# Python
python --version  # 3.11.0 以上

# Git
git --version

# pnpm
pnpm --version
```

---

## Supabase設定

### 1. プロジェクト作成

1. [Supabase Dashboard](https://supabase.com/dashboard) にアクセス
2. 「New Project」をクリック
3. プロジェクト情報を入力：
   - **Name**: `swipelaunch`
   - **Database Password**: 強力なパスワードを生成
   - **Region**: `Northeast Asia (Tokyo)` または最寄りのリージョン
4. 「Create new project」をクリック（約2分待機）

### 2. 認証情報取得

プロジェクト作成後、以下の情報をコピー：

1. **Settings** → **API** へ移動
2. 以下をメモ：
   - `Project URL`
   - `anon public` キー
   - `service_role` キー（秘密にする）

### 3. データベーステーブル作成

1. **SQL Editor** へ移動
2. 「New query」をクリック
3. [DESIGN_SPEC.md](./DESIGN_SPEC.md) の「4.1 主要テーブル」のSQLをコピー＆実行
4. 全テーブルが作成されたことを確認

### 4. Row Level Security (RLS) 設定

```sql
-- users テーブルのRLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own data"
  ON users FOR SELECT
  USING (auth.uid() = id);

CREATE POLICY "Users can update own data"
  ON users FOR UPDATE
  USING (auth.uid() = id);

-- landing_pages テーブルのRLS
ALTER TABLE landing_pages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Sellers can CRUD own LPs"
  ON landing_pages FOR ALL
  USING (auth.uid() = seller_id);

CREATE POLICY "Anyone can view published LPs"
  ON landing_pages FOR SELECT
  USING (status = 'published');

-- 他のテーブルも同様にRLS設定
```

### 5. Storage設定（画像バケット）

※Cloudflare R2を使用する場合は不要

1. **Storage** へ移動
2. 「New bucket」をクリック
3. **Name**: `lp-images`, **Public**: ON
4. 「Create bucket」をクリック

---

## Cloudflare R2設定

### 1. アカウント作成

1. [Cloudflare Dashboard](https://dash.cloudflare.com/) にサインアップ
2. R2が利用可能になるまで待機（即時または数時間）

### 2. バケット作成

1. 左メニュー **R2** をクリック
2. 「Create bucket」をクリック
3. **Bucket name**: `swipelaunch-media`
4. **Location**: `Automatic`
5. 「Create bucket」をクリック

### 3. API トークン作成

1. **R2** → **Manage R2 API Tokens** へ移動
2. 「Create API Token」をクリック
3. 設定：
   - **Token name**: `swipelaunch-api`
   - **Permissions**: `Admin Read & Write`
   - **TTL**: `Forever`
4. 「Create API Token」をクリック
5. 以下をメモ：
   - `Access Key ID`
   - `Secret Access Key`
   - `Endpoint URL`（例: `https://abc123.r2.cloudflarestorage.com`）

### 4. 公開ドメイン設定（オプション）

1. バケット詳細ページへ移動
2. **Settings** → **Public Access** で「Allow Access」
3. 公開URL（例: `https://pub-abc123.r2.dev`）をメモ

---

## Upstash Redis設定

### 1. アカウント作成

1. [Upstash Console](https://console.upstash.com/) にサインアップ
2. 無料プラン（10,000 commands/day）を選択

### 2. Redis データベース作成

1. 「Create Database」をクリック
2. 設定：
   - **Name**: `swipelaunch-cache`
   - **Type**: `Regional`
   - **Region**: `ap-northeast-1` (Tokyo)
3. 「Create」をクリック

### 3. 接続情報取得

1. データベース詳細ページで以下をコピー：
   - `UPSTASH_REDIS_REST_URL`
   - `UPSTASH_REDIS_REST_TOKEN`

---

## フロントエンド環境構築

### 1. プロジェクトクローン・作成

```bash
cd /mnt/e/dev/Cusor/lp

# Next.jsプロジェクト作成
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir

cd frontend
```

### 2. 依存関係インストール

```bash
pnpm install @supabase/supabase-js @supabase/auth-helpers-nextjs @supabase/ssr
pnpm install zustand
pnpm install swiper framer-motion
pnpm install react-hook-form zod
pnpm install @hookform/resolvers
pnpm install lucide-react
pnpm install clsx tailwind-merge
pnpm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
pnpm install recharts
pnpm install qrcode.react
pnpm install @types/qrcode.react -D
pnpm install react-hot-toast
pnpm install date-fns
```

### 3. 環境変数設定

**`.env.local`**
```env
# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://xxxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# バックエンドAPI
NEXT_PUBLIC_API_URL=http://localhost:8000

# アプリケーション
NEXT_PUBLIC_APP_URL=http://localhost:3000
NEXT_PUBLIC_APP_NAME=SwipeLaunch

# Redis (Upstash)
UPSTASH_REDIS_REST_URL=https://xxx.upstash.io
UPSTASH_REDIS_REST_TOKEN=xxxxx
```

### 4. TypeScript設定

**`tsconfig.json`** に以下を追加：
```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

### 5. Tailwind設定

**`tailwind.config.ts`**
```typescript
import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          500: '#3b82f6',
          700: '#1d4ed8',
        },
      },
    },
  },
  plugins: [],
}
export default config
```

---

## バックエンド環境構築

### 1. プロジェクト作成

```bash
cd /mnt/e/dev/Cusor/lp

# バックエンドディレクトリ作成
mkdir backend
cd backend

# 仮想環境作成
python -m venv venv

# 仮想環境有効化
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 2. 依存関係インストール

```bash
pip install fastapi==0.116.1
pip install uvicorn[standard]==0.35.0
pip install supabase>=2.4.0
pip install python-multipart==0.0.20
pip install pydantic==2.11.7
pip install python-dotenv>=0.19.0
pip install pillow>=10.0.0
pip install boto3>=1.28.0
pip install redis>=4.0.0
pip install httpx>=0.24.0
pip install pyjwt>=2.8.0
pip install python-jose[cryptography]

# requirements.txt生成
pip freeze > requirements.txt
```

### 3. 環境変数設定

**`.env`**
```env
# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... # service_role key

# Cloudflare R2
CLOUDFLARE_R2_ACCOUNT_ID=abc123
CLOUDFLARE_R2_ACCESS_KEY=xxxxx
CLOUDFLARE_R2_SECRET_KEY=xxxxx
CLOUDFLARE_R2_BUCKET_NAME=swipelaunch-media
CLOUDFLARE_R2_PUBLIC_URL=https://pub-abc123.r2.dev

# Redis
REDIS_URL=redis://default:xxxxx@xxx.upstash.io:6379

# アプリケーション
API_HOST=0.0.0.0
API_PORT=8000
FRONTEND_URL=http://localhost:3000

# セキュリティ
JWT_SECRET=your-super-secret-jwt-key-change-this
API_KEY=your-api-key-for-internal-calls
```

### 4. プロジェクト構造作成

```bash
mkdir -p app/{models,routes,services,middleware,utils}
touch app/__init__.py
touch app/main.py
touch app/config.py
touch app/models/__init__.py
touch app/routes/__init__.py
touch app/services/__init__.py
```

### 5. FastAPI基本設定

**`app/config.py`**
```python
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_key: str
    
    # Cloudflare R2
    cloudflare_r2_account_id: str
    cloudflare_r2_access_key: str
    cloudflare_r2_secret_key: str
    cloudflare_r2_bucket_name: str
    cloudflare_r2_public_url: str
    
    # Redis
    redis_url: str
    
    # App
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    frontend_url: str
    
    # Security
    jwt_secret: str
    api_key: str
    
    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
```

**`app/main.py`**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings

app = FastAPI(title="SwipeLaunch API", version="1.0.0")

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "SwipeLaunch API is running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# ルート追加（後で実装）
# from app.routes import auth, lp, products, analytics, media
# app.include_router(auth.router)
# app.include_router(lp.router)
# app.include_router(products.router)
# app.include_router(analytics.router)
# app.include_router(media.router)
```

---

## ローカル開発開始

### 1. バックエンド起動

```bash
cd /mnt/e/dev/Cusor/lp/backend

# 仮想環境有効化
source venv/bin/activate  # or venv\Scripts\activate on Windows

# サーバー起動
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

ブラウザで確認: http://localhost:8000
Swagger UI: http://localhost:8000/docs

### 2. フロントエンド起動

```bash
cd /mnt/e/dev/Cusor/lp/frontend

# 開発サーバー起動
pnpm dev
```

ブラウザで確認: http://localhost:3000

### 3. 開発フロー

1. **新機能開発時**:
   ```bash
   # 新しいブランチ作成
   git checkout -b feature/your-feature-name
   
   # 開発
   # ...
   
   # コミット
   git add .
   git commit -m "Add: your feature description"
   ```

2. **バックエンドAPI追加時**:
   - `app/routes/` に新しいルーターを追加
   - `app/models/` にPydanticモデル定義
   - `app/main.py` でルーター登録
   - Swagger UIで動作確認

3. **フロントエンドコンポーネント追加時**:
   - `src/components/` にコンポーネント作成
   - `src/app/` でページ作成
   - ブラウザで動作確認

---

## トラブルシューティング

### Supabase接続エラー

**症状**: `Error: Invalid Supabase URL`

**解決策**:
```bash
# .env.local の NEXT_PUBLIC_SUPABASE_URL を確認
# 末尾の "/" を削除
NEXT_PUBLIC_SUPABASE_URL=https://xxxxx.supabase.co  # OK
NEXT_PUBLIC_SUPABASE_URL=https://xxxxx.supabase.co/ # NG
```

### Cloudflare R2アップロードエラー

**症状**: `AccessDenied: Access Denied`

**解決策**:
1. R2 API トークンの権限を確認（`Admin Read & Write`必須）
2. バケット名が正しいか確認
3. エンドポイントURLを確認（アカウントIDが含まれているか）

### CORS エラー

**症状**: ブラウザコンソールに `CORS policy blocked`

**解決策**:
```python
# app/main.py の CORS設定を確認
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # フロントエンドのURLと一致させる
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Node.js メモリエラー

**症状**: `JavaScript heap out of memory`

**解決策**:
```bash
# package.json の scripts に追加
"dev": "NODE_OPTIONS='--max-old-space-size=4096' next dev"
```

### Python パッケージインストールエラー

**症状**: `error: Microsoft Visual C++ 14.0 or greater is required`

**解決策**:
1. Windows: [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) をインストール
2. または、プリビルド版を使用：
   ```bash
   pip install --only-binary :all: pillow
   ```

---

## 次のステップ

開発環境が整ったら、以下を確認してください：

1. ✅ Supabaseに接続できる
2. ✅ バックエンドAPI（http://localhost:8000）が起動する
3. ✅ フロントエンド（http://localhost:3000）が起動する
4. ✅ 画像アップロードテスト（Cloudflare R2）
5. ✅ Redis接続確認

すべてOKなら、[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) に従って開発を進めましょう！

---

## 参考リンク

- [Next.js公式ドキュメント](https://nextjs.org/docs)
- [FastAPI公式ドキュメント](https://fastapi.tiangolo.com/)
- [Supabase公式ドキュメント](https://supabase.com/docs)
- [Cloudflare R2ドキュメント](https://developers.cloudflare.com/r2/)
- [Swiper公式ドキュメント](https://swiperjs.com/)
