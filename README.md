# Customer Graph ID: an open-source Customer Intelligence Platform

**One resolved Person ID powering a decision engine, a rep lookup tool, and audience activation with measurement.**

> **Status: alpha.** Runs end to end and is tested. You can load your own data and protect the API with a key, but there is **no multi-tenancy or user management** and channel providers are **mock**. Great for evaluation, prototyping, and building on. Not yet safe to expose with real customer data. See [Limitations](#limitations).

Live demo: **https://neerajyadavhub.github.io/CustomerIntelligencePlatform/**

## What it does

- **CDP / decision engine** - identity resolution plus an inspectable rules engine (e.g. reactivation-offer eligibility), every decision logged with its reasoning.
- **Rep App** - search any identifier, get one unified profile across accounts, with a suggested talking point.
- **Marketing Intelligence** - build an audience from signals/scores, preview size, sync to a channel, then **measure** it: impressions, spend, conversions, ROAS by channel and over time.

All three share one Person ID layer, served by a FastAPI backend ([`cgid-api/`](cgid-api/)).

```mermaid
flowchart LR
  UI[Web UI: CDP / Rep / Marketing] --> API[Customer Graph ID API<br/>FastAPI]
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
cd cgid-api
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload
```

## Use it with your own data

```bash
# 1. Start it with an API key (data endpoints require it)
export API_KEYS=$(openssl rand -hex 32)
docker compose up --build        # or run uvicorn; remove the demo SEED_* lines for real data

# 2. Load people (or use CDP > Import Data in the UI at http://localhost:8000). Matching is on normalized email / phone / external_user_id;
#    records that share an identifier are merged into one Person ID.
curl -X POST localhost:8000/ingest/csv -H "Authorization: Bearer $API_KEYS" \
  -H "Content-Type: text/csv" --data-binary @customers.csv
```

CSV columns: `external_user_id, email, phone, account_type, source`; `score:<model>` columns become model scores; every other column is a numeric signal. JSON is available at `POST /ingest/records`. Then build audiences over those signals/scores via `/audience`. Interactive docs at `/docs`.

Matching is exact on normalized identifiers (no fuzzy/probabilistic matching), so a shared household phone will link people - pass `auto_merge=false` to report conflicts instead.

## Built-in models

Upload orders and get scores back, no data science team needed. These are transparent formulas (not trained ML), so every number is explainable. Run them with **CDP > Import Data > Score customers** or `POST /models/run`; list them at `GET /models`.

| Model | Scores written | Needs these columns |
|---|---|---|
| RFM | `rfm_recency`, `rfm_frequency`, `rfm_monetary` (1-5) plus a segment (champions, loyal, new, at risk, lapsed) | `days_since_last_order`, `orders`, `total_spend` |
| Churn risk | `churn_risk` (0-1) | `days_since_last_order`, `orders` (`tenure_days` improves it) |
| Lifetime value | `clv_12m` (expected revenue, next 12 months) | above plus `total_spend` |
| Win-back timing | `days_past_expected_gap`, `winback_due` (1 = overdue but not yet lost) | `days_since_last_order`, `orders` (2+), `tenure_days` |
| Discount sensitivity | `discount_sensitivity` (0-1) | `orders`, `promo_orders` |

Scores are ordinary model scores, so audiences can use them directly, e.g. `churn_risk > 0.7` and `clv_12m > 500`. Formulas are documented in [`cgid-api/app/scoring.py`](cgid-api/app/scoring.py). To use your own trained model instead, ingest its output as `score:<name>` columns.

## Use cases and how to do them

| Use case | How |
|---|---|
| **Paid media suppression** | Create an audience `orders > 0`, then `GET /audience/{id}/export?purpose=suppress`. Upload the hashed CSV as an exclusion list in Meta or Google so acquisition spend skips existing customers. |
| **Lookalike seeds** | Create an audience of your best customers (e.g. `clv_12m > 500`), then `GET /audience/{id}/export?purpose=target`. Upload as the seed for a lookalike audience. |
| **Consent-aware activation** | Syncs and `target` exports include only people whose `marketing_consent` signal is `1`. Missing consent counts as no consent. The sync response reports `excluded_no_consent`. |
| **Duplicate cleanup** | `GET /identity/duplicates` (or **Import Data > Duplicate report**): accounts vs. real people, and the most-linked people. |
| **Win-back timing** | Run the models, then build an audience `winback_due = 1`. |
| **Reactivation, offer eligibility** | `POST /decision/evaluate` with the built-in rules; every decision is logged with its reason. |

Exports are hashed files (SHA-256 emails and phones) for **manual upload**; there is no live push to Meta or Google yet. Check each platform's current upload spec before a production upload. Not built yet: real channel sync, outreach triggers/sending, multi-tenancy (agency reporting).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local SQLite | Postgres URL for real deployments |
| `RESOLVER_MODE` | `mock` | `mock` or `segment` (stub) |
| `METRICS_MODE` | `mock` | `mock` or `meta` (stub) |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `SEED_DEMO_DATA` / `SEED_ALLOW_RESET` | unset | Demo seeding. **Wipes the database.** Never use on real data |
| `CONSENT_SIGNAL` | `marketing_consent` | Name of the signal that records consent (1 = opted in) |
| `DEFAULT_PHONE_COUNTRY_CODE` | `1` | Country code added to 10-digit phone numbers before hashing |
| `API_KEYS` | unset (open) | Comma-separated API keys; set this for any real deployment |
| `PORT` | `8000` | Container listen port |

See [`cgid-api/.env.example`](cgid-api/.env.example).

## Extending it

- **Real channel metrics**: implement `MetricsProvider` in `app/measurement_engine.py` (Meta/Google/TikTok).
- **Real identity source**: implement `IdentityResolver` in `app/identity_resolver.py`.
- **New decisions**: add an entry to `ACTION_RULES` in `app/decision_engine.py`.

## Limitations

- Authentication is a shared API key only (`API_KEYS`): no users, roles, or multi-tenancy. The bundled UI keeps your key in this browser only (enter it on the Import Data screen).
- Channel sync and performance data are mocked; Meta/Segment adapters are stubs.
- Audience rules are ANDed numeric conditions only.
- Docker image is built and smoke-tested in CI; it was not built locally by the author.

## Contributing & community

[CONTRIBUTING](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md). Licensed under [Apache-2.0](LICENSE).

## Repo layout

```
index.html, prd.html     Web UI and PRD (served by GitHub Pages)
cgid-api/         FastAPI backend, tests, Dockerfile
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

### 2. Updating the backend (Customer Graph ID API)

The backend lives and deploys separately, since GitHub Pages can't run
it. Deploy `cgid-api/` to a host that runs Docker/Python — Render,
Railway, or Fly.io all work with the included `Dockerfile` (see
[`cgid-api/README.md`](cgid-api/README.md) for exact
steps). Once deployed with auto-deploy on push enabled, updating the
backend is the same git workflow: edit, commit, push — the host rebuilds
and redeploys on its own.

### Connecting the frontend to a live backend

The frontend resolves which API to call in this order:

1. A `?api=https://your-backend-url` query parameter, if present (handy
   for testing a specific deployment without changing code).
