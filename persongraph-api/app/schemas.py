import datetime as dt
from typing import List, Optional, Any
from pydantic import BaseModel


class IdentityOut(BaseModel):
    external_user_id: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    account_type: str
    match_confidence: float
    source: str
    last_synced: dt.datetime

    class Config:
        from_attributes = True


class IdentityLookupResponse(BaseModel):
    person_id: str
    identities: List[IdentityOut]
    match_confidence: float  # overall confidence for this resolution
    source: str
    last_updated: dt.datetime


class SignalOut(BaseModel):
    name: str
    value: float
    updated_at: dt.datetime

    class Config:
        from_attributes = True


class ModelScoreOut(BaseModel):
    model_name: str
    model_version: str
    score: float
    scored_at: dt.datetime

    class Config:
        from_attributes = True


class DecisionOut(BaseModel):
    action: str
    result: str
    reason: str
    rule_applied: Optional[str]
    model_name: Optional[str]
    model_version: Optional[str]
    conflict_detected: bool
    created_at: dt.datetime

    class Config:
        from_attributes = True


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
    op: str   # one of: > < >= <= = !=
    value: Any


class AudienceCreate(BaseModel):
    name: str
    rule: List[AudienceRule]


class AudienceOut(BaseModel):
    id: str
    name: str
    rule: List[AudienceRule]
    created_at: dt.datetime

    class Config:
        from_attributes = True


class AudiencePreview(BaseModel):
    audience_id: str
    matched_count: int
    sample_person_ids: List[str]


class ChannelSyncRequest(BaseModel):
    channel: str


class ChannelSyncOut(BaseModel):
    channel: str
    status: str
    matched_count: int
    total_count: int
    synced_at: dt.datetime

    class Config:
        from_attributes = True
