"""
Post-activation measurement: performance of an audience after it's been
synced to a channel, so marketing can answer "how did Q3 Reactivation
actually perform on Meta" without leaving Customer Graph ID.

Same pattern as identity_resolver.py: everything in the app talks to the
MetricsProvider interface below, never to Meta/Google directly, so
swapping MockMetricsProvider for a real one is a one-line change in
main.py.

--------------------------------------------------------------------------
HOW A REAL PROVIDER WORKS (what MetaInsightsProvider should do):

  1. A real sync (POST /audience/{id}/sync) must store the external
     campaign/ad-set id the channel hands back — today's mock sync
     doesn't keep one, since it never calls a real API. That id is what
     this provider queries by.

  2. Authenticate against the channel's reporting endpoint with the same
     ad-account/business credentials used for the sync itself:
       - Meta: Marketing API "Insights" endpoint
         (https://developers.facebook.com/docs/marketing-api/insights)
       - Google: Google Ads API `GoogleAdsService.SearchStream` with a
         GAQL report query
       - An ESP: its own campaign-stats endpoint

  3. Pull daily breakdowns (impressions, clicks, spend, conversions,
     revenue) for the date range since the last successful pull.

  4. Upsert PerformanceMetric rows keyed by (sync_id, date) — overwrite
     an existing day rather than skip it, since platforms commonly revise
     same-day numbers for 24-72 hours after.

  5. Run this on a schedule per active sync (hourly or daily), the same
     way a real IdentityResolver.sync() would run on a schedule.
--------------------------------------------------------------------------
"""
import os
import random
import datetime as dt
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
from . import models
from .clock import utcnow

HISTORY_DAYS = 14


class MetricsProvider(ABC):
    @abstractmethod
    def backfill(self, db: Session, sync: "models.ChannelSync") -> int:
        """Called once, right after a sync is created, to populate its
        initial performance history. Returns rows written."""
        raise NotImplementedError

    @abstractmethod
    def pull_latest(self, db: Session, sync: "models.ChannelSync") -> int:
        """Called on a schedule to refresh the most recent day(s).
        Returns rows written/updated."""
        raise NotImplementedError


class MockMetricsProvider(MetricsProvider):
    """Demo/dev provider. Generates a plausible performance curve from
    the sync's own matched_count — a ramp-up over the first few days,
    then day-to-day noise — so the dashboard has realistic-looking
    numbers immediately, with no external credentials needed. Use this
    until a real channel's reporting API is wired up."""

    def backfill(self, db: Session, sync: models.ChannelSync, reach_override: int = None) -> int:
        # reach_override lets the demo seed simulate a realistic audience
        # size (thousands) even though only a handful of people are
        # actually seeded in this dev database — matched_count itself
        # stays honest to the real seeded population; this only scales
        # the simulated performance curve so the dashboard isn't all
        # zeros. A real deployment with a real customer base wouldn't
        # need this — matched_count would already be the real number.
        base_reach = max(reach_override or sync.matched_count, 1)
        rng = random.Random(sync.id * 97 + 13)  # deterministic per sync
        written = 0
        for day_offset in range(HISTORY_DAYS, 0, -1):
            date = utcnow() - dt.timedelta(days=day_offset)
            ramp = min(1.0, (HISTORY_DAYS - day_offset + 1) / 4)
            noise = rng.uniform(0.85, 1.15)
            impressions = max(1, int(base_reach * rng.uniform(2.5, 4.0) * ramp * noise))
            ctr = rng.uniform(0.008, 0.022)
            clicks = int(impressions * ctr)
            cpc = rng.uniform(0.55, 1.35)
            spend = round(clicks * cpc, 2)
            cvr = rng.uniform(0.04, 0.11)
            conversions = int(clicks * cvr)
            aov = rng.uniform(85, 260)
            revenue = round(conversions * aov, 2)
            db.add(models.PerformanceMetric(
                sync_id=sync.id, date=date, impressions=impressions,
                clicks=clicks, spend=spend, conversions=conversions,
                revenue=revenue,
            ))
            written += 1
        db.commit()
        return written

    def pull_latest(self, db: Session, sync: models.ChannelSync) -> int:
        # The mock's backfill already covers the full window. A real
        # provider would upsert just the last day or two here.
        return 0


