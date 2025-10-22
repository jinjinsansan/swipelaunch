# スワイプ型LP制作プラットフォーム 詳細設計書

## 1. プロジェクト概要

### 1.1 サービス名
**Ｄ－swipe**（仮称）

### 1.2 サービスコンセプト
商材販売者が手軽にスワイプ型LPを作成・公開でき、エンドユーザーへ商材を販売できるプラットフォーム。LPcatsの低価格版として、必要十分な機能を提供。

### 1.3 主要ユーザー
1. **商材販売者**（メインユーザー）：LP作成・商材販売
2. **エンドユーザー**：LPを閲覧・商材購入

### 1.4 開発期間
**2ヶ月以内**（フェーズ1: MVP → フェーズ2: 機能拡張）

---

## 2. システムアーキテクチャ

### 2.1 全体構成

```
┌─────────────────────────────────────────────────────────┐
│                    クライアント層                          │
├─────────────────────────────────────────────────────────┤
│  管理画面           │  LP公開ページ      │  商材購入ページ │
│  (Next.js)         │  (Next.js)        │  (Next.js)     │
└─────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│                  API Gateway層                           │
├─────────────────────────────────────────────────────────┤
│              Next.js API Routes + FastAPI               │
│     認証・認可 / レート制限 / ロギング                     │
└─────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│                   ビジネスロジック層                       │
├─────────────────────────────────────────────────────────┤
│  LP管理      │  ユーザー管理  │  決済処理  │  分析エンジン │
│  (FastAPI)   │  (Supabase)   │  (FastAPI) │  (FastAPI)   │
└─────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────┐
│                     データ層                              │
├─────────────────────────────────────────────────────────┤
│  PostgreSQL    │  Redis Cache  │  S3/R2 Storage         │
│  (Supabase)    │  (Upstash)    │  (Cloudflare R2)       │
└─────────────────────────────────────────────────────────┘
```

### 2.2 ドメイン構成
- **管理画面**: `admin.swipelaunch.com`（仮）
- **LP公開**: `swipelaunch.com/{seller_id}/{lp_id}`
- **商材購入**: `swipelaunch.com/product/{product_id}`

---

## 3. 技術スタック

### 3.1 フロントエンド
| 技術 | 用途 | 既存システムとの統一 |
|------|------|---------------------|
| Next.js 14 | フレームワーク | ✅ |
| React 18 | UI構築 | ✅ |
| TypeScript | 型安全性 | ✅ |
| Tailwind CSS | スタイリング | ✅ |
| Framer Motion | アニメーション（スワイプ） | ✅ |
| Swiper.js | スワイプ機能 | ➕新規 |
| Zustand | 状態管理 | ✅ |
| React Hook Form | フォーム管理 | ➕新規 |

### 3.2 バックエンド
| 技術 | 用途 | 既存システムとの統一 |
|------|------|---------------------|
| FastAPI | APIサーバー | ✅ |
| Python 3.11+ | 開発言語 | ✅ |
| Pydantic | データバリデーション | ✅ |
| Supabase | 認証・DB | ✅ |
| PostgreSQL | メインDB | ✅ |
| Redis (Upstash) | キャッシュ・セッション | ✅ |
| Cloudflare R2 | 画像・動画ストレージ | ➕新規 |

### 3.3 インフラ
| 技術 | 用途 |
|------|------|
| Vercel | フロントエンドホスティング |
| Render / Railway | バックエンドホスティング |
| Cloudflare R2 | メディアストレージ（低コスト） |
| Supabase | DB・認証 |

---

## 4. データベース設計

### 4.1 主要テーブル

#### 4.1.1 users（ユーザー）
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email VARCHAR(255) UNIQUE NOT NULL,
  username VARCHAR(100) UNIQUE NOT NULL,
  user_type VARCHAR(20) NOT NULL, -- 'seller' or 'buyer'
  point_balance INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

#### 4.1.2 landing_pages（LP情報）
```sql
CREATE TABLE landing_pages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  seller_id UUID REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL,
  slug VARCHAR(100) UNIQUE NOT NULL, -- URL用スラッグ
  status VARCHAR(20) DEFAULT 'draft', -- 'draft', 'published', 'archived'
  swipe_direction VARCHAR(20) DEFAULT 'vertical', -- 'vertical' or 'horizontal'
  is_fullscreen BOOLEAN DEFAULT false,
  total_views INTEGER DEFAULT 0,
  total_cta_clicks INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

#### 4.1.3 lp_steps（LPステップ）
```sql
CREATE TABLE lp_steps (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  step_order INTEGER NOT NULL,
  image_url TEXT NOT NULL,
  video_url TEXT,
  animation_type VARCHAR(50), -- 'fade', 'slide', 'arrow'
  step_views INTEGER DEFAULT 0,
  step_exits INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);
