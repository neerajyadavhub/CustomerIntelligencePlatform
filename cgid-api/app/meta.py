"""
Meta (Facebook/Instagram) Marketing API client.

Covers exactly what Customer Graph ID needs:
  - check the ad account and token
  - create a Custom Audience and load/refresh it with hashed emails/phones
  - read the audience's size and processing status
  - find the ad sets that target an audience and pull their daily insights

Everything goes through one small HTTP wrapper that turns Meta's errors into
plain-English hints (expired token, missing permission, Custom Audience Terms
not accepted, rate limits). Data is only ever sent hashed; see exports.py.

Configuration (environment):
  META_MODE              mock (default) | live
  META_ACCESS_TOKEN      system-user token with ads_management + ads_read
  META_AD_ACCOUNT_ID     numeric id, with or without the "act_" prefix
  META_API_VERSION       default v25.0 (check Meta's changelog; versions expire)
  META_CONVERSION_ACTION action type counted as a conversion (default: purchase)
"""
import json
import os
import random
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import httpx

GRAPH = "https://graph.facebook.com"
DEFAULT_VERSION = "v25.0"
BATCH_SIZE = 10_000          # Meta's per-request limit for audience uploads
RATE_LIMIT_CODES = {4, 17, 32, 613}
MAX_RETRIES = 3

HINTS = {
    190: "The access token is invalid or has expired. Generate a new system-user token and update META_ACCESS_TOKEN.",
    1870090: "The Custom Audience Terms have not been accepted for this ad account. Accept them once in Ads Manager (Audiences > Create audience > Customer list), then retry.",
    1870050: "This ad account is not linked to the Business Manager that owns your app. Add the ad account to the business and give the system user access to it.",
    200: "The token is missing a permission. It needs ads_management and ads_read, and the system user must be assigned to this ad account.",
    10: "The token is missing a permission. It needs ads_management and ads_read, and the system user must be assigned to this ad account.",
    803: "Meta could not find that object. Check META_AD_ACCOUNT_ID (digits only, or act_<digits>).",
}


class MetaError(Exception):
    def __init__(self, message: str, code: Optional[int] = None, subcode: Optional[int] = None, status: Optional[int] = None):
        super().__init__(message)
        self.code, self.subcode, self.status = code, subcode, status


def env_mode() -> str:
    mode = os.getenv("META_MODE", "").strip().lower()
    if not mode and os.getenv("METRICS_MODE", "").strip().lower() == "meta":
        mode = "live"  # legacy setting
    return mode or "mock"


def is_live() -> bool:
    return env_mode() == "live"


def normalize_account_id(raw: str) -> str:
    raw = (raw or "").strip()
    return raw if raw.startswith("act_") else f"act_{raw}"


