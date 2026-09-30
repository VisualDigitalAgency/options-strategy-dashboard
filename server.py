"""JSON-RPC 2.0 server exposing the strategy engine to the React dashboard.

Run: python server.py  (listens on http://localhost:8000/rpc)
Background work (screens, SL monitor, auto-trade) runs in the worker: python -m engine.worker
This process only answers requests, so any number of copies can run side by side.
"""

import functools
import logging
import math
import os
import secrets
import time
import traceback

import pandas as pd
import requests
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from engine import auth, autotrade, broker, cache, config, data_fetch, db, market_calendar, risk_rules, span, users, virtual
from engine.batch import ScreenReader
from engine.worker import HEARTBEAT, next_screen_at
from rpc_guard import InvalidParams, validate

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # an RPC call is a few hundred bytes; refuse anything huge
if os.environ.get("TRUST_PROXY") == "1":
    # Behind Caddy: take the client IP and scheme from exactly one proxy hop, so login limits
    # and the audit log see the real visitor. Never enable this without a proxy in front.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
log = logging.getLogger("theta.rpc")
throttle = cache.Throttle()  # shared through Redis by every API process

# Expensive calls hit NSE. These gaps keep one client from getting the server IP blocked.
FORCE_SCREEN_EVERY = 120      # seconds between forced screen refreshes
REPRICE_EVERY = 30            # seconds between forced position re-pricing
DETAIL_EVAL_EVERY = 15        # seconds between on-demand evaluations of the same uncached symbol

_universe_cache = {"at": 0.0, "symbols": []}


def universe() -> list[str]:
    """Nifty 50 symbols, cached 6 h: validation runs on every call and must not hit NSE each time."""
    if time.time() - _universe_cache["at"] > 6 * 3600 or not _universe_cache["symbols"]:
        _universe_cache.update(at=time.time(), symbols=risk_rules.get_universe())
    return _universe_cache["symbols"]


HEAVY_FIELDS = ("history", "chain", "sr_zones")
screen = ScreenReader()


