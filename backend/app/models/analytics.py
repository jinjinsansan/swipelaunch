from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# ステップファネルデータ
class StepFunnelData(BaseModel):
    step_id: str
    step_order: int
    step_views: int
    step_exits: int
    conversion_rate: float  # 次のステップへの遷移率

# CTA別クリックデータ
class CTAClickData(BaseModel):
    cta_id: Optional[str] = None
    step_id: Optional[str] = None
    cta_type: Optional[str] = None
    click_count: int

# LP分析レスポンス
class LPAnalyticsResponse(BaseModel):
    lp_id: str
    title: str
    slug: str
    status: str
    
    # 基本統計
    total_views: int
    total_cta_clicks: int
    total_sessions: int
    
    # コンバージョン率
    cta_conversion_rate: float  # (total_cta_clicks / total_views) * 100
    
    # ステップファネル
    step_funnel: List[StepFunnelData]
    
    # CTA別クリック数
    cta_clicks: List[CTAClickData]
    
    # 期間
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

# イベントログレスポンス
class EventLogResponse(BaseModel):
    id: str
    lp_id: str
    step_id: Optional[str] = None
    cta_id: Optional[str] = None
    event_type: str
    session_id: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

# イベントログリストレスポンス
class EventLogListResponse(BaseModel):
    data: List[EventLogResponse]
    total: int
    limit: int
    offset: int
    
    # フィルター情報
    event_type_filter: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
