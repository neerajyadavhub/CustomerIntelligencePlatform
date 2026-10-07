# Smart Engine

An interactive prototype of a unified customer-intelligence platform:
one resolved **Person ID** feeding three products —

- **CDP** — identity resolution + a rules-based decision engine (e.g.
  reactivation-offer eligibility), with a live "Decision Ledger."
- **Rep App** — a sales/concierge lookup tool: search a customer, get
  one unified profile even if they've shopped under more than one
  account, with a suggested talking point.
- **Marketing Intelligence** — build an audience from signals/scores,
  preview its size, sync it to a channel, and measure how it performed
  after — impressions, spend, conversions, ROAS, by channel and over time.

Live demo: **https://neerajyadavhub.github.io/CustomerIntelligencePlatform/**

Backed by a real, tested FastAPI backend — [`persongraph-api/`](persongraph-api/)
— not just a UI mockup. The frontend works standalone with realistic
static demo data, and upgrades to live API calls automatically when the
backend is reachable (look for the connection indicator in the sidebar).

## Repo layout

```
CustomerIntelligencePlatform/
  frontend/index.html    The three-app prototype (what GitHub Pages serves)
  prd.html                Styled product requirements doc, linked from the demo
  persongraph-api/        FastAPI backend — identity, decisioning, audiences
    README.md              Backend-specific docs (endpoints, deploy, config)
```

## Maintaining the live link

`https://neerajyadavhub.github.io/CustomerIntelligencePlatform/` is a
**GitHub Pages** site — it only serves static files (HTML/CSS/JS). It
cannot run the Python backend. That splits maintenance into two
independent pieces:

### 1. Updating the frontend (the page itself)

GitHub Pages rebuilds automatically from the branch/folder you configured
in Settings → Pages. There's nothing to redo in Settings for routine
changes — just:

```bash
# edit frontend/index.html (or prd.html) locally, then:
git add frontend/index.html
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
3. Otherwise, a hardcoded default baked into `frontend/index.html`
   (currently a placeholder: `https://your-persongraph-api.onrender.com`).

Once you've deployed the backend and have its real URL, open
`frontend/index.html`, find the line:

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

## Running everything locally

```bash
# backend
cd persongraph-api
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload

# frontend — open directly, or serve it:
cd ../frontend
python -m http.server 5500
# then visit http://127.0.0.1:5500/?api=http://127.0.0.1:8000
```

Locally, the frontend defaults to `http://127.0.0.1:8000` automatically,
so the `?api=` param above is optional unless you're running the backend
on a different port.

## What to try in the demo

- **CDP** — open a person's profile, click "Load live identity" to pull
  real resolved identities from the backend, and run the reactivation
  decision to see the eligible/suppressed logic and its reasoning.
- **Rep App** — search for `jordyn` (or her email/phone) and open her
  unified profile — note the three linked identities.
- **Marketing** — build an audience (e.g. propensity > 0.7), run it
  live, and sync it to a channel to see the match-rate behavior. Then
  open **Measurement** and click "Load from live API" to see that same
  audience's post-sync performance — impressions, spend, conversions,
  ROAS, broken out by channel and over time.

## Status & provenance

This is a portfolio/reference project: no auth, no multi-tenancy, no
real channel integrations (see `persongraph-api/README.md` for the full
"what this is not" list). The identity-resolution and decisioning
patterns are modeled on real industry practice, generalized and
rewritten for this project — not copied from any employer's proprietary
system. See [`CASE-STUDY.md`](CASE-STUDY.md) for the problem/approach/
outcome write-up.