def _ist_today() -> str:
    return (pd.Timestamp.now("UTC").tz_localize(None) + pd.Timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def _with_events(c: dict, events: list[dict], today: str, after: str | None = None) -> dict:
    """Adds the stock's corporate events from today (or after `after`) through this row's expiry."""
    if c.get("symbol"):
        c["events"] = market_calendar.events_until(events, c["symbol"], today, c.get("expiry"), after)
    return c


def _prev_expiries(rows: list[dict]) -> dict[tuple[str, str], str | None]:
    """(symbol, expiry) -> that stock's previous screened expiry. The screener badges each event only
    on the cycle it falls in: results on 9 Oct show on the Oct row, not again on Nov and Dec."""
    by_symbol: dict[str, list[str]] = {}
    for c in rows:
        if c.get("symbol") and c.get("expiry"):
            by_symbol.setdefault(c["symbol"], []).append(c["expiry"])
    out = {}
    for sym, exps in by_symbol.items():
        exps = sorted(set(exps))
        out.update({(sym, x): (exps[i - 1] if i else None) for i, x in enumerate(exps)})
    return out


def _light(c: dict) -> dict:
    """List-view row: drops the heavy fields but keeps the few numbers the screener row draws."""
    out = {k: v for k, v in c.items() if k not in HEAVY_FIELDS}
    spot, hist = c.get("spot"), c.get("history") or []
    if spot and hist:
        # yfinance includes today's candle after the close; the previous session is the one before it.
        today = _ist_today()
        prev = hist[-2] if len(hist) > 1 and hist[-1]["date"] == today else hist[-1]
        out["prev_close"] = prev["close"]
    chain = c.get("chain") or []
    if spot and chain:
        atm = min(chain, key=lambda r: abs(r["strikePrice"] - spot))
        ivs = [v for v in (atm.get("CE_IV"), atm.get("PE_IV")) if v]
        out["atm_iv"] = round(sum(ivs) / len(ivs), 1) if ivs else None
    if spot:
        out["sr_near"] = [
            {"level": z["level"], "type": z["type"]}
            for z in c.get("sr_zones") or [] if abs(z["level"] - spot) / spot < 0.2
        ]
    return out


def get_screened_candidates(force_refresh: bool = False):
    """Returns the cached screen instantly. Never waits on NSE: the refresher thread keeps it fresh.
    force_refresh only asks for an early background refresh; the cached rows are still returned."""
    throttled = 0
    state = screen.state
    if force_refresh:
        if throttle.allow("force_screen", FORCE_SCREEN_EVERY):
            screen.request_refresh()
        else:
            throttled = throttle.wait_left("force_screen", FORCE_SCREEN_EVERY)
    finished = state["finished_at"]
    events, today = market_calendar.load()["events"], _ist_today()
    rows = screen.snapshot()
    prev = _prev_expiries(rows)
    return {
        "candidates": [_with_events(_light(c), events, today, prev.get((c.get("symbol"), c.get("expiry"))))
                       for c in rows],
        "generated_at": finished,
        "refreshing": state["running"],
        "next_refresh_at": next_screen_at(finished) if finished else None,
        "span_source": state["span_source"],
        "progress": {k: state.get(k) for k in ("running", "done", "total", "batch", "batches", "pass", "passes", "error")},
        "refresh_throttled_s": throttled,
    }


def get_trade_detail(symbol: str, expiry: str | None = None):
    """One stock's full screen row for `expiry` (YYYY-MM-DD). Without it, or once that cycle has
    rolled off the screen, the nearest cycle at least MIN_DTE days out."""
    events, today = market_calendar.load()["events"], _ist_today()
    found = screen.get(symbol, expiry)
    if found:
        return _with_events(dict(found), events, today)
    # Not screened yet (first screen still in flight): evaluate this one stock on demand, rate-limited.
    if not throttle.allow(f"detail:{symbol}", DETAIL_EVAL_EVERY):
        raise ValueError(f"{symbol} is still being screened; try again in a few seconds")
    span.load(universe())
    row = risk_rules.pick_cycle(risk_rules.safe_evaluate_cycles(symbol), expiry)
    return _with_events(dict(row), events, today) if row else row


def get_market_calendar():
    """NSE trading holidays and Nifty 50 corporate events, from the worker's daily copy, plus the
    expiry dates the last screen covered (the calendar groups events by expiry cycle)."""
    data = market_calendar.load()
    today = _ist_today()
    expiries = sorted({c["expiry"] for c in screen.snapshot() if c.get("expiry") and c["expiry"] >= today})
    return {
        "holidays": data["holidays"],
        "events": [{**e, "days_away": (pd.Timestamp(e["date"]) - pd.Timestamp(today)).days,
                    "risky": e["type"] in market_calendar.RISKY} for e in data["events"] if e["date"] >= today],
        "fetched_at": data["fetched_at"],
        "errors": data["errors"],
        "expiries": expiries,
        "today": today,
    }


def va_refresh_positions(user_id: int):
    """Re-price now, at most every REPRICE_EVERY seconds per user; otherwise the cached snapshot."""
    if throttle.allow(f"reprice:{user_id}", REPRICE_EVERY):
        return virtual.refresh_positions(user_id)
    return virtual.cached_positions(user_id)


def get_config():
    return {
        "pcr_range": [config.PCR_MIN, config.PCR_MAX],
        "min_dte": config.MIN_DTE,
        "screen_dte_range": [config.SCREEN_DTE_FLOOR, config.SCREEN_DTE_CEIL],
        "delta_max_abs": config.DELTA_MAX_ABS,
        "sl_grace_days": config.SL_GRACE_DAYS,
        "time_exit_dte": config.TIME_EXIT_DTE,
        "sr_lookback_days": config.SR_LOOKBACK_DAYS,
        "sr_zone_width_pct": config.SR_ZONE_WIDTH_PCT,
        "exposure_min_pct": config.EXPOSURE_MIN_PCT,
        "universe": universe(),
    }


def calc_margin(symbol: str, expiry: str, legs: list, lots: int = 1):
    """SPAN + exposure for SHORT legs [{side, strike}] at `lots` lots, ignoring existing positions."""
    lot = data_fetch.fetch_lot_size(symbol, pd.Timestamp(expiry))
    if not lot:
        raise ValueError(f"Lot size for {symbol} {expiry} not found")
    spot = virtual.quote(symbol, expiry, legs[0]["side"], float(legs[0]["strike"]))["spot"]
    signed = [{"side": l["side"], "strike": float(l["strike"]), "qty": -lot * int(lots)} for l in legs]
    return {**virtual.group_margin(symbol, expiry, signed, spot), "lot_size": lot}


def va_get_positions(user_id: int):
    """Cached snapshot, re-priced by the monitor thread; never waits on NSE."""
    return virtual.cached_positions(user_id)


def _then_refresh(fn):
    """Account-changing calls re-price the snapshot right away, so the next read shows the change."""
    @functools.wraps(fn)  # keeps fn's signature visible to rpc_guard.validate
    def wrapped(user_id, **kw):
        result = fn(user_id, **kw)
        # The change is committed. A failed re-price (NSE slow or down) must not turn that into an
        # error, or the user retries and trades twice; the monitor re-prices within a minute anyway.
        try:
            virtual.refresh_positions(user_id)
        except Exception:
            log.warning("re-price after %s failed for user %s", fn.__name__, user_id, exc_info=True)
        return result
    return wrapped


def va_autotrade_run_now(user_id: int):
    """Runs auto-trade on the current screen. Refuses while a screen is still in progress."""
    state = screen.state
    if state["running"] or not state["finished_at"]:
        raise ValueError("The screen is still running; try again when it finishes")
    result = autotrade.run(user_id, screen.snapshot(), trigger="manual")
    virtual.refresh_positions(user_id)
    return result


# ---------- request context and auth methods ----------

COOKIE = os.environ.get("SESSION_COOKIE", "__Host-theta")
# A random id per browser, kept 2 years. It grants no access; it lets sign-up spot a browser
# that already has an account. Only its SHA-256 is stored.
DEVICE_COOKIE = os.environ.get("DEVICE_COOKIE", "__Host-theta-dev")
DEVICE_DAYS = 730
# Origins allowed to call /rpc. The dev frontend proxies /rpc, so the page and API share one origin.
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()}