class MetaInsightsProvider(MetricsProvider):
    """Pulls real performance from Meta for a synced audience.

    How it works: find the ad sets in the ad account whose targeting includes
    the sync's Meta Custom Audience, pull their daily insights since the sync
    date, add them up per day, and upsert one PerformanceMetric per day
    (overwriting, because Meta revises recent days). Conversions and revenue
    count the action type set in META_CONVERSION_ACTION (default: purchase).
    Pulls are rate-limited per sync (META_PULL_MIN_MINUTES, default 15)."""

    _last_pull: dict = {}

    def __init__(self, client=None):
        self.client = client

    def _client(self):
        if self.client is None:
            from .meta import get_client
            self.client = get_client()
        return self.client

    def backfill(self, db: Session, sync: models.ChannelSync) -> int:
        return self.pull_latest(db, sync)

    def pull_latest(self, db: Session, sync: models.ChannelSync) -> int:
        from .meta import MetaError
        if not sync.external_audience_id:
            return 0
        min_minutes = float(os.getenv("META_PULL_MIN_MINUTES", "15"))
        last = self._last_pull.get(sync.id)
        if last and (utcnow() - last).total_seconds() < min_minutes * 60:
            return 0
        self._last_pull[sync.id] = utcnow()
        try:
            client = self._client()
            adsets = client.adsets_using_audience(sync.external_audience_id)
            if not adsets:
                sync.external_status = (
                    f"No ad sets target Meta audience {sync.external_audience_id} yet. "
                    "Create a campaign in Ads Manager that targets it; results will appear here."
                )
                db.commit()
                return 0
            since = sync.synced_at.date().isoformat()
            until = utcnow().date().isoformat()
            action = os.getenv("META_CONVERSION_ACTION", "purchase")
            days: dict = {}
            for adset in adsets:
                for r in client.adset_insights(adset["id"], since, until, action):
                    d = days.setdefault(r["date"], dict(impressions=0, clicks=0, spend=0.0, conversions=0, revenue=0.0))
                    for k in d:
                        d[k] += r[k]
        except MetaError as exc:
            sync.external_status = f"Could not pull Meta insights: {exc}"
            db.commit()
            return 0
        written = 0
        for date_str, vals in days.items():
            date = dt.datetime.fromisoformat(date_str)
            row = (
                db.query(models.PerformanceMetric)
                .filter(models.PerformanceMetric.sync_id == sync.id, models.PerformanceMetric.date == date)
                .first()
            )
            if row is None:
                row = models.PerformanceMetric(sync_id=sync.id, date=date)
                db.add(row)
            row.impressions, row.clicks = vals["impressions"], vals["clicks"]
            row.spend, row.conversions, row.revenue = round(vals["spend"], 2), vals["conversions"], round(vals["revenue"], 2)
            written += 1
        sync.external_status = f"Pulled Meta insights for {len(adsets)} ad set(s) across {written} day(s)."
        db.commit()
        return written


class RoutingProvider(MetricsProvider):
    """Meta syncs get real Meta data; every other channel keeps the mock."""

    def __init__(self, mock: MetricsProvider, meta: MetricsProvider):
        self.mock, self.meta = mock, meta

    def _for(self, sync):
        return self.meta if sync.channel == "meta_ads" else self.mock

    def backfill(self, db, sync):
        return self._for(sync).backfill(db, sync)

    def pull_latest(self, db, sync):
        return self._for(sync).pull_latest(db, sync)


def get_metrics_provider() -> MetricsProvider:
    from .meta import is_live
    if is_live():
        return RoutingProvider(MockMetricsProvider(), MetaInsightsProvider())
    return MockMetricsProvider()


def summarize(metrics):
    """Roll a list of PerformanceMetric rows into one totals dict with
    derived rates (CTR, CPA, ROAS)."""
    impressions = sum(m.impressions for m in metrics)
    clicks = sum(m.clicks for m in metrics)
    spend = sum(m.spend for m in metrics)
    conversions = sum(m.conversions for m in metrics)
    revenue = sum(m.revenue for m in metrics)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": round(spend, 2),
        "conversions": conversions,
        "revenue": round(revenue, 2),
        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
        "cpa": round(spend / conversions, 2) if conversions else 0.0,
        "roas": round(revenue / spend, 2) if spend else 0.0,
    }
