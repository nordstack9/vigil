"""Vigil — endpoint uptime monitor with sample data."""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

ENDPOINTS = [
    {"name": "Payment API", "url": "api.stripe.com/v1/charges", "protocol": "HTTPS", "region": "us-east-1", "group": "Payment"},
    {"name": "Auth Service", "url": "auth.internal:8443/health", "protocol": "HTTPS", "region": "us-east-1", "group": "Core"},
    {"name": "Primary DB", "url": "pg-primary.internal:5432", "protocol": "TCP", "region": "us-east-1", "group": "Database"},
    {"name": "Replica DB", "url": "pg-replica.internal:5432", "protocol": "TCP", "region": "us-west-2", "group": "Database"},
    {"name": "Redis Cache", "url": "redis.internal:6379", "protocol": "TCP", "region": "us-east-1", "group": "Cache"},
    {"name": "Webhook Ingest", "url": "hooks.app.com/ingest", "protocol": "HTTPS", "region": "eu-west-1", "group": "Integrations"},
    {"name": "Search Index", "url": "es.internal:9200/_cluster/health", "protocol": "HTTP", "region": "us-east-1", "group": "Search"},
    {"name": "CDN Origin", "url": "origin.cdn.app.com/health", "protocol": "HTTPS", "region": "global", "group": "Edge"},
    {"name": "DNS Resolver", "url": "ns1.app.com", "protocol": "DNS", "region": "global", "group": "Edge"},
    {"name": "Email Relay", "url": "smtp.internal:587", "protocol": "TCP", "region": "us-east-1", "group": "Notifications"},
]

random.seed(99)


def generate_data():
    now = datetime(2026, 9, 28, 14, 32, 0)
    results = []

    for ep in ENDPOINTS:
        base_ms = random.choice([12, 18, 24, 35, 48, 65, 88, 110, 145, 210])
        is_degraded = ep["name"] == "Search Index"
        is_down = False

        checks_24h = []
        total = 288  # 5-min intervals over 24h
        failures = 0
        for i in range(total):
            t = now - timedelta(minutes=5 * (total - 1 - i))
            if is_degraded and 80 < i < 100:
                status = "degraded"
                ms = base_ms * random.uniform(3.5, 6.0)
            elif is_degraded and i == 90:
                status = "down"
                ms = 0
                failures += 1
            elif random.random() < 0.003:
                status = "down"
                ms = 0
                failures += 1
            else:
                status = "operational"
                ms = base_ms * random.uniform(0.7, 1.5)
            checks_24h.append({"time": t.strftime("%H:%M"), "status": status, "ms": round(ms, 1)})

        ok_checks = [c for c in checks_24h if c["status"] == "operational"]
        all_ms = [c["ms"] for c in ok_checks] if ok_checks else [0]
        all_ms_sorted = sorted(all_ms)
        n = len(all_ms_sorted)

        uptime_pct = round((total - failures) / total * 100, 2)
        if uptime_pct > 99.99:
            uptime_pct = 99.99

        current = checks_24h[-1]
        current_status = current["status"]
        if is_degraded and current["status"] == "operational":
            current_status = "operational"

        # last 90 days uptime
        days_30 = round(100 - random.uniform(0.01, 0.15), 2) if not is_degraded else round(100 - random.uniform(0.3, 0.8), 2)

        results.append({
            "name": ep["name"],
            "url": ep["url"],
            "protocol": ep["protocol"],
            "region": ep["region"],
            "group": ep["group"],
            "status": current_status,
            "response_ms": round(current["ms"], 1),
            "uptime_24h": uptime_pct,
            "uptime_30d": days_30,
            "p50": round(all_ms_sorted[n // 2], 1) if n else 0,
            "p95": round(all_ms_sorted[int(n * 0.95)] if n else 0, 1),
            "p99": round(all_ms_sorted[int(n * 0.99)] if n else 0, 1),
            "checks_24h": checks_24h,
            "heatmap": [c["status"] for c in checks_24h[-48:]],  # last 4 hours in 5-min blocks
        })

    return results, now


DATA, GENERATED_AT = generate_data()

INCIDENTS = [
    {"time": "Sep 28, 14:18", "severity": "resolved", "title": "Search Index latency spike", "detail": "p95 exceeded 400ms for 12 minutes. Triggered auto-scaling. Resolved after new nodes joined cluster."},
    {"time": "Sep 27, 03:42", "severity": "resolved", "title": "DNS propagation delay", "detail": "TTL expiry caused 45s resolution delay in eu-west-1. Self-recovered."},
    {"time": "Sep 25, 11:05", "severity": "resolved", "title": "Redis failover", "detail": "Primary node OOM. Sentinel promoted replica in 2.1s. Zero dropped connections."},
]


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    all_operational = all(e["status"] == "operational" for e in DATA)
    any_down = any(e["status"] == "down" for e in DATA)

    if any_down:
        system_status = "partial_outage"
        system_label = "Partial Outage"
    elif not all_operational:
        system_status = "degraded"
        system_label = "Degraded Performance"
    else:
        system_status = "operational"
        system_label = "All Systems Operational"

    groups = {}
    for ep in DATA:
        g = ep["group"]
        if g not in groups:
            groups[g] = []
        groups[g].append(ep)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "system_status": system_status,
        "system_label": system_label,
        "endpoints": DATA,
        "groups": groups,
        "incidents": INCIDENTS,
        "generated_at": GENERATED_AT.strftime("%b %d, %Y — %H:%M UTC"),
        "total_endpoints": len(DATA),
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8902)