class Ctx:
    """What the server knows about the caller. Never built from client params."""

    def __init__(self):
        self.token = request.cookies.get(COOKIE)
        self.ip = request.remote_addr  # behind Caddy: ProxyFix sets this from X-Forwarded-For (phase 5)
        self.ua = request.headers.get("User-Agent")
        self.user = auth.active_user(auth.session_user(self.token))
        raw = request.cookies.get(DEVICE_COOKIE)
        self.new_device = None if raw and 20 <= len(raw) <= 64 else secrets.token_urlsafe(24)
        self.device = auth._hash(raw if self.new_device is None else self.new_device)
        self.set_cookie: str | None = None
        self.clear_cookie = False

    @property
    def user_id(self) -> int | None:
        return self.user["id"] if self.user else None


def auth_register(_ctx: Ctx, name: str, email: str, password: str):
    return auth.register(name, email, password, ip=_ctx.ip, device=_ctx.device)


def auth_login(_ctx: Ctx, email: str, password: str):
    token, user = auth.login(email, password, ip=_ctx.ip, ua=_ctx.ua, device=_ctx.device)
    auth.end_session(_ctx.token)  # a fresh token on every sign-in: no session fixation
    _ctx.set_cookie = token
    return user


def auth_verify_email(_ctx: Ctx, email: str, code: str):
    return auth.verify_email(email, code, ip=_ctx.ip)


def auth_resend_code(_ctx: Ctx, email: str):
    return auth.resend_code(email, ip=_ctx.ip)


def auth_forgot_password(_ctx: Ctx, email: str):
    return auth.request_password_reset(email, ip=_ctx.ip)


def auth_reset_password(_ctx: Ctx, token: str, new_password: str):
    return auth.confirm_password_reset(token, new_password, ip=_ctx.ip)


def auth_me(_ctx: Ctx):
    return auth.me(_ctx.user_id) if _ctx.user else None


def auth_logout(_ctx: Ctx):
    if _ctx.user:
        auth.audit("logout", actor_id=_ctx.user_id, target_user_id=_ctx.user_id, ip=_ctx.ip)
    auth.end_session(_ctx.token)
    _ctx.clear_cookie = True
    return {"ok": True}


