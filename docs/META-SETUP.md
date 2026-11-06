# Connect Customer Graph ID to Meta

This walks one company from zero to a working loop: customers in, an audience in
Meta, results back. Plan on about two hours, most of it in Meta's UI.

You need: a Meta ad account that is already running ads (with a payment method),
admin access to its Business Manager, and a machine with Docker.

> **Status.** The Meta integration was built from Meta's documentation and tested
> against simulated responses. Your first live run is the first time it talks to
> the real API, so expect to report a bug or two. The `doctor` command in step 5
> exists to find problems before you upload anything.

## 1. Create a Meta app (10 min)

1. Go to https://developers.facebook.com/apps and create an app. Choose the
   **Business** type and add the **Marketing API** product.
2. You do **not** need app review or Business Verification to use the API on ad
   accounts you administer yourself. Leave the app in development mode.

## 2. Create a system user and token (15 min)

1. In Business Settings > Users > **System users**, add a system user (Admin).
2. Assign it your **ad account** with full control, and your **app**.
3. Generate a token for the app with the permissions **`ads_management`** and
   **`ads_read`**. Copy it once; Meta won't show it again.
4. Note your **ad account ID** (Ads Manager > Account overview; digits, sometimes
   shown as `act_123...`).

## 3. Accept Meta's Custom Audience Terms (2 min)

In Ads Manager go to **Audiences > Create audience > Custom audience > Customer
list** and accept the terms when prompted, then close without creating anything.
Without this the first upload fails with "Custom Audience Terms Not Accepted".

## 4. Configure and start (10 min)

```bash
git clone https://github.com/neerajyadavhub/CustomerIntelligencePlatform.git
cd CustomerIntelligencePlatform
cp .env.example .env
```

Edit `.env`: set `POSTGRES_PASSWORD`, `API_KEYS` (`openssl rand -hex 32`),
`META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`, and `META_MODE=live`. Then:

```bash
docker compose -f docker-compose.customer.yml up -d --build
```

The UI and API are at http://localhost:8000. In the UI, open **CDP > Import Data**
and enter your API key once.

## 5. Run the setup check (2 min)

```bash
docker compose -f docker-compose.customer.yml run --rm api python -m app.doctor --meta-write-test
```

It checks the database, API key, CORS, your data, and Meta, and with
`--meta-write-test` creates and immediately deletes a tiny test audience to prove
write access and accepted terms. Fix every FAIL before continuing; each line says how.

| Message | Fix |
|---|---|
| token invalid or expired | Generate a new system-user token (step 2) |
| missing a permission | The token needs `ads_management` and `ads_read`, and the system user must be assigned the ad account |
| Custom Audience Terms not accepted | Step 3 |
| not linked to the Business Manager | Add the ad account to the business that owns the app |
| rate-limiting | Wait a few minutes; the app already retries with backoff |

## 6. Load your customers (15 min)

Export customers from your store/CRM as a CSV with these columns (any extra
numeric column becomes a signal):

```
email,phone,external_user_id,orders,total_spend,days_since_last_order,tenure_days,promo_orders,marketing_consent
```

`marketing_consent` must be `1` for people who opted in to marketing. **Anyone
without it is never uploaded to Meta**; missing counts as no consent. Import it
(Import Data screen, or `POST /ingest/csv`), then click **Score customers**.

## 7. Create an audience and send it to Meta

1. Create an audience over your data, for example `churn_risk > 0.7` and
   `clv_12m > 500` (Marketing > Audience Builder, or `POST /audience`).
2. Sync it to **meta_ads** (`POST /audience/{id}/sync` with `{"channel": "meta_ads"}`).
   Only hashed emails and phone numbers (SHA-256) leave your server.
3. In Ads Manager you will see a Custom Audience named **"CGID - <your audience name>"**.
   Meta takes up to 24 hours to process it. Check progress with
   `POST /syncs/{sync_id}/refresh`, which reads the matched size back.
4. Syncing the same audience again **replaces its members** and keeps the same
   Meta audience, so ad sets that use it keep working.

## 8. Run a campaign and see results here

Create a campaign in Ads Manager with an **ad set that targets the audience**.
After it runs, `GET /audience/{id}/performance` (and the Measurement screen) shows
impressions, clicks, spend, conversions, revenue and ROAS for that audience,
pulled from Meta (at most once per 15 minutes per sync).

Until an ad set targets the audience, the sync's status says so.

## Things to know

- **Numbers can differ from Ads Manager.** Conversions and revenue count the action
  type in `META_CONVERSION_ACTION` (default `purchase`); attribution windows and
  recent-day revisions mean small differences. Set the action to match your pixel.
- **Meta API versions expire.** Set `META_API_VERSION` to a current version if calls
  start failing after a Meta change.
- **You are responsible for lawful use.** Only upload people who consented, honor
  deletion/opt-out requests (re-sync to replace the audience), and follow Meta's
  Custom Audience terms. Meta may block audiences that imply health or financial status.
- **Secure it.** The API listens on localhost only; put a TLS proxy in front, keep
  `.env` out of git, and rotate the token if it leaks.
- **Not included yet:** other ad platforms, Conversions API event upload, multi-user
  logins, and scheduled syncs (sync is on demand).
