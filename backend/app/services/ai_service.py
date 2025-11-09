import hashlib
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Literal
from uuid import uuid4

from openai import OpenAI

from app.config import settings
from app.models.ai import (
    AIWizardInput,
    BonusItem,
    Testimonial,
    NoteAIContext,
    NoteProofreadRequest,
    NoteProofreadResponse,
    NoteProofreadCorrection,
    NoteRewriteRequest,
    NoteRewriteResponse,
    NoteRewriteCandidate,
    NoteRewriteMetrics,
    NoteRewriteQuality,
    NoteRewriteCompliance,
    NoteRewriteFeedbackRequest,
    NoteRewriteExperiment,
    NoteStructureRequest,
    NoteStructureResponse,
    NoteStructureSuggestion,
    NoteReviewRequest,
    NoteReviewResponse,
    NoteReviewIssue,
)
from app.services.template_mapper import (
    select_hero_for_business,
    get_hero_metadata,
    HERO_VIDEO_TEMPLATES,
)


COLOR_THEMES: Dict[str, Dict[str, str]] = {
    "urgent_red": {
        "primary": "#DC2626",
        "secondary": "#EF4444",
        "accent": "#F97316",
        "background": "#111116",
        "text": "#F8FAFC",
    },
    "energy_orange": {
        "primary": "#EA580C",
        "secondary": "#F97316",
        "accent": "#F59E0B",
        "background": "#1A1207",
        "text": "#FFEAD5",
    },
    "gold_premium": {
        "primary": "#B45309",
        "secondary": "#D97706",
        "accent": "#FBBF24",
        "background": "#120D03",
        "text": "#FDE68A",
    },
    "power_blue": {
        "primary": "#1E40AF",
        "secondary": "#3B82F6",
        "accent": "#60A5FA",
        "background": "#0B1120",
        "text": "#E2E8F0",
    },
    "passion_pink": {
        "primary": "#BE185D",
        "secondary": "#EC4899",
        "accent": "#F472B6",
        "background": "#1B0F1B",
        "text": "#FCE7F3",
    },
}


DEFAULT_THEME = "urgent_red"

GENERIC_CTA_TITLES = {
    "今すぐ始めよう",
    "今すぐスタート",
    "今すぐ開始",
    "今すぐ行動しよう",
}

GENERIC_CTA_SUBTITLES = {
    "情報には鮮度がある。５分でLPを公開して、今すぐ販売を開始。",
    "最短で成果を手に入れましょう。",
}

GENERIC_PRIMARY_CTA_TEXTS = {
    "無料で始める",
    "無料でスタート",
    "無料体験",
}

GENERIC_SECONDARY_CTA_TEXTS = {
    "デモを見る",
    "資料請求",
}

GENERIC_BONUS_TITLES = {
    "今だけの特典",
    "限定特典",
    "申込特典",
}

GENERIC_BONUS_SUBTITLES = {
    "お申込者限定で以下の特典をプレゼント",
    "成果までの距離を一気に縮める特典を期間限定でご提供します。",
    "導入直後から成果を出すための特典を無償提供。",
}

GENERIC_BONUS_TOTAL_VALUES = {
    "合計109,800円相当",
    "合計128,000円相当",
    "合計156,000円相当",
    "合計178,000円相当",
    "合計198,000円相当",
}

GENERIC_GUARANTEE_TITLES = {
    "30日間 全額返金保証",
    "30日間の全額返金保証",
    "安心の返金保証",
    "返金保証制度",
    "Premium Assurance",
    "返金保証ポリシー",
}

GENERIC_GUARANTEE_SUBTITLES = {
    "リスクゼロで体験いただくために、安心の保証制度を用意しています。",
    "お申し込みから30日以内なら、理由を問わず返金を承ります。",
    "安心してお試しいただけます",
    "結果に納得いただけない場合は、申請だけで全額返金いたします。",
    "安心してご利用いただけるよう、初月はリスクゼロでお試しいただけます。",
    "安心してご導入いただけるよう、プレミアム保証をご用意しています。",
    "導入後30日以内であれば、全額返金に対応いたします。",
}

GENERIC_GUARANTEE_DETAILS = {
    "条件は一切ありません。実際に使ってみてご満足いただけなければ、メール一本で全額返金いたします。",
    "初回ローンチを実施して成果が得られなかった場合、メール1通で返金を申請できます。手数料は一切かかりません。",
    "導入から30日以内であれば、使用状況に関わらず全額返金いたします。",
    "サポートチームと伴走した上で成果が出なかった場合、契約初月の利用料を全額返金します。",
    "ご導入から45日以内に成果が得られなかった場合は、100%返金いたします。",
    "フォームから申請いただくだけで、3営業日以内に返金手続きを進めます。",
}

GENERIC_GUARANTEE_BADGES = {
    "Risk Free",
    "安心サポート",
    "Guarantee",
    "Premium Care",
    "Secure",
    "保証付き",
}

GENERIC_GUARANTEE_BULLETS = {
    "専任サポートが導入〜初回ローンチまで伴走",
    "再現性の高いAIプロンプトテンプレート付き",
    "返金サポート専用窓口を24時間以内に対応",
    "導入オンボーディングを専任CSがサポート",
    "プロジェクト設計テンプレートを全員に配布",
    "サポートチームが24時間以内に回答",
    "返金時もサポート担当が手続き支援",
    "返金後も問題点のフィードバックを共有",
    "継続利用の押し売りは一切なし",
    "専任コンシェルジュが返金申請をサポート",
    "返金後もナレッジ資料を30日閲覧可能",
    "解約アンケートで改善要望を反映",
    "契約期間に関わらず申請可能",
    "返金時の手数料は弊社が負担",
    "担当者が継続的にフォロー",
}

# 新しいテンプレートライブラリに対応したブロックシーケンス
BLOCK_SEQUENCE = [
    {
        "block_type": "top-hero-1",
        "template_id": None,  # 選択されたヒーローIDを使用
        "outline_label": "ヒーローセクション",
    },
    {
        "block_type": "top-problem-1",
        "template_id": "top-problem-swipe-metrics",
        "outline_label": "スワイプ型の優位性",
    },
    {
        "block_type": "top-highlights-1",
        "template_id": "top-highlights-differentiator",
        "outline_label": "競合との差別化",
    },
    {
        "block_type": "top-before-after-1",
        "template_id": "top-before-after-pricing-contrast",
        "outline_label": "料金比較",
    },
    {
        "block_type": "top-testimonials-1",
        "template_id": None,
        "outline_label": "お客様の声",
    },
    {
        "block_type": "top-bonus-1",
        "template_id": None,
        "outline_label": "申込特典",
    },
    {
        "block_type": "top-pricing-1",
        "template_id": None,
        "outline_label": "料金プラン",
    },
    {
        "block_type": "top-faq-1",
        "template_id": None,
        "outline_label": "よくある質問",
    },
    {
        "block_type": "top-guarantee-1",
        "template_id": None,
        "outline_label": "返金保証",
    },
    {
        "block_type": "top-countdown-1",
        "template_id": None,
        "outline_label": "締切カウントダウン",
    },
    {
        "block_type": "top-inline-cta-1",
        "template_id": "top-inline-cta-editor-proof",
        "outline_label": "LPエディタ証明CTA",
    },
    {
        "block_type": "top-media-spotlight-1",
        "template_id": "top-media-spotlight-handwritten",
        "outline_label": "テンプレートギャラリー",
    },
    {
        "block_type": "handwritten-hero-1",
        "template_id": "handwritten-hero-casual",
        "outline_label": "手書き風ヒーロー",
    },
    {
        "block_type": "handwritten-features-1",
        "template_id": "handwritten-features-simple",
        "outline_label": "手書き風の特徴",
    },
    {
        "block_type": "handwritten-testimonials-1",
        "template_id": "handwritten-testimonials-friendly",
        "outline_label": "手書き風の声",
    },
    {
        "block_type": "handwritten-cta-1",
        "template_id": "handwritten-cta-friendly",
        "outline_label": "手書き風CTA",
    },
    {
        "block_type": "top-cta-1",
        "template_id": "top-cta-final-call",
        "outline_label": "今すぐ申し込む",
    },
]


OUTLINE_FALLBACK_LABELS = {item["block_type"]: item["outline_label"] for item in BLOCK_SEQUENCE}


DEFAULT_TEMPLATE_VARIANTS = {
    "top-hero-1": "top-hero-dswipe-official",
    "top-problem-1": "top-problem-swipe-metrics",
    "top-highlights-1": "top-highlights-differentiator",
    "top-before-after-1": "top-before-after-pricing-contrast",
    "top-inline-cta-1": "top-inline-cta-editor-proof",
    "top-media-spotlight-1": "top-media-spotlight-handwritten",
    "top-cta-1": "top-cta-final-call",
    "handwritten-hero-1": "handwritten-hero-casual",
    "handwritten-features-1": "handwritten-features-simple",
    "handwritten-testimonials-1": "handwritten-testimonials-friendly",
    "handwritten-cta-1": "handwritten-cta-friendly",
}


def get_openai_client():
    """OpenAIクライアントを取得"""
    return OpenAI(api_key=settings.openai_api_key)