def auth_change_password(_ctx: Ctx, current_password: str, new_password: str):
    return auth.change_password(_ctx.user_id, current_password, new_password, _ctx.token, ip=_ctx.ip)


def prefs_set(_ctx: Ctx, theme: str | None = None, palette: str | None = None):
    return auth.set_prefs(_ctx.user_id, theme, palette)


def admin_list_users(_ctx: Ctx):
    return auth.list_users()


def admin_set_status(_ctx: Ctx, target_id: int, status: str):
    return auth.set_status(_ctx.user_id, target_id, status, ip=_ctx.ip)


def admin_list_blocked(_ctx: Ctx):
    return auth.list_blocked()


def admin_unblock_signup(_ctx: Ctx, target_id: int):
    return auth.unblock_signup(_ctx.user_id, target_id, ip=_ctx.ip)


def admin_reset_password(_ctx: Ctx, target_id: int):
    return auth.reset_password(_ctx.user_id, target_id, ip=_ctx.ip)


def admin_audit_log(_ctx: Ctx, limit: int = 100):
    with db.tx() as c:
        return c.all("SELECT l.id, l.ts, l.action, host(l.ip) AS ip, l.detail, a.email AS actor, t.email AS target "
                     "FROM audit_log l LEFT JOIN users a ON a.id = l.actor_id "
                     "LEFT JOIN users t ON t.id = l.target_user_id ORDER BY l.id DESC LIMIT :n", n=limit)


# ---------- real broker (phase 1: Zerodha, admin-only soft launch) ----------
# Only Zerodha is connectable right now, so the broker name isn't a client-supplied param yet;
# a second broker later adds it back once there's a real choice to make.


def broker_connect_url(_ctx: Ctx):
    return broker.connect_url(_ctx.user_id)


def broker_exchange_token(_ctx: Ctx, request_token: str, state: str):
    return broker.exchange_token(_ctx.user_id, request_token, state)


# ---------- method tables ----------
# Who may call what:
#   PUBLIC   anyone; the handler gets the request context
#   ACCOUNT  signed in; context (needs the session token or the user)
#   METHODS  signed in; shared market data, same answer for every user
#   USER     signed in; first argument is the acting user's id, supplied by the server.
#            rpc_guard refuses a client-sent `user_id`, so no request can act for someone else.
#   ADMIN    signed in with the admin role; context

PUBLIC_METHODS = {"auth_register": auth_register, "auth_login": auth_login, "auth_me": auth_me,
                  "auth_verify_email": auth_verify_email, "auth_resend_code": auth_resend_code,
                  "auth_forgot_password": auth_forgot_password, "auth_reset_password": auth_reset_password}

ACCOUNT_METHODS = {"auth_logout": auth_logout, "auth_change_password": auth_change_password, "prefs_set": prefs_set}

METHODS = {
    "get_screened_candidates": get_screened_candidates,
    "get_trade_detail": get_trade_detail,
    "get_config": get_config,
    "get_market_calendar": get_market_calendar,
    "calc_margin": calc_margin,
}

USER_METHODS = {
    # Virtual trading
    "va_get_account": virtual.cached_account,
    "va_refresh_positions": va_refresh_positions,
    "va_get_positions": va_get_positions,
    "va_get_orders": virtual.get_orders,
    "va_get_closed": virtual.get_closed,
    "va_get_open_orders": virtual.get_open_orders,
    "va_price_levels": virtual.price_levels,
    "va_cancel_order": _then_refresh(virtual.cancel_order),
    "va_modify_order": _then_refresh(virtual.modify_order),
    "va_preview_order": virtual.preview_order,
    "va_place_order": _then_refresh(virtual.place_order),
    "va_exit_position": _then_refresh(virtual.exit_position),
    "va_exit_group": _then_refresh(virtual.exit_group),
    "va_set_sl_mode": _then_refresh(virtual.set_sl_mode),
    "va_dismiss_alert": _then_refresh(virtual.dismiss_alert),
    "va_reset": _then_refresh(virtual.reset),
    # Auto-trade (virtual account only)
    "va_get_autotrade": autotrade.get_settings,
    "va_set_autotrade": autotrade.set_settings,
    "va_autotrade_runs": autotrade.get_runs,
    "va_autotrade_run_now": va_autotrade_run_now,
    # Real broker (phase 1: Zerodha). Connecting itself is admin-only (ADMIN_METHODS below); once
    # connected, these are the acting user's own methods same as the va_* ones above.
    "broker_status": broker.status,
    "broker_disconnect": broker.disconnect,
    "broker_get_positions": broker.get_positions,
    "broker_get_margins": broker.get_margins,
    "broker_account_summary": broker.account_summary,
    "broker_preview_order": broker.preview_order,
    "broker_place_order": broker.place_order,
    "broker_stop_alerts": broker.stop_alerts,
}

