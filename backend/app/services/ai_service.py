import os
from openai import OpenAI
from typing import List, Dict, Any
from app.config import settings

def get_openai_client():
    """OpenAIクライアントを取得"""
    return OpenAI(api_key=settings.openai_api_key)

class AIService:
    """OpenAI APIを使用したAI機能"""
    
    @staticmethod
    async def generate_lp_structure(business: str, target: str, goal: str, description: str = None) -> Dict[str, Any]:
        """LP構成を提案"""
        
        prompt = f"""
あなたは情報商材LPのコンバージョン最適化のプロフェッショナルです。
売れる情報商材LPを作成するために、以下の情報に基づいて最適な構成を提案してください。

情報商材ジャンル: {business}
ターゲット層: {target}
コンバージョン目標: {goal}
商品・ノウハウ詳細: {description or '未入力'}

**重要**: 情報商材LPでは以下の要素が必須です：
- インパクトのある見出し（実績数字、緊急性）
- 問題提起（ターゲットの悩み）
- ビフォーアフター（変化の証拠）
- 実績・権威性の証明
- 限定性・緊急性の訴求
- 特別価格（通常価格→特別価格）
- 豊富なお客様の声
- 返金保証・リスクフリー訴求
- 複数のCTA配置

業種に応じた推奨配色：
- 投資・FX・副業: 緊急レッド系（primary: #DC2626）
- ダイエット・筋トレ: エネルギーオレンジ系（primary: #EA580C）
- 高額商品: ゴールドプレミアム系（primary: #B45309）
- 学習・資格: パワーブルー系（primary: #1E40AF）
- 恋愛・美容: パッションピンク系（primary: #BE185D）

以下の形式でJSON形式で回答してください：
{{
  "recommended_blocks": ["countdown-1", "problem-1", "before-after-1", "special-price-1", "bonus-list-1", "guarantee-1", "author-profile-1", "scarcity-1", "sticky-cta-1"],
  "color_scheme": {{
    "primary": "#DC2626",
    "secondary": "#EF4444",
    "accent": "#F59E0B",
    "background": "#111827",
    "text": "#FFFFFF"
  }},
  "structure": [
    {{"block": "countdown-1", "title": "⏰ 特別価格は残りわずか！", "urgencyText": "今すぐ申し込まないと、この価格では二度と手に入りません"}},
    {{"block": "problem-1", "title": "こんなお悩みありませんか？", "problems": ["悩み1", "悩み2", "悩み3", "悩み4", "悩み5"]}},
    {{"block": "before-after-1", "title": "驚きの変化", "beforeText": "実践前の状態", "afterText": "実践後の変化"}},
    {{"block": "author-profile-1", "name": "著者名", "title": "肩書き", "bio": "経歴・実績", "achievements": ["実績1", "実績2", "実績3"]}},
    {{"block": "special-price-1", "title": "今だけ特別価格", "originalPrice": "298000", "specialPrice": "98000", "discountBadge": "67% OFF"}},
    {{"block": "bonus-list-1", "title": "豪華特典プレゼント", "bonuses": [{{"title": "特典1", "value": "29800円相当"}}, {{"title": "特典2", "value": "50000円相当"}}], "totalValue": "189600円"}},
    {{"block": "guarantee-1", "title": "100%満足保証", "guaranteeType": "90日間 全額返金保証", "description": "リスクフリー訴求"}},
    {{"block": "scarcity-1", "title": "募集枠残りわずか", "remainingCount": 3, "totalCount": 50}},
    {{"block": "sticky-cta-1", "buttonText": "今すぐ申し込む", "subText": "残り3名で募集終了"}}
  ],
  "reasoning": "この構成で高いコンバージョンが期待できる理由"
}}
"""
        
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": """あなたは情報商材LPのコンバージョン最適化の専門家です。高額商品を売るための心理学、緊急性訴求、社会的証明を駆使した売れるLP構成を提案します。

**重要**: 必ず以下のブロックタイプのみを使用してください：
- countdown-1: カウントダウンタイマー
- problem-1: 問題提起リスト
- before-after-1: ビフォーアフター比較
- special-price-1: 特別価格表示
- bonus-list-1: ボーナス特典リスト
- guarantee-1: 返金保証
- author-profile-1: 著者プロフィール
- urgency-1: 緊急性バナー
- scarcity-1: 限定枠表示
- sticky-cta-1: 固定CTAバー

これ以外のブロックタイプ（testimonial-1など）は使用しないでください。必ずJSON形式で回答してください。"""},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        import json
        return json.loads(response.choices[0].message.content)
    
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
        # 生成された文章を分割
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
        
        import json
        return json.loads(response.choices[0].message.content)
