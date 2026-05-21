"""Google Analytics 4 Data API router — server-side, service account auth."""
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from config.database import engine
from models.order import OrderTable, OrderLine
from models.user import User
from services.auth import get_current_user

try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Metric,
        RunReportRequest,
        RunRealtimeReportRequest,
    )
    from google.oauth2 import service_account
except ModuleNotFoundError:
    BetaAnalyticsDataClient = None
    DateRange = Dimension = Metric = RunReportRequest = RunRealtimeReportRequest = None
    service_account = None

router = APIRouter(prefix="/ga4", tags=["GA4 Analytics"])

_CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "../config/ga4_credentials.json")
_PROPERTY_ID = "properties/536976944"


def _client() -> BetaAnalyticsDataClient:
    if BetaAnalyticsDataClient is None or service_account is None:
        raise HTTPException(
            status_code=503,
            detail="GA4 dependencies are not installed. Install google-analytics-data.",
        )
    creds = service_account.Credentials.from_service_account_file(
        _CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    return BetaAnalyticsDataClient(credentials=creds)


def _rows_to_list(response, dim_keys: list[str], metric_keys: list[str]) -> list[dict]:
    result = []
    for row in response.rows:
        entry = {}
        for i, key in enumerate(dim_keys):
            entry[key] = row.dimension_values[i].value
        for i, key in enumerate(metric_keys):
            entry[key] = row.metric_values[i].value
        result.append(entry)
    return result


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _fetch_overview(client, start, end, prev_start, prev_end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[
            DateRange(start_date=str(start), end_date=str(end)),
            DateRange(start_date=str(prev_start), end_date=str(prev_end)),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="screenPageViews"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
        ],
    )
    resp = client.run_report(req)

    def _extract(rows, idx):
        for row in rows:
            if row.dimension_values and row.dimension_values[0].value == str(idx):
                return row
        return rows[idx] if len(rows) > idx else None

    cur = _extract(resp.rows, 0)
    prev = _extract(resp.rows, 1)

    def _val(row, i, cast=float):
        return cast(row.metric_values[i].value) if row else 0

    cs, cu, cv, cb, cd = _val(cur, 0, int), _val(cur, 1, int), _val(cur, 2, int), _val(cur, 3), _val(cur, 4)
    ps, pu, pv, pb, pd = _val(prev, 0, int), _val(prev, 1, int), _val(prev, 2, int), _val(prev, 3), _val(prev, 4)

    return {
        "sessions": cs, "users": cu, "pageviews": cv,
        "bounce_rate": cb, "avg_session_duration": cd,
        "prev": {"sessions": ps, "users": pu, "pageviews": pv, "bounce_rate": pb, "avg_session_duration": pd},
        "change": {
            "sessions": _pct_change(cs, ps), "users": _pct_change(cu, pu),
            "pageviews": _pct_change(cv, pv), "bounce_rate": _pct_change(cb, pb),
            "avg_session_duration": _pct_change(cd, pd),
        },
    }


def _fetch_sessions_by_day(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="date")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
        order_bys=[{"dimension": {"dimension_name": "date"}}],
    )
    return _rows_to_list(client.run_report(req), ["date"], ["sessions", "users"])


def _fetch_top_pages(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="pagePath"), Dimension(name="pageTitle")],
        metrics=[Metric(name="screenPageViews"), Metric(name="totalUsers")],
        limit=10,
        order_bys=[{"metric": {"metric_name": "screenPageViews"}, "desc": True}],
    )
    return _rows_to_list(client.run_report(req), ["path", "title"], ["views", "users"])


def _fetch_sources(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
        limit=20,
        order_bys=[{"metric": {"metric_name": "sessions"}, "desc": True}],
    )
    return _rows_to_list(client.run_report(req), ["source", "medium"], ["sessions", "users"])


def _fetch_devices(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="deviceCategory")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
    )
    return _rows_to_list(client.run_report(req), ["device"], ["sessions", "users"])


def _fetch_countries(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="country")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
        limit=10,
        order_bys=[{"metric": {"metric_name": "sessions"}, "desc": True}],
    )
    return _rows_to_list(client.run_report(req), ["country"], ["sessions", "users"])


def _fetch_new_vs_returning(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="newVsReturning")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
    )
    return _rows_to_list(client.run_report(req), ["type"], ["sessions", "users"])


def _fetch_hourly(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="hour")],
        metrics=[Metric(name="sessions")],
        order_bys=[{"dimension": {"dimension_name": "hour"}}],
    )
    rows = {int(r.dimension_values[0].value): int(r.metric_values[0].value) for r in client.run_report(req).rows}
    return [{"hour": h, "sessions": rows.get(h, 0)} for h in range(24)]


def _fetch_landing_pages(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="landingPage")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers"), Metric(name="bounceRate")],
        limit=10,
        order_bys=[{"metric": {"metric_name": "sessions"}, "desc": True}],
    )
    return _rows_to_list(client.run_report(req), ["path"], ["sessions", "users", "bounce_rate"])


def _fetch_events(client, start, end):
    req = RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount"), Metric(name="totalUsers")],
        limit=20,
        order_bys=[{"metric": {"metric_name": "eventCount"}, "desc": True}],
    )
    return _rows_to_list(client.run_report(req), ["event"], ["count", "users"])


