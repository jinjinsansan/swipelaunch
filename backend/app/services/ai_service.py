import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.config import settings
from app.models.ai import AIWizardInput, BonusItem, Testimonial
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

# 新しいテンプレートライブラリに対応したブロックシーケンス
ALLOWED_BLOCK_SEQUENCE = [
    "top-hero-1",          # ヒーロー（動画背景） - 動的に選択
    "top-problem-1",       # 問題提起
    "top-highlights-1",    # ハイライト・特徴
    "top-before-after-1",  # ビフォーアフター
    "top-testimonials-1",  # お客様の声
    "top-bonus-1",         # 特典
    "top-pricing-1",       # 価格表
    "top-faq-1",           # FAQ
    "top-guarantee-1",     # 保証
    "top-countdown-1",     # カウントダウン
    "top-cta-1",           # CTA
]


OUTLINE_FALLBACK_LABELS = {
    "top-hero-1": "ヒーローセクション",
    "top-problem-1": "課題の共感",
    "top-highlights-1": "選ばれる理由",
    "top-before-after-1": "導入前後の変化",
    "top-testimonials-1": "お客様の声",
    "top-bonus-1": "申込特典",
    "top-pricing-1": "料金プラン",
    "top-faq-1": "よくある質問",
    "top-guarantee-1": "返金保証",
    "top-countdown-1": "締切カウントダウン",
    "top-cta-1": "今すぐ申し込む",
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
                "- top-problem-1: 共感と課題提示（3-5個の問題点）",
                "- top-highlights-1: 選ばれる理由（3個の特徴・アイコン付き）",
                "- top-before-after-1: 導入前後の変化訴求",
                "- top-testimonials-1: お客様の声・社会的証明（3件）",
                "- top-bonus-1: 申込特典の一覧（3-5個）",
                "- top-pricing-1: 料金プラン",
                "- top-faq-1: よくある質問（3-5個）",
                "- top-guarantee-1: 返金保証・安心材料",
                "- top-countdown-1: 締切カウントダウン",
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

        # ブロックマップを作成（重複防止）
        block_map: Dict[str, Dict[str, Any]] = {}
        for block in ai_blocks:
            block_type = block.get("blockType")
            if block_type in ALLOWED_BLOCK_SEQUENCE and block_type not in block_map:
                block_map[block_type] = block

        processed_blocks: List[Dict[str, Any]] = []

        for block_type in ALLOWED_BLOCK_SEQUENCE:
            block_data = block_map.get(block_type)
            if not block_data:
                block_data = {
                    "blockType": block_type,
                    "reason": "コンテキストを基に自動補完しました。",
                    "content": {},
                }

            # 選択されたヒーローIDを渡す
            processed_block = AIService._apply_defaults(
                block_data, input_data, selected_hero_id=selected_hero_id
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
        selected_hero_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """各ブロックにデフォルト値を適用"""
        
        block_type = block.get("blockType")
        content = dict(block.get("content") or {})
        reason = block.get("reason") or "ユーザー入力に基づき生成されました。"

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
            
            # AIが生成した値を尊重（setdefaultは使わない）
            if "title" not in content:
                content["title"] = "今だけの特典"
            if "subtitle" not in content:
                content["subtitle"] = "お申込者限定で以下の特典をプレゼント"
            
            total_value = content.get("totalValue") or AIService._calculate_bonus_total(bonuses)
            if total_value:
                content["totalValue"] = total_value
            
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
            
            # AIが生成した値を優先（setdefaultは最後のフォールバックのみ）
            if "title" not in content:
                if guarantee and guarantee.headline:
                    content["title"] = guarantee.headline
                # 固定文言は削除 - AIに生成させる
            
            if "subtitle" not in content:
                content["subtitle"] = "安心してお試しいただけます"
            
            # descriptionもAI生成を優先
            if "description" not in content:
                if guarantee and guarantee.description:
                    content["description"] = guarantee.description
                # 固定文言は削除 - AIに生成させる
            
            if "badgeText" not in content:
                content["badgeText"] = "100%保証"
            
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

        # ===== top-cta-1: CTA =====
        elif block_type == "top-cta-1":
            reason = "最終的な行動喚起で、明確な次のステップを提示するため。"
            
            # AIが生成した値を優先（固定文言は最小限に）
            if "title" not in content:
                content["title"] = "今すぐ始めよう"  # 最小限のフォールバック
            
            if "subtitle" not in content:
                # ユーザー入力から生成
                content["subtitle"] = f"{product.name}で、{desired_outcome}を実現しましょう。"
            
            if "buttonText" not in content:
                content["buttonText"] = call_to_action  # ユーザー入力
            
            if "buttonUrl" not in content:
                content["buttonUrl"] = "/register"
            
            if "secondaryButtonText" not in content:
                # 固定文言は削除 - AIに生成させる or 空のまま
                pass
            
            if "secondaryButtonUrl" not in content:
                content["secondaryButtonUrl"] = "/download"
            
            content.setdefault("textColor", "#0F172A")
            content.setdefault("backgroundColor", "#E0F2FE")

        return {
            "blockType": block_type,
            "content": content,
            "reason": reason,
        }

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
