"""
PersonGraph API — identity resolution, decisioning, and audiences in one
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
import datetime as dt
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import models, schemas, decision_engine, audience_engine
from .database import Base, engine, get_db
from .identity_resolver import get_resolver

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PersonGraph API",
    description="Identity resolution, decisioning, and audience activation for one unified Person ID.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before production — see README
    allow_methods=["*"],
    allow_headers=["*"],
)

resolver = get_resolver()


@app.get("/health", tags=["meta"])
def health():
    """Always-JSON endpoint for the frontend's connection check — stable
    regardless of whether '/' is serving API info or the frontend."""
    return {"service": "PersonGraph API", "status": "ok"}


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
        return {"service": "PersonGraph API", "status": "ok", "docs": "/docs"}
else:
    @app.get("/", tags=["meta"])
    def root():
        return {"service": "PersonGraph API", "status": "ok", "docs": "/docs"}


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
        last_updated=max([i.last_synced for i in person.identities], default=dt.datetime.utcnow()),
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
    audience = models.Audience(name=req.name, rule=[r.dict() for r in req.rule])
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
        synced_at=dt.datetime.utcnow(),
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)
    return sync


@app.get("/audience/{audience_id}/syncs", response_model=list[schemas.ChannelSyncOut], tags=["audience"])
def list_syncs(audience_id: str, db: Session = Depends(get_db)):
    return db.query(models.ChannelSync).filter(models.ChannelSync.audience_id == audience_id).all()
