# Contributing

Thanks for helping make this better. This project is early (alpha), so the
most valuable contributions are real-world integrations, bug reports from
trying it on real data shapes, and tests.

## Good first contributions

- A real `MetricsProvider` (Meta Insights, Google Ads, TikTok, an ESP) — see
  `loomid-api/app/measurement_engine.py`
- A real `IdentityResolver` (Segment, mParticle, your warehouse) — see
  `loomid-api/app/identity_resolver.py`
- New actions in the decision engine's `ACTION_RULES` registry
- Authentication / multi-tenancy (open an issue first to agree on the design)
- Docs fixes and clearer error messages

## Dev setup

```bash
cd loomid-api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Tests run against an isolated temporary SQLite database. To run against
Postgres: `TEST_DATABASE_URL=postgresql://... pytest` (the suite wipes and
reseeds that database, so use a throwaway one).

Run the API: `python -m app.seed && uvicorn app.main:app --reload`, or
`docker compose up --build` from the repo root.

## The two copies of the UI

`index.html` and `prd.html` at the repo root are what GitHub Pages serves.
Copies live in `loomid-api/static/` so the API can serve the UI itself.
Keep them identical — CI fails if they differ:

```bash
cp index.html prd.html loomid-api/static/
```

## Pull requests

1. Open an issue for anything larger than a small fix.
2. Add or update tests for behavior changes. CI must pass.
3. Keep PRs focused; describe what changed and why.
4. By contributing you agree your work is licensed under Apache-2.0
   (see `LICENSE`), as in section 5 of that license.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md).