class AIService:
    """OpenAI APIを使用したAI機能"""

    @staticmethod
    async def generate_lp_structure(input_data: AIWizardInput) -> Dict[str, Any]:
        """ユーザー入力を基にLP構成・コピーを生成する"""

        theme_key = input_data.theme or DEFAULT_THEME
        palette = COLOR_THEMES.get(theme_key, COLOR_THEMES[DEFAULT_THEME])

        # ビジネス情報から最適なヒーローブロックを選択
        selected_hero_id = select_hero_for_business(
            business=input_data.business,
            target=input_data.target,
            goal=input_data.goal,
            theme=theme_key
        )
        hero_metadata = get_hero_metadata(selected_hero_id)
        
        context_json = json.dumps(input_data.dict(), ensure_ascii=False, indent=2)

        # ヒーローブロックのメタデータをプロンプトに含める
        hero_descriptions = []
        for hero in HERO_VIDEO_TEMPLATES:
            hero_descriptions.append(
                f"- {hero['id']}: {hero['name']}\n"
                f"  説明: {hero['description']}\n"
                f"  動画: {hero['videoUrl']}\n"
                f"  適合ジャンル: {', '.join(hero['suitable_for'])}\n"
                f"  キーワード: {', '.join(hero['keywords'])}"
            )
        heroes_metadata_text = "\n\n".join(hero_descriptions)

        block_sequence_description = "\n".join(
            [
                "- top-hero-1: 冒頭ヒーローセクション（動画背景・約束・CTA）",
                "- top-problem-1: 共感と課題提示（データを交えて4-5個の問題点を列挙）",
                "- top-highlights-1: 競合との差別化ポイントを3項目で提示",
                "- top-before-after-1: 導入前後の費用・成果ギャップを明示",
                "- top-testimonials-1: お客様の声・社会的証明（3件）",
                "- top-bonus-1: 申込特典の一覧（3-5個）",
                "- top-pricing-1: 料金プラン",
                "- top-faq-1: よくある質問（3-5個）",
                "- top-guarantee-1: 返金保証・安心材料",
                "- top-countdown-1: 締切カウントダウン",
                "- top-inline-cta-1: LPエディタで制作した証明と即時行動を促すインラインCTA",
                "- top-media-spotlight-1: テンプレートギャラリーや制作実例の紹介",
                "- handwritten-hero-1: 手書き風ヒーローで世界観を紹介",
                "- handwritten-features-1: 手書き風でテンプレートの魅力を列挙",
                "- handwritten-testimonials-1: 手書き風の声で親近感を補強",
                "- handwritten-cta-1: 手書き風CTAでやさしく行動を促す",
                "- top-cta-1: 最終CTA（行動喚起）",
            ]
        )

        field_requirements = """
### top-hero-1 (ヒーロー・動画背景)
{
  "title": "メインキャッチコピー（20-30文字）",
  "subtitle": "サブキャッチコピー（40-60文字）",
  "tagline": "タグライン（10-15文字・英語可）",
  "highlightText": "ハイライト文字（10-15文字）",
  "buttonText": "メインCTAボタン文字",
  "buttonUrl": "/register",
  "secondaryButtonText": "サブCTAボタン文字",
  "secondaryButtonUrl": "/demo",
  "backgroundVideoUrl": "選択されたヒーローの動画URL",
  "textColor": "#FFFFFF",
  "backgroundColor": "#050814",
  "accentColor": テーマのアクセントカラー,
  "buttonColor": テーマのプライマリカラー
}

### top-problem-1 (問題提起)
{
  "title": "こんなお悩みはありませんか？",
  "subtitle": "多くの方が直面する現実",
  "problems": ["問題1", "問題2", "問題3", "問題4"],
  "textColor": "#0F172A",
  "backgroundColor": "#FFFFFF"
}

### top-highlights-1 (特徴・ハイライト)
{
  "title": "選ばれる理由",
  "tagline": "Features",
  "features": [
    {
      "icon": "🎨",
      "title": "特徴タイトル",
      "description": "特徴の説明文"
    }
  ],
  "textColor": "#0F172A",
  "backgroundColor": "#F8FAFC"
}

### top-before-after-1 (ビフォーアフター)
{
  "title": "導入前と導入後の変化",
  "before": {
    "label": "Before",
    "description": "課題の状態（50-80文字）"
  },
  "after": {
    "label": "After",
    "description": "解決後の状態（50-80文字）"
  },
  "textColor": "#0F172A",
  "backgroundColor": "#FFFFFF"
}

### top-testimonials-1 (お客様の声)
{
  "title": "お客様の声",
  "subtitle": "導入企業や受講生のリアルな成果をご紹介します。",
  "testimonials": [
    {
      "name": "受講者A",
      "role": "マーケター / 年間売上1.2億円",
      "quote": "コメント文（60-100文字）"
    },
    {
      "name": "受講者B",
      "role": "副業スタート / 20代",
      "quote": "コメント文（60-100文字）"
    },
    {
      "name": "受講者C",
      "role": "コミュニティ運営 / 40代",
      "quote": "コメント文（60-100文字）"
    }
  ],
  "textColor": "#0F172A",
  "backgroundColor": "#F8FAFC"
}
【重要】testimonialsは必ず3つ以上生成してください。実績や成果が異なる多様な受講者の声を含めてください。

### top-bonus-1 (特典)
{
  "title": "今だけの特典",
  "subtitle": "お申込者限定で以下の特典をプレゼント",
  "bonuses": [
    {
      "title": "特典タイトル",
      "description": "特典の説明",
      "value": "29,800円相当"
    }
  ],
  "totalValue": "120,000円相当",
  "textColor": "#0F172A",
  "backgroundColor": "#FFFBEB"
}

### top-pricing-1 (価格表)
{
  "title": "料金プラン",
  "plans": [
    {
      "name": "プラン名",
      "price": "98,000円",
      "features": ["特徴1", "特徴2", "特徴3"],
      "buttonText": "申し込む",
      "highlighted": true
    }
  ],
  "textColor": "#0F172A",
  "backgroundColor": "#FFFFFF"
}

### top-faq-1 (FAQ)
{
  "title": "よくある質問",
  "subtitle": "導入前によくいただく質問をまとめました。",
  "items": [
    {
      "question": "質問文",
      "answer": "回答文"
    }
  ],
  "textColor": "#F8FAFC",
  "backgroundColor": "#0F172A"
}

### top-guarantee-1 (保証)
{
  "title": "30日間 全額返金保証",
  "subtitle": "安心してお試しいただけます",
  "description": "30日以内にご満足いただけなければ、理由を問わず全額返金いたします。",
  "badgeText": "100%保証",
  "textColor": "#0F172A",
  "backgroundColor": "#ECFDF5"
}

### top-countdown-1 (カウントダウン)
{
  "title": "特別オファー終了まで",
  "urgencyText": "締切までに参加いただいた方限定で、追加特典と返金保証をご提供します。",
  "targetDate": "2025-12-31T23:59:59Z",
  "textColor": "#FFFFFF",
  "backgroundColor": "#DC2626"
}

### top-inline-cta-1 (インラインCTA)
{
  "eyebrow": "LP Proof",
  "title": "このページもエディタで制作されています",
  "subtitle": "ユーザーの事例や編集体験などを短く紹介してください。",
  "buttonText": "エディタを試す",
  "buttonUrl": "/register",
  "textColor": テーマのテキストカラー,
  "backgroundColor": テーマの背景カラー,
  "accentColor": テーマのアクセントカラー,
  "buttonColor": テーマのプライマリカラー
}

### top-media-spotlight-1 (テンプレートギャラリー)
{
  "tagline": "Template Showcase",
  "title": "テンプレートギャラリーのタイトル",
  "subtitle": "テンプレートの特徴や活用シーンを説明するリード文",
  "caption": "画像キャプションや撮影情報",
  "buttonText": "テンプレートを見る",
  "buttonUrl": "/templates",
  "imageUrl": "テンプレートを象徴する画像URL（未指定でも可）",
  "textColor": テーマのテキストカラー,
  "backgroundColor": テーマの背景カラー,
  "accentColor": テーマのアクセントカラー,
  "buttonColor": テーマのプライマリカラー
}

### handwritten-hero-1 (手書き風ヒーロー)
{
  "title": "手書き風ヒーローのタイトル（改行も活用）",
  "subtitle": "やさしいトーンのサブコピー",
  "tagline": "英語タグライン",
  "highlightText": "強調テキスト",
  "buttonText": "行動を促す言葉",
  "buttonUrl": "/templates",
  "secondaryButtonText": "詳細CTA",
  "secondaryButtonUrl": "/about",
  "backgroundColor": "#FFFBEB",
  "textColor": "#78350F",
  "buttonColor": "#F59E0B",
  "secondaryButtonColor": "#FFFFFF"
}

### handwritten-features-1 (手書き風特徴)
{
  "title": "手書き風で伝える見出し",
  "tagline": "英語ラベル",
  "features": [
    {
      "icon": "⭐",
      "title": "特徴タイトル",
      "description": "詳細説明"
    }
  ],
  "layout": "grid",
  "backgroundColor": "#FFFFFF",
  "textColor": "#1F2937"
}

### handwritten-testimonials-1 (手書き風お客様の声)
{
  "title": "お客様の声",
  "testimonials": [
    {
      "quote": "コメント",
      "name": "名前",
      "role": "肩書き",
      "rating": 5
    }
  ],
  "backgroundColor": "#FFFFFF",
  "textColor": "#1F2937"
}

### handwritten-cta-1 (手書き風CTA)
{
  "eyebrow": "英語ラベル",
  "title": "やさしい口調のCTAタイトル",
  "subtitle": "短いサブコピー",
  "buttonText": "ボタンテキスト",
  "buttonUrl": "/register",
  "buttonColor": "#000000",
  "buttonTextColor": "#FFFFFF",
  "backgroundColor": "#FFFFFF",
  "textColor": "#1F2937"
}

### top-cta-1 (CTA)
{
  "title": "今すぐ始めよう",
  "subtitle": "情報には鮮度がある。５分でLPを公開して、今すぐ販売を開始。",
  "buttonText": "無料で始める",
  "buttonUrl": "/register",
  "secondaryButtonText": "デモを見る",
  "secondaryButtonUrl": "/demo",
  "textColor": "#0F172A",
  "backgroundColor": "#E0F2FE"
}
"""

        system_prompt = (
            "あなたは情報商材LPのコンバージョン最適化に特化したクリエイティブディレクターです。"
            "心理トリガー・権威性・社会的証明・緊急性を統合し、"
            "ユーザー入力を基にほぼ完成形の日本語コピーを生成してください。"
            "\n\n"
            "**重要な原則**：\n"
            "1. ユーザーが入力した情報「のみ」を使用してください\n"
            "2. テンプレート的な汎用文言は一切使用しないでください\n"
            "3. ユーザーのビジネス・商品・ターゲットに完全に特化した内容を生成してください\n"
            "4. 情報が不足している場合は、ユーザーの入力から論理的に推測して補完してください\n"
            "5. すべてのブロックの全フィールドを必ず埋めてください（空にしないこと）\n"
            "\n"
            "重要：ヒーローブロックは以下から最適なものを選択してください：\n\n"
            f"{heroes_metadata_text}"
        )

        user_prompt = f"""
# 目的
ヒアリングで得た情報を基に、すぐに公開できるレベルの日本語LP構成とコピーを生成してください。

# 重要な制約（必読）
**絶対に守ること**：
1. ユーザーが入力した情報「のみ」を使用してください
2. テンプレート的な固定文言は一切使用しないでください
3. ユーザーのビジネス・商品・ターゲットに特化した内容を生成してください
4. 情報が不足している場合は、ユーザーの入力から論理的に推測して補完してください
5. すべてのフィールドを必ず埋めてください（空にしないこと）

# 入力データ
{context_json}

# 推奨ヒーローブロック
ビジネス分析の結果、以下のヒーローが最適です：
- ID: {selected_hero_id}
- 名前: {hero_metadata['name'] if hero_metadata else 'ヒーロー'}
- 動画URL: {hero_metadata['videoUrl'] if hero_metadata else '/videos/pixta.mp4'}

このヒーローIDを必ず使用してください。

# 必須ブロック（順番厳守）
{block_sequence_description}

# 各ブロックのフィールド定義
{field_requirements}

# コンテンツ生成のガイドライン

## top-problem-1（問題提起）
- ユーザーのビジネスとターゲットから、具体的な悩みを3-5個生成
- 例：「投資・FX」→「チャートの見方が分からず損失ばかり」「含み損を抱えて夜も眠れない」など
- 絶対に汎用的な文言を使わないこと

## top-highlights-1（特徴）
- ユーザーの商品説明や提供形式から、具体的な特徴を3個生成
- 「簡単３ステップ」のような汎用表現は禁止
- 商品固有の強みを表現すること

## top-testimonials-1（お客様の声）
- ユーザーのビジネス・ターゲット・目標から、リアルな声を3つ生成
- 年齢・職業・成果はターゲットに合わせること
- 「受講者A」のような汎用名は禁止
- 具体的な名前（仮名可）と肩書きを設定

## top-bonus-1（特典）
**重要**: ユーザーが入力した特典情報を「必ず」使用してください
- title, subtitleはユーザーのオファーに特化した内容に
- 「今だけの特典」のような汎用表現は禁止
- ユーザーが入力した特典タイトル・説明・価値を必ず反映

## top-faq-1（よくある質問）
- ユーザーのビジネスとオファーに特化した質問を3-5個生成
- 「初心者でも実践できますか？」のような汎用的な質問は最小限に
- 商品・価格・提供形式に関する具体的な質問を優先

## top-guarantee-1（返金保証）
**重要**: ユーザーが入力した保証情報を「必ず」使用してください
- title, description, subtitleはユーザー入力から生成
- 「30日間 全額返金保証」のような汎用表現は禁止（ユーザー入力があれば）
- ユーザーが入力した保証内容を必ず反映

## top-cta-1（最終CTA）
**重要**: ユーザーの商品名・目標・CTAテキストを「必ず」使用してください
- title, subtitleはユーザーの商品・目標に特化した内容に
- 「今すぐ始めよう」「まずは資料請求」のような汎用表現は禁止
- buttonTextはユーザーが入力したCTAテキストを必ず使用

## top-inline-cta-1（インラインCTA）
- 「このページもエディタで制作」など、即時性・信頼性を訴求する短いコピーを生成
- CTAボタンには「無料で試す」「今すぐ編集する」などの行動動詞を入れる
- subtitleには編集体験の簡単さや導入メリットを簡潔に記載

## top-media-spotlight-1（テンプレートギャラリー）
- テンプレートのバリエーションや制作実例を紹介
- キャプションにはスクリーンショットの説明や制作裏話など具体情報を入れる
- 画像URLが未指定の場合は、AI生成では説明文を充実させ、手動差し替えがわかるように

## handwritten-hero-1（手書き風ヒーロー）
- 改行を活用した柔らかいトーンで、テンプレートの温かさ・親しみやすさを表現
- ハイライトには「手書き風」「ほっこり」など世界観が伝わる語を入れる
- 二次CTAは「詳しく見る」「実例をみる」などハードルの低い言葉を選ぶ

## handwritten-features-1（手書き風特徴）
- 手書きテンプレの魅力・利用シーン・差別化ポイントを3項目で整理
- アイコンには⭐や✍️など、手書き風を連想させる絵文字を使用
- 説明文は語りかけるような口調で親しみを出す

## handwritten-testimonials-1（手書き風お客様の声）
- 手書きテンプレを使ったユーザーの感想を3件生成し、実感ベースのコメントにする
- 名前と肩書きは親しみやすい仮名や属性を設定（例："都内在住デザイナー・真由美さん"）
- 手書きの温かみや使いやすさに言及させる

## handwritten-cta-1（手書き風CTA）
- ボタン文言は「無料ではじめる」「気軽に相談する」などやさしい表現にする
- サブコピーで"一緒に"や"気軽に"など、伴走感・敷居の低さを強調
- 迷っている人の背中を押す一言を付け加える

# 出力要件
- 出力言語は必ず日本語。
- ヒーローブロックは推奨されたものを使用（blockType: "top-hero-1"、content.backgroundVideoUrl: "{hero_metadata['videoUrl'] if hero_metadata else '/videos/pixta.mp4'}"）
- ブロックは上記の順番で作成し、欠落なく出力すること。
- 数字・期間・成果・限定数などは可能な限り具体的で信頼感のある値を設定する。
- ユーザーの入力から推測して、すべてのフィールドを必ず埋めること。
- JSON形式で以下の構造のみを返すこと。

{{
  "selectedHero": "{selected_hero_id}",
  "outline": ["セクション概要1", "セクション概要2", ...],
  "blocks": [
    {{
      "blockType": "top-hero-1",
      "reason": "このブロックが効果的な理由",
      "content": {{ 
        "title": "...",
        "backgroundVideoUrl": "{hero_metadata['videoUrl'] if hero_metadata else '/videos/pixta.mp4'}",
        ...ヒーローの全フィールド 
      }}
    }},
    {{
      "blockType": "top-problem-1",
      "content": {{ ...問題提起の全フィールド }}
    }},
    ...（全ブロック）
  ]
}}
"""

        ai_result: Dict[str, Any] = {"outline": [], "blocks": []}

        try:
            client = get_openai_client()
            response = client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            raw_content = response.choices[0].message.content
            if raw_content:
                ai_result = json.loads(raw_content)
        except Exception as exc:
            print(f"AI構成生成エラー: {exc}")

        ai_blocks = ai_result.get("blocks") or []
        outline = ai_result.get("outline") if isinstance(ai_result.get("outline"), list) else []
        outline_missing = len(outline) == 0

        # シーケンスに沿ってブロックを割り当て（同一blockTypeが複数あっても順番通りに処理）
        assigned_blocks: List[Optional[Dict[str, Any]]] = [None] * len(BLOCK_SEQUENCE)
        used_indices: set[int] = set()

        for seq_idx, sequence_item in enumerate(BLOCK_SEQUENCE):
            block_type = sequence_item["block_type"]
            for ai_idx, ai_block in enumerate(ai_blocks):
                if ai_idx in used_indices:
                    continue
                if ai_block.get("blockType") == block_type:
                    assigned_blocks[seq_idx] = ai_block
                    used_indices.add(ai_idx)
                    break

        processed_blocks: List[Dict[str, Any]] = []

        for seq_idx, sequence_item in enumerate(BLOCK_SEQUENCE):
            block_type = sequence_item["block_type"]
            template_hint = sequence_item.get("template_id")

            block_data = assigned_blocks[seq_idx]
            if not block_data:
                block_data = {
                    "blockType": block_type,
                    "reason": "コンテキストを基に自動補完しました。",
                    "content": {},
                }

            # 選択されたヒーローIDおよびテンプレートIDを渡す
            processed_block = AIService._apply_defaults(
                block_data,
                input_data,
                selected_hero_id=selected_hero_id,
                template_id=template_hint,
            )
            processed_blocks.append(processed_block)

            if outline_missing:
                heading = (
                    processed_block["content"].get("title")
                    or processed_block["content"].get("tagline")
                    or OUTLINE_FALLBACK_LABELS.get(block_type)
                    or block_type
                )
                outline.append(heading)

        return {
            "theme": theme_key,
            "selectedHero": selected_hero_id,
            "palette": {
                "primary": palette["primary"],
                "accent": palette["accent"],
                "secondary": palette.get("secondary") or palette["accent"],
                "background": palette["background"],
                "surface": palette["background"],
                "text": palette["text"],
            },
            "outline": outline,
            "blocks": processed_blocks,
        }

    @staticmethod
    def _apply_defaults(
        block: Dict[str, Any], 
        data: AIWizardInput,
        selected_hero_id: Optional[str] = None,
        template_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """各ブロックにデフォルト値を適用"""
        
        block_type = block.get("blockType")
        content = dict(block.get("content") or {})
        reason = block.get("reason") or "ユーザー入力に基づき生成されました。"

        if template_id:
            block["templateId"] = template_id
        elif block_type == "top-hero-1" and selected_hero_id:
            block["templateId"] = selected_hero_id
        else:
            default_variant = DEFAULT_TEMPLATE_VARIANTS.get(block_type)
            if default_variant:
                block.setdefault("templateId", default_variant)

        def _is_blank(value: Optional[str]) -> bool:
            return not isinstance(value, str) or not value.strip()

        def _coalesce(*values: Optional[str], fallback: str = "") -> str:
            for value in values:
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return fallback

        theme_key = data.theme or DEFAULT_THEME
        palette = COLOR_THEMES.get(theme_key, COLOR_THEMES[DEFAULT_THEME])
        content.setdefault("themeKey", theme_key)

        product = data.product
        offer = data.offer
        price = offer.price
        audience = data.audience
        proof = data.proof
        narrative = data.narrative

        pain_points = audience.pain_points or []
        desired_outcome = audience.desired_outcome or data.goal
        call_to_action = offer.call_to_action or "今すぐ申し込む"
        scarcity_text = offer.scarcity or ""
        deadline_text = price.deadline if price else None

        # ===== top-hero-1: ヒーロー（動画背景） =====
        if block_type == "top-hero-1":
            reason = "冒頭で強い約束とCTAを提示し、信頼と期待感を一気に高めるため。"
            
            # 選択されたヒーローの動画URLを設定
            hero_metadata = get_hero_metadata(selected_hero_id) if selected_hero_id else None
            if hero_metadata and hero_metadata.get("videoUrl"):
                content["backgroundVideoUrl"] = hero_metadata["videoUrl"]
            else:
                content.setdefault("backgroundVideoUrl", "/videos/pixta.mp4")
            
            content.setdefault("tagline", (narrative.unique_mechanism if narrative and narrative.unique_mechanism else product.format or data.business))
            
            hero_title = content.get("title") or product.transformation or product.promise
            if not hero_title:
                hero_title = f"{product.name}で{desired_outcome}を最短で実現"
            content["title"] = hero_title
            
            subtitle = content.get("subtitle") or product.description or data.additional_notes or "あなたの理想を叶える実戦型カリキュラムを提供します。"
            content["subtitle"] = subtitle
            
            highlight = content.get("highlightText") or product.promise or (narrative.unique_mechanism if narrative and narrative.unique_mechanism else desired_outcome)
            content["highlightText"] = highlight
            
            content.setdefault("buttonText", call_to_action)
            content.setdefault("buttonUrl", "/register")
            content.setdefault("secondaryButtonText", "詳細を見る")
            content.setdefault("secondaryButtonUrl", "/about")
            
            content.setdefault("textColor", "#FFFFFF")
            content.setdefault("backgroundColor", palette["background"])
            content.setdefault("accentColor", palette["accent"])
            content.setdefault("buttonColor", palette["primary"])
            content.setdefault("overlayColor", palette["background"])
            content.setdefault("secondaryButtonColor", "#F8FAFC")

        # ===== top-problem-1: 問題提起 =====
        elif block_type == "top-problem-1":
            reason = "ターゲットの痛みを言語化し、強い共感を生むため。"
            content.setdefault("title", "こんなお悩みはありませんか？")
            content.setdefault("subtitle", f"{audience.persona or '多くの方'}が直面する現実")
            
            problems = content.get("problems") if isinstance(content.get("problems"), list) else []
            # AIが生成しなかった場合のみ、ユーザー入力から使用（固定テキストは使わない）
            if not problems and pain_points:
                problems = pain_points[:5]
            content["problems"] = problems[:5] if problems else []
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#FFFFFF")

        # ===== top-highlights-1: ハイライト =====
        elif block_type == "top-highlights-1":
            reason = "選ばれる理由を明確に示し、差別化ポイントを訴求するため。"
            content.setdefault("title", "選ばれる理由")
            content.setdefault("tagline", "Features")
            
            features = content.get("features") if isinstance(content.get("features"), list) else []
            # AIが生成しなかった場合のみ、ユーザー入力から使用（固定テキストは使わない）
            if not features:
                key_features = product.key_features or []
                if key_features:
                    features = [
                        {"icon": "🎨", "title": f, "description": f"効果的な{f}で成果を最大化"} 
                        for f in key_features[:3]
                    ]
            content["features"] = features[:3] if features else []
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#F8FAFC")

        # ===== top-before-after-1: ビフォーアフター =====
        elif block_type == "top-before-after-1":
            reason = "導入前後のギャップを可視化し、成果のイメージを明確にするため。"
            content.setdefault("title", "導入前と導入後の変化")
            
            # AIが生成したbeforeText/afterTextを取得（後方互換性のため）
            before_text = content.get("beforeText") or (pain_points[0] if pain_points else "時間も労力も投資したのに成果が出ない状態")
            after_text = content.get("afterText") or product.transformation or desired_outcome or "売上と時間の両立が実現"
            
            # フロントエンドが期待するbefore/after構造に変換
            before = content.get("before", {})
            if not isinstance(before, dict):
                before = {}
            before.setdefault("label", "Before")
            before.setdefault("description", before_text)
            
            after = content.get("after", {})
            if not isinstance(after, dict):
                after = {}
            after.setdefault("label", "After")
            after.setdefault("description", after_text)
            
            content["before"] = before
            content["after"] = after
            
            # 古いフィールドを削除
            content.pop("beforeText", None)
            content.pop("afterText", None)
            content.pop("beforeTitle", None)
            content.pop("afterTitle", None)
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#FFFFFF")

        # ===== top-testimonials-1: お客様の声 =====
        elif block_type == "top-testimonials-1":
            reason = "第三者の実績で権威性と安心感を補強するため。"
            testimonials = AIService._testimonials_to_dict(
                content.get("testimonials"), proof, audience.persona or data.target
            )
            content["testimonials"] = testimonials
            content.setdefault("title", "お客様の声")
            content.setdefault("subtitle", "導入企業や受講生のリアルな成果をご紹介します。")
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#F8FAFC")

        # ===== top-bonus-1: 特典 =====
        elif block_type == "top-bonus-1":
            reason = "申込特典の価値を可視化し、値引き以上の価値を訴求するため。"
            # AIが生成したbonusesを優先、なければユーザー入力から使用
            bonuses = AIService._bonuses_to_dict(content.get("bonuses"), offer.bonuses)
            if not bonuses and product.deliverables:
                bonuses = [
                    {"title": deliverable, "description": "即実践可能な特典", "value": "29,800円相当"} 
                    for deliverable in product.deliverables[:3]
                ]
            content["bonuses"] = bonuses[:5]
            
            product_label = _coalesce(product.name, data.business, data.goal, fallback="このプログラム")
            audience_label = _coalesce(audience.persona, data.target, fallback="参加者")
            bonus_count = len(content["bonuses"])

            if (_is_blank(content.get("title"))
                or content.get("title", "").strip() in GENERIC_BONUS_TITLES):
                count_label = f"{bonus_count}大特典" if bonus_count >= 3 else "限定特典"
                content["title"] = f"{product_label}参加者向け{count_label}"

            if (_is_blank(content.get("subtitle"))
                or content.get("subtitle", "").strip() in GENERIC_BONUS_SUBTITLES):
                outcome_text = _coalesce(
                    desired_outcome,
                    product.transformation,
                    product.promise,
                    product.description,
                )
                if outcome_text:
                    content["subtitle"] = f"{audience_label}が{outcome_text}を現実にするための特典ラインナップです。"
                else:
                    content["subtitle"] = f"{audience_label}の成果を後押しする実践特典をご用意しました。"
            
            total_value = content.get("totalValue") or AIService._calculate_bonus_total(bonuses)
            if total_value and total_value.strip() not in GENERIC_BONUS_TOTAL_VALUES:
                content["totalValue"] = total_value
            elif total_value:
                calculated = AIService._calculate_bonus_total(bonuses)
                if calculated:
                    content["totalValue"] = calculated
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#FFFBEB")

        # ===== top-pricing-1: 価格表 =====
        elif block_type == "top-pricing-1":
            reason = "料金プランを明確に提示し、購入の意思決定をサポートするため。"
            content.setdefault("title", "料金プラン")
            
            plans = content.get("plans") if isinstance(content.get("plans"), list) else []
            if not plans:
                special_price = (price.special if price else None) or "98,000円"
                original_price = (price.original if price else None)
                
                features_list = product.key_features or [
                    "全カリキュラムへのアクセス",
                    "個別サポート",
                    "返金保証",
                ]
                
                plans = [
                    {
                        "name": "スタンダードプラン",
                        "price": special_price,
                        "features": features_list[:5],
                        "buttonText": call_to_action,
                        "highlighted": True,
                    }
                ]
            content["plans"] = plans
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#FFFFFF")

        # ===== top-faq-1: FAQ =====
        elif block_type == "top-faq-1":
            reason = "よくある疑問を事前に解消し、購入への不安を取り除くため。"
            content.setdefault("title", "よくある質問")
            content.setdefault("subtitle", "導入前によくいただく質問をまとめました。")
            
            items = content.get("items") if isinstance(content.get("items"), list) else []
            # AIが生成しなかった場合のみ、ユーザー入力から使用（固定テキストは使わない）
            if not items:
                objections = audience.objections if audience.objections else []
                if objections:
                    items = [
                        {"question": obj, "answer": f"{product.name}では、{obj.replace('？', '')}についても手厚くサポートしています。"}
                        for obj in objections[:3]
                    ]
            content["items"] = items[:5] if items else []
            
            content.setdefault("textColor", "#F8FAFC")
            content.setdefault("backgroundColor", "#0F172A")

        # ===== top-guarantee-1: 保証 =====
        elif block_type == "top-guarantee-1":
            reason = "リスクを取り除き、申込への心理的ハードルを下げるため。"
            guarantee = offer.guarantee
            product_label = _coalesce(product.name, data.business, fallback="このサービス")

            detail_text = _coalesce(
                content.get("guaranteeDetails"),
                content.get("description"),
                guarantee.description if guarantee else None,
            )
            if detail_text:
                content["guaranteeDetails"] = detail_text
                content["description"] = detail_text
            
            title_value = content.get("title") if isinstance(content.get("title"), str) else ""
            if (_is_blank(title_value)
                or title_value.strip() in GENERIC_GUARANTEE_TITLES):
                headline = guarantee.headline.strip() if guarantee and isinstance(guarantee.headline, str) and guarantee.headline.strip() else None
                content["title"] = headline or f"{product_label}の安心保証"
            else:
                content["title"] = title_value.strip()

            subtitle_value = content.get("subtitle") if isinstance(content.get("subtitle"), str) else ""
            if (_is_blank(subtitle_value)
                or subtitle_value.strip() in GENERIC_GUARANTEE_SUBTITLES):
                condition_text = guarantee.conditions.strip() if guarantee and isinstance(guarantee.conditions, str) and guarantee.conditions.strip() else None
                if condition_text:
                    content["subtitle"] = condition_text
                elif deadline_text:
                    content["subtitle"] = f"{deadline_text}までの成果を保証します。"
                else:
                    content["subtitle"] = f"{product_label}をリスクなくお試しいただけます。"
            else:
                content["subtitle"] = subtitle_value.strip()

            details_value = content.get("guaranteeDetails") if isinstance(content.get("guaranteeDetails"), str) else ""
            if (_is_blank(details_value)
                or details_value.strip() in GENERIC_GUARANTEE_DETAILS):
                fallback_detail = _coalesce(
                    guarantee.description if guarantee else None,
                    guarantee.conditions if guarantee else None,
                    fallback=f"{product_label}をご利用後も満足いただけない場合は、簡単な手続きで返金に対応します。",
                )
                content["guaranteeDetails"] = fallback_detail
                content["description"] = fallback_detail
            else:
                stripped = details_value.strip()
                content["guaranteeDetails"] = stripped
                content["description"] = stripped

            badge_value = content.get("badgeText") if isinstance(content.get("badgeText"), str) else ""
            if (_is_blank(badge_value)
                or badge_value.strip() in GENERIC_GUARANTEE_BADGES):
                if guarantee and isinstance(guarantee.headline, str) and guarantee.headline.strip():
                    badge = guarantee.headline.strip().replace("保証", "").replace(" ", "")
                    content["badgeText"] = badge[:8] or "保証付き"
                elif desired_outcome:
                    content["badgeText"] = f"{desired_outcome}保証"
                else:
                    content["badgeText"] = "保証付き"
            else:
                content["badgeText"] = badge_value.strip()

            bullet_points = content.get("bulletPoints") if isinstance(content.get("bulletPoints"), list) else []
            if not bullet_points or all(
                isinstance(point, str) and point.strip() in GENERIC_GUARANTEE_BULLETS
                for point in bullet_points
            ):
                candidate_texts: List[str] = []
                if guarantee and isinstance(guarantee.conditions, str) and guarantee.conditions.strip():
                    candidate_texts.append(guarantee.conditions)
                if guarantee and isinstance(guarantee.description, str) and guarantee.description.strip():
                    candidate_texts.append(guarantee.description)
                if detail_text and detail_text not in candidate_texts:
                    candidate_texts.append(detail_text)

                extracted: List[str] = []
                for text in candidate_texts:
                    segments = [segment.strip(" ・-•\u3000") for segment in re.split(r"[\n。・•●◆▶︎➡︎→⇒]", text) if segment.strip()]
                    for segment in segments:
                        if len(extracted) >= 5:
                            break
                        extracted.append(segment)
                    if len(extracted) >= 5:
                        break

                if not extracted and scarcity_text:
                    extracted.append(scarcity_text.strip())
                if not extracted and desired_outcome:
                    extracted.append(f"{desired_outcome}まで専任が伴走サポート")
                if not extracted:
                    extracted.append(f"{product_label}チームが返金手続きまでサポート")

                bullet_points = extracted[:3]
                content["bulletPoints"] = bullet_points
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#ECFDF5")

        # ===== top-countdown-1: カウントダウン =====
        elif block_type == "top-countdown-1":
            reason = "締切を明示し、今すぐ行動する理由を与えるため。"
            content.setdefault("title", "特別オファー終了まで")
            
            urgency = content.get("urgencyText") or scarcity_text or (
                deadline_text and f"{deadline_text}までの申込で特典適用"
            ) or "締切までに参加いただいた方限定で、追加特典と返金保証をご提供します。"
            content["urgencyText"] = urgency
            
            default_target = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat()
            content["targetDate"] = content.get("targetDate") or default_target
            
            content.setdefault("textColor", "#FFFFFF")
            content.setdefault("backgroundColor", "#DC2626")

        # ===== top-inline-cta-1: インラインCTA =====
        elif block_type == "top-inline-cta-1":
            reason = "LPエディタで制作した実例を示し、即時行動を促すため。"

            eyebrow = content.get("eyebrow") if isinstance(content.get("eyebrow"), str) else ""
            if _is_blank(eyebrow):
                content["eyebrow"] = "Product Proof"

            proof_title = content.get("title") if isinstance(content.get("title"), str) else ""
            if _is_blank(proof_title):
                product_label = _coalesce(product.name, data.business, fallback="このページ")
                content["title"] = f"{product_label}もエディタで制作されています"
            else:
                content["title"] = proof_title.strip()

            proof_subtitle = content.get("subtitle") if isinstance(content.get("subtitle"), str) else ""
            if _is_blank(proof_subtitle):
                base = _coalesce(
                    product.description,
                    narrative.origin_story if narrative else None,
                    data.additional_notes,
                )
                content["subtitle"] = base or "実際の制作フローを体験できる無料エディタをご用意しています。"
            else:
                content["subtitle"] = proof_subtitle.strip()

            primary_text = content.get("buttonText") if isinstance(content.get("buttonText"), str) else ""
            if _is_blank(primary_text):
                content["buttonText"] = call_to_action or "エディタを試す"
            else:
                content["buttonText"] = primary_text.strip()

            if _is_blank(content.get("buttonUrl")):
                content["buttonUrl"] = "/register"

            content.setdefault("textColor", palette["text"])
            content.setdefault("backgroundColor", palette["background"])
            content.setdefault("accentColor", palette["accent"])
            content.setdefault("buttonColor", palette["primary"])

        # ===== top-media-spotlight-1: メディアスポットライト =====
        elif block_type == "top-media-spotlight-1":
            reason = "テンプレートや制作実例を紹介し、視覚的な信頼感を補強するため。"

            tagline_value = content.get("tagline") if isinstance(content.get("tagline"), str) else ""
            if _is_blank(tagline_value):
                content["tagline"] = "Template Showcase"
            else:
                content["tagline"] = tagline_value.strip()

            spotlight_title = content.get("title") if isinstance(content.get("title"), str) else ""
            if _is_blank(spotlight_title):
                product_label = _coalesce(product.name, data.business, fallback="テンプレート")
                content["title"] = f"{product_label}の世界観を体感"
            else:
                content["title"] = spotlight_title.strip()

            spotlight_subtitle = content.get("subtitle") if isinstance(content.get("subtitle"), str) else ""
            if _is_blank(spotlight_subtitle):
                content["subtitle"] = _coalesce(
                    product.description,
                    narrative.unique_mechanism if narrative else None,
                    fallback="テンプレートの活用シーンと制作の裏側をご紹介します。",
                )
            else:
                content["subtitle"] = spotlight_subtitle.strip()

            caption_value = content.get("caption") if isinstance(content.get("caption"), str) else ""
            if _is_blank(caption_value):
                content["caption"] = "D-swipeテンプレートギャラリー"
            else:
                content["caption"] = caption_value.strip()

            primary_text = content.get("buttonText") if isinstance(content.get("buttonText"), str) else ""
            if _is_blank(primary_text):
                content["buttonText"] = "テンプレート一覧を見る"
            else:
                content["buttonText"] = primary_text.strip()

            if _is_blank(content.get("buttonUrl")):
                content["buttonUrl"] = "/templates"

            if _is_blank(content.get("imageUrl")):
                content["imageUrl"] = "/gallery/dswipe-template-showcase.png"

            content.setdefault("textColor", palette["text"])
            content.setdefault("backgroundColor", palette["background"])
            content.setdefault("accentColor", palette["accent"])
            content.setdefault("buttonColor", palette["primary"])

        # ===== handwritten-hero-1: 手書き風ヒーロー =====
        elif block_type == "handwritten-hero-1":
            reason = "手書き風の世界観でテンプレートの柔らかさと親近感を伝えるため。"
            product_label = _coalesce(product.name, data.business, fallback="あなたのブランド")
            content.setdefault("tagline", "HANDWRITTEN STYLE")

            hero_title = content.get("title") if isinstance(content.get("title"), str) else ""
            if _is_blank(hero_title):
                desired = _coalesce(desired_outcome, product.transformation, fallback="理想のLPを作ろう")
                content["title"] = f"{product_label}\n手描きテンプレートで{desired}" if desired else f"{product_label}\n手描きテンプレート"
            else:
                content["title"] = hero_title.strip()

            hero_subtitle = content.get("subtitle") if isinstance(content.get("subtitle"), str) else ""
            if _is_blank(hero_subtitle):
                base = _coalesce(
                    product.description,
                    narrative.origin_story if narrative else None,
                    data.additional_notes,
                    fallback="あたたかみのあるレイアウトで、ファンに寄り添うLPをつくりましょう。",
                )
                content["subtitle"] = base
            else:
                content["subtitle"] = hero_subtitle.strip()

            highlight = content.get("highlightText") if isinstance(content.get("highlightText"), str) else ""
            if _is_blank(highlight):
                content["highlightText"] = "全10種テンプレ"
            else:
                content["highlightText"] = highlight.strip()

            primary_text = content.get("buttonText") if isinstance(content.get("buttonText"), str) else ""
            if _is_blank(primary_text):
                content["buttonText"] = call_to_action or "無料で始める"
            else:
                content["buttonText"] = primary_text.strip()

            if _is_blank(content.get("buttonUrl")):
                content["buttonUrl"] = "/templates"

            secondary_text = content.get("secondaryButtonText") if isinstance(content.get("secondaryButtonText"), str) else ""
            if _is_blank(secondary_text):
                content["secondaryButtonText"] = "テンプレートを見る"
            else:
                content["secondaryButtonText"] = secondary_text.strip()

            if _is_blank(content.get("secondaryButtonUrl")):
                content["secondaryButtonUrl"] = "/templates"

            content.setdefault("textColor", "#78350F")
            content.setdefault("backgroundColor", "#FFFBEB")
            content.setdefault("buttonColor", "#F59E0B")
            content.setdefault("secondaryButtonColor", "#FFFFFF")

        # ===== handwritten-features-1: 手書き風特徴 =====
        elif block_type == "handwritten-features-1":
            reason = "手書きテンプレの魅力を3つの特徴でわかりやすく伝えるため。"
            content.setdefault("title", "こんな手書き風テンプレが使えます")
            content.setdefault("tagline", "HANDWRITTEN TEMPLATE")

            features = content.get("features") if isinstance(content.get("features"), list) else []
            if not features:
                key_features = product.key_features or []
                if key_features:
                    features = [
                        {
                            "icon": "✍️",
                            "title": feature,
                            "description": f"手描きスタイルで{feature}を魅力的に表現できます。",
                        }
                        for feature in key_features[:3]
                    ]
                else:
                    features = [
                        {"icon": "⭐", "title": "温かみのある紙質テクスチャ", "description": "既存LPにはない親近感が生まれます。"},
                        {"icon": "📒", "title": "メモ風の補足エリア", "description": "重要ポイントを手書きメモとして強調できます。"},
                        {"icon": "💬", "title": "吹き出しコメント", "description": "講師や受講生の声を手描き感で配置できます。"},
                    ]
            content["features"] = features[:3]
            content.setdefault("layout", "grid")
            content.setdefault("textColor", "#1F2937")
            content.setdefault("backgroundColor", "#FFFFFF")

        # ===== handwritten-testimonials-1: 手書き風お客様の声 =====
        elif block_type == "handwritten-testimonials-1":
            reason = "手書き風の言葉で親しみやすい実績を見せ、導入ハードルを下げるため。"
            testimonials = AIService._testimonials_to_dict(
                content.get("testimonials"), proof, audience.persona or data.target
            )
            if not testimonials:
                testimonials = [
                    {
                        "name": "真由美さん",
                        "role": "都内在住デザイナー",
                        "quote": "手書きテンプレでブランドの温度感がそのまま伝わりました。",
                    },
                    {
                        "name": "健太さん",
                        "role": "オンライン講師",
                        "quote": "受講生から『手書き風がかわいい！』と反応をもらえました。",
                    },
                    {
                        "name": "あかりさん",
                        "role": "コミュニティ運営",
                        "quote": "テンプレを差し替えるだけで一気に親近感が高まりました。",
                    },
                ]
            content["testimonials"] = testimonials[:3]
            content.setdefault("title", "手書きテンプレ利用者の声")
            content.setdefault("textColor", "#1F2937")
            content.setdefault("backgroundColor", "#FFFFFF")

        # ===== handwritten-cta-1: 手書き風CTA =====
        elif block_type == "handwritten-cta-1":
            reason = "手書き風のやさしいトーンで、行動のハードルを下げるため。"
            content.setdefault("eyebrow", "LET'S START")

            cta_title = content.get("title") if isinstance(content.get("title"), str) else ""
            if _is_blank(cta_title):
                product_label = _coalesce(product.name, data.business, fallback="一緒にはじめましょう")
                content["title"] = f"{product_label}を、やさしくスタート"
            else:
                content["title"] = cta_title.strip()

            cta_subtitle = content.get("subtitle") if isinstance(content.get("subtitle"), str) else ""
            if _is_blank(cta_subtitle):
                base = _coalesce(
                    product.description,
                    narrative.roadmap if narrative else None,
                    fallback="わからないところは一緒に伴走するので、安心してください。",
                )
                content["subtitle"] = base
            else:
                content["subtitle"] = cta_subtitle.strip()

            primary_text = content.get("buttonText") if isinstance(content.get("buttonText"), str) else ""
            if _is_blank(primary_text):
                content["buttonText"] = call_to_action or "無料ではじめる"
            else:
                content["buttonText"] = primary_text.strip()

            if _is_blank(content.get("buttonUrl")):
                content["buttonUrl"] = "/register"

            content.setdefault("buttonColor", "#000000")
            content.setdefault("buttonTextColor", "#FFFFFF")
            content.setdefault("textColor", "#1F2937")
            content.setdefault("backgroundColor", "#FFFFFF")

        # ===== top-cta-1: CTA =====
        elif block_type == "top-cta-1":
            reason = "最終的な行動喚起で、明確な次のステップを提示するため。"
            product_label = _coalesce(product.name, data.business, fallback="このサービス")
            desired = _coalesce(desired_outcome, product.transformation, product.promise)
            mechanism = _coalesce(narrative.unique_mechanism if narrative else None)
            guarantee = offer.guarantee
            title_text = content.get("title") if isinstance(content.get("title"), str) else ""
            subtitle_text = content.get("subtitle") if isinstance(content.get("subtitle"), str) else ""
            primary_text = content.get("buttonText") if isinstance(content.get("buttonText"), str) else ""
            secondary_text = content.get("secondaryButtonText") if isinstance(content.get("secondaryButtonText"), str) else ""
            
            if _is_blank(content.get("eyebrow")) and mechanism:
                content["eyebrow"] = mechanism

            lacks_personalization = False
            if desired and desired not in title_text:
                lacks_personalization = True
            if product_label and product_label not in title_text:
                lacks_personalization = True

            title_needs_override = (
                _is_blank(title_text)
                or title_text.strip() in GENERIC_CTA_TITLES
                or lacks_personalization
            )

            if title_needs_override:
                if desired:
                    content["title"] = f"{desired}を叶える{product_label}"
                else:
                    content["title"] = f"{product_label}で次の成果へ"
            else:
                content["title"] = title_text.strip()

            subtitle_needs_override = (
                _is_blank(subtitle_text)
                or subtitle_text.strip() in GENERIC_CTA_SUBTITLES
                or subtitle_text.strip() == title_text.strip()
            )

            if subtitle_needs_override:
                base = _coalesce(
                    product.description,
                    narrative.origin_story if narrative else None,
                    data.goal,
                )
                extra = ""
                if guarantee and isinstance(guarantee.headline, str) and guarantee.headline.strip():
                    extra = f"{guarantee.headline.strip()}付きでリスクなくスタートできます。"
                elif scarcity_text:
                    extra = scarcity_text
                if base and extra:
                    content["subtitle"] = f"{base} {extra}"
                elif base:
                    content["subtitle"] = base
                else:
                    content["subtitle"] = extra or f"{product_label}の詳細を今すぐ確認してください。"
            else:
                content["subtitle"] = subtitle_text.strip()

            if call_to_action:
                content["buttonText"] = call_to_action.strip()
            elif _is_blank(primary_text) or primary_text.strip() in GENERIC_PRIMARY_CTA_TEXTS:
                content["buttonText"] = "詳細を見る"
            else:
                content["buttonText"] = primary_text.strip()

            if _is_blank(content.get("buttonUrl")):
                content["buttonUrl"] = "/register"

            secondary_needs_override = (
                _is_blank(secondary_text)
                or secondary_text.strip() in GENERIC_SECONDARY_CTA_TEXTS
            )
            if secondary_needs_override:
                if price and (price.special or price.original):
                    content["secondaryButtonText"] = "料金プランを見る"
                else:
                    content["secondaryButtonText"] = f"{product_label}の詳細を見る"
            else:
                content["secondaryButtonText"] = secondary_text.strip()

            if _is_blank(content.get("secondaryButtonUrl")):
                content["secondaryButtonUrl"] = "#pricing"
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#E0F2FE")

        result_block = {
            "blockType": block_type,
            "content": content,
            "reason": reason,
        }
        template_identifier = block.get("templateId") or template_id
        if template_identifier:
            result_block["templateId"] = template_identifier

        return result_block

    @staticmethod
    def _bonuses_to_dict(existing: Any, bonuses: Optional[List[BonusItem]]) -> List[Dict[str, str]]:
        """特典リストを辞書リストに変換"""
        items: List[Dict[str, str]] = []
        
        if isinstance(existing, list):
            for bonus in existing:
                if isinstance(bonus, dict) and bonus.get("title"):
                    items.append({
                        "title": bonus.get("title"),
                        "description": bonus.get("description") or "",
                        "value": bonus.get("value") or "",
                    })
        
        if not items and bonuses:
            for bonus in bonuses:
                items.append({
                    "title": bonus.title,
                    "description": bonus.description or "",
                    "value": bonus.value or "",
                })
        
        return items[:5]

    @staticmethod
    def _calculate_bonus_total(bonuses: List[Dict[str, str]]) -> Optional[str]:
        """特典の合計金額を計算"""
        total = 0
        counted = False
        
        for bonus in bonuses:
            numeric = AIService._parse_int(bonus.get("value"))
            if numeric:
                total += numeric
                counted = True
        
        if counted and total > 0:
            return f"合計{total:,}円相当"
        return None

    @staticmethod
    def _testimonials_to_dict(
        existing: Any, 
        proof: Optional[Any], 
        persona: Optional[str]
    ) -> List[Dict[str, Any]]:
        """お客様の声を辞書リストに変換"""
        items: List[Dict[str, Any]] = []
        
        if isinstance(existing, list):
            for testimonial in existing:
                if isinstance(testimonial, dict):
                    text = testimonial.get("text") or testimonial.get("quote")
                    if text:
                        items.append({
                            "name": testimonial.get("name") or "受講者",
                            "role": testimonial.get("role") or "",
                            "quote": text,
                        })
        
        # AIが生成しなかった場合のみ、ユーザー入力から使用（固定テキストは使わない）
        if not items and proof and getattr(proof, "testimonials", None):
            for testimonial in proof.testimonials[:3]:
                if isinstance(testimonial, Testimonial):
                    items.append({
                        "name": testimonial.name or "受講者",
                        "role": testimonial.role or "",
                        "quote": testimonial.quote,
                    })
        
        # 固定テキストは削除 - AIに生成させる
        return items[:3]

    @staticmethod
    def _parse_int(value: Optional[str]) -> Optional[int]:
        """文字列から数値を抽出"""
        if not value:
            return None
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    @staticmethod
    def _calc_discount_badge(original: Optional[str], special: Optional[str]) -> Optional[str]:
        """割引率を計算してバッジテキストを生成"""
        original_value = AIService._parse_int(original)
        special_value = AIService._parse_int(special)
        
        if original_value and special_value and original_value > special_value:
            discount = int(round((1 - (special_value / original_value)) * 100))
            if discount > 0:
                return f"{discount}% OFF"
        return None

    @staticmethod
    async def generate_text(text_type: str, context: Dict[str, Any], count: int = 3) -> List[str]:
        """テキストを生成（見出し、説明文など）"""

        prompts = {
            "headline": f"""
情報商材: {context.get('product', '商品')}
ターゲット: {context.get('target', '一般')}
ジャンル: {context.get('business', '一般')}

情報商材LPで売れる、インパクトのある見出しを{count}つ提案してください。
以下の要素を含めてください：
- 実績数字（例：月収100万円、30日で-10kg）
- 緊急性（例：今だけ、期間限定）
- ターゲットへの問いかけ（例：〜で悩んでいませんか？）

各見出しは25文字以内。1行に1つずつ、番号なしで出力してください。
""",
            "subtitle": f"""
メイン見出し: {context.get('headline', '')}
情報商材: {context.get('product', '商品')}

見出しを補完し、さらに興味を引くサブタイトルを{count}つ提案してください。
以下を意識してください：
- 限定性（例：先着〇名限定）
- ベネフィット（例：初心者でも実践可能）
- 権威性（例：1000名が実証）

各サブタイトルは40文字以内。1行に1つずつ、番号なしで出力してください。
""",
            "description": f"""
情報商材: {context.get('product', '商品')}
特徴: {context.get('features', [])}

情報商材の価値を最大限に伝える説明文を{count}つ提案してください。
以下を含めてください：
- 具体的な成果（数字で示す）
- 実践の簡単さ
- リスクの低さ

各説明文は120文字前後。1つの提案ごとに空行を入れて出力してください。
""",
            "cta": f"""
目的: {context.get('goal', '行動喚起')}
情報商材: {context.get('product', '商品')}

高いクリック率を生むCTAボタンの文言を{count}つ提案してください。
情報商材LPでは以下を意識：
- 緊急性（例：今すぐ、残りわずか）
- 限定性（例：先着〇名）
- ベネフィット強調（例：無料で試す、特別価格で）

各文言は15文字以内。1行に1つずつ、番号なしで出力してください。
""",
        }

        prompt = prompts.get(text_type, f"{text_type}の文章を{count}つ生成してください。")

        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {
                    "role": "system", 
                    "content": "あなたは情報商材に特化したプロのコピーライターです。高額商品でも売れる、心理学に基づいた文章を作成します。緊急性、限定性、社会的証明を駆使してください。"
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.8
        )

        content = response.choices[0].message.content
        texts = [t.strip() for t in content.split('\n') if t.strip() and not t.strip().startswith(('1.', '2.', '3.', '4.', '5.'))]
        return texts[:count]

    @staticmethod
    async def analyze_and_suggest_improvements(lp_data: Dict[str, Any], analytics: Dict[str, Any]) -> Dict[str, Any]:
        """分析結果に基づいて改善提案"""

        prompt = f"""
あなたはコンバージョン最適化のエキスパートです。
以下のLP分析データを見て、改善提案をしてください。

LP情報:
- タイトル: {lp_data.get('title')}
- ステップ数: {lp_data.get('step_count')}
- CTA数: {lp_data.get('cta_count')}

分析データ:
- 総閲覧数: {analytics.get('total_views')}
- CTA転換率: {analytics.get('cta_conversion_rate')}%
- ステップファネル: {analytics.get('step_funnel')}

以下の形式でJSON形式で回答してください：
{{
  "suggestions": [
    {{
      "type": "headline" | "structure" | "cta" | "design",
      "priority": "high" | "medium" | "low",
      "issue": "問題点",
      "suggestion": "具体的な改善提案",
      "expected_impact": "期待される効果"
    }}
  ],
  "overall_score": 85,
  "reasoning": "総合的な評価理由"
}}
"""

        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "あなたはランディングページ最適化のエキスパートです。JSON形式で回答してください。"},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )

        return json.loads(response.choices[0].message.content)


