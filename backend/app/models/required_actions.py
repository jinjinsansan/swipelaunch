from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime

# メールアドレス登録リクエスト
class EmailSubmitRequest(BaseModel):
    email: EmailStr = Field(..., description="メールアドレス")
    session_id: Optional[str] = Field(None, description="セッションID")

# LINE確認リクエスト
class LineConfirmRequest(BaseModel):
    line_user_id: Optional[str] = Field(None, description="LINE User ID（オプション）")
    session_id: Optional[str] = Field(None, description="セッションID")

# アクション完了レスポンス
class ActionCompletionResponse(BaseModel):
    completion_id: str
    action_type: str
    completed_at: datetime
    message: str

# 必須アクション情報
class RequiredActionInfo(BaseModel):
    id: str
    action_type: str
    step_id: Optional[str] = None
    is_required: bool
    action_config: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True

# 必須アクション状態レスポンス
class RequiredActionsStatusResponse(BaseModel):
    lp_id: str
    session_id: Optional[str] = None
    required_actions: List[RequiredActionInfo]
    completed_actions: List[str]  # 完了したaction_idのリスト
    all_completed: bool  # 全ての必須アクションが完了しているか
