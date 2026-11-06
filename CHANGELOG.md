# Changelog

All notable changes are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/); versions are pre-1.0 and
may include breaking changes.

## [Unreleased]

### Changed (rename)
- Project renamed to **Customer Graph ID** (previously "Smart Engine"/"PersonGraph"): backend folder is now `cgid-api/`, Docker image `cgid-api`, default database/user names `cgid`. Demo data uses generic `CUST-` customer IDs.

### Added
- Consent enforcement on channel syncs (`enforce_consent`, default on) with `excluded_no_consent` reporting.
- Hashed audience exports: `GET /audience/{id}/export?purpose=target|suppress`.
- `GET /identity/duplicates` report and a **Duplicate report** button; win-back timing model.
- Built-in formula models (RFM, churn risk, 12-month lifetime value, discount sensitivity): `GET /models`, `POST /models/run`, and a **Score customers** button in the UI.
- **Import Data** screen in the UI (CSV upload/paste, merge toggle, per-row errors, API key entry). The UI now uses its own origin as the API when the API serves it.
- Bring-your-own-data ingestion: `POST /ingest/records` and `/ingest/csv` with normalized email/phone matching, automatic merge of linked people, and conflict reporting.
- Optional API-key authentication (`API_KEYS`).
- `render.yaml` one-click deploy; Docker image published to GHCR on `v*` tags.
- Automated test suite (pytest) covering identity, decisions, audiences,
  measurement, seeding; GitHub Actions CI (Python 3.11–3.13, Postgres,
  Docker build + smoke test, bundled-UI sync check).
- `docker compose up` with Postgres; non-root container with healthcheck.
- `CORS_ORIGINS` allowlist, community docs, issue/PR templates.

### Changed
- Seeding refuses to wipe a non-SQLite database unless `SEED_ALLOW_RESET=true`;
  the container no longer seeds at build time.
- Audience rules are validated (operator and numeric value) and return 422
  instead of failing later with a 500.
- Failed channel syncs no longer produce performance data.

### Fixed
- Ingest dropped a new email when the record shared a phone with an existing account; it is now kept as a linked account.
- Pinned `psycopg2-binary` 2.9.10 (2.9.9 does not build on Python 3.13).
- Removed deprecated `datetime.utcnow()` usage.

## [0.1.0-alpha]
- Initial CDP, Rep App, Marketing Intelligence + Measurement prototype with
  FastAPI backend.