NOTE_AI_MODEL = "gpt-4o-mini"

LOGGER = logging.getLogger(__name__)


COMPLIANCE_HEURISTICS: List[Dict[str, Any]] = [
    {
        "pattern": re.compile(r"(100[%％]|１００％|絶対に|必ず)[^\n]{0,20}(稼げる|儲かる|成功する)", re.IGNORECASE),
        "status": "block",
        "category": "over_promise",
        "reason": "「絶対に」「100%」などの確約表現と収益の組み合わせは景品表示法に抵触する可能性があります。",
    },
    {
        "pattern": re.compile(r"(完治|治癒|治す|全快)[^\n]{0,10}(癌|がん|病気|疾患|ウイルス)", re.IGNORECASE),
        "status": "caution",
        "category": "medical_claim",
        "reason": "医療・治療効果を断定する表現が含まれています。薬機法に配慮してください。",
    },
    {
        "pattern": re.compile(r"(副作用なし|リスク0|誰でも)[^\n]{0,15}(痩せる|やせる|保証)", re.IGNORECASE),
        "status": "caution",
        "category": "health_claim",
        "reason": "健康・減量に関するリスクゼロを断定する表現が含まれています。",
    },
    {
        "pattern": re.compile(r"1日で|１日で|24時間で|即日で"),
        "status": "caution",
        "category": "time_promise",
        "reason": "極端に短期間での成果を断定する表現が含まれています。",
    },
]


