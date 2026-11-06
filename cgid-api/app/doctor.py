"""
Setup check. Run it after configuring, before your first real sync:

    python -m app.doctor                      # local
    docker compose run --rm api python -m app.doctor
    python -m app.doctor --meta-write-test    # also create+delete a tiny test
                                              # audience in Meta to prove write
                                              # access and accepted terms

Prints PASS / WARN / FAIL with the fix for each problem; exits 1 on any FAIL.
"""
import os
import sys

from sqlalchemy import text

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def run_checks(meta_write_test: bool = False, client_factory=None) -> list:
    from . import meta, models
    from .audience_engine import consent_signal
    from .database import SessionLocal, engine

    results = []

    def add(status, name, detail=""):
        results.append((status, name, detail))

    # Database
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        add(PASS, "Database reachable", engine.dialect.name)
    except Exception as exc:  # noqa: BLE001 - report any connection problem
        add(FAIL, "Database reachable", f"{exc.__class__.__name__}: check DATABASE_URL")
        return results

    # Security
    if os.getenv("API_KEYS", "").strip():
        add(PASS, "API key required", "API_KEYS is set")
    else:
        add(FAIL, "API key required", "API_KEYS is empty, so anyone who can reach the API can read and change data. Set it (openssl rand -hex 32).")
    if os.getenv("CORS_ORIGINS", "*").strip() in ("", "*"):
        add(WARN, "CORS origins", "Allows any website to call the API from a browser. Set CORS_ORIGINS to your own origins.")
    else:
        add(PASS, "CORS origins", os.getenv("CORS_ORIGINS"))

    # Data
    with SessionLocal() as db:
        people = db.query(models.Person).count()
        consent = db.query(models.Signal).filter(models.Signal.name == consent_signal(), models.Signal.value == 1.0).count()
        scored = db.query(models.ModelScore).count()
    if people == 0:
        add(WARN, "Customer data", "No people yet. Import a CSV (Import Data screen or POST /ingest/csv).")
    else:
        add(PASS, "Customer data", f"{people} people")
        if consent == 0:
            add(WARN, "Marketing consent", f"No one has {consent_signal()} = 1, so syncs to Meta would upload nobody. Add that column to your import.")
        else:
            add(PASS, "Marketing consent", f"{consent} people opted in")
        if scored == 0:
            add(WARN, "Models", "No scores yet. Run POST /models/run (Score customers) to enable audiences like churn_risk > 0.7.")

    # Meta
    mode = meta.env_mode()
    if mode != "live":
        add(WARN, "Meta", "META_MODE is not 'live': Meta syncs and reporting are simulated. See docs/META-SETUP.md.")
        return results
    missing = [v for v in ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID") if not os.getenv(v)]
    if missing:
        add(FAIL, "Meta credentials", f"Missing: {', '.join(missing)}")
        return results
    add(PASS, "Meta credentials", f"ad account {meta.normalize_account_id(os.getenv('META_AD_ACCOUNT_ID'))}, API {os.getenv('META_API_VERSION', meta.DEFAULT_VERSION)}")
    try:
        client = (client_factory or meta.get_client)()
        info = client.check()
        if info.get("active"):
            add(PASS, "Meta ad account", f"{info.get('name')} ({info.get('currency')}), active")
        else:
            add(FAIL, "Meta ad account", f"{info.get('name')} is not active (account_status={info.get('account_status')}, disable_reason={info.get('disable_reason')}).")
    except meta.MetaError as exc:
        add(FAIL, "Meta ad account", str(exc))
        return results
    if meta_write_test:
        try:
            test_id = client.create_audience("CGID setup test (safe to delete)", "Created by app.doctor; removed immediately.")
            client.delete_audience(test_id)
            add(PASS, "Meta write access", "created and deleted a test audience; Custom Audience Terms accepted")
        except meta.MetaError as exc:
            add(FAIL, "Meta write access", str(exc))
    else:
        add(WARN, "Meta write access", "Not tested. Run with --meta-write-test to create and delete a tiny test audience.")
    return results


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    results = run_checks(meta_write_test="--meta-write-test" in argv)
    marks = {PASS: "  PASS", WARN: "  WARN", FAIL: "  FAIL"}
    for status, name, detail in results:
        print(f"{marks[status]}  {name}" + (f" - {detail}" if detail else ""))
    failed = sum(1 for r in results if r[0] == FAIL)
    warned = sum(1 for r in results if r[0] == WARN)
    print(f"\n{len(results) - failed - warned} passed, {warned} warnings, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