2. `http://127.0.0.1:8000` automatically, when running on localhost.
3. Otherwise, a hardcoded default baked into `index.html`
   (currently a placeholder: `https://your-cgid-api.onrender.com`).

Once you've deployed the backend and have its real URL, open
`index.html`, find the line:

```js
const DEFAULT_PROD_API = 'https://your-cgid-api.onrender.com';
```

replace the placeholder with your real backend URL, then commit and
push. After that, every visitor to the GitHub Pages link gets live data
automatically — no `?api=` param needed. Until that URL is updated
with a real, reachable backend, the demo quietly falls back to its
built-in static demo data, which is why it still looks complete even
with no backend connected.

### A third option: one combined URL

If you'd rather not keep the frontend on GitHub Pages and the backend on
a separate host, you can deploy both together from `cgid-api/`
as a single service with one URL — see "Combined single-URL deploy" in
[`cgid-api/README.md`](cgid-api/README.md). This is an
alternative to the two-host setup above, not a requirement; the existing
`neerajyadavhub.github.io` link keeps working fine either way, since it
doesn't care where the backend lives as long as `DEFAULT_PROD_API` points
to it.

## Running tests

```bash
cd cgid-api
pip install -r requirements-dev.txt
pytest
```

## Provenance

Customer Graph ID is an independent open-source project. Its identity-resolution and decisioning patterns are based on general industry practice, and it contains no code, data, or confidential information from any employer. See [`CASE-STUDY.md`](CASE-STUDY.md).
