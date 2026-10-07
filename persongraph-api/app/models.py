"""
Core schema.

Person        — the resolved real-world identity (Person ID)
Identity      — one linked account/identifier belonging to a Person
Signal        — a raw behavioral/attribute signal, keyed by person
ModelScore    — a model output (propensity, churn risk, etc.), keyed by person
Decision      — a logged eligibility/activation decision, with its full reasoning trace
Audience          — a saved, rule-based audience definition
ChannelSync       — a sync event of an Audience to an external channel
PerformanceMetric — one day of channel performance for a ChannelSync,
                    populated by a MetricsProvider (measurement_engine.py)
"""
import uuid
import datetime as dt
from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, ForeignKey, JSON, Integer, Text
)
from sqlalchemy.orm import relationship
from .database import Base


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class Person(Base):
    __tablename__ = "persons"
    person_id = Column(String, primary_key=True, default=lambda: _uid("PER"))
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    identities = relationship("Identity", back_populates="person", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="person", cascade="all, delete-orphan")
    scores = relationship("ModelScore", back_populates="person", cascade="all, delete-orphan")
    decisions = relationship("Decision", back_populates="person", cascade="all, delete-orphan")


class Identity(Base):
    """One linked account/identifier that Segment (or your resolver) has
    attributed to this Person. match_confidence and source are what the
    sync job (see identity_resolver.py) writes on every merge."""
    __tablename__ = "identities"
    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(String, ForeignKey("persons.person_id"), nullable=False)
    external_user_id = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    account_type = Column(String, default="unknown")  # personal | business | anonymous
    match_confidence = Column(Float, default=1.0)
    source = Column(String, default="segment")
    last_synced = Column(DateTime, default=dt.datetime.utcnow)

    person = relationship("Person", back_populates="identities")


class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(String, ForeignKey("persons.person_id"), nullable=False)
    name = Column(String, nullable=False)   # e.g. "days_since_last_activity"
    value = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=dt.datetime.utcnow)

    person = relationship("Person", back_populates="signals")


class ModelScore(Base):
    __tablename__ = "model_scores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(String, ForeignKey("persons.person_id"), nullable=False)
    model_name = Column(String, nullable=False)     # e.g. "propensity_to_convert"
    model_version = Column(String, default="v1")
    score = Column(Float, nullable=False)
    scored_at = Column(DateTime, default=dt.datetime.utcnow)

    person = relationship("Person", back_populates="scores")


class Decision(Base):
    """Every eligibility/activation decision, logged with its full reasoning
    trace so /person/{id}/decisions can answer 'why' for any outcome."""
    __tablename__ = "decisions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(String, ForeignKey("persons.person_id"), nullable=False)
    action = Column(String, nullable=False)          # e.g. "reactivation_offer"
    result = Column(String, nullable=False)           # eligible | suppressed | queued
    reason = Column(Text, nullable=False)
    rule_applied = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    model_version = Column(String, nullable=True)
    conflict_detected = Column(Boolean, default=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    person = relationship("Person", back_populates="decisions")


class Audience(Base):
    """A saved, rule-based audience. `rule` is a JSON list of conditions,
    ANDed together in v1:
      [{"field": "propensity_to_convert", "op": ">", "value": 0.7},
       {"field": "marketing_consent", "op": "=", "value": true}]
    """
    __tablename__ = "audiences"
    id = Column(String, primary_key=True, default=lambda: _uid("AUD"))
    name = Column(String, nullable=False)
    rule = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    syncs = relationship("ChannelSync", back_populates="audience", cascade="all, delete-orphan")


class ChannelSync(Base):
    __tablename__ = "channel_syncs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    audience_id = Column(String, ForeignKey("audiences.id"), nullable=False)
    channel = Column(String, nullable=False)          # email | meta_ads | google_ads | sms
    status = Column(String, default="pending")         # pending | synced | failed
    matched_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)
    synced_at = Column(DateTime, default=dt.datetime.utcnow)

    audience = relationship("Audience", back_populates="syncs")
    metrics = relationship("PerformanceMetric", back_populates="sync", cascade="all, delete-orphan")


class PerformanceMetric(Base):
    """One day of channel performance for a single ChannelSync (one
    audience pushed to one channel). Written by a MetricsProvider — see
    measurement_engine.py — either backfilled immediately in the mock
    provider, or pulled on a schedule from the real channel's reporting
    API once that's wired up."""
    __tablename__ = "performance_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_id = Column(Integer, ForeignKey("channel_syncs.id"), nullable=False)
    date = Column(DateTime, nullable=False)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    spend = Column(Float, default=0.0)
    conversions = Column(Integer, default=0)
    revenue = Column(Float, default=0.0)

    sync = relationship("ChannelSync", back_populates="metrics")
