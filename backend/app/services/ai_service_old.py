import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.config import settings
from app.models.ai import AIWizardInput, BonusItem, Testimonial


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

ALLOWED_BLOCK_SEQUENCE = [
    "hero-aurora",
    "countdown-1",
    "problem-1",
    "before-after-1",
    "testimonial-1",
    "special-price-1",
    "bonus-list-1",
    "guarantee-1",
    "author-profile-1",
    "scarcity-1",
    "sticky-cta-1",
]


OUTLINE_FALLBACK_LABELS = {
    "hero-aurora": "ヒーローセクション",
    "countdown-1": "締切カウントダウン",
    "problem-1": "共感・問題提起",
    "before-after-1": "ビフォーアフター",
    "testimonial-1": "導入事例",
    "special-price-1": "特別価格",
    "bonus-list-1": "豪華特典",
    "guarantee-1": "返金保証",
    "author-profile-1": "監修者・権威",
    "scarcity-1": "残席・限定性",
    "sticky-cta-1": "固定CTA",
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

        context_json = json.dumps(input_data.dict(), ensure_ascii=False, indent=2)

        block_sequence_description = "\n".join(
            [
                "- hero-aurora: 冒頭ヒーローセクション（約束・CTA・実績）",
                "- countdown-1: 申込締切のカウントダウン",
                "- problem-1: 共感と課題提示",
                "- before-after-1: 導入前後の変化訴求",
                "- testimonial-1: 導入事例・社会的証明",
                "- special-price-1: 特別価格とオファー",
                "- bonus-list-1: 申込特典の一覧",
                "- guarantee-1: 返金保証・安心材料",
                "- author-profile-1: 監修者・講師プロフィール",
                "- scarcity-1: 限定枠・残数訴求",
                "- sticky-cta-1: 固定CTAによる行動喚起",
            ]
        )

        field_requirements = (
            "- hero-aurora: tagline, title, subtitle, highlightText, buttonText, secondaryButtonText, stats(3件{value,label})\n"
            "- countdown-1: title, urgencyText, targetDate(ISO8601), showDays, showHours, showMinutes, showSeconds\n"
            "- problem-1: title, subtitle, problems(4-6個)\n"
            "- before-after-1: title, beforeTitle, beforeText, afterTitle, afterText\n"
            "- testimonial-1: title, testimonials(3件: name, role, text, rating)\n"
            "- special-price-1: title, originalPrice, specialPrice, discountBadge, buttonText, subtitle, features\n"
            "- bonus-list-1: title, subtitle, bonuses[{title, description, value}], totalValue\n"
            "- guarantee-1: title, subtitle, guaranteeType, description, badgeText\n"
            "- author-profile-1: name, title, bio, achievements(3件), signatureText\n"
            "- scarcity-1: title, message, remainingCount, totalCount\n"
            "- sticky-cta-1: title, description, buttonText, subText, position"
        )

        system_prompt = (
            "あなたは情報商材LPのコンバージョン最適化に特化したクリエイティブディレクターです。"
            "心理トリガー・権威性・社会的証明・緊急性を統合し、"
            "ユーザー入力を基にほぼ完成形の日本語コピーを生成してください。"
        )

        user_prompt = f"""
# 目的
ヒアリングで得た情報を基に、すぐに公開できるレベルの日本語LP構成とコピーを生成してください。

# 入力データ
{context_json}

# 必須ブロック（順番厳守）
{block_sequence_description}

# 出力要件
- 出力言語は必ず日本語。
- ブロックは上記の順番で作成し、欠落なく出力すること。
- 各ブロックの主要フィールド:
{field_requirements}
- 数字・期間・成果・限定数などは可能な限り具体的で信頼感のある値を設定する。
- 情報が不足している場合は、コンバージョン最適化の観点から説得力のある内容を補完する。
- JSON形式で以下の構造のみを返すこと。
{{
  "outline": ["セクション概要1", "セクション概要2", ...],
  "blocks": [
    {{
      "blockType": "hero-aurora",
      "reason": "このブロックが効果的な理由",
      "content": {{ ブロック固有フィールド }}
    }}
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

            processed_block = AIService._apply_defaults(block_data, input_data)
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
    def _apply_defaults(block: Dict[str, Any], data: AIWizardInput) -> Dict[str, Any]:
        block_type = block.get("blockType")
        content = dict(block.get("content") or {})
        reason = block.get("reason") or "ユーザー入力に基づき生成されました。"

        theme_key = data.theme or DEFAULT_THEME
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

        if block_type == "hero-aurora":
            reason = "冒頭で強い約束とCTAを提示し、信頼と期待感を一気に高めるため。"
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
            content.setdefault("secondaryButtonText", "導入事例を確認する")

            stats = content.get("stats") if isinstance(content.get("stats"), list) else []
            if not stats:
                stats_candidates: List[Dict[str, str]] = []
                if price and price.special:
                    stats_candidates.append({"value": price.special, "label": "期間限定価格"})
                if product.duration:
                    stats_candidates.append({"value": product.duration, "label": "伴走期間"})
                if product.key_features:
                    stats_candidates.append({"value": f"{len(product.key_features)}項目", "label": "主要メリット"})
                if offer.bonuses:
                    stats_candidates.append({"value": f"+{len(offer.bonuses)}特典", "label": "特典総額"})
                if not stats_candidates:
                    stats_candidates = [
                        {"value": "3 STEP", "label": "導入プロセス"},
                        {"value": "95%", "label": "受講満足度"},
                        {"value": "30日", "label": "成果実感"},
                    ]
                content["stats"] = stats_candidates[:3]

        elif block_type == "countdown-1":
            reason = "締切を明示し、今すぐ行動する理由を与えるため。"
            content.setdefault("title", "申込締切まで残りわずか")
            urgency = content.get("urgencyText") or scarcity_text or (deadline_text and f"{deadline_text}までの申込で特典適用") or "枠が埋まり次第、募集を終了します。"
            content["urgencyText"] = urgency
            # Use timezone-aware datetime to avoid deprecated datetime.utcnow()
            default_target = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat()
            content["targetDate"] = content.get("targetDate") or default_target
            content.setdefault("showDays", True)
            content.setdefault("showHours", True)
            content.setdefault("showMinutes", True)
            content.setdefault("showSeconds", False)

        elif block_type == "problem-1":
            reason = "ターゲットの痛みを言語化し、強い共感を生むため。"
            content.setdefault("title", "こんなお悩みはありませんか？")
            content.setdefault("subtitle", f"{audience.persona or '多くの方'}が直面する現実")
            problems = content.get("problems") if isinstance(content.get("problems"), list) else []
            if not problems:
                problems = pain_points[:5] if pain_points else [
                    "情報が多すぎて何から手を付ければ良いか分からない",
                    "独学では再現性が低く、成果が安定しない",
                    "時間も広告費も投入したのに売上が伸び悩んでいる",
                    "魅力的なコピーを書けず申し込みにつながらない",
                    "ローンチのたびに徹夜続きで疲弊してしまう",
                ]
            content["problems"] = problems[:6]

        elif block_type == "before-after-1":
            reason = "導入前後のギャップを可視化し、成果のイメージを明確にするため。"
            content.setdefault("title", "導入前と導入後の変化")
            before_text = content.get("beforeText") or (pain_points[0] if pain_points else "時間も労力も投資したのに成果が出ない状態")
            after_text = content.get("afterText") or product.transformation or desired_outcome or "売上と時間の両立が実現"
            content.setdefault("beforeTitle", "導入前")
            content.setdefault("afterTitle", "導入後")
            content["beforeText"] = before_text
            content["afterText"] = after_text

        elif block_type == "testimonial-1":
            reason = "第三者の実績で権威性と安心感を補強するため。"
            testimonials = AIService._testimonials_to_dict(content.get("testimonials"), proof, audience.persona or data.target)
            content["testimonials"] = testimonials
            content.setdefault("title", "受講者の成果事例")
            content.setdefault("layout", content.get("layout") or "card")

        elif block_type == "special-price-1":
            reason = "今申し込む価値と金銭的な魅力を最大化するため。"
            content.setdefault("title", "今だけの特別オファー")
            special_price = content.get("specialPrice") or (price.special if price else None)
            original_price = content.get("originalPrice") or (price.original if price else None)
            if special_price:
                content["specialPrice"] = special_price
            if original_price:
                content["originalPrice"] = original_price
            discount_badge = content.get("discountBadge") or AIService._calc_discount_badge(original_price, special_price)
            if discount_badge:
                content["discountBadge"] = discount_badge
            subtitle = content.get("subtitle") or (price.payment_plan if price and price.payment_plan else "申込者限定で特別価格をご用意しました。")
            content["subtitle"] = subtitle
            content.setdefault("buttonText", call_to_action)
            if not content.get("features") and product.key_features:
                content["features"] = product.key_features[:4]

        elif block_type == "bonus-list-1":
            reason = "申込特典の価値を可視化し、値引き以上の価値を訴求するため。"
            bonuses = AIService._bonuses_to_dict(content.get("bonuses"), offer.bonuses)
            if not bonuses and product.deliverables:
                bonuses = [{"title": deliverable, "description": "", "value": ""} for deliverable in product.deliverables[:3]]
            content["bonuses"] = bonuses[:5]
            content.setdefault("title", "申込者限定の豪華特典")
            content.setdefault("subtitle", "即実践できる特典で成果までの距離を一気に縮めます")
            total_value = content.get("totalValue") or AIService._calculate_bonus_total(bonuses)
            if total_value:
                content["totalValue"] = total_value

        elif block_type == "guarantee-1":
            reason = "リスクを取り除き、申込への心理的ハードルを下げるため。"
            guarantee = offer.guarantee
            content.setdefault("title", (guarantee.headline if guarantee and guarantee.headline else "安心の保証制度"))
            content.setdefault("subtitle", "結果が出るまで伴走するリスクゼロの仕組み")
            content.setdefault("guaranteeType", (guarantee.description if guarantee and guarantee.description else "30日間 全額返金保証"))
            description = content.get("description") or (guarantee.conditions if guarantee and guarantee.conditions else "条件なしでご満足いただけなければ、申請だけでご返金いたします。")
            content["description"] = description
            content.setdefault("badgeText", guarantee.headline if guarantee and guarantee.headline else "リスクゼロ")

        elif block_type == "author-profile-1":
            reason = "誰が提供しているのかを明確にし、信頼感と専門性を訴求するため。"
            content.setdefault("name", (proof.authority_name if proof and proof.authority_name else "監修者"))
            content.setdefault("title", (proof.authority_title if proof and proof.authority_title else "コンバージョン戦略家"))
            bio = content.get("bio") or (proof.authority_bio if proof and proof.authority_bio else proof.authority_headline if proof and proof.authority_headline else f"{product.name}を主宰し、{audience.persona or '受講生'}の成果創出を支援しています。")
            content["bio"] = bio
            achievements = content.get("achievements") if isinstance(content.get("achievements"), list) else None
            if not achievements:
                if proof and proof.achievements:
                    achievements = proof.achievements[:3]
                elif product.deliverables:
                    achievements = product.deliverables[:3]
                else:
                    achievements = [
                        "累計3,200名以上のローンチを支援",
                        "平均CVRを2.3倍に改善",
                        "大手企業・著名講師のプロジェクトを多数監修",
                    ]
            content["achievements"] = achievements
            content.setdefault("signatureText", proof.authority_name if proof and proof.authority_name else product.name)

        elif block_type == "scarcity-1":
            reason = "残席や限定性を明示し、今申し込まない理由を無くすため。"
            content.setdefault("title", "残席状況のご案内")
            message = content.get("message") or scarcity_text or (deadline_text and f"{deadline_text}までの先着枠です。") or "募集枠が埋まり次第、予告なく終了します。"
            content["message"] = message
            remaining_value = content.get("remainingCount")
            remaining = remaining_value if isinstance(remaining_value, int) else AIService._parse_int(str(remaining_value)) if remaining_value else None
            if remaining is None:
                remaining = AIService._parse_int(scarcity_text) or 5
            total_value = content.get("totalCount")
            total = total_value if isinstance(total_value, int) else AIService._parse_int(str(total_value)) if total_value else None
            if total is None:
                total = max(remaining + 5, 30)
            content["remainingCount"] = remaining
            content["totalCount"] = total

        elif block_type == "sticky-cta-1":
            reason = "ページ滞在中どこからでも行動できるようにするため。"
            content.setdefault("title", call_to_action)
            description = content.get("description") or product.promise or "限定特典と保証付きで、今すぐ成果への一歩を踏み出せます。"
            content["description"] = description
            content["buttonText"] = call_to_action
            sub_text = content.get("subText") or desired_outcome or "先着順でご案内しています。"
            content["subText"] = sub_text
            content.setdefault("position", content.get("position") or "bottom")

        return {
            "blockType": block_type,
            "content": content,
            "reason": reason,
        }

    @staticmethod
    def _bonuses_to_dict(existing: Any, bonuses: Optional[List[BonusItem]]) -> List[Dict[str, str]]:
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
    def _testimonials_to_dict(existing: Any, proof: Optional[Any], persona: Optional[str]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if isinstance(existing, list):
            for testimonial in existing:
                if isinstance(testimonial, dict):
                    text = testimonial.get("text") or testimonial.get("quote")
                    if text:
                        items.append({
                            "name": testimonial.get("name") or testimonial.get("role") or "受講者",
                            "role": testimonial.get("role") or "",
                            "text": text,
                            "rating": testimonial.get("rating") or 5,
                        })
        if not items and proof and getattr(proof, "testimonials", None):
            for testimonial in proof.testimonials[:3]:
                if isinstance(testimonial, Testimonial):
                    items.append({
                        "name": testimonial.name or (testimonial.role or "受講者"),
                        "role": testimonial.role or "",
                        "text": testimonial.quote,
                        "rating": 5,
                    })
        if not items and proof and getattr(proof, "achievements", None):
            for achievement in proof.achievements[:3]:
                items.append({
                    "name": proof.authority_name or "実績紹介",
                    "role": proof.authority_title or "",
                    "text": achievement,
                    "rating": 5,
                })
        if not items:
            persona_label = persona or "受講者"
            items = [
                {"name": "受講者A", "role": persona_label, "text": "導入後、ローンチ準備の時間が1/3になり、CVRも着実に伸びました。", "rating": 5},
                {"name": "受講者B", "role": "副業スタート", "text": "テンプレートに沿って進めるだけで、初回ローンチから想定以上の売上を達成できました。", "rating": 5},
                {"name": "受講者C", "role": "コミュニティ運営", "text": "コピーと構成が一体になっているので、伝えたい価値を最短で形にできました。", "rating": 5},
            ]
        return items[:3]

    @staticmethod
    def _parse_int(value: Optional[str]) -> Optional[int]:
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
                {"role": "system", "content": "あなたは情報商材に特化したプロのコピーライターです。高額商品でも売れる、心理学に基づいた文章を作成します。緊急性、限定性、社会的証明を駆使してください。"},
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
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

from openai import OpenAI

from app.config import settings
from app.models.ai import AIWizardInput, BonusItem, Testimonial


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

ALLOWED_BLOCK_SEQUENCE = [
    "hero-aurora",
    "countdown-1",
    "problem-1",
    "before-after-1",
    "testimonial-1",
    "special-price-1",
    "bonus-list-1",
    "guarantee-1",
    "author-profile-1",
    "scarcity-1",
    "sticky-cta-1",
]


OUTLINE_FALLBACK_LABELS = {
    "hero-aurora": "ヒーローセクション",
    "countdown-1": "締切カウントダウン",
    "problem-1": "共感・問題提起",
    "before-after-1": "ビフォーアフター",
    "testimonial-1": "導入事例",
    "special-price-1": "特別価格",
    "bonus-list-1": "豪華特典",
    "guarantee-1": "返金保証",
    "author-profile-1": "監修者・権威",
    "scarcity-1": "残席・限定性",
    "sticky-cta-1": "固定CTA",
}
