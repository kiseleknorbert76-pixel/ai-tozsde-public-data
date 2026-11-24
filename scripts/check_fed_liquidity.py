"""Read-only monitor of the published Fed liquidity snapshot (no data rewriting)."""
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

H41 = "https://www.federalreserve.gov/releases/h41/current/"
RRP = "https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/10.json"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
ALLOWED_SOURCES = {"fed_assets": (H41, FRED + "WALCL"), "tga": (H41, FRED + "WDTGAL"), "rrp_overnight": (RRP, FRED + "RRPONTSYD")}


def verify(path, now=None):
    now = now or datetime.now(timezone.utc)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    observed = date.fromisoformat(payload["observed_at"])
    checked = datetime.fromisoformat(payload["checked_at"].replace("Z", "+00:00"))
    if checked.tzinfo is None:
        raise ValueError("missing_timezone")
    age_hours = (now - checked).total_seconds() / 3600
    observation_age_days = (now.date() - observed).days
    if payload.get("schema_version") != 1 or payload.get("status") != "ok" or payload.get("frequency") != "weekly":
        raise ValueError("invalid_schema")
    if observed.weekday() != 2 or not 0 <= observation_age_days <= 13:
        raise ValueError("observation_stale_or_invalid")
    if not 0 <= age_hours <= 72:
        raise ValueError("source_verification_expired")
    rows = payload["indicators"]
    if len(rows) != 3:
        raise ValueError("invalid_indicator_count")
    values = {}
    for row in rows:
        key = row["key"]
        expected_sources = ALLOWED_SOURCES.get(key, ())
        value = row["value"]
        if key in values or key not in ("fed_assets", "tga", "rrp_overnight") or row["observed_at"] != observed.isoformat() or row["source_url"] not in expected_sources or row["unit"] != "million_usd" or row["status"] != "ok" or type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid_indicator")
        values[key] = value
    if len(values) != 3:
        raise ValueError("missing_indicator")
    liq = payload["liquidity"]
    if liq["observed_at"] != observed.isoformat() or liq["formula"] != "fed_assets - tga - rrp_overnight" or liq["unit"] != "million_usd" or not math.isclose(liq["value"], values["fed_assets"]-values["tga"]-values["rrp_overnight"], abs_tol=0.001, rel_tol=0):
        raise ValueError("invalid_liquidity_arithmetic")
    return {"observation_date": observed.isoformat(), "checked_at": checked.isoformat(), "status": "verified"}


if __name__ == "__main__":
    try:
        print(json.dumps(verify(sys.argv[1] if len(sys.argv) > 1 else "fed-liquidity.json")))
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print(f"::error::Fed public snapshot check failed: {error}", file=sys.stderr)
        sys.exit(1)
