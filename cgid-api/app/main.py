"""
Customer Graph ID API — identity resolution, decisioning, and audiences in one
small FastAPI service.

Run locally:
    python -m app.seed      # one-time: create tables + demo data
    uvicorn app.main:app --reload

Then open http://127.0.0.1:8000/docs for interactive API docs.

If a static/ folder with index.html sits next to this app/ folder (see
the project README), this same service also serves the frontend at "/" —
one deploy, one URL. If static/ is absent, "/" just returns API info.
"""
import os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import models, schemas, decision_engine, audience_engine, measurement_engine, ingest, scoring
from .auth import install_auth
from .clock import utcnow
from .database import Base, engine, get_db
from .identity_resolver import get_resolver
from .measurement_engine import get_metrics_provider

Base.metadata.create_all(bind=engine)


def cors_origins_from_env() -> list:
    """Browser origins allowed to call this API.

    Defaults to "*" so the demo works from any page (for example the
    GitHub Pages frontend). For a real deployment set CORS_ORIGINS to a
    comma-separated allowlist, e.g.
    CORS_ORIGINS="https://app.example.com,https://admin.example.com"."""
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(
    title="Customer Graph ID API",
    description="Identity resolution, decisioning, and audience activation for one unified Person ID.",
    version="0.1.0",
)

install_auth(app)  # registered before CORS so CORS headers wrap 401 responses

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_from_env(),  # "*" by default; set CORS_ORIGINS in production
    allow_methods=["*"],
    allow_headers=["*"],
)

resolver = get_resolver()
metrics_provider = get_metrics_provider()


@app.get("/health", tags=["meta"])
def health():
    """Always-JSON endpoint for the frontend's connection check — stable
    regardless of whether '/' is serving API info or the frontend."""
    return {"service": "Customer Graph ID API", "status": "ok"}


# ----------------------------------------------------------------- static
# Optional single-URL deployment: when static/index.html exists, serve it
# at "/" (and prd.html alongside it) so one Render/Railway deploy serves
# both the API and the frontend from one URL. Absent static/, "/" just
# returns API info — the standalone-backend mode used when the frontend
# is hosted separately (e.g. on GitHub Pages).
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
_serving_frontend = os.path.isdir(STATIC_DIR) and os.path.isfile(os.path.join(STATIC_DIR, "index.html"))

if _serving_frontend:
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/prd.html", include_in_schema=False)
    def serve_prd():
        prd_path = os.path.join(STATIC_DIR, "prd.html")
        if os.path.isfile(prd_path):
            return FileResponse(prd_path)
        raise HTTPException(status_code=404, detail="prd.html not bundled in static/")

    @app.get("/api-info", tags=["meta"])
    def api_info():
        return {"service": "Customer Graph ID API", "status": "ok", "docs": "/docs"}
else:
    @app.get("/", tags=["meta"])
    def root():
        return {"service": "Customer Graph ID API", "status": "ok", "docs": "/docs"}


# ---------------------------------------------------------------- identity
@app.get("/identity/lookup", response_model=schemas.IdentityLookupResponse, tags=["identity"])
def identity_lookup(identifier: str, db: Session = Depends(get_db)):
    person = resolver.resolve(db, identifier)
    if not person:
        raise HTTPException(status_code=404, detail=f"No person resolved for identifier '{identifier}'.")
    overall_confidence = min([i.match_confidence for i in person.identities], default=1.0)
    return schemas.IdentityLookupResponse(
        person_id=person.person_id,
        identities=person.identities,
        match_confidence=overall_confidence,
        source="segment",
        last_updated=max([i.last_synced for i in person.identities], default=utcnow()),
    )