class MetaClient:
    def __init__(
        self,
        access_token: str,
        ad_account_id: str,
        api_version: str = DEFAULT_VERSION,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not access_token or not ad_account_id:
            raise MetaError("META_ACCESS_TOKEN and META_AD_ACCOUNT_ID must both be set.")
        self.token = access_token
        self.account = normalize_account_id(ad_account_id)
        self.version = api_version
        self._http = httpx.Client(timeout=30, transport=transport)
        self._sleep = sleep

    # -- plumbing -----------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{GRAPH}/{self.version}/{path.lstrip('/')}"

    def _request(self, method: str, path_or_url: str, params: Optional[dict] = None, data: Optional[dict] = None) -> dict:
        url = path_or_url if path_or_url.startswith("http") else self._url(path_or_url)
        for attempt in range(MAX_RETRIES + 1):
            q = dict(params or {})
            body = dict(data or {})
            if not path_or_url.startswith("http"):  # paging URLs already carry the token
                (body if method in ("POST", "DELETE") else q)["access_token"] = self.token
            try:
                resp = self._http.request(method, url, params=q, data=body or None)
            except httpx.HTTPError as exc:
                raise MetaError(f"Could not reach Meta: {exc.__class__.__name__}") from None
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            err = payload.get("error") if isinstance(payload, dict) else None
            if resp.status_code < 400 and not err:
                return payload
            code = (err or {}).get("code")
            if code in RATE_LIMIT_CODES and attempt < MAX_RETRIES:
                self._sleep(2 ** attempt)
                continue
            raise self._to_error(err or {}, resp.status_code)
        raise MetaError("Meta rate limit exceeded; try again later.", status=429)

    @staticmethod
    def _to_error(err: dict, status: int) -> MetaError:
        code, sub = err.get("code"), err.get("error_subcode")
        base = err.get("error_user_msg") or err.get("message") or f"Meta returned HTTP {status}"
        hint = HINTS.get(sub) or HINTS.get(code)
        if code in RATE_LIMIT_CODES:
            hint = "Meta is rate-limiting this app. Wait a few minutes and retry."
        text = f"{base} ({hint})" if hint else base
        return MetaError(text, code=code, subcode=sub, status=status)

    # -- account ------------------------------------------------------------
    def check(self) -> dict:
        """Verify the token can see the ad account. Returns name/status/currency."""
        info = self._request("GET", self.account, params={"fields": "name,account_status,currency,disable_reason"})
        info["active"] = info.get("account_status") == 1
        return info

    # -- audiences ----------------------------------------------------------
    def create_audience(self, name: str, description: str = "") -> str:
        out = self._request("POST", f"{self.account}/customaudiences", data={
            "name": name,
            "description": description,
            "subtype": "CUSTOM",
            "customer_file_source": "USER_PROVIDED_ONLY",
        })
        return str(out["id"])

    def delete_audience(self, audience_id: str) -> None:
        self._request("DELETE", audience_id)

    def replace_users(self, audience_id: str, rows: List[Tuple[str, str]], session_id: Optional[int] = None) -> dict:
        """Replace the audience's members with `rows` of (email_sha256, phone_sha256),
        in batches of 10,000 sharing one session. Blank strings mean 'no value'."""
        if not rows:
            raise MetaError("Nothing to upload: no hashable emails or phone numbers.")
        session_id = session_id or random.randint(1, 2**31 - 1)
        batches = [rows[i:i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
        received = invalid = 0
        for seq, batch in enumerate(batches, start=1):
            out = self._request("POST", f"{audience_id}/usersreplace", data={
                "session": json.dumps({
                    "session_id": session_id,
                    "batch_seq": seq,
                    "last_batch_flag": seq == len(batches),
                    "estimated_num_total": len(rows),
                }),
                "payload": json.dumps({
                    "schema": ["EMAIL_SHA256", "PHONE_SHA256"],
                    "data": [[e, p] for e, p in batch],
                }),
            })
            received += int(out.get("num_received", len(batch)))
            invalid += int(out.get("num_invalid_entries", 0))
        return {"batches": len(batches), "received": received, "invalid": invalid, "session_id": session_id}

    def get_audience(self, audience_id: str) -> dict:
        return self._request("GET", audience_id, params={
            "fields": "name,approximate_count_lower_bound,approximate_count_upper_bound,operation_status,delivery_status",
        })

    # -- reporting ----------------------------------------------------------
    def _paged(self, path: str, params: dict) -> Iterable[dict]:
        out = self._request("GET", path, params=params)
        while True:
            for item in out.get("data", []):
                yield item
            nxt = (out.get("paging") or {}).get("next")
            if not nxt:
                return
            out = self._request("GET", nxt)

    def adsets_using_audience(self, audience_id: str) -> List[dict]:
        """Ad sets in the account whose targeting includes the audience."""
        found = []
        for adset in self._paged(f"{self.account}/adsets", {"fields": "id,name,targeting", "limit": 200}):
            targeted = (adset.get("targeting") or {}).get("custom_audiences") or []
            if any(str(a.get("id")) == str(audience_id) for a in targeted):
                found.append({"id": adset["id"], "name": adset.get("name", "")})
        return found

    def adset_insights(self, adset_id: str, since: str, until: str, conversion_action: str = "purchase") -> List[dict]:
        """Daily rows: date, impressions, clicks, spend, conversions, revenue."""
        rows = []
        params = {
            "fields": "impressions,clicks,spend,actions,action_values",
            "time_increment": 1,
            "time_range": json.dumps({"since": since, "until": until}),
            "limit": 100,
        }
        for r in self._paged(f"{adset_id}/insights", params):
            def pick(key):
                for a in r.get(key) or []:
                    if a.get("action_type") == conversion_action:
                        return float(a.get("value", 0))
                return 0.0
            rows.append({
                "date": r["date_start"],
                "impressions": int(r.get("impressions", 0)),
                "clicks": int(r.get("clicks", 0)),
                "spend": float(r.get("spend", 0)),
                "conversions": int(pick("actions")),
                "revenue": pick("action_values"),
            })
        return rows


def get_client() -> MetaClient:
    return MetaClient(
        os.getenv("META_ACCESS_TOKEN", ""),
        os.getenv("META_AD_ACCOUNT_ID", ""),
        api_version=os.getenv("META_API_VERSION", DEFAULT_VERSION),
    )
