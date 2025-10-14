# SwipeLaunch API仕様書

## 目次
1. [概要](#概要)
2. [認証](#認証)
3. [エンドポイント一覧](#エンドポイント一覧)
4. [Auth API](#auth-api)
5. [Landing Page API](#landing-page-api)
6. [Media API](#media-api)
7. [Product API](#product-api)
8. [Analytics API](#analytics-api)
9. [Point API](#point-api)
10. [エラーコード](#エラーコード)

---

## 概要

### ベースURL
- **開発環境**: `http://localhost:8000`
- **本番環境**: `https://api.swipelaunch.com`（仮）

### レスポンス形式
すべてのレスポンスはJSON形式

### HTTP ステータスコード
| コード | 説明 |
|--------|------|
| 200 | 成功 |
| 201 | 作成成功 |
| 400 | リクエスト不正 |
| 401 | 認証エラー |
| 403 | 権限なし |
| 404 | リソース未検出 |
| 500 | サーバーエラー |

---

## 認証

### 認証方式
**Bearer Token (Supabase JWT)**

リクエストヘッダーに以下を含める：
```
Authorization: Bearer <access_token>
```

### トークン取得
Supabase Authでログイン後、`access_token`を取得

---

## エンドポイント一覧

| カテゴリ | メソッド | パス | 説明 |
|---------|---------|------|------|
| **Auth** | POST | `/auth/register` | ユーザー登録 |
| | POST | `/auth/login` | ログイン |
| | GET | `/auth/me` | 現在のユーザー情報 |
| **LP** | POST | `/lp` | LP作成 |
| | GET | `/lp` | LP一覧取得 |
| | GET | `/lp/{id}` | LP詳細取得 |
| | PUT | `/lp/{id}` | LP更新 |
| | DELETE | `/lp/{id}` | LP削除 |
| | POST | `/lp/{id}/publish` | LP公開 |
| | GET | `/lp/slug/{slug}` | スラッグからLP取得 |
| **Steps** | POST | `/lp/{lp_id}/steps` | ステップ追加 |
| | PUT | `/lp/{lp_id}/steps/{step_id}` | ステップ更新 |
| | DELETE | `/lp/{lp_id}/steps/{step_id}` | ステップ削除 |
| | PUT | `/lp/{lp_id}/steps/reorder` | ステップ並び替え |
| **CTA** | POST | `/lp/{lp_id}/ctas` | CTA追加 |
| | PUT | `/ctas/{cta_id}` | CTA更新 |
| | DELETE | `/ctas/{cta_id}` | CTA削除 |
| | POST | `/ctas/{cta_id}/click` | CTAクリック記録 |
| **Media** | POST | `/media/upload` | 画像/動画アップロード |
| | DELETE | `/media` | メディア削除 |
| **Products** | POST | `/products` | 商材作成 |
| | GET | `/products` | 商材一覧 |
| | GET | `/products/{id}` | 商材詳細 |
| | PUT | `/products/{id}` | 商材更新 |
| | DELETE | `/products/{id}` | 商材削除 |
| | POST | `/products/{id}/purchase` | 商材購入 |
| **Analytics** | GET | `/analytics/lp/{lp_id}` | LP分析データ |
| | GET | `/analytics/lp/{lp_id}/funnel` | ステップファネル |
| | POST | `/analytics/track` | イベントトラッキング |
| **Points** | GET | `/points/balance` | ポイント残高 |
| | POST | `/points/charge` | ポイントチャージ |
| | GET | `/points/transactions` | 取引履歴 |

---

## Auth API

### POST /auth/register
ユーザー登録

**リクエスト**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "username": "johndoe",
  "user_type": "seller"  // 'seller' or 'buyer'
}
```

**レスポンス** (201 Created)
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "username": "johndoe",
    "user_type": "seller",
    "point_balance": 0
  },
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "..."
}
```

---

### POST /auth/login
ログイン

**リクエスト**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!"
}
```

**レスポンス** (200 OK)
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "username": "johndoe",
    "user_type": "seller"
  },
  "access_token": "...",
  "refresh_token": "..."
}
```

---

### GET /auth/me
現在のユーザー情報取得

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**レスポンス** (200 OK)
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "johndoe",
  "user_type": "seller",
  "point_balance": 1500,
  "created_at": "2025-01-14T10:00:00Z"
}
```

---

## Landing Page API

### POST /lp
LP作成

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**リクエスト**
```json
{
  "title": "新商品プロモーション",
  "slug": "new-product-promo",
  "swipe_direction": "vertical",  // 'vertical' or 'horizontal'
  "is_fullscreen": false
}
```

**レスポンス** (201 Created)
```json
{
  "id": "lp-uuid",
  "seller_id": "user-uuid",
  "title": "新商品プロモーション",
  "slug": "new-product-promo",
  "status": "draft",
  "swipe_direction": "vertical",
  "is_fullscreen": false,
  "total_views": 0,
  "total_cta_clicks": 0,
  "created_at": "2025-01-14T10:00:00Z",
  "public_url": "https://swipelaunch.com/johndoe/new-product-promo"
}
```

---

### GET /lp
LP一覧取得（自分のLPのみ）

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**クエリパラメータ**
- `status`: フィルター (`draft`, `published`, `archived`)
- `limit`: 取得件数（デフォルト: 20）
- `offset`: オフセット（デフォルト: 0）

**レスポンス** (200 OK)
```json
{
  "data": [
    {
      "id": "lp-uuid",
      "title": "新商品プロモーション",
      "slug": "new-product-promo",
      "status": "published",
      "total_views": 1523,
      "total_cta_clicks": 87,
      "created_at": "2025-01-14T10:00:00Z"
    }
  ],
  "total": 5,
  "limit": 20,
  "offset": 0
}
```

---

### GET /lp/{id}
LP詳細取得

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**レスポンス** (200 OK)
```json
{
  "id": "lp-uuid",
  "seller_id": "user-uuid",
  "title": "新商品プロモーション",
  "slug": "new-product-promo",
  "status": "published",
  "swipe_direction": "vertical",
  "is_fullscreen": false,
  "total_views": 1523,
  "total_cta_clicks": 87,
  "steps": [
    {
      "id": "step-uuid-1",
      "step_order": 0,
      "image_url": "https://pub-xxx.r2.dev/step1.jpg",
      "video_url": null,
      "animation_type": "fade",
      "step_views": 1523,
      "step_exits": 234
    },
    {
      "id": "step-uuid-2",
      "step_order": 1,
      "image_url": "https://pub-xxx.r2.dev/step2.jpg",
      "step_views": 1289,
      "step_exits": 156
    }
  ],
  "ctas": [
    {
      "id": "cta-uuid",
      "step_id": null,
      "cta_type": "link",
      "button_image_url": "https://pub-xxx.r2.dev/cta-button.png",
      "button_position": "bottom",
      "link_url": "https://example.com/product",
      "is_required": false,
      "click_count": 87
    }
  ],
  "created_at": "2025-01-14T10:00:00Z"
}
```

---

### PUT /lp/{id}
LP更新

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**リクエスト**
```json
{
  "title": "新商品プロモーション（更新）",
  "swipe_direction": "horizontal",
  "is_fullscreen": true
}
```

**レスポンス** (200 OK)
```json
{
  "id": "lp-uuid",
  "title": "新商品プロモーション（更新）",
  "swipe_direction": "horizontal",
  "is_fullscreen": true,
  "updated_at": "2025-01-14T11:00:00Z"
}
```

---

### DELETE /lp/{id}
LP削除

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**レスポンス** (204 No Content)

---

### POST /lp/{id}/publish
LP公開

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**レスポンス** (200 OK)
```json
{
  "id": "lp-uuid",
  "status": "published",
  "public_url": "https://swipelaunch.com/johndoe/new-product-promo"
}
```

---

### GET /lp/slug/{slug}
スラッグからLP取得（公開されているLPのみ）

**レスポンス** (200 OK)
```json
{
  "id": "lp-uuid",
  "title": "新商品プロモーション",
  "seller": {
    "username": "johndoe"
  },
  "steps": [...],
  "ctas": [...]
}
```

---

## Steps API

### POST /lp/{lp_id}/steps
ステップ追加

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**リクエスト**
```json
{
  "step_order": 2,
  "image_url": "https://pub-xxx.r2.dev/step3.jpg",
  "video_url": null,
  "animation_type": "slide"
}
```

**レスポンス** (201 Created)
```json
{
  "id": "step-uuid-3",
  "lp_id": "lp-uuid",
  "step_order": 2,
  "image_url": "https://pub-xxx.r2.dev/step3.jpg",
  "animation_type": "slide",
  "step_views": 0,
  "step_exits": 0
}
```

---

### PUT /lp/{lp_id}/steps/reorder
ステップ並び替え

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**リクエスト**
```json
{
  "step_orders": [
    { "id": "step-uuid-1", "order": 0 },
    { "id": "step-uuid-3", "order": 1 },
    { "id": "step-uuid-2", "order": 2 }
  ]
}
```

**レスポンス** (200 OK)
```json
{
  "message": "Steps reordered successfully",
  "updated_count": 3
}
```

---

## CTA API

### POST /lp/{lp_id}/ctas
CTA追加

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**リクエスト**
```json
{
  "step_id": null,  // null = 全ステップ共通
  "cta_type": "newsletter",  // 'link', 'form', 'product', 'newsletter', 'line'
  "button_image_url": "https://pub-xxx.r2.dev/cta.png",
  "button_position": "bottom",  // 'top', 'bottom', 'floating'
  "link_url": "https://example.com/signup",
  "is_required": true  // 次へ進むのに必須
}
```

**レスポンス** (201 Created)
```json
{
  "id": "cta-uuid",
  "lp_id": "lp-uuid",
  "step_id": null,
  "cta_type": "newsletter",
  "button_image_url": "https://pub-xxx.r2.dev/cta.png",
  "button_position": "bottom",
  "link_url": "https://example.com/signup",
  "is_required": true,
  "click_count": 0
}
```

---

### POST /ctas/{cta_id}/click
CTAクリック記録（トラッキング用）

**リクエスト**
```json
{
  "session_id": "session-uuid",
  "timestamp": "2025-01-14T12:00:00Z"
}
```

**レスポンス** (200 OK)
```json
{
  "message": "Click recorded",
  "new_click_count": 88
}
```

---

## Media API

### POST /media/upload
画像/動画アップロード

**ヘッダー**
```
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

**リクエスト**
```
form-data:
  file: <binary>
```

**レスポンス** (201 Created)
```json
{
  "url": "https://pub-xxx.r2.dev/abc123.jpg",
  "file_name": "abc123.jpg",
  "file_size": 245678,
  "content_type": "image/jpeg"
}
```

**エラー** (400 Bad Request)
```json
{
  "error": "File too large. Max size: 10MB"
}
```

---

### DELETE /media
メディア削除

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**リクエスト**
```json
{
  "url": "https://pub-xxx.r2.dev/abc123.jpg"
}
```

**レスポンス** (204 No Content)

---

## Product API

### POST /products
商材作成

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**リクエスト**
```json
{
  "lp_id": "lp-uuid",
  "title": "プレミアムコース",
  "description": "1年間のプレミアムアクセス",
  "price_in_points": 5000,
  "stock_quantity": 100,
  "is_available": true
}
```

**レスポンス** (201 Created)
```json
{
  "id": "product-uuid",
  "seller_id": "user-uuid",
  "lp_id": "lp-uuid",
  "title": "プレミアムコース",
  "description": "1年間のプレミアムアクセス",
  "price_in_points": 5000,
  "stock_quantity": 100,
  "is_available": true,
  "total_sales": 0,
  "created_at": "2025-01-14T10:00:00Z"
}
```

---

### GET /products
商材一覧取得

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**クエリパラメータ**
- `seller_id`: 販売者でフィルター
- `is_available`: 販売可能なもののみ

**レスポンス** (200 OK)
```json
{
  "data": [
    {
      "id": "product-uuid",
      "title": "プレミアムコース",
      "price_in_points": 5000,
      "stock_quantity": 95,
      "total_sales": 5
    }
  ],
  "total": 3
}
```

---

### POST /products/{id}/purchase
商材購入

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**リクエスト**
```json
{
  "quantity": 1
}
```

**レスポンス** (200 OK)
```json
{
  "transaction_id": "tx-uuid",
  "product": {
    "id": "product-uuid",
    "title": "プレミアムコース"
  },
  "amount_paid": 5000,
  "new_balance": 3000,
  "purchase_date": "2025-01-14T12:00:00Z"
}
```

**エラー** (400 Bad Request)
```json
{
  "error": "Insufficient points. Required: 5000, Available: 3000"
}
```

---

## Analytics API

### GET /analytics/lp/{lp_id}
LP分析データ取得

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**クエリパラメータ**
- `start_date`: 開始日（YYYY-MM-DD）
- `end_date`: 終了日（YYYY-MM-DD）

**レスポンス** (200 OK)
```json
{
  "lp_id": "lp-uuid",
  "period": {
    "start": "2025-01-01",
    "end": "2025-01-14"
  },
  "summary": {
    "total_views": 1523,
    "unique_visitors": 987,
    "total_cta_clicks": 87,
    "conversion_rate": 8.8,
    "avg_time_on_page": 45.3
  },
  "daily_data": [
    {
      "date": "2025-01-14",
      "views": 234,
      "unique_visitors": 189,
      "cta_clicks": 12,
      "conversion_rate": 6.4
    }
  ]
}
```

---

### GET /analytics/lp/{lp_id}/funnel
ステップファネル取得

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**レスポンス** (200 OK)
```json
{
  "lp_id": "lp-uuid",
  "funnel": [
    {
      "step_order": 0,
      "step_views": 1523,
      "step_exits": 234,
      "pass_through_rate": 84.6
    },
    {
      "step_order": 1,
      "step_views": 1289,
      "step_exits": 156,
      "pass_through_rate": 87.9
    },
    {
      "step_order": 2,
      "step_views": 1133,
      "step_exits": 87,
      "pass_through_rate": 92.3
    }
  ]
}
```

---

### POST /analytics/track
イベントトラッキング

**リクエスト**
```json
{
  "event_type": "step_view",  // 'step_view', 'step_exit', 'cta_click', 'conversion'
  "lp_id": "lp-uuid",
  "step_id": "step-uuid",
  "session_id": "session-uuid",
  "timestamp": "2025-01-14T12:00:00Z"
}
```

**レスポンス** (200 OK)
```json
{
  "message": "Event tracked successfully"
}
```

---

## Point API

### GET /points/balance
ポイント残高取得

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**レスポンス** (200 OK)
```json
{
  "user_id": "user-uuid",
  "point_balance": 8000,
  "last_updated": "2025-01-14T12:00:00Z"
}
```

---

### POST /points/charge
ポイントチャージ（管理者機能）

**ヘッダー**
```
Authorization: Bearer <access_token>
X-API-Key: <admin_api_key>
```

**リクエスト**
```json
{
  "user_id": "user-uuid",
  "amount": 10000,
  "description": "Initial charge"
}
```

**レスポンス** (200 OK)
```json
{
  "transaction_id": "tx-uuid",
  "user_id": "user-uuid",
  "amount": 10000,
  "new_balance": 18000,
  "timestamp": "2025-01-14T12:00:00Z"
}
```

---

### GET /points/transactions
取引履歴取得

**ヘッダー**
```
Authorization: Bearer <access_token>
```

**クエリパラメータ**
- `limit`: 取得件数（デフォルト: 20）
- `offset`: オフセット（デフォルト: 0）

**レスポンス** (200 OK)
```json
{
  "data": [
    {
      "id": "tx-uuid",
      "transaction_type": "purchase",
      "amount": -5000,
      "description": "プレミアムコース購入",
      "related_product_id": "product-uuid",
      "created_at": "2025-01-14T12:00:00Z"
    },
    {
      "id": "tx-uuid-2",
      "transaction_type": "charge",
      "amount": 10000,
      "description": "Initial charge",
      "created_at": "2025-01-14T10:00:00Z"
    }
  ],
  "total": 2
}
```

---

## エラーコード

### 標準エラーレスポンス
```json
{
  "error": "Error message",
  "error_code": "ERROR_CODE",
  "details": {}
}
```

### エラーコード一覧

| エラーコード | HTTPステータス | 説明 |
|-------------|---------------|------|
| `UNAUTHORIZED` | 401 | 認証トークンが無効 |
| `FORBIDDEN` | 403 | アクセス権限なし |
| `NOT_FOUND` | 404 | リソースが見つからない |
| `VALIDATION_ERROR` | 400 | リクエストデータが不正 |
| `INSUFFICIENT_POINTS` | 400 | ポイント不足 |
| `FILE_TOO_LARGE` | 400 | ファイルサイズ超過 |
| `INVALID_FILE_TYPE` | 400 | ファイル形式が不正 |
| `SLUG_ALREADY_EXISTS` | 400 | スラッグが既に使用されている |
| `OUT_OF_STOCK` | 400 | 在庫切れ |
| `INTERNAL_ERROR` | 500 | サーバー内部エラー |

---

## レート制限

- **認証なし**: 10 req/min
- **認証あり**: 100 req/min
- **メディアアップロード**: 20 req/min

レート制限超過時のレスポンス：
```json
{
  "error": "Rate limit exceeded",
  "retry_after": 60
}
```

---

## Webhook（将来対応）

商材購入やLP閲覧などのイベント発生時に外部URLへ通知

**設定方法**: 管理画面でWebhook URLを登録

**ペイロード例**
```json
{
  "event": "product.purchased",
  "data": {
    "product_id": "product-uuid",
    "buyer_id": "user-uuid",
    "amount": 5000,
    "timestamp": "2025-01-14T12:00:00Z"
  }
}
```

---

## 次のステップ

API仕様書を確認したら、以下の順で実装を進めてください：

1. ✅ Supabaseテーブル作成
2. ✅ 基本的なCRUD APIから実装
3. ✅ Postman/ThunderClientでAPIテスト
4. ✅ フロントエンドから呼び出し

Swagger UI（http://localhost:8000/docs）でインタラクティブにAPIをテストできます。
