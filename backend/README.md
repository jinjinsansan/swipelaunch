# Ｄ－swipe Backend API

スワイプ型LP制作プラットフォームのバックエンドAPI

## セットアップ

### 1. 仮想環境作成（推奨）

```bash
# Windowsの場合
python -m venv venv
venv\Scripts\activate

# Linux/Macの場合
python3 -m venv venv
source venv/bin/activate
```

### 2. 依存関係インストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数設定

```bash
# .env.exampleをコピーして編集
cp .env.example .env
# .envファイルを編集して、Supabase、Cloudflare R2などの認証情報を設定
```

### 4. サーバー起動

```bash
# 開発サーバー起動
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# または
python app/main.py
```

## API確認

- **ルートURL**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **ヘルスチェック**: http://localhost:8000/health

## プロジェクト構造

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPIアプリケーション
│   ├── config.py            # 設定管理
│   ├── models/              # Pydanticモデル
│   ├── routes/              # APIルート
│   │   ├── auth.py          # 認証API
│   │   ├── lp.py            # LP管理API
│   │   ├── products.py      # 商材API
│   │   ├── analytics.py     # 分析API
│   │   └── media.py         # メディアAPI
│   ├── services/            # ビジネスロジック
│   │   ├── storage.py       # Cloudflare R2
│   │   └── image_processor.py
│   ├── middleware/          # ミドルウェア
│   │   └── auth.py
│   └── utils/               # ユーティリティ
│       └── helpers.py
├── tests/                   # テスト
├── .env                     # 環境変数（Git追跡しない）
├── .env.example             # 環境変数テンプレート
├── requirements.txt         # Python依存関係
└── README.md
```

## 開発状況

- [x] プロジェクトセットアップ
- [x] 基本的なFastAPIアプリケーション
- [ ] Supabase連携
- [ ] 認証API実装
- [ ] LP管理API実装
- [ ] メディアアップロード実装
- [ ] 分析機能実装

## 次のステップ

1. Supabaseプロジェクトを作成
2. `.env`ファイルにSupabase認証情報を設定
3. データベーステーブル作成
4. 認証APIの実装開始
