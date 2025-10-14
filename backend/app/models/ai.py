from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class AIWizardInput(BaseModel):
    business: str
    target: str
    goal: str
    description: Optional[str] = None

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