class NoteAIService:
    """NOTE記事向けのAI補助機能"""

    @staticmethod
    def _ensure_enabled() -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OpenAI API key is not configured.")

    @staticmethod
    def _block_text(block: Any) -> str:
        text: Optional[str] = getattr(block, "text", None)
        if not text and isinstance(block, dict):
            text = block.get("text")  # type: ignore[assignment]
        if text:
            return str(text)

        data: Optional[Dict[str, Any]] = None
        if hasattr(block, "data"):
            possible = getattr(block, "data")
            if isinstance(possible, dict):
                data = possible
        elif isinstance(block, dict):
            possible = block.get("data")
            if isinstance(possible, dict):
                data = possible

        if data:
            raw_text = data.get("text")
            if isinstance(raw_text, str) and raw_text.strip():
                return raw_text
            items = data.get("items")
            if isinstance(items, list):
                collected = [str(item).strip() for item in items if isinstance(item, str) and item.strip()]
                if collected:
                    return "\n".join(collected)

        return ""

    @staticmethod
    def _build_context_summary(context: NoteAIContext) -> str:
        lines: List[str] = [
            f"タイトル: {context.title}",
            f"概要: {context.excerpt or '（未設定）'}",
        ]
        if context.categories:
            lines.append(f"カテゴリ: {', '.join(context.categories)}")
        if context.audience:
            lines.append(f"想定読者: {context.audience}")
        if context.tone:
            lines.append(f"希望トーン: {context.tone}")
        lines.append("本文ブロック:")
        for block in context.blocks:
            snippet = block.text
            if not snippet and isinstance(block.data, dict):
                raw = block.data.get("text")
                if isinstance(raw, str):
                    snippet = raw
                elif block.type == "list" and isinstance(block.data.get("items"), list):
                    items = [str(item) for item in block.data["items"] if isinstance(item, str)]
                    snippet = " / ".join(items[:4])
            snippet = (snippet or "").strip()
            if len(snippet) > 160:
                snippet = snippet[:160] + "…"
            lines.append(f"- [{block.type}] {block.id}: {snippet or '（内容なし）'}")
        return "\n".join(lines)

    @staticmethod
    def _call_json_chat(system_prompt: str, user_prompt: str, temperature: float = 0.6) -> Dict[str, Any]:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=NOTE_AI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        raw = response.choices[0].message.content if response.choices else None
        if not raw:
            return {}
        return json.loads(raw)

    @staticmethod
    def _split_paragraphs(text: str) -> List[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    @staticmethod
    def _sentence_count(text: str) -> int:
        segments = re.split(r"[。．\.！？!?]+", text)
        count = len([segment.strip() for segment in segments if segment.strip()])
        return max(1, count)

    @staticmethod
    def _bullet_count(text: str) -> int:
        bullet_pattern = re.compile(r"^([\-*•●・]|[0-9]+[\.)、．])\s*")
        count = 0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if bullet_pattern.match(stripped):
                count += 1
        return count

    @staticmethod
    def _estimate_reading_time_seconds(length: int) -> int:
        # 日本語文章を1分あたり約420文字読むと仮定
        seconds = math.ceil((length / 420) * 60)
        return max(15, seconds)

    @staticmethod
    def _build_metrics(original_text: str, revised_text: str) -> NoteRewriteMetrics:
        original_length = max(1, len(original_text))
        revised_length = len(revised_text)
        paragraphs = NoteAIService._split_paragraphs(revised_text)
        metrics = NoteRewriteMetrics(
            paragraph_count=len(paragraphs) or 1,
            sentence_count=NoteAIService._sentence_count(revised_text),
            length=revised_length,
            length_ratio=round(revised_length / original_length, 3),
            bullet_count=NoteAIService._bullet_count(revised_text),
            reading_time_seconds=NoteAIService._estimate_reading_time_seconds(revised_length),
        )
        return metrics

    @staticmethod
    def _score_candidate(
        original_text: str,
        metrics: NoteRewriteMetrics,
        original_stats: Dict[str, int],
        warnings: List[str],
        block_type: Optional[str],
        revised_text: str,
    ) -> int:
        score = 100.0

        ratio = metrics.length_ratio
        if ratio < 0.85:
            score -= (0.85 - ratio) * 160 + 20
        elif ratio > 1.25:
            score -= (ratio - 1.25) * 160 + 20
        else:
            score += max(0.0, (1.05 - abs(1 - ratio)) * 10)

        paragraph_diff = abs(metrics.paragraph_count - max(1, original_stats["paragraph_count"]))
        if paragraph_diff > 0:
            score -= min(35, paragraph_diff * 12)

        sentence_diff = abs(metrics.sentence_count - max(1, original_stats["sentence_count"]))
        if sentence_diff > 4:
            score -= (sentence_diff - 4) * 4

        original_bullets = original_stats["bullet_count"]
        if original_bullets > 0:
            bullet_diff = abs(metrics.bullet_count - original_bullets)
            if bullet_diff > 0:
                score -= min(30, bullet_diff * 10)

        if metrics.length == original_stats["length"] and original_text.strip():
            score -= 10  # 変化がない場合は減点

        score -= min(40, len(warnings) * 6)

        if block_type == "heading":
            if "\n" in revised_text:
                score -= 35
            if len(revised_text.strip()) > 60:
                score -= min(30, len(revised_text.strip()) - 60)
        elif block_type == "list":
            if metrics.bullet_count == 0:
                score -= 35
        elif block_type == "quote":
            paragraph_gap = metrics.paragraph_count - max(1, original_stats["paragraph_count"])
            if paragraph_gap > 1:
                score -= min(20, paragraph_gap * 8)

        return max(0, min(100, int(round(score))))

    @staticmethod
    def _assign_rewrite_experiment(
        request: NoteRewriteRequest,
        context: NoteAIContext,
        user_id: Optional[str] = None,
    ) -> NoteRewriteExperiment:
        experiment_id = "note-ai-rewrite-phase7"
        seed_components = [experiment_id, request.target_block_id or ""]
        if user_id:
            seed_components.append(user_id)
        seed_components.append(context.title or "")
        seed = "::".join(seed_components)
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 100
        variant_id = "control" if bucket < 50 else "quality_insights"
        cohort_id = "bucket-{:02d}".format(bucket // 10)
        parameters = {
            "assignment_seed": digest,
            "bucket": bucket,
        }
        return NoteRewriteExperiment(
            experiment_id=experiment_id,
            variant_id=variant_id,
            cohort_id=cohort_id,
            parameters=parameters,
        )

    @staticmethod
    def _normalize_line_endings(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _sanitize_heading_text(text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        heading = re.sub(r"\s+", " ", lines[0])
        return heading[:80]

    @staticmethod
    def _apply_proofread_suggestion(original_text: str, snippet: str, suggestion: str) -> str:
        original = NoteAIService._normalize_line_endings(original_text)
        needle = NoteAIService._normalize_line_endings(snippet)
        replacement = NoteAIService._normalize_line_endings(suggestion)

        if not original:
            return replacement

        if needle and needle in original:
            return original.replace(needle, replacement, 1)

        collapsed_original = re.sub(r"\s+", " ", original)
        collapsed_needle = re.sub(r"\s+", " ", needle)
        collapsed_replacement = re.sub(r"\s+", " ", replacement)

        if needle and collapsed_needle in collapsed_original:
            # When only spacing differs, prefer using collapsed substitution but fall back to replacement structure.
            if replacement.strip():
                return replacement
            return original

        # If replacement is empty, keep original text. Otherwise prefer replacement when longer than snippet heuristic.
        if replacement.strip():
            if not needle or len(replacement) >= len(needle) or len(original) <= len(replacement) * 1.1:
                return replacement

        return original

    @staticmethod
    def _evaluate_compliance(text: str) -> NoteRewriteCompliance:
        normalized = text.strip()
        if not normalized:
            return NoteRewriteCompliance()

        status: Literal["pass", "caution", "block"] = "pass"  # type: ignore[assignment]
        categories: List[str] = []
        reasons: List[str] = []
        allow_application = True

        for rule in COMPLIANCE_HEURISTICS:
            pattern = rule.get("pattern")
            if isinstance(pattern, re.Pattern) and pattern.search(normalized):
                category = rule.get("category")
                reason = rule.get("reason")
                rule_status = rule.get("status", "caution")
                if isinstance(category, str) and category not in categories:
                    categories.append(category)
                if isinstance(reason, str):
                    reasons.append(reason)
                if rule_status == "block":
                    status = "block"
                    allow_application = False
                elif status != "block" and rule_status == "caution":
                    status = "caution"

        try:
            client = get_openai_client()
            moderation = client.moderations.create(
                model="omni-moderation-latest",
                input=normalized[:15000],
            )
            results = getattr(moderation, "results", None)
            result = results[0] if results else None
            if result:
                flagged = getattr(result, "flagged", False)
                category_map = getattr(result, "categories", {}) or {}
                if flagged:
                    status = "block"
                    allow_application = False
                    reasons.append("OpenAIモデレーションで不適切と判定されました。")
                for category_name, is_flagged in category_map.items():
                    if is_flagged and category_name not in categories:
                        categories.append(str(category_name))
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Compliance moderation check failed: %s", exc)
            if status == "pass":
                status = "caution"
            reasons.append("自動モデレーションチェックが完了しませんでした。内容を再確認してください。")

        unique_reasons = list(dict.fromkeys(reasons))
        return NoteRewriteCompliance(
            status=status,
            categories=categories,
            reasons=unique_reasons,
            allow_application=allow_application,
        )

    @staticmethod
    async def rewrite_block(request: NoteRewriteRequest) -> NoteRewriteResponse:
        NoteAIService._ensure_enabled()
        context = request.context
        summary = NoteAIService._build_context_summary(context)
        target = next((block for block in context.blocks if block.id == request.target_block_id), None)
        if not target:
            raise ValueError("Target block not found in context")
        original_text = (target.text or "").strip()
        if not original_text and isinstance(target.data, dict):
            raw = target.data.get("text")
            if isinstance(raw, str):
                original_text = raw.strip()
        if not original_text:
            raise ValueError("Target block does not contain rewritable text")

        instructions = request.instructions or "読みやすさと説得力を高めてください。"
        style_hint = request.style_hint or context.tone or "自然で信頼感のある日本語"
        block_type = target.type
        original_stats = {
            "length": len(original_text),
            "paragraph_count": len(NoteAIService._split_paragraphs(original_text)) or 1,
            "sentence_count": NoteAIService._sentence_count(original_text),
            "bullet_count": NoteAIService._bullet_count(original_text),
        }

        experiment = NoteAIService._assign_rewrite_experiment(request, context)
        LOGGER.info(
            "note_ai_rewrite_exposure: experiment_id=%s variant_id=%s block_id=%s",
            experiment.experiment_id,
            experiment.variant_id,
            request.target_block_id,
        )

        block_type_label = {
            "paragraph": "本文",
            "heading": "見出し",
            "quote": "引用",
            "list": "箇条書き",
        }.get(block_type or "paragraph", str(block_type))

        type_requirements: List[str] = []
        if block_type == "heading":
            type_requirements.extend(
                [
                    "見出しは1行で完結にまとめ、60文字以内を目安にする",
                    "終止符（。や！など）は可能な限り付けず、キーワードを並べて印象を高める",
                ]
            )
        elif block_type == "list":
            type_requirements.extend(
                [
                    "各項目は箇条書きの形式（- ・ 1. などの記号）を維持する",
                    "項目数や順序を大きく変えず、内容の磨き込みに集中する",
                ]
            )
        elif block_type == "quote":
            type_requirements.extend(
                [
                    "引用の趣旨を尊重しつつ、句読点や改行を整えて読みやすくする",
                    "引用でない新しい主張や要素を追加しない",
                ]
            )

        base_requirements = [
            "重要な事実や具体例、数値などの情報を削除しない",
            "文章量は原文の80%〜120%程度で維持する",
            "段落構造や箇条書きの項目数を保ちつつ、表現を自然な日本語へ整える",
            "原文になかった情報や主張を無断で付け足さない",
            "各候補は互いに十分な差異をつけ、編集方針が分かるようにする",
        ]
        requirements_text = "\n".join([f"- {item}" for item in base_requirements + type_requirements])

        system_prompt = (
            "あなたは優秀な編集者です。文脈を崩さずに文章の質を高め、複数の改善案を提示します。"
        )
        user_prompt = f'''
以下はNOTE記事の概要です。内容を把握したうえで、指定した段落をリライトし、最大3つの改善案を提示してください。

{summary}

対象ブロックID: {target.id}
ブロックタイプ: {block_type_label} ({block_type})
元の文章:
"""{original_text}"""

指示: {instructions}
トーンの希望: {style_hint}
必ず守ること:
{requirements_text}

JSON形式で以下のように回答してください:
{{
  "candidates": [
    {{
      "title": "簡潔なラベル（例：読みやすさ重視）",
      "revised_text": "リライト案",
      "reasoning": "変更の意図や編集方針",
      "tone": "採用したトーン（任意）",
      "strengths": ["改善のポイント"],
      "warnings": ["留意点"]
    }}
  ],
  "evaluation_notes": "候補全体に関するメモ（任意）"
}}

候補が1つしか適切でない場合は1つのみで構いません。
'''

        result = NoteAIService._call_json_chat(system_prompt, user_prompt, temperature=0.65)

        raw_candidates: List[Dict[str, Any]] = []
        if isinstance(result.get("candidates"), list):
            raw_candidates = [item for item in result["candidates"] if isinstance(item, dict)]
        else:
            single_text = result.get("revised_text")
            if isinstance(single_text, str) and single_text.strip():
                raw_candidates = [
                    {
                        "title": result.get("title") or "候補1",
                        "revised_text": single_text,
                        "reasoning": result.get("reasoning"),
                        "tone": result.get("tone"),
                        "strengths": result.get("strengths"),
                        "warnings": result.get("warnings"),
                    }
                ]

        candidates: List[NoteRewriteCandidate] = []

        for index, payload in enumerate(raw_candidates[:3]):
            revised = payload.get("revised_text") or payload.get("text") or ""
            if not isinstance(revised, str):
                continue
            revised_text = revised.strip()
            if not revised_text:
                continue
            revised_text = NoteAIService._normalize_line_endings(revised_text)

            heading_adjusted = False
            if block_type == "heading":
                sanitized_heading = NoteAIService._sanitize_heading_text(revised_text)
                if sanitized_heading != revised_text:
                    heading_adjusted = True
                    revised_text = sanitized_heading
            title_raw = payload.get("title")
            title = title_raw.strip() if isinstance(title_raw, str) and title_raw.strip() else f"候補{index + 1}"
            reasoning_raw = payload.get("reasoning") or payload.get("analysis")
            reasoning = reasoning_raw.strip() if isinstance(reasoning_raw, str) and reasoning_raw.strip() else None
            tone_raw = payload.get("tone") or payload.get("tone_applied")
            tone_applied = tone_raw.strip() if isinstance(tone_raw, str) and tone_raw.strip() else style_hint

            strengths_raw = payload.get("strengths")
            strengths = [str(item).strip() for item in strengths_raw if isinstance(item, str) and item.strip()] if isinstance(strengths_raw, list) else []
            warnings_raw = payload.get("warnings")
            warnings = [str(item).strip() for item in warnings_raw if isinstance(item, str) and item.strip()] if isinstance(warnings_raw, list) else []

            if heading_adjusted:
                warnings.append("見出しは1行で整理してください。")

            metrics = NoteAIService._build_metrics(original_text, revised_text)

            if metrics.length_ratio < 0.8:
                warnings.append("文章量が原文の80%未満です。")
            elif metrics.length_ratio > 1.25:
                warnings.append("文章量が原文の125%を超えています。")

            if metrics.paragraph_count < original_stats["paragraph_count"]:
                warnings.append("段落数が原文より減少しています。")

            if original_stats["bullet_count"] > 0 and metrics.bullet_count != original_stats["bullet_count"]:
                warnings.append("箇条書きの項目数が原文と一致していません。")

            if block_type == "heading":
                if "\n" in revised_text:
                    warnings.append("見出しは改行を含めず1行で記述してください。")
                if len(revised_text.strip()) > 60:
                    warnings.append("見出しは60文字以内に収めてください。")
            elif block_type == "list":
                if metrics.bullet_count == 0:
                    warnings.append("箇条書きの形式を維持してください。")
            elif block_type == "quote":
                if metrics.paragraph_count > max(1, original_stats["paragraph_count"]) + 1:
                    warnings.append("引用ブロックが冗長です。段落を整理してください。")

            if revised_text == original_text:
                warnings.append("原文と内容がほとんど変わっていません。")

            if not strengths:
                if metrics.paragraph_count == original_stats["paragraph_count"]:
                    strengths.append("段落構造を維持しています。")
                strengths.append("読みやすさと一貫性を意識した調整です。")

            compliance = NoteAIService._evaluate_compliance(revised_text)
            for reason in compliance.reasons:
                if reason not in warnings:
                    warnings.append(reason)

            strengths = list(dict.fromkeys(strengths))
            warnings = list(dict.fromkeys(warnings))

            score = NoteAIService._score_candidate(
                original_text,
                metrics,
                original_stats,
                warnings,
                block_type,
                revised_text,
            )
            if compliance.status == "block":
                score = min(score, 10)
            elif compliance.status == "caution":
                score = max(0, score - 20)

            candidate = NoteRewriteCandidate(
                id=str(uuid4()),
                title=title,
                revised_text=revised_text,
                reasoning=reasoning,
                tone_applied=tone_applied,
                score=score,
                metrics=metrics,
                strengths=strengths,
                warnings=warnings,
                compliance=compliance,
            )
            candidates.append(candidate)

        original_metrics = NoteAIService._build_metrics(original_text, original_text)
        original_candidate = NoteRewriteCandidate(
            id=str(uuid4()),
            title="原文を維持",
            revised_text=original_text,
            reasoning="変更を適用しない場合はこちらを選択してください。",
            tone_applied=context.tone or "原文",
            score=NoteAIService._score_candidate(
                original_text,
                original_metrics,
                original_stats,
                ["原文と同一です。"],
                block_type,
                original_text,
            ),
            metrics=original_metrics,
            strengths=["内容をそのまま維持します。"],
            warnings=["原文と同一です。"],
            compliance=NoteRewriteCompliance(),
        )

        if all(candidate.revised_text != original_text for candidate in candidates):
            candidates.append(original_candidate)

        if not candidates:
            candidates.append(original_candidate)

        seen_texts: Dict[str, NoteRewriteCandidate] = {}
        for candidate in candidates:
            key = candidate.revised_text
            existing = seen_texts.get(key)
            if existing is None:
                seen_texts[key] = candidate
                continue
            existing_compliance = existing.compliance.status if existing.compliance else "pass"
            candidate_compliance = candidate.compliance.status if candidate.compliance else "pass"
            if existing_compliance == "block" and candidate_compliance != "block":
                seen_texts[key] = candidate
                continue
            if candidate.score > existing.score:
                seen_texts[key] = candidate

        unique_candidates = list(seen_texts.values())
        unique_candidates.sort(key=lambda item: item.score, reverse=True)
        viable_candidates = [item for item in unique_candidates if not item.compliance or item.compliance.allow_application]
        preferred_candidates = viable_candidates or unique_candidates
        recommended_candidate = preferred_candidates[0]
        recommended_candidate_id = recommended_candidate.id

        evaluation_notes = result.get("evaluation_notes")
        if not isinstance(evaluation_notes, str) or not evaluation_notes.strip():
            aggregated_warnings: List[str] = []
            for candidate in unique_candidates:
                aggregated_warnings.extend(candidate.warnings)
            if aggregated_warnings:
                unique_warning_texts = sorted(set(aggregated_warnings))
                evaluation_notes = "注意点: " + " / ".join(unique_warning_texts[:3])
            else:
                evaluation_notes = None

        alerts: List[str] = []
        for candidate in unique_candidates:
            compliance = candidate.compliance
            if not compliance:
                continue
            if compliance.status in {"caution", "block"}:
                alerts.extend(compliance.reasons or candidate.warnings)
        alerts = list(dict.fromkeys(alerts))

        score_threshold = recommended_candidate.score >= 75
        compliance_status = recommended_candidate.compliance.status if recommended_candidate.compliance else "pass"
        compliance_threshold = compliance_status != "block"
        alerts_threshold = len(alerts) == 0
        thresholds = {
            "score_minimum": score_threshold,
            "compliance_pass": compliance_threshold,
            "no_alerts": alerts_threshold,
        }
        ready_for_release = all(thresholds.values()) and compliance_status != "caution"

        quality = NoteRewriteQuality(
            scoring_version="2025-11-phase6",
            evaluated_at=datetime.now(timezone.utc),
            global_score=recommended_candidate.score,
            summary=evaluation_notes or "AI候補の評価が完了しました。",
            alerts=alerts[:5],
            thresholds=thresholds,
            ready_for_release=ready_for_release,
        )

        LOGGER.info(
            "note_ai_rewrite_quality: %s",
            json.dumps(
                {
                    "block_id": target.id,
                    "recommended_candidate_id": recommended_candidate_id,
                    "score": recommended_candidate.score,
                    "thresholds": thresholds,
                    "ready_for_release": ready_for_release,
                    "alerts": alerts[:5],
                    "experiment": experiment.dict(),
                },
                ensure_ascii=False,
            ),
        )

        return NoteRewriteResponse(
            block_id=target.id,
            original_text=original_text,
            candidates=unique_candidates,
            recommended_candidate_id=recommended_candidate_id,
            evaluation_notes=evaluation_notes,
            quality=quality,
            experiment=experiment,
        )

    @staticmethod
    def record_rewrite_feedback(request: NoteRewriteFeedbackRequest) -> None:
        NoteAIService._ensure_enabled()
        payload = request.dict()
        payload["received_at"] = datetime.now(timezone.utc).isoformat()
        LOGGER.info("note_ai_rewrite_feedback: %s", json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def assign_rewrite_experiment(
        request: NoteRewriteRequest,
        user_id: Optional[str] = None,
    ) -> NoteRewriteExperiment:
        return NoteAIService._assign_rewrite_experiment(request, request.context, user_id=user_id)

    @staticmethod
    def assign_rewrite_experiment_by_seed(
        seed: Optional[str] = None,
        note_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> NoteRewriteExperiment:
        pseudo_request = NoteRewriteRequest(
            context=NoteAIContext(
                title=note_id or "",
                excerpt=None,
                categories=[],
                tone=None,
                audience=None,
                language="ja",
                blocks=[],
            ),
            target_block_id=seed or "seed-default",
        )
        return NoteAIService._assign_rewrite_experiment(pseudo_request, pseudo_request.context, user_id=user_id)

    @staticmethod
    async def proofread(request: NoteProofreadRequest) -> NoteProofreadResponse:
        NoteAIService._ensure_enabled()
        context = request.context
        summary = NoteAIService._build_context_summary(context)
        focus = request.focus or "spelling"

        block_lookup: Dict[str, Any] = {str(block.id): block for block in context.blocks if getattr(block, "id", None)}

        system_prompt = "あなたは日本語の校正者です。誤字脱字、文体の整合性、語尾の統一も確認します。"
        user_prompt = f"""
以下のNOTE記事について、{focus} を中心に校正結果を提示してください。

{summary}

JSON形式で以下の通りに回答してください:
{{
  "summary": "全体的な所感",
  "corrections": [
    {{
      "block_id": "対象ブロックID",
      "original": "修正前の表現（原文から抜粋）",
      "suggestion": "該当ブロック全体の修正後テキスト（段落や改行を含めて完全に出力）",
      "explanation": "理由"
    }}
  ]
}}
"""

        result = NoteAIService._call_json_chat(system_prompt, user_prompt, temperature=0.4)
        corrections_payload = result.get("corrections") if isinstance(result.get("corrections"), list) else []
        corrections: List[NoteProofreadCorrection] = []
        for item in corrections_payload:
            block_id = item.get("block_id")
            original = item.get("original")
            suggestion = item.get("suggestion")
            if not (block_id and original and suggestion):
                continue
            block = block_lookup.get(str(block_id))
            block_text = NoteAIService._block_text(block) if block else ""
            applied = NoteAIService._apply_proofread_suggestion(block_text, str(original), str(suggestion))
            corrections.append(
                NoteProofreadCorrection(
                    block_id=block_id,
                    original=original,
                    suggestion=applied,
                    explanation=item.get("explanation"),
                )
            )

        return NoteProofreadResponse(
            summary=result.get("summary"),
            corrections=corrections,
        )

    @staticmethod
    async def suggest_structure(request: NoteStructureRequest) -> NoteStructureResponse:
        NoteAIService._ensure_enabled()
        context = request.context
        summary = NoteAIService._build_context_summary(context)
        goal = request.desired_outcome or "読者の理解と購買意欲を高める"

        system_prompt = "あなたは構成編集の専門家です。読みやすさと説得力を両立させる提案を行います。"
        user_prompt = f"""
以下のNOTE記事を読み、構成と流れを改善するための提案を最大3つ提示してください。

{summary}

目標: {goal}

補足条件:
- suggested_text には説明文ではなく、そのままNOTEに挿入できる完成済みの文章を記載する（1〜3段落程度）
- action が reorder または trim の場合は suggested_text を空文字にしてもよい
- suggested_block_type には paragraph・heading・list・quote のいずれかを指定し、該当しない場合は null を指定する
- 構成変更だけでなく、必要に応じて完成した見出しや本文の例も提示する

JSON形式で回答してください:
{{
  "outline": ["提案後の簡易アウトライン"],
  "suggestions": [
    {{
      "title": "提案タイトル",
      "description": "提案の詳細",
      "action": "insert|reorder|expand|trim",
      "block_id": "関連ブロックID",
      "suggested_block_type": "paragraph|heading|list|quote|null",
      "suggested_text": "挿入や修正の例（挿入不要な場合は空文字）"
    }}
  ]
}}
"""

        result = NoteAIService._call_json_chat(system_prompt, user_prompt, temperature=0.5)
        outline = result.get("outline") if isinstance(result.get("outline"), list) else None
        suggestions_raw = result.get("suggestions") if isinstance(result.get("suggestions"), list) else []
        suggestions: List[NoteStructureSuggestion] = []
        for item in suggestions_raw:
            title = item.get("title")
            description = item.get("description")
            if not title or not description:
                continue
            action = item.get("action") or "insert"
            if action not in {"insert", "reorder", "expand", "trim"}:
                action = "insert"
            raw_text = item.get("suggested_text") if isinstance(item.get("suggested_text"), str) else None
            suggested_text = None
            if isinstance(raw_text, str):
                normalized_text = NoteAIService._normalize_line_endings(raw_text).strip()
                if normalized_text:
                    suggested_text = normalized_text

            block_type_hint_raw = item.get("suggested_block_type")
            block_type_hint = block_type_hint_raw.lower() if isinstance(block_type_hint_raw, str) else None
            if block_type_hint not in {"paragraph", "heading", "list", "quote"}:
                block_type_hint = None

            if action in {"reorder", "trim"}:
                suggested_text = None

            if suggested_text and suggested_text.strip() == description.strip():
                suggested_text = None

            suggestions.append(
                NoteStructureSuggestion(
                    title=title,
                    description=description,
                    action=action,  # type: ignore[arg-type]
                    block_id=item.get("block_id"),
                    suggested_text=suggested_text,
                    suggested_block_type=block_type_hint,  # type: ignore[arg-type]
                )
            )

        return NoteStructureResponse(suggestions=suggestions, outline=outline)

    @staticmethod
    async def review(request: NoteReviewRequest) -> NoteReviewResponse:
        NoteAIService._ensure_enabled()
        context = request.context
        summary = NoteAIService._build_context_summary(context)

        system_prompt = "あなたは編集長です。記事全体を評価し、改善すべき点を示してください。"
        user_prompt = f"""
以下のNOTE記事を評価し、読者体験と説得力の観点からフィードバックを提示してください。

{summary}

JSON形式で回答してください:
{{
  "score": 0-100 の整数,
  "summary": "全体講評",
  "issues": [
    {{
      "severity": "info|warn|error",
      "message": "指摘内容",
      "block_id": "対象ブロックID",
      "field": "任意のフィールド"
    }}
  ],
  "recommended_actions": ["次のステップ"]
}}
"""

        result = NoteAIService._call_json_chat(system_prompt, user_prompt, temperature=0.45)
        score = result.get("score")
        if not isinstance(score, int):
            score = 75
        summary_text = result.get("summary") or "全体として読みやすい記事です。"
        issues_raw = result.get("issues") if isinstance(result.get("issues"), list) else []
        issues: List[NoteReviewIssue] = []
        for item in issues_raw:
            message = item.get("message")
            severity = item.get("severity") or "info"
            if not message:
                continue
            if severity not in {"info", "warn", "error"}:
                severity = "info"
            issues.append(
                NoteReviewIssue(
                    severity=severity,  # type: ignore[arg-type]
                    message=message,
                    block_id=item.get("block_id"),
                    field=item.get("field"),
                )
            )

        recommended_actions = result.get("recommended_actions")
        if not isinstance(recommended_actions, list):
            recommended_actions = []

        return NoteReviewResponse(
            score=score,
            summary=summary_text,
            issues=issues,
            recommended_actions=recommended_actions,
        )

