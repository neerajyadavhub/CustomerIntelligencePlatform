import datetime as dt
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict

# Read ORM objects directly. protected_namespaces is cleared on the models
# that have `model_name` / `model_version` fields, which Pydantic would
# otherwise warn about because of its reserved `model_` prefix.
ORM = ConfigDict(from_attributes=True)
ORM_WITH_MODEL_FIELDS = ConfigDict(from_attributes=True, protected_namespaces=())


class IdentityOut(BaseModel):
    model_config = ORM

    external_user_id: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    account_type: str
    match_confidence: float
    source: str
    last_synced: dt.datetime


class IdentityLookupResponse(BaseModel):
    person_id: str
    identities: List[IdentityOut]
    match_confidence: float  # overall confidence for this resolution
    source: str
    last_updated: dt.datetime


class SignalOut(BaseModel):
    model_config = ORM

    name: str
    value: float
    updated_at: dt.datetime


class ModelScoreOut(BaseModel):
    model_config = ORM_WITH_MODEL_FIELDS

    model_name: str
    model_version: str
    score: float
    scored_at: dt.datetime


class DecisionOut(BaseModel):
    model_config = ORM_WITH_MODEL_FIELDS

    action: str
    result: str
    reason: str
    rule_applied: Optional[str]
    model_name: Optional[str]
    model_version: Optional[str]
    conflict_detected: bool
    created_at: dt.datetime


class PersonProfile(BaseModel):
    person_id: str
    identities: List[IdentityOut]
    signals: List[SignalOut]
    scores: List[ModelScoreOut]
    recent_decisions: List[DecisionOut]


class DecisionEvaluateRequest(BaseModel):
    person_id: str
    action: str


class AudienceRule(BaseModel):
    field: str
    # Validated here so a bad rule is rejected with a 422 when the audience is
    # created, instead of crashing later when it is previewed or synced.
    op: Literal[">", "<", ">=", "<=", "=", "!="]
    value: float


class AudienceCreate(BaseModel):
    name: str
    rule: List[AudienceRule]


class AudienceOut(BaseModel):
    model_config = ORM

    id: str
    name: str
    rule: List[AudienceRule]
    created_at: dt.datetime


class AudiencePreview(BaseModel):
    audience_id: str
    matched_count: int
    sample_person_ids: List[str]


class ChannelSyncRequest(BaseModel):
    channel: str


class ChannelSyncOut(BaseModel):
    model_config = ORM

    channel: str
    status: str
    matched_count: int
    total_count: int
    synced_at: dt.datetime


class PerformancePoint(BaseModel):
    date: dt.datetime
    channel: str
    impressions: int
    clicks: int
    spend: float
    conversions: int
    revenue: float


class ChannelBreakdown(BaseModel):
    channel: str
    impressions: int
    clicks: int
    spend: float
    conversions: int
    revenue: float
    ctr: float
    cpa: float
    roas: float


class AudiencePerformanceSummary(BaseModel):
    audience_id: str
    audience_name: str
    channels: List[str]
    impressions: int
    clicks: int
    spend: float
    conversions: int
    revenue: float
    ctr: float
    cpa: float
    roas: float
    by_channel: List[ChannelBreakdown]
    timeseries: List[PerformancePoint]


# ------------------------------------------------------------------ ingest
class IngestRecord(BaseModel):
    external_user_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    account_type: Optional[str] = None
    source: Optional[str] = None
    signals: dict = {}
    scores: dict = {}


class IngestRequest(BaseModel):
    records: list[IngestRecord]
    auto_merge: bool = True


class IngestError(BaseModel):
    index: int
    error: str


class IngestResult(BaseModel):
    received: int
    created: int
    updated: int
    merged: int
    errors: list[IngestError]
