from fastapi import APIRouter, Depends, HTTPException, status
from app.models.ai import (
    AIWizardInput,
    AITextGenerationRequest,
    AITextGenerationResponse,
    AIImprovementSuggestion,
    AIImprovementResponse,
    NoteRewriteRequest,
    NoteRewriteResponse,
    NoteProofreadRequest,
    NoteProofreadResponse,
    NoteStructureRequest,
    NoteStructureResponse,
    NoteReviewRequest,
    NoteReviewResponse,
    NoteRewriteFeedbackRequest,
    NoteRewriteFeedbackResponse,
    ExperimentAssignmentRequest,
    ExperimentAssignmentResponse,
)
from app.services.ai_service import AIService, NoteAIService
from app.routes.auth import get_current_user
from app.config import settings

router = APIRouter(prefix="/ai", tags=["AI"])


def _ensure_ai_ready() -> None:
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI機能は現在利用できません。管理者にお問い合わせください。",
        )

@router.post("/wizard", response_model=dict)
async def ai_wizard(
    input_data: AIWizardInput,
    current_user: dict = Depends(get_current_user)
):
    """
    AIウィザード: ユーザー入力に基づいてLP構成を提案
    """
    try:
        result = await AIService.generate_lp_structure(input_data)
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


@router.post("/notes/rewrite", response_model=NoteRewriteResponse)
async def rewrite_note_block(
    request: NoteRewriteRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_ai_ready()
    try:
        return await NoteAIService.rewrite_block(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"NOTEリライトに失敗しました: {exc}")


@router.post("/notes/rewrite/feedback", response_model=NoteRewriteFeedbackResponse)
async def record_rewrite_feedback(
    request: NoteRewriteFeedbackRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_ai_ready()
    try:
        NoteAIService.record_rewrite_feedback(request)
        return NoteRewriteFeedbackResponse()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"フィードバックの記録に失敗しました: {exc}")


@router.post("/notes/rewrite/experiment", response_model=ExperimentAssignmentResponse)
async def assign_rewrite_experiment(
    request: ExperimentAssignmentRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_ai_ready()
    try:
        experiment = NoteAIService.assign_rewrite_experiment_by_seed(
            seed=request.seed,
            note_id=request.note_id,
            user_id=request.user_id,
        )
        return ExperimentAssignmentResponse(experiment=experiment)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"実験割り当てに失敗しました: {exc}")


@router.post("/notes/proofread", response_model=NoteProofreadResponse)
async def proofread_note(
    request: NoteProofreadRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_ai_ready()
    try:
        return await NoteAIService.proofread(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"NOTE校正に失敗しました: {exc}")


@router.post("/notes/structure", response_model=NoteStructureResponse)
async def suggest_note_structure(
    request: NoteStructureRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_ai_ready()
    try:
        return await NoteAIService.suggest_structure(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"構成提案に失敗しました: {exc}")


@router.post("/notes/review", response_model=NoteReviewResponse)
async def review_note(
    request: NoteReviewRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_ai_ready()
    try:
        return await NoteAIService.review(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"レビュー生成に失敗しました: {exc}")

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