ADMIN_METHODS = {
    "admin_list_users": admin_list_users,
    "admin_set_status": admin_set_status,
    "admin_reset_password": admin_reset_password,
    "admin_audit_log": admin_audit_log,
    "admin_list_blocked": admin_list_blocked,
    "admin_unblock_signup": admin_unblock_signup,
    # Real-money connection, soft-launched to admins only; see doc/2026-09-26-broker-integration-phase1-zerodha.md
    "broker_connect_url": broker_connect_url,
    "broker_exchange_token": broker_exchange_token,
}

# Methods whose `symbol` may be outside the current Nifty 50 (they only act on existing positions).
ANY_SYMBOL = {"va_exit_group", "va_price_levels"}

# With a temporary password, only these work until it is changed.
WHILE_MUST_CHANGE = {"auth_me", "auth_logout", "auth_change_password"}

TABLES = [(PUBLIC_METHODS, "public"), (ACCOUNT_METHODS, "account"), (METHODS, "shared"),
          (USER_METHODS, "user"), (ADMIN_METHODS, "admin")]
_names = [n for t, _ in TABLES for n in t]
assert len(_names) == len(set(_names)), "an RPC name appears in two tables"

NOT_SIGNED_IN, FORBIDDEN, MUST_CHANGE, UNVERIFIED = -32001, -32003, -32004, -32005


def _error(req_id, code, message, status=200):
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}), status


# Errors raised on purpose with a message meant for the user (insufficient margin, strike not in
# chain, stale screen, wrong password). Anything else is a bug or an upstream failure and stays
# in the server log.
USER_ERRORS = (ValueError, TimeoutError)
# NSE or another data source failed or changed shape: not a bug here, and worth telling the user.
UPSTREAM_ERRORS = (requests.RequestException, data_fetch.NseSchemaError)
UPSTREAM_MESSAGE = "Market data from NSE isn't available right now. Try again in a minute"


def _internal(req_id, what: str):
    """Logs the traceback under a short reference and returns a generic error carrying it."""
    ref = secrets.token_hex(3)
    log.error("%s failed (ref %s): %s", what, ref, traceback.format_exc())
    return _error(req_id, -32603, f"Something went wrong on the server (ref {ref})")


@app.errorhandler(HTTPException)
def http_error(e: HTTPException):
    """404, 405, 413 and the rest as JSON-RPC errors, not Flask's HTML pages."""
    return _error(None, -32600, e.description or e.name, e.code or 500)


@app.errorhandler(Exception)
def unhandled_error(e: Exception):
    return _internal(None, f"{request.method} {request.path}")[0], 500


@app.after_request
def security_headers(resp):
    # Caddy adds these too in production (phase 5); set here so the API is safe on its own.
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/healthz")
def healthz():
    """For the container health check: Postgres answers, Redis answers, a worker is alive."""
    checks = {"postgres": False, "redis": cache.up(), "worker": cache.exists(HEARTBEAT)}
    try:
        with db.tx() as c:
            checks["postgres"] = c.value("SELECT 1") == 1
    except Exception:
        pass
    # The API can serve without Redis or a worker (cached screen, live pricing), not without Postgres.
    return jsonify(checks), (200 if checks["postgres"] else 503)


