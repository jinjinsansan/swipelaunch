# AIアシスタント完全更新 実装設計書

## 目的
新しいテンプレートライブラリに完全対応し、AIが豊富なヒーローブロックから適切に選択できるようにする

## 変更ファイル

### バックエンド
1. `/backend/app/services/template_mapper.py` (新規作成) ✅
   - ヒーローメタデータ（19種類）
   - ビジネスロジックマッピング
   - テーマ親和性

2. `/backend/app/services/ai_service.py` (大幅更新)
   - ALLOWED_BLOCK_SEQUENCE を新しいブロックタイプに更新
   - ヒーロー選択ロジックの実装
   - 各ブロックのフィールド定義を新テンプレートに対応

### フロントエンド
3. `/app/lp/[id]/edit/page.tsx` (小修正)
   - AI生成後のブロック作成ロジック確認

## 新しいブロックシーケンス

```python
ALLOWED_BLOCK_SEQUENCE = [
    # ヒーロー（動的選択）
    "top-hero-1",  # or "top-hero-image-1"
    
    # 問題提起・共感
    "top-problem-1",
    
    # ハイライト・特徴
    "top-highlights-1",
    
    # ビフォーアフター
    "top-before-after-1",
    
    # 社会的証明
    "top-testimonials-1",
    
    # 特典
    "top-bonus-1",
    
    # 価格
    "top-pricing-1",
    
    # FAQ
    "top-faq-1",
    
    # 保証
    "top-guarantee-1",
    
    # 緊急性
    "top-countdown-1",
    
    # CTA
    "top-cta-1",
]
```

## ヒーロー選択ロジック

### 入力情報
- business (ジャンル)
- target (ターゲット)
- goal (目標)
- theme (テーマカラー)

### 選択基準
1. **キーワードマッチング**
   - 「投資・FX」→ hero-finance, hero-money-rain
   - 「ダイエット・筋トレ」→ hero-running-man
   - 「恋愛」→ hero-couple
   - など19パターン

2. **テーマ親和性**
   - urgent_red → hero-finance, hero-night-road
   - energy_orange → hero-running-man
   - passion_pink → hero-couple
   - power_blue → hero-book-flip, hero-keyboard
   - gold_premium → hero-gold-particles, hero-smoke

3. **フォールバック**
   - マッチなし → テーマで選択
   - 最終 → top-hero-landing

### ビデオファイル名のキーワード
- `/videos/hero-keyboard.mp4` → 「プログラミング」「Web制作」「SaaS」
- `/videos/hero-running-man.mp4` → 「ダイエット」「筋トレ」「フィットネス」
- `/videos/hero-finance-man.mp4` → 「投資」「FX」「資産運用」
- など、AIプロンプトに含めて判断させる

## OpenAIプロンプト更新

### 必須情報をプロンプトに含める
1. 全ヒーローのメタデータ
2. 各ヒーローの適合ジャンル
3. ビデオファイル名とキーワード
4. テーマカラーとの親和性

### プロンプト例
```
# 利用可能なヒーローブロック
以下の19種類のヒーローから、ユーザーのビジネスに最適なものを1つ選択してください：

1. top-hero-landing (汎用・情報鮮度) - videoUrl: /videos/pixta.mp4
   適合: 全般、情報商材
   
2. top-hero-book-flip (知識・学習) - videoUrl: /videos/hero-book-flip.mp4
   適合: 教育、資格、英語学習
   キーワード: 書籍、知識、学習
   
3. top-hero-running-man (フィットネス) - videoUrl: /videos/hero-running-man.mp4
   適合: ダイエット、筋トレ
   キーワード: 走る、ランニング、運動
   
... (全19種類を列挙)

ユーザーのビジネス: {{ business }}
ターゲット: {{ target }}
テーマ: {{ theme }}

上記を考慮し、最も効果的なヒーローブロックのIDを選択してください。
```

## フィールド定義の更新

### top-hero-1 (動画背景)
```python
{
    "title": "メインキャッチコピー",
    "subtitle": "サブキャッチコピー",
    "tagline": "タグライン",
    "highlightText": "ハイライト文字",
    "buttonText": "メインCTA",
    "buttonUrl": "/register",
    "secondaryButtonText": "サブCTA",
    "secondaryButtonUrl": "/demo",
    "backgroundVideoUrl": "/videos/hero-xxx.mp4",  # 選択されたヒーローの動画
    "textColor": "#FFFFFF",
    "backgroundColor": "#050814",
    "accentColor": theme_palette.accent,
    "buttonColor": theme_palette.primary,
}
```

### top-problem-1
```python
{
    "title": "こんなお悩みはありませんか？",
    "subtitle": "多くの方が直面する現実",
    "problems": ["問題1", "問題2", "問題3", "問題4"],
    "textColor": "#0F172A",
    "backgroundColor": "#FFFFFF",
}
```