# ------------------------------------------------------------------ person
@app.get("/person/{person_id}", response_model=schemas.PersonProfile, tags=["person"])
def get_person(person_id: str, db: Session = Depends(get_db)):
    person = db.query(models.Person).filter(models.Person.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found.")
    recent_decisions = (
        db.query(models.Decision)
        .filter(models.Decision.person_id == person_id)
        .order_by(models.Decision.created_at.desc())
        .limit(10)
        .all()
    )
    return schemas.PersonProfile(
        person_id=person.person_id,
        identities=person.identities,
        signals=person.signals,
        scores=person.scores,
        recent_decisions=recent_decisions,
    )


# ---------------------------------------------------------------- decision
@app.post("/decision/evaluate", response_model=schemas.DecisionOut, tags=["decision"])
def evaluate_decision(req: schemas.DecisionEvaluateRequest, db: Session = Depends(get_db)):
    person = db.query(models.Person).filter(models.Person.person_id == req.person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found.")
    try:
        decision = decision_engine.evaluate(db, person, req.action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return decision


@app.get("/person/{person_id}/decisions", response_model=list[schemas.DecisionOut], tags=["decision"])
def get_decisions(person_id: str, db: Session = Depends(get_db)):
    return (
        db.query(models.Decision)
        .filter(models.Decision.person_id == person_id)
        .order_by(models.Decision.created_at.desc())
        .all()
    )


# --------------------------------------------------------------- audience
@app.post("/audience", response_model=schemas.AudienceOut, tags=["audience"])
def create_audience(req: schemas.AudienceCreate, db: Session = Depends(get_db)):
    audience = models.Audience(name=req.name, rule=[r.model_dump() for r in req.rule])
    db.add(audience)
    db.commit()
    db.refresh(audience)
    return audience


@app.get("/audience", response_model=list[schemas.AudienceOut], tags=["audience"])
def list_audiences(db: Session = Depends(get_db)):
    return db.query(models.Audience).all()


@app.get("/audience/{audience_id}/preview", response_model=schemas.AudiencePreview, tags=["audience"])
def preview_audience(audience_id: str, db: Session = Depends(get_db)):
    audience = db.query(models.Audience).filter(models.Audience.id == audience_id).first()
    if not audience:
        raise HTTPException(status_code=404, detail="Audience not found.")
    matched = audience_engine.evaluate_audience(db, audience.rule)
    return schemas.AudiencePreview(audience_id=audience.id, matched_count=len(matched), sample_person_ids=matched[:10])


@app.post("/audience/{audience_id}/sync", response_model=schemas.ChannelSyncOut, tags=["audience"])
def sync_audience(audience_id: str, req: schemas.ChannelSyncRequest, db: Session = Depends(get_db)):
    audience = db.query(models.Audience).filter(models.Audience.id == audience_id).first()
    if not audience:
        raise HTTPException(status_code=404, detail="Audience not found.")
    matched = audience_engine.evaluate_audience(db, audience.rule)
    # Real integration point: call the channel's API here (Meta Conversions API,
    # Google Ads Customer Match, your ESP's API, etc). This mock marks 92% as
    # successfully matched, mirroring real hashed-email match rates.
    matched_count = int(len(matched) * 0.92)
    sync = models.ChannelSync(
        audience_id=audience.id,
        channel=req.channel,
        status="synced" if matched else "failed",
        matched_count=matched_count,
        total_count=len(matched),
        synced_at=utcnow(),
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)

    # Kick off performance measurement for this sync. The mock provider
    # backfills a realistic 14-day curve immediately; a real provider
    # would instead record the external campaign id here and let a
    # scheduled pull_latest() populate it over time.
    # A sync that matched nobody is recorded as failed and has nothing to
    # measure, so it must not get performance data.
    if sync.status == "synced":
        metrics_provider.backfill(db, sync)

    return sync


@app.get("/audience/{audience_id}/syncs", response_model=list[schemas.ChannelSyncOut], tags=["audience"])
def list_syncs(audience_id: str, db: Session = Depends(get_db)):
    return db.query(models.ChannelSync).filter(models.ChannelSync.audience_id == audience_id).all()


# ------------------------------------------------------------- performance
@app.get("/audience/{audience_id}/performance", response_model=schemas.AudiencePerformanceSummary, tags=["measurement"])
def audience_performance(audience_id: str, db: Session = Depends(get_db)):
    """Post-activation measurement: every channel this audience has been
    synced to, rolled up into one summary plus a daily timeseries — the
    Amplitude/GA-style view of 'how did this audience actually perform.'"""
    audience = db.query(models.Audience).filter(models.Audience.id == audience_id).first()
    if not audience:
        raise HTTPException(status_code=404, detail="Audience not found.")

    syncs = (
        db.query(models.ChannelSync)
        .filter(models.ChannelSync.audience_id == audience_id, models.ChannelSync.status == "synced")
        .all()
    )
    all_metrics = []
    timeseries = []
    by_channel_metrics = {}
    for sync in syncs:
        metrics_provider.pull_latest(db, sync)  # no-op for the mock; refreshes a real provider
        rows = (
            db.query(models.PerformanceMetric)
            .filter(models.PerformanceMetric.sync_id == sync.id)
            .order_by(models.PerformanceMetric.date)
            .all()
        )
        all_metrics.extend(rows)
        by_channel_metrics.setdefault(sync.channel, []).extend(rows)
        for m in rows:
            timeseries.append(schemas.PerformancePoint(
                date=m.date, channel=sync.channel, impressions=m.impressions,
                clicks=m.clicks, spend=m.spend, conversions=m.conversions,
                revenue=m.revenue,
            ))
    timeseries.sort(key=lambda p: p.date)

    overall = measurement_engine.summarize(all_metrics)
    by_channel = [
        schemas.ChannelBreakdown(channel=ch, **measurement_engine.summarize(rows))
        for ch, rows in by_channel_metrics.items()
    ]

    return schemas.AudiencePerformanceSummary(
        audience_id=audience.id,
        audience_name=audience.name,
        channels=sorted(by_channel_metrics.keys()),
        timeseries=timeseries,
        by_channel=by_channel,
        **overall,
    )


# ------------------------------------------------------------------ ingest
@app.post("/ingest/records", response_model=schemas.IngestResult, tags=["ingest"])
def ingest_json(req: schemas.IngestRequest, db: Session = Depends(get_db)):
    """Load people, signals and model scores. Records are matched to existing
    people on normalized email/phone/external_user_id; matches are merged."""
    return ingest.ingest_records(db, [r.model_dump() for r in req.records], req.auto_merge)


@app.post("/ingest/csv", response_model=schemas.IngestResult, tags=["ingest"])
async def ingest_csv(request: Request, auto_merge: bool = True, db: Session = Depends(get_db)):
    """Same as /ingest/records but takes a raw text/csv body. Columns:
    external_user_id, email, phone, account_type, source; score:<model> for
    model scores; every other column is a numeric signal."""
    body = (await request.body()).decode("utf-8-sig")
    records = ingest.parse_csv(body)
    if not records:
        raise HTTPException(status_code=400, detail="CSV body has no data rows.")
    return ingest.ingest_records(db, records, auto_merge)


# ------------------------------------------------------------------ models
@app.get("/models", tags=["models"])
def list_models():
    """Built-in formula models, the signals each needs, and the scores each writes."""
    return {"model_version": scoring.MODEL_VERSION, "models": scoring.CATALOG}


@app.post("/models/run", response_model=schemas.ModelRunResult, tags=["models"])
def run_models(req: schemas.ModelRunRequest = schemas.ModelRunRequest(), db: Session = Depends(get_db)):
    """Compute built-in models for everyone who has the required signals and
    save the results as model scores (re-running overwrites, never duplicates)."""
    try:
        return scoring.run_models(db, req.models)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
