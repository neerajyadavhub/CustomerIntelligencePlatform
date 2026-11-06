"""Optional API-key authentication.

Set API_KEYS to one or more comma-separated secrets to require a key on every
data endpoint (send it as `Authorization: Bearer <key>` or `X-API-Key: <key>`).
When API_KEYS is unset the API is open - fine for local use and the demo,
never for real data. /health, /docs and the bundled demo UI stay public.
"""
import hmac
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

PROTECTED_PREFIXES = ("/identity", "/person", "/decision", "/audience", "/ingest")


def configured_keys() -> list:
    raw = os.getenv("API_KEYS", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


def _presented_key(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("x-api-key", "").strip()


def install_auth(app: FastAPI) -> None:
    @app.middleware("http")
    async def require_api_key(request: Request, call_next):
        keys = configured_keys()  # read per request so config changes apply without code changes
        if (
            keys
            and request.method != "OPTIONS"
            and request.url.path.startswith(PROTECTED_PREFIXES)
        ):
            presented = _presented_key(request)
            if not any(hmac.compare_digest(presented, k) for k in keys):
                return JSONResponse(
                    {"detail": "Missing or invalid API key."},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)
