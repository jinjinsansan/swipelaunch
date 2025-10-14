from fastapi import APIRouter, Depends, HTTPException
from app.models.ai import (
    AIWizardInput,
    AIStructureSuggestion,
    AITextGenerationRequest,
    AITextGenerationResponse,
    AIImprovementSuggestion,
    AIImprovementResponse
)
from app.services.ai_service import AIService
from app.routes.auth import get_current_user

router = APIRouter(prefix="/ai", tags=["AI"])

@router.post("/wizard", response_model=dict)
async def ai_wizard(
    input_data: AIWizardInput,
    current_user: dict = Depends(get_current_user)
):
    """
    AIウィザード: ユーザー入力に基づいてLP構成を提案
    """
    try:
        result = await AIService.generate_lp_structure(
            business=input_data.business,
            target=input_data.target,
            goal=input_data.goal,
            description=input_data.description
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI生成エラー: {str(e)}")

@router.post("/generate-text", response_model=AITextGenerationResponse)
async def generate_text(
    request: AITextGenerationRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    テキスト生成: 見出し、説明文、CTAなどを生成
    
    - type: 'headline', 'subtitle', 'description', 'cta'
    - context: 生成に必要なコンテキスト情報
    """
    try:
        count = request.options.get('count', 3) if request.options else 3
        texts = await AIService.generate_text(
            text_type=request.type,
            context=request.context,
            count=count
        )
        return AITextGenerationResponse(
            generated_text=texts,
            used_prompt=f"Generated {request.type} with context: {request.context}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"テキスト生成エラー: {str(e)}")

@router.post("/improve", response_model=dict)
async def suggest_improvements(
    request: AIImprovementSuggestion,
    current_user: dict = Depends(get_current_user)
):
    """
    改善提案: 分析データに基づいてLP改善を提案
    """
    try:
        # LPデータと分析データを取得（実装省略）
        lp_data = {"title": "Sample LP", "step_count": 5, "cta_count": 2}
        
        result = await AIService.analyze_and_suggest_improvements(
            lp_data=lp_data,
            analytics=request.analytics_data
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析エラー: {str(e)}")

@router.get("/templates")
async def get_templates(current_user: dict = Depends(get_current_user)):
    """
    テンプレート一覧取得
    """
    from app.config import get_supabase_client
    supabase = get_supabase_client()
    
    try:
        response = supabase.table('template_blocks').select('*').eq('is_active', True).execute()
        return {"templates": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"テンプレート取得エラー: {str(e)}")

@router.get("/cta-styles")
async def get_cta_styles(current_user: dict = Depends(get_current_user)):
    """
    CTAボタンスタイル一覧取得
    """
    from app.config import get_supabase_client
    supabase = get_supabase_client()
    
    try:
        response = supabase.table('cta_button_styles').select('*').eq('is_active', True).execute()
        return {"styles": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CTAスタイル取得エラー: {str(e)}")
