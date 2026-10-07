# PersonGraph API

A small FastAPI backend implementing identity resolution, rules-based
decisioning, and audience segmentation/activation behind one resolved
Person ID. This is the reference backend for the Smart Engine prototype
(CDP + Rep App + Marketing Intelligence) one level up in this repo.

## What this is

- **Identity resolution** — look up any known identifier (email, phone,
  external user ID) and get back the canonical `Person ID` plus every
  linked identity, with a match confidence per identity.
- **Decision engine** — an explicit, inspectable rules engine (not a
  black-box model call) that evaluates actions like "is this person
  eligible for a reactivation offer," with every decision logged with
  its reasoning, the rule that fired, and whether a conflict was
  detected (e.g. high propensity but suppressed).
- **Audience engine** — build an audience from ANDed conditions over
  signals/scores, preview the matched count, and "sync" it to a channel
  (mocked — see below).
- **Measurement engine** — once an audience is synced to a channel, pull
  back its performance (impressions, clicks, spend, conversions, revenue)
  and roll it up per audience and per channel, with a daily trend — the
  "what happened after we activated this" view a channel-native dashboard
  can't give you across multiple channels at once.

## What this is not

- No authentication or multi-tenancy — every request sees all data.
- No billing.
- No real channel integrations yet — `POST /audience/{id}/sync` mocks a
  92% match rate rather than calling Meta/Google/an ESP.
- No real measurement pull yet — `MockMetricsProvider` generates a
  realistic-looking performance curve rather than calling Meta's
  Insights API or Google Ads' reporting API.
- `RESOLVER_MODE=segment` is a stub with `TODO`s, not a working Segment
  integration — see "Swapping in a real identity provider" below.

Treat this as a reference implementation to build on, not a
production-ready service.

## Quickstart

```bash
cd persongraph-api
pip install -r requirements.txt
python -m app.seed        # creates persongraph.db with 4 demo people
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for interactive API docs, or try:

```bash
curl "http://127.0.0.1:8000/identity/lookup?identifier=jordyn@personalmail.com"
```

## Project structure

```
persongraph-api/
  app/
    main.py              FastAPI app, all routes
    database.py          SQLAlchemy engine/session (SQLite by default)
    models.py            Person, Identity, Signal, ModelScore,
                          Decision, Audience, ChannelSync
    schemas.py           Pydantic request/response models
    identity_resolver.py IdentityResolver interface + Mock/Segment impls
    decision_engine.py   Eligibility rules + ACTION_RULES registry
    audience_engine.py   Audience rule evaluation
    measurement_engine.py MetricsProvider interface + Mock/Meta impls
    seed.py              Demo data (4 people, a synced demo audience,
                          and 14 days of performance history)
  static/                Optional — see "Combined single-URL deploy" below
  requirements.txt
  Dockerfile
  .env.example
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Always-JSON liveness check |
| GET | `/identity/lookup?identifier=` | Resolve an identifier to a Person |
| GET | `/person/{person_id}` | Full profile: identities, signals, scores, recent decisions |
| POST | `/decision/evaluate` | Evaluate an action for a person, log the decision |
| GET | `/person/{person_id}/decisions` | Decision history for a person |
| POST | `/audience` | Create an audience from a rule |
| GET | `/audience` | List saved audiences |
| GET | `/audience/{id}/preview` | Matched count + sample Person IDs |
| POST | `/audience/{id}/sync` | Mock-sync an audience to a channel (auto-backfills 14 days of mock performance) |
| GET | `/audience/{id}/syncs` | Sync history for an audience |
| GET | `/audience/{id}/performance` | Rolled-up performance (summary, per-channel breakdown, daily timeseries) |

## Configuration

Copy `.env.example` to `.env` and adjust:

- `DATABASE_URL` — leave unset for local SQLite, or set a Postgres URL
  for production (e.g. Render's managed Postgres).
- `RESOLVER_MODE` — `mock` (default, uses seeded local data) or
  `segment` (stub — needs the TODOs in `identity_resolver.py` finished).
- `SEGMENT_API_KEY`, `SEGMENT_SPACE_ID` — only used by the Segment resolver.
- `METRICS_MODE` — `mock` (default, generates a realistic performance
  curve) or `meta` (stub — needs the TODOs in `measurement_engine.py`
  finished, plus `META_ACCESS_TOKEN`/`META_AD_ACCOUNT_ID` below).
- `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID` — only used by the Meta
  Insights provider.

## Deploying (Render, Railway, Fly.io — any Docker host)

1. Push this repo (or just the `persongraph-api/` folder) to GitHub.
2. On Render: **New → Web Service**, connect the repo, set the root
   directory to `persongraph-api` if deploying the whole monorepo,
   and let it build from the included `Dockerfile`.
3. Set environment variables from `.env.example` in the host's dashboard
   (at minimum, nothing is required to run with the SQLite/mock defaults,
   but SQLite on most hosts is ephemeral — add a Postgres `DATABASE_URL`
   for anything beyond a demo).
4. Enable auto-deploy on push so updates ship automatically.
5. Once live, note the service URL (e.g. `https://your-service.onrender.com`)
   — the frontend needs it (see the top-level README's "Connecting the
   frontend to a live backend" section).

## Combined single-URL deploy (optional)

By default this is an API-only service, meant to be paired with the
frontend hosted separately (e.g. GitHub Pages). If you'd rather deploy
*everything* — frontend and backend — to one host under one URL:

1. Copy the frontend into this folder: `cp ../frontend/index.html static/`
   and, if you want the PRD reachable too, `cp ../prd.html static/`.
2. `main.py` detects `static/index.html` at startup and switches modes:
   `GET /` serves the frontend HTML instead of JSON API info (API info
   moves to `/api-info`), and `GET /prd.html` serves the PRD if present.
   `GET /health` always stays JSON either way, so the frontend's own
   connection check keeps working regardless of mode.
3. Deploy as above. The one URL you get back now serves both the app
   and the API — no `?api=` query param needed, since the frontend's
   same-origin default picks up the API automatically when not on
   localhost and no override is given.

This is an alternative to the GitHub-Pages-plus-separate-backend setup,
not a requirement — pick whichever fits where you want this to live.

## Swapping in a real identity provider

`app/identity_resolver.py` defines `IdentityResolver`, an abstract
interface with one method the rest of the app calls: `resolve(db, identifier)`.
`MockResolver` is the seeded-data implementation used by default.
`SegmentResolver` is a stub with the real Segment Profile API call
pattern documented in its docstring but not implemented — finish those
TODOs (an API call to Segment's Profile API, mapping the response onto
the same `Person`/`Identity` shape) and switch `RESOLVER_MODE=segment`
to go live without changing any other code, since every route calls
`get_resolver()` rather than a concrete class.

## Swapping in a real measurement provider

`app/measurement_engine.py` defines `MetricsProvider`, the same kind of
small interface as `IdentityResolver`: `backfill(db, sync)` (called once
right after a sync) and `pull_latest(db, sync)` (called on a schedule to
refresh recent days). `MockMetricsProvider` is the default — it generates
a plausible 14-day curve from the sync's own `matched_count` so the
dashboard has real-looking numbers with no external credentials. To go
live, finish `MetaInsightsProvider` (or write an equivalent for Google
Ads/your ESP) against that channel's real reporting API — the module's
docstring spells out the call pattern, including the one thing a real
`sync()` has to do differently from today's mock: store the external
campaign/ad-set id the channel hands back, since that's what the
reporting API is queried by. Switch `METRICS_MODE=meta` once implemented;
every route calls `get_metrics_provider()` rather than a concrete class,
so nothing else changes.

## A note on provenance

The identity-resolution and decisioning patterns here are modeled on
real industry practice (Segment-style Identity Resolution, customer-360
PRDs), generalized and rewritten for this reference project — all
naming, schema, and sample data are original to this repo, not copied
from any employer's proprietary system. If you're adapting this into
something you plan to sell, get your own legal/IP review before using
any prior employer's specific product names, schemas, or documents —
this disclaimer is informational, not legal advice.