```

#### 4.1.4 lp_ctas（CTAボタン）
```sql
CREATE TABLE lp_ctas (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  step_id UUID REFERENCES lp_steps(id) ON DELETE SET NULL, -- NULL=全体共通
  cta_type VARCHAR(50) NOT NULL, -- 'link', 'form', 'product', 'newsletter', 'line'
  button_image_url TEXT NOT NULL,
  button_position VARCHAR(20) DEFAULT 'bottom', -- 'top', 'bottom', 'floating'
  link_url TEXT,
  is_required BOOLEAN DEFAULT false, -- 次へ進むのに必須か
  click_count INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);
```

#### 4.1.5 products（商材）
```sql
CREATE TABLE products (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  seller_id UUID REFERENCES users(id) ON DELETE CASCADE,
  lp_id UUID REFERENCES landing_pages(id) ON DELETE SET NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  price_in_points INTEGER NOT NULL,
  stock_quantity INTEGER,
  is_available BOOLEAN DEFAULT true,
  total_sales INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

#### 4.1.6 point_transactions（ポイント取引）
```sql
CREATE TABLE point_transactions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  transaction_type VARCHAR(50) NOT NULL, -- 'purchase', 'sale', 'refund', 'commission'
  amount INTEGER NOT NULL, -- 正=増加、負=減少
  related_product_id UUID REFERENCES products(id),
  description TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

#### 4.1.7 lp_analytics（LP分析データ）
```sql
CREATE TABLE lp_analytics (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  total_sessions INTEGER DEFAULT 0,
  unique_visitors INTEGER DEFAULT 0,
  avg_time_on_page FLOAT,
  conversion_rate FLOAT,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(lp_id, date)
);
```

#### 4.1.8 ab_tests（ABテスト）
```sql
CREATE TABLE ab_tests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lp_id UUID REFERENCES landing_pages(id) ON DELETE CASCADE,
  test_name VARCHAR(255) NOT NULL,
  variant_a_id UUID REFERENCES lp_steps(id),
  variant_b_id UUID REFERENCES lp_steps(id),
  status VARCHAR(20) DEFAULT 'running', -- 'running', 'paused', 'completed'
  traffic_split INTEGER DEFAULT 50, -- A側のトラフィック比率(%)
  winner VARCHAR(10), -- 'A', 'B', or NULL
  created_at TIMESTAMP DEFAULT NOW(),
  ended_at TIMESTAMP
);
```

---

## 5. 機能要件（優先順位付き）

### 5.1 フェーズ1: MVP（1ヶ月目）

#### 🔴 最優先機能
1. **ユーザー認証・管理**
   - メール/パスワード認証（Supabase Auth）
   - 販売者・購入者の区別
   - プロフィール編集

2. **LP作成機能**
   - 画像アップロード（ドラッグ&ドロップ）
   - ステップ順序の並び替え
   - プレビュー機能（QRコード付き）
   - 縦/横スワイプ選択
   - CTAボタン設置（画像アップロード）

3. **LP公開機能**
   - 専用URL発行（`/seller-name/lp-slug`）
   - スワイプ操作UI（Swiper.js + Framer Motion）
   - CTA固定表示（フローティング）
   - レスポンシブ対応

4. **基本分析機能**
   - ステップ別PV/離脱率
   - CTAクリック数
   - CV計測

#### 🟡 次優先機能
5. **ポイントシステム基礎**
   - ポイント購入（手動チャージ）
   - ポイント残高表示
   - 取引履歴

6. **商材管理**
   - 商材登録（タイトル・説明・価格）
   - LPと商材の紐付け
   - 在庫管理

### 5.2 フェーズ2: 機能拡張（2ヶ月目）

#### 🟢 重要機能
7. **必須アクション機能**
   - メルマガ登録必須ゲート
   - LINE連携必須ゲート
   - 次ステップへの進行制御

8. **ポイント決済完全版**
   - 商材購入フロー
   - 手数料計算（プラットフォーム収益）
   - 自動ポイント精算

9. **LP改善機能**
   - バージョン管理
   - ABテスト（1枚目のみ or 順序入替）
   - ヒートマップ風分析

10. **メディア最適化**
    - 動画アップロード対応
    - ストリーミング配信
    - 画像自動最適化

#### 🔵 付加機能
11. **アンケート型LP**
    - HTMLブロック挿入
    - 一問一答式フォーム

12. **通知機能**
    - 売上通知
    - LP閲覧通知

---

## 6. 画面設計

### 6.1 販売者側画面

#### 6.1.1 ダッシュボード
- LP一覧（作成日・ステータス・PV・CV）
- ポイント残高・売上サマリー
- クイックアクション（新規LP作成）

#### 6.1.2 LP作成画面
```
┌────────────────────────────────────┐
│  LP作成エディタ                     │
├────────────────────────────────────┤
│ [LP名] [スラッグ] [方向: 縦/横]     │
│                                    │
│ ┌──────────────┐                  │
│ │ ステップ1     │  [↑][↓] [削除]   │
│ │ [画像プレビュー] │                 │
│ └──────────────┘                  │
│ ┌──────────────┐                  │
│ │ ステップ2     │  [↑][↓] [削除]   │
│ │ [画像プレビュー] │                 │
│ └──────────────┘                  │
│ [+ ステップ追加]                    │
│                                    │
│ [CTAボタン設定]                     │
│ ┌──────────────┐                  │
│ │ [画像選択]    │                  │
│ │ リンク先: ___  │                  │
│ │ □ 必須アクション│                 │
│ └──────────────┘                  │
│                                    │
│ [プレビュー] [下書き保存] [公開]    │
└────────────────────────────────────┘
```

#### 6.1.3 分析画面
- LP別パフォーマンス
- ステップファネル（各ステップの通過率）
- 時系列グラフ（日別PV/CV）
- ABテスト結果

#### 6.1.4 商材管理画面
- 商材一覧
- 販売履歴
- ポイント精算

### 6.2 エンドユーザー側画面

#### 6.2.1 LP閲覧ページ
```
┌────────────────────────────────────┐
│     [ステップ画像全画面表示]         │
│                                    │
│                                    │
│      👆 スワイプで次へ              │
│                                    │
├────────────────────────────────────┤
│  [CTAボタン（固定表示）]            │
└────────────────────────────────────┘
```

#### 6.2.2 商材購入ページ
- 商材詳細
- ポイント残高確認
- 購入ボタン
- 購入完了（ダウンロード/アクセス情報）

---

## 7. 開発フェーズ詳細

### 7.1 フェーズ1: MVP（Week 1-4）

**Week 1-2: 基盤構築**
- プロジェクトセットアップ
- DB設計・テーブル作成
- 認証システム実装
- 基本UI/UXデザイン

**Week 3: コア機能実装**
- LP作成エディタ
- 画像アップロード（Cloudflare R2連携）
- ステップ並び替え機能

**Week 4: 公開・分析機能**
- スワイプLP表示
- 専用URL発行
- 基本分析ダッシュボード
- **MVP公開**

### 7.2 フェーズ2: 機能拡張（Week 5-8）

**Week 5: ポイントシステム**
- ポイント購入機能
- 商材登録・管理
- 購入フロー実装

**Week 6: 必須アクション機能**
- メルマガ/LINE連携ゲート
- 外部API連携（SendGrid, LINE）
- フォーム送信制御

**Week 7: 改善機能**
- バージョン管理
- ABテスト機能
- 動画対応

**Week 8: テスト・リリース**
- 統合テスト
- パフォーマンス最適化
- **正式リリース**

---

## 8. 非機能要件

### 8.1 パフォーマンス
- LP初回表示: 2秒以内
- 画像最適化: WebP変換 + CDN配信
- 同時接続: 1000セッション対応

### 8.2 セキュリティ
- HTTPS必須
- CSRF/XSS対策
- レート制限（API: 100req/min）
- ポイント取引の二重防止（トランザクション）

### 8.3 スケーラビリティ
- 画像ストレージ: 300ユーザー × 10LP × 10ステップ × 5MB = 150GB
- DB: PostgreSQL（Supabase Pro: 8GB RAM）
- Redis: セッション・キャッシュ管理

---

## 9. コスト試算（月額）

| 項目 | サービス | プラン | 費用 |
|------|---------|--------|------|
| フロントエンド | Vercel | Pro | $20 |
| バックエンド | Render | Starter | $7 |
| DB・認証 | Supabase | Pro | $25 |
| ストレージ | Cloudflare R2 | 従量課金 | ~$10 |
| Redis | Upstash | 従量課金 | ~$5 |
| ドメイン | - | - | $15 |
| **合計** | - | - | **$82** |

※ユーザー増加時は段階的にスケールアップ

---

## 10. リスク管理

### 10.1 技術リスク
| リスク | 影響 | 対策 |
|--------|------|------|
| ストレージコスト超過 | 高 | 画像圧縮・容量制限 |
| スワイプUIのブラウザ互換性 | 中 | Swiper.js利用 |
| ポイント決済の不整合 | 高 | トランザクション処理 |

### 10.2 ビジネスリスク
| リスク | 影響 | 対策 |
|--------|------|------|
| LPcatsとの差別化不足 | 高 | 低価格＋独自機能 |
| 初期ユーザー獲得難 | 中 | βテスター募集 |

---

## 11. 今後の拡張可能性

1. **AI機能**: LP自動生成・改善提案
2. **マーケットプレイス**: LP テンプレート販売
3. **外部連携**: Shopify, WordPress プラグイン
4. **多言語対応**: 英語・中国語展開

---

## 12. 変更履歴

- 2025-01-14: 初版作成
