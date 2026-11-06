# Smart Engine (PersonGraph)

**Open-source customer intelligence: one resolved Person ID powering a decision engine, a rep lookup tool, and audience activation with measurement.**

> **Status: alpha.** Runs end to end and is tested, but has **no authentication or multi-tenancy** and ships with **mock** channel/identity providers. Great for evaluation, prototyping, and building on. Not yet safe to expose with real customer data. See [Limitations](#limitations).

Live demo: **https://neerajyadavhub.github.io/CustomerIntelligencePlatform/**

## What it does

- **CDP / decision engine** - identity resolution plus an inspectable rules engine (e.g. reactivation-offer eligibility), every decision logged with its reasoning.
- **Rep App** - search any identifier, get one unified profile across accounts, with a suggested talking point.
- **Marketing Intelligence** - build an audience from signals/scores, preview size, sync to a channel, then **measure** it: impressions, spend, conversions, ROAS by channel and over time.

All three share one Person ID layer, served by a FastAPI backend ([`persongraph-api/`](persongraph-api/)).

```mermaid
flowchart LR
  UI[Web UI: CDP / Rep / Marketing] --> API[PersonGraph API<br/>FastAPI]
  API --> ID[IdentityResolver<br/>mock | segment]
  API --> DE[Decision engine<br/>ACTION_RULES]
  API --> AE[Audience engine]
  API --> ME[MetricsProvider<br/>mock | meta]
  API --> DB[(SQLite / Postgres)]
```

## Quickstart (one command)

```bash
git clone https://github.com/neerajyadavhub/CustomerIntelligencePlatform.git
cd CustomerIntelligencePlatform
docker compose up --build
```

Open http://localhost:8000 (UI) or http://localhost:8000/docs (API). This starts Postgres with **throwaway demo data**.

Without Docker:

```bash
cd persongraph-api
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local SQLite | Postgres URL for real deployments |
| `RESOLVER_MODE` | `mock` | `mock` or `segment` (stub) |
| `METRICS_MODE` | `mock` | `mock` or `meta` (stub) |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `SEED_DEMO_DATA` / `SEED_ALLOW_RESET` | unset | Demo seeding. **Wipes the database.** Never use on real data |
| `PORT` | `8000` | Container listen port |

See [`persongraph-api/.env.example`](persongraph-api/.env.example).

## Extending it

- **Real channel metrics**: implement `MetricsProvider` in `app/measurement_engine.py` (Meta/Google/TikTok).
- **Real identity source**: implement `IdentityResolver` in `app/identity_resolver.py`.
- **New decisions**: add an entry to `ACTION_RULES` in `app/decision_engine.py`.

## Limitations

- No authentication, authorization, or multi-tenancy.
- Channel sync and performance data are mocked; Meta/Segment adapters are stubs.
- Audience rules are ANDed numeric conditions only.
- Docker image is built and smoke-tested in CI; it was not built locally by the author.

## Contributing & community

[CONTRIBUTING](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md). Licensed under [Apache-2.0](LICENSE).

## Repo layout

```
index.html, prd.html     Web UI and PRD (served by GitHub Pages)
persongraph-api/         FastAPI backend, tests, Dockerfile
  static/                Copies of the UI so the API can serve it (kept in sync by CI)
docker-compose.yml       API + Postgres
.github/workflows/ci.yml Tests, Postgres, Docker smoke test
```

## Hosting the demo on GitHub Pages

`https://neerajyadavhub.github.io/CustomerIntelligencePlatform/` is a
**GitHub Pages** site — it only serves static files (HTML/CSS/JS). It
cannot run the Python backend. That splits maintenance into two
independent pieces:

### 1. Updating the frontend (the page itself)

GitHub Pages rebuilds automatically from the branch/folder you configured
in Settings → Pages. There's nothing to redo in Settings for routine
changes — just:

```bash
# edit index.html (or prd.html) locally, then:
git add index.html
git commit -m "Update demo"
git push
```

The live site updates at the same URL within about a minute of the push.
If your Pages source is configured to serve from the repo root rather
than `/frontend`, copy the updated file to wherever Pages is pointed
(e.g. `index.html` at the repo root) before committing — check
Settings → Pages → "Branch" to see which folder is live.

### 2. Updating the backend (PersonGraph API)

The backend lives and deploys separately, since GitHub Pages can't run
it. Deploy `persongraph-api/` to a host that runs Docker/Python — Render,
Railway, or Fly.io all work with the included `Dockerfile` (see
[`persongraph-api/README.md`](persongraph-api/README.md) for exact
steps). Once deployed with auto-deploy on push enabled, updating the
backend is the same git workflow: edit, commit, push — the host rebuilds
and redeploys on its own.

### Connecting the frontend to a live backend

The frontend resolves which API to call in this order:

1. A `?api=https://your-backend-url` query parameter, if present (handy
   for testing a specific deployment without changing code).
2. `http://127.0.0.1:8000` automatically, when running on localhost.
3. Otherwise, a hardcoded default baked into `index.html`
   (currently a placeholder: `https://your-persongraph-api.onrender.com`).

Once you've deployed the backend and have its real URL, open
`index.html`, find the line:

```js
const DEFAULT_PROD_API = 'https://your-persongraph-api.onrender.com';
```

replace the placeholder with your real backend URL, then commit and
push. After that, every visitor to the GitHub Pages link gets live data
automatically — no `?api=` param needed. Until that URL is updated
with a real, reachable backend, the demo quietly falls back to its
built-in static demo data, which is why it still looks complete even
with no backend connected.

### A third option: one combined URL

If you'd rather not keep the frontend on GitHub Pages and the backend on
a separate host, you can deploy both together from `persongraph-api/`
as a single service with one URL — see "Combined single-URL deploy" in
[`persongraph-api/README.md`](persongraph-api/README.md). This is an
alternative to the two-host setup above, not a requirement; the existing
`neerajyadavhub.github.io` link keeps working fine either way, since it
doesn't care where the backend lives as long as `DEFAULT_PROD_API` points
to it.

## Running tests

```bash
cd persongraph-api
pip install -r requirements-dev.txt
pytest
```

## Provenance

Identity-resolution and decisioning patterns are modeled on general industry practice, generalized and rewritten for this project, not copied from any employer's proprietary system. See [`CASE-STUDY.md`](CASE-STUDY.md).
