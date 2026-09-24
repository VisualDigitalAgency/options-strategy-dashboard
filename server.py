"""JSON-RPC 2.0 server exposing the strategy engine to the React dashboard.

Run: python server.py  (listens on http://localhost:8000/rpc)
"""

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

from engine import config, data_fetch, risk_rules, span, virtual
from engine.batch import ScreenJob

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173"])

CACHE_TTL_SECONDS = 600  # NSE blocks aggressive polling; 10 min is plenty for 30+ DTE trades
HEAVY_FIELDS = ("history", "chain", "sr_zones")
job = ScreenJob()


def get_screened_candidates(force_refresh: bool = False):
    """Starts a batch screen if needed and returns whatever has finished so far."""
    job.ensure(force=force_refresh, ttl=CACHE_TTL_SECONDS)
    light = [{k: v for k, v in c.items() if k not in HEAVY_FIELDS} for c in job.snapshot()]
    return {
        "candidates": light,
        "generated_at": job.state["finished_at"],
        "span_source": job.state["span_source"],
        "progress": {k: job.state[k] for k in ("running", "done", "total", "batch", "batches", "error")},
    }


def get_trade_detail(symbol: str):
    found = job.get(symbol)
    if found:
        return found
    # Not screened yet (a batch is still in flight): evaluate this one stock on demand.
    span.load(risk_rules.get_universe())
    return risk_rules.safe_evaluate(symbol)


def get_config():
    return {
        "pcr_range": [config.PCR_MIN, config.PCR_MAX],
        "min_dte": config.MIN_DTE,
        "delta_max_abs": config.DELTA_MAX_ABS,
        "sl_grace_days": config.SL_GRACE_DAYS,
        "sr_lookback_days": config.SR_LOOKBACK_DAYS,
        "sr_zone_width_pct": config.SR_ZONE_WIDTH_PCT,
        "exposure_min_pct": config.EXPOSURE_MIN_PCT,
        "universe": risk_rules.get_universe(),
    }


def calc_margin(symbol: str, expiry: str, legs: list, lots: int = 1):
    """SPAN + exposure for SHORT legs [{side, strike}] at `lots` lots, ignoring existing positions."""
    lot = data_fetch.fetch_lot_size(symbol, pd.Timestamp(expiry))
    if not lot:
        raise ValueError(f"Lot size for {symbol} {expiry} not found")
    spot = virtual.quote(symbol, expiry, legs[0]["side"], float(legs[0]["strike"]))["spot"]
    signed = [{"side": l["side"], "strike": float(l["strike"]), "qty": -lot * int(lots)} for l in legs]
    return {**virtual.group_margin(symbol, expiry, signed, spot), "lot_size": lot}


def va_get_positions():
    virtual.run_checks()
    return virtual.get_positions()


METHODS = {
    "get_screened_candidates": get_screened_candidates,
    "get_trade_detail": get_trade_detail,
    "get_config": get_config,
    "calc_margin": calc_margin,
    # Virtual trading
    "va_get_account": virtual.get_account,
    "va_get_positions": va_get_positions,
    "va_get_orders": virtual.get_orders,
    "va_get_closed": virtual.get_closed,
    "va_preview_order": virtual.preview_order,
    "va_place_order": virtual.place_order,
    "va_exit_position": virtual.exit_position,
    "va_exit_group": virtual.exit_group,
    "va_set_sl_mode": virtual.set_sl_mode,
    "va_dismiss_alert": virtual.dismiss_alert,
    "va_reset": virtual.reset,
}


def _error(req_id, code, message):
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


@app.post("/rpc")
def rpc():
    body = request.get_json(silent=True)
    if not body or body.get("jsonrpc") != "2.0" or "method" not in body:
        return _error(None, -32600, "Invalid Request")

    req_id = body.get("id")
    method = METHODS.get(body["method"])
    if method is None:
        return _error(req_id, -32601, f"Method not found: {body['method']}")

    params = body.get("params") or {}
    try:
        result = method(**params) if isinstance(params, dict) else method(*params)
    except TypeError as e:
        return _error(req_id, -32602, f"Invalid params: {e}")
    except Exception as e:
        return _error(req_id, -32000, str(e))

    return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})


if __name__ == "__main__":
    virtual.init()
    virtual.start_monitor()
    app.run(host="127.0.0.1", port=8000, debug=False, threaded=True)
