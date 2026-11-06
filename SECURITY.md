# Security Policy

## Status

This project is **alpha** and ships **without authentication or
multi-tenancy**: every API request can read and modify all data. Do not
expose it to the public internet with real customer data. Put it behind your
own authentication proxy / private network until auth is added.

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private reporting:
**Security tab → "Report a vulnerability"** on this repository.

Include steps to reproduce and the affected version/commit. We aim to
acknowledge reports within a few days.

## Hardening notes for deployers

- Set `CORS_ORIGINS` to your real origins (default is `*`).
- Never set `SEED_DEMO_DATA` / `SEED_ALLOW_RESET` against real data; seeding
  wipes the database.
- Provide `DATABASE_URL` and channel credentials via environment variables or
  a secret manager, never commit `.env`.
- The container runs as a non-root user.