def _finite(v):
    """Python's JSON writes NaN/Infinity, which browsers refuse to parse: the whole reply then fails
    with a bare 200. Live chains have gaps (no IV, no bid), so turn those into null."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_finite(x) for x in v]
    return v


@app.post("/rpc")
def rpc():
    # CSRF: browsers always send Origin on a cross-site POST; only our own page may call.
    if request.headers.get("Origin") not in ALLOWED_ORIGINS:
        return _error(None, FORBIDDEN, "Requests from this origin are not allowed", 403)
    if request.mimetype != "application/json":
        return _error(None, -32600, "Invalid Request", 415)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return _error(None, -32600, "Invalid Request")

    req_id = body.get("id")
    name = body["method"]
    found = next(((t[name], kind) for t, kind in TABLES if name in t), None)
    if found is None:
        return _error(req_id, -32601, "Method not found")
    method, kind = found

    try:
        ctx = Ctx()
    except Exception:
        return _internal(req_id, "session lookup")
    if kind != "public":
        if not ctx.user:
            return _error(req_id, NOT_SIGNED_IN, "Sign in to continue")
        if ctx.user["must_change_password"] and name not in WHILE_MUST_CHANGE:
            return _error(req_id, MUST_CHANGE, "Set a new password to continue")
        if kind == "admin" and ctx.user["role"] != "admin":
            return _error(req_id, FORBIDDEN, "Admins only")

    try:
        # Closing what you hold never depends on today's index list: a stock that left the Nifty 50
        # at a rebalance must still be exitable. The ticker shape is checked either way.
        params = validate(method, body.get("params"), universe=None if name in ANY_SYMBOL else universe)
    except InvalidParams as e:
        return _error(req_id, -32602, f"Invalid params: {e}")
    except Exception:  # e.g. the Nifty 50 list couldn't be loaded; never an HTML 500
        return _internal(req_id, f"validating rpc {name}")

    try:
        if kind == "user":
            result = method(ctx.user_id, **params)
        elif kind == "shared":
            result = method(**params)
        else:
            result = method(ctx, **params)
    except UPSTREAM_ERRORS:  # before USER_ERRORS: requests' JSON decode error is a ValueError
        log.warning("rpc %s: upstream data failed", name, exc_info=True)
        return _error(req_id, -32000, UPSTREAM_MESSAGE)
    except auth.EmailUnverified as e:  # the client swaps to the code form
        return _error(req_id, UNVERIFIED, str(e))
    except USER_ERRORS as e:
        return _error(req_id, -32000, str(e))
    except Exception:
        return _internal(req_id, f"rpc {name}")

    resp = jsonify({"jsonrpc": "2.0", "id": req_id, "result": _finite(result)})
    secure = COOKIE.startswith("__Host-") or os.environ.get("COOKIE_SECURE", "1") == "1"
    if ctx.set_cookie:
        resp.set_cookie(COOKIE, ctx.set_cookie, max_age=auth.SESSION_CAP_DAYS * 86400, path="/",
                        secure=secure, httponly=True, samesite="Lax")
    elif ctx.clear_cookie:
        resp.delete_cookie(COOKIE, path="/", secure=secure, httponly=True, samesite="Lax")
    if ctx.new_device:  # kept after sign-out, so the browser is still recognised at sign-up
        resp.set_cookie(DEVICE_COOKIE, ctx.new_device, max_age=DEVICE_DAYS * 86400, path="/",
                        secure=secure, httponly=True, samesite="Lax")
    return resp


def wait_for_postgres(timeout: float = 30.0, poll: float = 1.0) -> bool:
    """Server startup can race with the dev containers coming up. Retry briefly and keep the API
    process alive so local developers can start it before the database is ready."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with db.tx() as c:
                c.value("SELECT 1")
            return True
        except Exception:
            time.sleep(poll)
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not wait_for_postgres(timeout=float(os.environ.get("DB_STARTUP_TIMEOUT", "30"))):
        log.warning("Postgres is still unavailable; continuing in degraded mode until it comes online")
    try:
        users.bootstrap_local_user()
    except Exception:
        log.warning("bootstrap_local_user() failed; app will keep running in degraded mode until Postgres is reachable",
                    exc_info=True)
    app.run(host="127.0.0.1", port=8000, debug=False, threaded=True)
