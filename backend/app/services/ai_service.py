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

以下の形式でJSON形式で回答してください：
{{
  "recommended_blocks": ["hero-impact", "problem", "result-proof", "testimonial-detailed", "pricing-special", "guarantee", "cta-urgent"],
  "color_scheme": {{
    "primary": "#EF4444",
    "secondary": "#F59E0B",
    "accent": "#FBBF24",
    "background": "#111827",
    "text": "#FFFFFF"
  }},
  "structure": [
    {{"block": "hero-impact", "title": "【実績訴求】インパクトある見出し", "subtitle": "緊急性を含むサブタイトル"}},
    {{"block": "problem", "title": "こんなお悩みありませんか？", "items": ["悩み1", "悩み2", "悩み3"]}},
    {{"block": "result-proof", "title": "驚きの変化", "beforeText": "ビフォー", "afterText": "アフター"}},
    {{"block": "testimonial-detailed", "title": "実践者の声", "count": 6}},
    {{"block": "pricing-special", "title": "特別価格", "originalPrice": "通常価格", "specialPrice": "今だけ価格", "discount": "割引率"}},
    {{"block": "guarantee", "title": "100%返金保証", "text": "リスクフリー訴求"}},
    {{"block": "cta-urgent", "title": "今すぐ申し込む", "buttonText": "限定〇名で締切", "urgency": "残りわずか"}}
  ],
  "reasoning": "この構成で高いコンバージョンが期待できる理由"
}}
"""
        
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "あなたは情報商材LPのコンバージョン最適化の専門家です。高額商品を売るための心理学、緊急性訴求、社会的証明を駆使した売れるLP構成を提案します。必ずJSON形式で回答してください。"},
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
