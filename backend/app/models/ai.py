from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal


class BonusItem(BaseModel):
    title: str
    description: Optional[str] = None
    value: Optional[str] = None


class PriceInfo(BaseModel):
    original: Optional[str] = None
    special: Optional[str] = None
    currency: Optional[str] = None
    payment_plan: Optional[str] = None
    deadline: Optional[str] = None


class GuaranteeInfo(BaseModel):
    headline: Optional[str] = None
    description: Optional[str] = None
    conditions: Optional[str] = None


class OfferDetails(BaseModel):
    price: Optional[PriceInfo] = None
    bonuses: Optional[List[BonusItem]] = None
    guarantee: Optional[GuaranteeInfo] = None
    call_to_action: Optional[str] = None
    scarcity: Optional[str] = None


class ProductDetails(BaseModel):
    name: str
    description: Optional[str] = None
    format: Optional[str] = None
    duration: Optional[str] = None
    delivery: Optional[str] = None
    transformation: Optional[str] = None
    promise: Optional[str] = None
    key_features: Optional[List[str]] = None
    deliverables: Optional[List[str]] = None


class AudienceDetails(BaseModel):
    persona: Optional[str] = None
    desired_outcome: Optional[str] = None
    pain_points: Optional[List[str]] = None
    objections: Optional[List[str]] = None
    aspirations: Optional[List[str]] = None


class Testimonial(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    quote: str
    result: Optional[str] = None


class ProofDetails(BaseModel):
    authority_headline: Optional[str] = None
    authority_name: Optional[str] = None
    authority_title: Optional[str] = None
    authority_bio: Optional[str] = None
    achievements: Optional[List[str]] = None
    testimonials: Optional[List[Testimonial]] = None
    media_mentions: Optional[List[str]] = None
    social_proof: Optional[List[str]] = None


class NarrativeDetails(BaseModel):
    origin_story: Optional[str] = None
    unique_mechanism: Optional[str] = None
    roadmap: Optional[str] = None


class AIWizardInput(BaseModel):
    business: str
    target: str
    goal: str
    theme: Optional[str] = None
    language: Optional[str] = "ja"
    product: ProductDetails
    audience: AudienceDetails
    offer: OfferDetails
    proof: Optional[ProofDetails] = None
    narrative: Optional[NarrativeDetails] = None
    additional_notes: Optional[str] = None
    tone: Optional[str] = None

class AIStructureSuggestion(BaseModel):
    recommended_blocks: List[str]
    color_scheme: Dict[str, str]
    structure: List[Dict[str, Any]]
    reasoning: str

class AITextGenerationRequest(BaseModel):
    type: str  # 'headline', 'subtitle', 'description', 'cta', 'testimonial'
    context: Dict[str, Any]
    options: Optional[Dict[str, Any]] = None

class AITextGenerationResponse(BaseModel):
    generated_text: List[str]  # 複数の提案
    used_prompt: str

class AIImprovementSuggestion(BaseModel):
    lp_id: str
    analytics_data: Dict[str, Any]

class AIImprovementResponse(BaseModel):
    suggestions: List[Dict[str, Any]]
    priority: str  # 'high', 'medium', 'low'
    reasoning: str


class NoteBlockPayload(BaseModel):
    id: str
    type: str
    access: Optional[str] = None
    text: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class NoteAIContext(BaseModel):
    title: str
    excerpt: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    tone: Optional[str] = None
    audience: Optional[str] = None
    language: Literal["ja", "en"] = "ja"
    blocks: List[NoteBlockPayload]


class NoteRewriteRequest(BaseModel):
    context: NoteAIContext
    target_block_id: str
    instructions: Optional[str] = None
    style_hint: Optional[str] = None


class NoteRewriteMetrics(BaseModel):
    paragraph_count: int
    sentence_count: int
    length: int
    length_ratio: float
    bullet_count: int
    reading_time_seconds: int


class NoteRewriteExperiment(BaseModel):
    experiment_id: str
    variant_id: str
    cohort_id: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class NoteRewriteQuality(BaseModel):
    scoring_version: str
    evaluated_at: datetime
    global_score: int
    summary: Optional[str] = None
    alerts: List[str] = Field(default_factory=list)
    thresholds: Dict[str, bool] = Field(default_factory=dict)
    ready_for_release: bool = False


class NoteRewriteCompliance(BaseModel):
    status: Literal["pass", "caution", "block"] = "pass"
    categories: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    allow_application: bool = True


class NoteRewriteCandidate(BaseModel):
    id: str
    title: str
    revised_text: str
    reasoning: Optional[str] = None
    tone_applied: Optional[str] = None
    score: int
    metrics: NoteRewriteMetrics
    strengths: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    compliance: Optional[NoteRewriteCompliance] = None


class NoteRewriteResponse(BaseModel):
    block_id: str
    original_text: str
    candidates: List[NoteRewriteCandidate]
    recommended_candidate_id: str
    evaluation_notes: Optional[str] = None
    quality: Optional[NoteRewriteQuality] = None
    experiment: Optional[NoteRewriteExperiment] = None


class NoteRewriteFeedbackRequest(BaseModel):
    block_id: str
    candidate_id: str
    rating: Literal["positive", "neutral", "negative"]
    issues: List[str] = Field(default_factory=list)
    comment: Optional[str] = None
    applied: bool = True
    duration_seconds: Optional[int] = None
    experiment_id: Optional[str] = None
    variant_id: Optional[str] = None


class NoteRewriteFeedbackResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ExperimentAssignmentRequest(BaseModel):
    user_id: Optional[str] = None
    note_id: Optional[str] = None
    seed: Optional[str] = None


class ExperimentAssignmentResponse(BaseModel):
    experiment: NoteRewriteExperiment


class NoteProofreadRequest(BaseModel):
    context: NoteAIContext
    focus: Optional[Literal["spelling", "style", "consistency"]] = None


class NoteProofreadCorrection(BaseModel):
    block_id: str
    original: str
    suggestion: str
    explanation: Optional[str] = None


class NoteProofreadResponse(BaseModel):
    corrections: List[NoteProofreadCorrection]
    summary: Optional[str] = None


class NoteStructureSuggestion(BaseModel):
    block_id: Optional[str] = None
    title: str
    description: str
    action: Literal["insert", "reorder", "expand", "trim"] = "insert"
    suggested_text: Optional[str] = None
    suggested_block_type: Optional[Literal["paragraph", "heading", "quote", "list"]] = None


class NoteStructureRequest(BaseModel):
    context: NoteAIContext
    desired_outcome: Optional[str] = None


class NoteStructureResponse(BaseModel):
    suggestions: List[NoteStructureSuggestion]
    outline: Optional[List[str]] = None


class NoteReviewRequest(BaseModel):
    context: NoteAIContext


class NoteReviewIssue(BaseModel):
    severity: Literal["info", "warn", "error"]
    message: str
    block_id: Optional[str] = None
    field: Optional[str] = None


class NoteReviewResponse(BaseModel):
    score: int
    summary: str
    issues: List[NoteReviewIssue]
    recommended_actions: List[str] = Field(default_factory=list)
