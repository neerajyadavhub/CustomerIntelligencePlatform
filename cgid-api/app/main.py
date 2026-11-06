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
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from . import models, schemas, decision_engine, audience_engine, measurement_engine, ingest, scoring, exports, channels, meta, migrate
from .auth import install_auth
from .clock import utcnow
from .database import Base, engine, get_db
from .identity_resolver import get_resolver
from .measurement_engine import get_metrics_provider

Base.metadata.create_all(bind=engine)
migrate.ensure_columns(engine)  # upgrade databases created by older versions


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
    excluded = []
    if req.enforce_consent:
        matched, excluded = audience_engine.split_by_consent(db, matched)
    # Real integration point: call the channel's API here (Meta Conversions API,
    # Google Ads Customer Match, your ESP's API, etc). This mock marks 92% as
    # successfully matched, mirroring real hashed-email match rates.
    if req.channel == channels.CHANNEL and meta.is_live():
        sync = _sync_to_meta(db, audience, matched)
    else:
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
    # backfills a realistic 14-day curve immediately; the Meta provider
    # pulls real insights (none until an ad set targets the audience).
    # A sync that failed has nothing to measure.
    if sync.status == "synced":
        metrics_provider.backfill(db, sync)

    sync.excluded_no_consent = len(excluded) if req.enforce_consent else None
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


# ----------------------------------------------------------- export / dedupe
@app.get("/audience/{audience_id}/export", tags=["audience"])
def export_audience(audience_id: str, purpose: str = "target", db: Session = Depends(get_db)):
    """Download an audience as a CSV of SHA-256 hashed emails/phones for manual
    upload to Meta or Google. purpose=target (lookalike seeds, custom audiences;
    consented people only) or purpose=suppress (exclusion lists; everyone)."""
    if purpose not in exports.PURPOSES:
        raise HTTPException(status_code=400, detail=f"purpose must be one of {', '.join(exports.PURPOSES)}.")
    audience = db.query(models.Audience).filter(models.Audience.id == audience_id).first()
    if not audience:
        raise HTTPException(status_code=404, detail="Audience not found.")
    matched = audience_engine.evaluate_audience(db, audience.rule)
    excluded = []
    if purpose == "target":
        matched, excluded = audience_engine.split_by_consent(db, matched)
    rows = exports.hashed_rows(db, matched)
    return Response(
        content=exports.to_csv(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{audience.id}-{purpose}.csv"',
            "X-People": str(len(matched)),
            "X-Rows": str(len(rows)),
            "X-Excluded-No-Consent": str(len(excluded)),
        },
    )


@app.get("/identity/duplicates", response_model=schemas.DuplicateReport, tags=["identity"])
def duplicate_report(db: Session = Depends(get_db)):
    """How many accounts are really the same people: accounts (identity records)
    versus resolved people, and the people with the most linked accounts."""
    from collections import defaultdict
    groups = defaultdict(list)
    for ident in db.query(models.Identity).all():
        groups[ident.person_id].append(ident)
    accounts = sum(len(v) for v in groups.values())
    people = len(groups)
    multi = {pid: v for pid, v in groups.items() if len(v) > 1}
    largest = sorted(multi.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:10]
    return schemas.DuplicateReport(
        accounts=accounts,
        people=people,
        duplicate_accounts=accounts - people,
        duplicate_rate=round((accounts - people) / accounts, 4) if accounts else 0.0,
        people_with_multiple_accounts=len(multi),
        largest_groups=[
            schemas.DuplicateGroup(person_id=pid, accounts=len(v), emails=sorted({i.email for i in v if i.email})[:5])
            for pid, v in largest
        ],
    )


# ------------------------------------------------------------------- meta
def _sync_to_meta(db: Session, audience: models.Audience, person_ids: list) -> models.ChannelSync:
    sync = models.ChannelSync(
        audience_id=audience.id, channel=channels.CHANNEL, status="failed",
        matched_count=0, total_count=len(person_ids), synced_at=utcnow(),
    )
    if not person_ids:
        sync.external_status = "No one in this audience to upload (after consent filtering)."
    else:
        try:
            result = channels.push_to_meta(db, meta.get_client(), audience, person_ids)
            sync.status = "synced"
            sync.matched_count = result["uploaded"]
            sync.external_audience_id = result["external_audience_id"]
            sync.external_status = result["status"]
        except meta.MetaError as exc:
            sync.external_status = f"Meta upload failed: {exc}"
    db.add(sync)
    db.commit()
    db.refresh(sync)
    return sync


@app.post("/syncs/{sync_id}/refresh", response_model=schemas.ChannelSyncOut, tags=["audience"])
def refresh_sync(sync_id: int, db: Session = Depends(get_db)):
    """Re-read a Meta sync's audience from Meta: matched size and processing status."""
    sync = db.query(models.ChannelSync).filter(models.ChannelSync.id == sync_id).first()
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found.")
    if not sync.external_audience_id:
        raise HTTPException(status_code=400, detail="This sync has no external audience to refresh.")
    if not meta.is_live():
        raise HTTPException(status_code=400, detail="META_MODE is not 'live'.")
    try:
        info = meta.get_client().get_audience(sync.external_audience_id)
    except meta.MetaError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    low = info.get("approximate_count_lower_bound")
    status = (info.get("operation_status") or {}).get("description")
    if isinstance(low, int) and low > 0:
        sync.matched_count = low
        sync.external_status = f"Meta audience {sync.external_audience_id}: about {low:,} matched people. {status or ''}".strip()
    else:
        sync.external_status = f"Meta audience {sync.external_audience_id} is still processing (no size yet). {status or ''}".strip()
    db.commit()
    db.refresh(sync)
    return sync


@app.get("/channels/meta", tags=["channels"])
def meta_status():
    """Is Meta configured, and can the token see the ad account?"""
    out = {"mode": meta.env_mode(), "api_version": os.getenv("META_API_VERSION", meta.DEFAULT_VERSION)}
    if not meta.is_live():
        return {**out, "connected": False, "detail": "META_MODE is not 'live'; Meta syncs are simulated."}
    try:
        return {**out, "connected": True, "account": meta.get_client().check()}
    except meta.MetaError as exc:
        return {**out, "connected": False, "detail": str(exc)}