### top-highlights-1
```python
{
    "title": "選ばれる理由",
    "tagline": "Features",
    "features": [
        {
            "icon": "🎨",
            "title": "特徴1",
            "description": "説明文"
        },
        ...
    ],
    "textColor": "#0F172A",
    "backgroundColor": "#F8FAFC",
}
```

### top-before-after-1
```python
{
    "title": "導入前と導入後の変化",
    "beforeTitle": "導入前",
    "beforeText": "課題の状態",
    "afterTitle": "導入後",
    "afterText": "解決後の状態",
    "textColor": "#0F172A",
    "backgroundColor": "#FFFFFF",
}
```

### top-testimonials-1
```python
{
    "title": "お客様の声",
    "subtitle": "導入企業や受講生のリアルな成果",
    "testimonials": [
        {
            "name": "山田太郎",
            "role": "マーケター",
            "quote": "コメント",
            "rating": 5
        },
        ...
    ],
    "textColor": "#0F172A",
    "backgroundColor": "#F8FAFC",
}
```

### top-bonus-1
```python
{
    "title": "今だけの特典",
    "subtitle": "お申込者限定",
    "bonuses": [
        {
            "title": "特典1",
            "description": "説明",
            "value": "29,800円相当"
        },
        ...
    ],
    "totalValue": "120,000円相当",
    "textColor": "#0F172A",
    "backgroundColor": "#FFFBEB",
}
```

### top-pricing-1
```python
{
    "title": "料金プラン",
    "plans": [
        {
            "name": "ベーシック",
            "price": "98,000円",
            "features": ["特徴1", "特徴2"],
            "buttonText": "申し込む",
            "highlighted": true
        }
    ],
    "textColor": "#0F172A",
    "backgroundColor": "#FFFFFF",
}
```

### top-faq-1
```python
{
    "title": "よくある質問",
    "subtitle": "導入前によくいただく質問",
    "items": [
        {
            "question": "質問",
            "answer": "回答"
        },
        ...
    ],
    "textColor": "#F8FAFC",
    "backgroundColor": "#0F172A",
}
```

### top-guarantee-1
```python
{
    "title": "30日間 全額返金保証",
    "subtitle": "安心してお試しいただけます",
    "description": "保証内容の説明",
    "badgeText": "100%保証",
    "textColor": "#0F172A",
    "backgroundColor": "#ECFDF5",
}
```

### top-countdown-1
```python
{
    "title": "特別オファー終了まで",
    "urgencyText": "締切までに参加で追加特典",
    "targetDate": "2025-12-31T23:59:59Z",
    "textColor": "#FFFFFF",
    "backgroundColor": "#DC2626",
}
```

### top-cta-1
```python
{
    "title": "今すぐ始めよう",
    "subtitle": "情報には鮮度がある",
    "buttonText": "無料で始める",
    "buttonUrl": "/register",
    "secondaryButtonText": "デモを見る",
    "secondaryButtonUrl": "/demo",
    "textColor": "#0F172A",
    "backgroundColor": "#E0F2FE",
}
```

## 実装順序

1. ✅ template_mapper.py作成
2. ✅ ai_service.pyの完全更新
3. ✅ フロントエンドの動作確認（aiToBlocks.tsが正しく処理）
4. ⏳ 本番環境でテスト実施

## テスト項目

### バックエンドテスト
- [ ] 投資・FX → top-hero-finance選択
- [ ] ダイエット → top-hero-running-man選択
- [ ] 恋愛 → top-hero-couple選択
- [ ] プログラミング → top-hero-keyboard選択
- [ ] 全11ブロックが生成される（top-hero-1, top-problem-1, ...）

### フロントエンドテスト
- [ ] AIウィザードからLP作成が成功
- [ ] 全ブロックが正常にレンダリング
- [ ] ヒーローブロックの動画が正しく表示
- [ ] 各ブロックの編集が可能
- [ ] テーマカラーが正しく適用

### エンドツーエンドテスト
1. AIウィザードで「投資・FX・副業」ジャンルを入力
2. テーマ「urgent_red」を選択
3. 生成ボタンをクリック
4. 期待結果：
   - top-hero-financeまたはtop-hero-money-rainが選択される
   - 全11ブロックが生成される
   - ブロックが正しい順序で表示される
   - 動画が再生される

## フロントエンド変更不要の理由

`/home/jinjinsansan/dswipe/lib/aiToBlocks.ts`の`convertAIResultToBlocks`関数：
- `getTemplateById(blockType)`でテンプレートを検索
- バックエンドが返す`blockType`（top-hero-1など）がフロントエンドのテンプレートIDと一致
- パレットカラーを自動適用
- テーマキーを保持

つまり、バックエンドが新しいブロックタイプを返すだけで、フロントエンドは自動的に処理します。
