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
あなたはランディングページ作成のプロフェッショナルです。
以下の情報に基づいて、最適なLP構成を提案してください。

業種: {business}
ターゲット層: {target}
目的: {goal}
商品・サービス: {description or '未入力'}

以下の形式でJSON形式で回答してください：
{{
  "recommended_blocks": ["hero-1", "text-img-1", "testimonial-1", "pricing-1", "cta-1"],
  "color_scheme": {{
    "primary": "#3B82F6",
    "secondary": "#10B981",
    "background": "#FFFFFF",
    "text": "#111827"
  }},
  "structure": [
    {{"block": "hero-1", "title": "提案する見出し", "subtitle": "提案するサブタイトル"}},
    {{"block": "text-img-1", "title": "特徴1", "text": "説明文"}},
    {{"block": "testimonial-1", "title": "お客様の声"}},
    {{"block": "pricing-1", "title": "料金プラン"}},
    {{"block": "cta-1", "title": "今すぐ始める", "buttonText": "無料で試す"}}
  ],
  "reasoning": "この構成を推奨する理由"
}}
"""
        
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "あなたはランディングページ作成のエキスパートです。JSON形式で回答してください。"},
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
商品・サービス: {context.get('product', '商品')}
ターゲット: {context.get('target', '一般')}
業種: {context.get('business', '一般')}

魅力的で短い見出しを{count}つ提案してください。各見出しは20文字以内。
1行に1つずつ、番号なしで出力してください。
""",
            "subtitle": f"""
メイン見出し: {context.get('headline', '')}
商品・サービス: {context.get('product', '商品')}

見出しを補完するサブタイトルを{count}つ提案してください。各サブタイトルは30文字以内。
1行に1つずつ、番号なしで出力してください。
""",
            "description": f"""
商品・サービス: {context.get('product', '商品')}
特徴: {context.get('features', [])}

商品の魅力を伝える説明文を{count}つ提案してください。各説明文は100文字前後。
1つの提案ごとに空行を入れて出力してください。
""",
            "cta": f"""
目的: {context.get('goal', '行動喚起')}
商品・サービス: {context.get('product', '商品')}

行動を促すCTAボタンの文言を{count}つ提案してください。各文言は10文字以内。
1行に1つずつ、番号なしで出力してください。
""",
        }
        
        prompt = prompts.get(text_type, f"{text_type}の文章を{count}つ生成してください。")
        
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "あなたはプロのコピーライターです。短く魅力的な文章を作成してください。"},
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