def _fetch_orders_by_day(start: date, end: date) -> dict:
    """Query DB: orders grouped by date → {date_str: {orders, revenue}}."""
    result: dict[str, dict] = {}
    with Session(engine) as session:
        rows = session.exec(
            select(OrderTable).where(
                OrderTable.order_date >= start,
                OrderTable.order_date <= end,
            )
        ).all()
    for row in rows:
        d = str(row.order_date)
        lines = []
        if row.order_lines_json:
            try:
                lines = [OrderLine(**l) for l in json.loads(row.order_lines_json)]
            except Exception:
                pass
        revenue = sum(l.unit_price * l.quantity for l in lines)
        if d not in result:
            result[d] = {"orders": 0, "revenue": 0.0}
        result[d]["orders"] += 1
        result[d]["revenue"] += revenue
    return result


def _fetch_orders_by_channel(start: date, end: date) -> list[dict]:
    """Orders grouped by channel for source attribution."""
    channels: dict[str, dict] = {}
    with Session(engine) as session:
        rows = session.exec(
            select(OrderTable).where(
                OrderTable.order_date >= start,
                OrderTable.order_date <= end,
            )
        ).all()
    for row in rows:
        ch = row.channel or "unknown"
        lines = []
        if row.order_lines_json:
            try:
                lines = [OrderLine(**l) for l in json.loads(row.order_lines_json)]
            except Exception:
                pass
        revenue = sum(l.unit_price * l.quantity for l in lines)
        if ch not in channels:
            channels[ch] = {"channel": ch, "orders": 0, "revenue": 0.0}
        channels[ch]["orders"] += 1
        channels[ch]["revenue"] += revenue
    return sorted(channels.values(), key=lambda x: x["orders"], reverse=True)


@router.get("/dashboard")
def ga4_dashboard(days: int = Query(30, ge=1, le=365)):
    """Single endpoint — fetches all GA4 data in parallel and returns one payload."""
    try:
        client = _client()
        end = date.today()
        start = end - timedelta(days=days - 1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)

        tasks = {
            "overview":         lambda: _fetch_overview(client, start, end, prev_start, prev_end),
            "sessions_by_day":  lambda: _fetch_sessions_by_day(client, start, end),
            "top_pages":        lambda: _fetch_top_pages(client, start, end),
            "sources":          lambda: _fetch_sources(client, start, end),
            "devices":          lambda: _fetch_devices(client, start, end),
            "countries":        lambda: _fetch_countries(client, start, end),
            "new_vs_returning": lambda: _fetch_new_vs_returning(client, start, end),
            "hourly":           lambda: _fetch_hourly(client, start, end),
            "landing_pages":    lambda: _fetch_landing_pages(client, start, end),
            "events":           lambda: _fetch_events(client, start, end),
        }

        results = {}
        with ThreadPoolExecutor(max_workers=9) as executor:
            futures = {executor.submit(fn): key for key, fn in tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                results[key] = future.result()

        results["days"] = days
        return results
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/correlation")
def ga4_correlation(days: int = Query(30, ge=1, le=365), user: User = Depends(get_current_user)):
    """GA4 sessions by day merged with DB orders by day + channel attribution."""
    try:
        client = _client()
        end = date.today()
        start = end - timedelta(days=days - 1)

        with ThreadPoolExecutor(max_workers=3) as ex:
            f_sessions = ex.submit(_fetch_sessions_by_day, client, start, end)
            f_orders_day = ex.submit(_fetch_orders_by_day, start, end)
            f_orders_ch = ex.submit(_fetch_orders_by_channel, start, end)
            sessions_by_day = f_sessions.result()
            orders_by_day = f_orders_day.result()
            orders_by_channel = f_orders_ch.result()

        # Merge: for each day, combine GA4 sessions + DB orders
        merged = []
        for row in sessions_by_day:
            raw = row["date"]  # "20250501"
            db_date = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
            day_orders = orders_by_day.get(db_date, {"orders": 0, "revenue": 0.0})
            merged.append({
                "date": raw,
                "sessions": int(row["sessions"]),
                "users": int(row["users"]),
                "orders": day_orders["orders"],
                "revenue": round(day_orders["revenue"], 0),
            })

        return {
            "by_day": merged,
            "by_channel": orders_by_channel,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/ai-context")
def ga4_ai_context(days: int = Query(30, ge=1, le=365), user: User = Depends(get_current_user)):
    """Compact GA4 summary for AI assistant context injection."""
    try:
        client = _client()
        end = date.today()
        start = end - timedelta(days=days - 1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)

        with ThreadPoolExecutor(max_workers=4) as ex:
            f_ov = ex.submit(_fetch_overview, client, start, end, prev_start, prev_end)
            f_src = ex.submit(_fetch_sources, client, start, end)
            f_ev = ex.submit(_fetch_events, client, start, end)
            f_ch = ex.submit(_fetch_orders_by_channel, start, end)
            ov = f_ov.result()
            sources = f_src.result()
            events = f_ev.result()
            channels = f_ch.result()

        top_sources = [f"{r['source']}/{r['medium']} ({r['sessions']} phiên)" for r in sources[:5]]
        top_events = [f"{r['event']} ({r['count']} lần)" for r in events[:8]]
        top_channels = [f"{r['channel']} ({r['orders']} đơn, {r['revenue']:,.0f}đ)" for r in channels[:5]]

        return {
            "days": days,
            "overview": ov,
            "top_sources": top_sources,
            "top_events": top_events,
            "order_channels": top_channels,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/realtime")
def ga4_realtime():
    """Active users right now — polled separately every 60s."""
    try:
        client = _client()
        req = RunRealtimeReportRequest(
            property=_PROPERTY_ID,
            metrics=[Metric(name="activeUsers")],
        )
        resp = client.run_realtime_report(req)
        return {"active_users": int(resp.rows[0].metric_values[0].value) if resp.rows else 0}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
