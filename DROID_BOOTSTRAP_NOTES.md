## プロジェクト概要

- ルート `/mnt/e/dev/Cusor/lp` はモノレポ構成で、FastAPI バックエンドと Next.js フロントエンドをそれぞれ `backend/` と `frontend/` 配下に保持しています。
- ルート自体が Git 管理されており、さらに `backend/.git`・`frontend/.git` が存在するため、**サブリポ構造**になっています。変更作業時はどの Git レポジトリを更新するかを必ず確認してください。

## ディレクトリ早見表

| パス | 役割 |
| --- | --- |
| `backend/app/main.py` | FastAPI のエントリポイント。`app` インスタンスを定義し、ルーターをマウント。 |
| `backend/app/routes/` | API ルーター群。`lp.py`, `ai.py`, `products.py` 等でエンドポイントを提供。 |
| `backend/app/models/` | Pydantic モデル。LP/CTA/AI 入出力定義など。 |
| `backend/app/services/` | 外部サービス連携。`ai_service.py` は OpenAI 連携、`storage.py` は Cloudflare R2。 |
| `backend/migrations/` & `*.sql` | Supabase(PostgreSQL) 用スキーマ変更 SQL。`lp_steps` に `content_data` などを追加。 |
| `backend/venv/` | Python 仮想環境。必要に応じて `./venv/bin/python` 経由で実行。 |
| `frontend/src/app/` | Next.js App Router ルート。エディタ・ダッシュボードなどのページ。 |
| `frontend/public/` | 画像・静的アセット。 |
| `frontend/package.json` | 依存関係とスクリプト (`dev`, `build`, `lint` 等)。 |

## バックエンド立ち上げ手順

1. 依存関係インストール
   ```bash
   cd /mnt/e/dev/Cusor/lp/backend
   ./venv/bin/pip install -r requirements.txt
   ```

2. 環境変数
   - `.env` は既存。Supabase URL/KEY、Cloudflare R2 認証、OpenAI API Key を設定。
   - `app/config.py` (`Settings`) が参照。未設定の場合は Supabase/API 呼び出しが失敗。

3. 実行コマンド
   ```bash
   cd /mnt/e/dev/Cusor/lp/backend
   ./venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. 主要エンドポイント
   - `POST /ai/wizard`: AIウィザード構成生成。
   - `POST /lp/{lp_id}/steps`: AI生成ブロック保存。`image_url` は空文字許容。
   - `POST /media/upload`: Cloudflare R2 経由でメディアアップロード。

5. テスト
   - 現状自動テストなし。最低限 `python3 -m compileall backend/app` で構文チェック。

## フロントエンド立ち上げ手順

1. 依存関係インストール
   ```bash
   cd /mnt/e/dev/Cusor/lp/frontend
   npm install
   ```

2. 環境変数
   - `.env.local` は未コミット。Supabase 公開 URL / anon key、バックエンド API URL を設定。
   - ビルド時は Vercel 環境変数を参照 (例: `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_SUPABASE_URL` 等)。

3. 開発サーバ
   ```bash
   npm run dev
   ```
   - デフォルトポート: `http://localhost:3000`。

4. 主要エリア
   - `src/app/page.tsx`: ダッシュボードトップ。
   - `src/app/(dashboard)/lp/[id]/edit/page.tsx`: LPエディタ。AI生成後のブロック自動保存処理あり。
   - `src/lib/`: API クライアント・テンプレート関連ユーティリティ (※実装状況は要確認)。

## AIウィザード関連メモ

- バックエンド `AIService.generate_lp_structure` が JSON 応答を生成し、フロントから Supabase の `lp_steps` へ保存します。
- `lp.py` の `create_step` は `image_url` 未指定時に空文字を保存し、`content_data` にブロックペイロードを保持します。
- 不具合が起きた場合は、**Supabase にステップが作成されているか (image_url 空文字許容)** と **AIレスポンス内容** を確認。

## デプロイ&運用メモ

- バックエンド: Render (サービス名: `swipelaunch-backend` 推定)。`requirements.txt` / `Dockerfile` ベースで起動。
- フロントエンド: Vercel (`https://swipe.dlogicai.in`)。`npm run build` → `npm run start`。
- CORS 設定: `backend/app/config.py` の `frontend_url` を本番 URL に合わせて更新済み。

## Git 運用注意

- ルートで作業する場合: `git status` で `backend/`・`frontend/` の変更をまとめて追跡。
- 各ディレクトリの `.git` を直接操作する場合は、ルートとの競合に注意 (コミット重複に要警戒)。
- コミット時は既存のメッセージスタイル (英語の短い説明 + 必要なら詳細メッセージ / Co-authored line) を踏襲。

## よく使うコマンドまとめ

```bash
# ルートで直近コミット確認
git log --oneline -5

# バックエンド起動 (ホットリロード)
cd backend && ./venv/bin/python -m uvicorn app.main:app --reload

# フロントエンド起動
cd frontend && npm run dev

# Python 構文チェック
cd backend && python3 -m compileall app
```

---
次回着任時は、上記メモを参照してプロジェクト構造・起動コマンドを即時把握してください。さらに詳細が必要な場合は `API_SPECIFICATION.md` や `IMPLEMENTATION_PLAN.md` を参照。最新の不具合情報は会話ログまたは Issue で共有される想定です。
