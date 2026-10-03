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
from flask import Flask, Response, abort, jsonify, request
from markupsafe import escape
from werkzeug.exceptions import HTTPException

from engine import app_settings, auth, autotrade, brand, broker, builder, cache, capital, cards, coins, cohort, config, habits, rms, data_fetch, db, leaderboard, lessons, market_calendar, permissions, pricing, progress, risk_rules, span, strategies, users, virtual
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


def builder_chain(symbol: str, expiry: str | None = None):
    """Strategy builder (#137): one stock's option chain for `expiry` (YYYY-MM-DD; default the
    first at least 30 days out) with deltas, lot size, the open expiries, results/dividend dates
    before expiry and the rules the page warns about. Shares the 60 s quote cache with orders."""
    return builder.chain(symbol, expiry)


def builder_levels(symbol: str):
    """Strategy builder: last month's floor pivots (P, R1-R4, S1-S4) and the swing support and
    resistance zones for one Nifty 50 stock, drawn on the payoff chart and used by the rule checks."""
    return builder.levels(symbol)


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
    """The screening thresholds the UI shows (engine/config.py) and the current Nifty 50 list."""
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


def auth_register(_ctx: Ctx, name: str, email: str, password: str, ref: str | None = None):
    """Requests an account and emails a 6-digit code to confirm the address; once confirmed, the
    account waits for admin approval. At most SIGNUPS_PER_IP sign-ups per hour from one IP.
    `ref` is an invite code from a referral link; an unknown one is ignored."""
    return auth.register(name, email, password, ip=_ctx.ip, device=_ctx.device, ref=ref)


def auth_login(_ctx: Ctx, email: str, password: str):
    """Signs in and sets the session cookie, with a new token every time. An unconfirmed account gets
    error -32005 and a fresh code. Wrong passwords are limited per email and IP (FAILS_PER_PAIR) and
    per IP (FAILS_PER_IP) within FAIL_WINDOW."""
    token, user = auth.login(email, password, ip=_ctx.ip, ua=_ctx.ua, device=_ctx.device)
    auth.end_session(_ctx.token)  # a fresh token on every sign-in: no session fixation
    _ctx.set_cookie = token
    return user


def auth_verify_email(_ctx: Ctx, email: str, code: str):
    """Confirms the sign-up email with the emailed code (spaces are ignored). CODE_TRIES guesses per
    code and VERIFY_PER_IP checks per IP in 15 minutes. An unknown email gets the same answer as a wrong code.
    With the owner's auto_approve setting on, the account becomes active and is signed in
    (`signed_in: true` and `user` in the answer); otherwise it waits for approval."""
    token, answer = auth.verify_email(email, code, ip=_ctx.ip, ua=_ctx.ua, device=_ctx.device)
    if token:  # auto-approved (#121): signed in straight away, with a fresh token
        auth.end_session(_ctx.token)
        _ctx.set_cookie = token
    return answer


def auth_resend_code(_ctx: Ctx, email: str):
    """Emails a new sign-up code: at most one per RESEND_GAP and CODES_PER_DAY a day. The answer is
    the same for an unknown email."""
    return auth.resend_code(email, ip=_ctx.ip)


def auth_forgot_password(_ctx: Ctx, email: str):
    """Emails a password-reset link valid for RESET_TTL. The answer is the same whether or not the
    email has an active account. One email per RESET_GAP per account, RESET_PER_IP requests per hour per IP."""
    return auth.request_password_reset(email, ip=_ctx.ip)


def auth_reset_password(_ctx: Ctx, token: str, new_password: str):
    """Sets a new password from the emailed reset token. The token works once, and every session of
    the account is ended."""
    return auth.confirm_password_reset(token, new_password, ip=_ctx.ip)


def lessons_list(_ctx: Ctx):
    """Every lesson in the learning path (title, level, order, summary, minutes, question count).
    Public while the owner keeps Learn on for readers, so lesson pages can be read and shared."""
    app_settings.require_reader(_ctx.user, "learn")
    return lessons.list_lessons()


def lessons_get(_ctx: Ctx, slug: str):
    """One lesson's body and quiz questions (never the answers), plus the previous and next
    lesson. Public while Learn is on for readers."""
    app_settings.require_reader(_ctx.user, "learn")
    return lessons.get_lesson(slug)


def app_info(_ctx: Ctx):
    """The app's name and logo version (null while the built-in mark is used), and the pages a
    signed-out visitor may open (`reader_pages`) and NSE trading holidays (`holidays`, ISO dates).
    Public; every page loads it."""
    return {**brand.info(), "reader_pages": app_settings.reader_pages(),
            "auto_approve": app_settings.get("auto_approve"),  # sign-up copy: instant or waits for approval
            "holidays": sorted(pricing.holidays())}  # NSE trading holidays, for the market clock


# Reader (#163): the builder for signed-out visitors. Every new stock/expiry is an NSE call from the
# server's IP, so each visitor IP is limited to one chain or levels load per READER_EVERY seconds.
READER_EVERY = 2.0


def _reader_builder(ctx: Ctx, what: str) -> None:
    app_settings.require_reader(ctx.user, "builder")
    if not ctx.user and not throttle.allow(f"reader:{what}:{ctx.ip}", READER_EVERY):
        raise ValueError("Too many requests: wait a moment and try again")


def levels_overview(_ctx: Ctx):
    """The 10 levels: title, minimum days, the capital reward for reaching it and the features it
    unlocks (labels). Level floors (config.LEVEL_MIN, e.g. the coin store) are listed only while the
    owner has the feature on for ordinary users. Public while Progress is on for readers; signed-out
    visitors see it in place of their own progress."""
    app_settings.require_reader(_ctx.user, "progress")
    on = set(permissions.features_for("user"))
    floors = {lv: [f for f, m in config.LEVEL_MIN.items() if m == lv and f in on] for lv in config.LEVEL_TITLES}
    return [{"level": lv, "title": t, "min_days": config.LEVEL_MIN_DAYS.get(lv), "capital": config.LEVEL_CAPITAL.get(lv),
             "unlocks": [permissions.LEVEL_LABELS.get(f, permissions.FEATURES[f])
                         for f in (*config.LEVEL_FEATURES.get(lv, ()), *floors[lv]) if f in permissions.FEATURES]}
            for lv, t in config.LEVEL_TITLES.items()]


def reader_universe(_ctx: Ctx):
    """The Nifty 50 symbols the builder offers. Public while the builder is on for readers."""
    app_settings.require_reader(_ctx.user, "builder")
    return universe()


def reader_chain(_ctx: Ctx, symbol: str, expiry: str | None = None):
    """builder_chain for signed-out visitors (same result); rate-limited per IP."""
    _reader_builder(_ctx, "chain")
    return builder.chain(symbol, expiry)


def reader_levels(_ctx: Ctx, symbol: str):
    """builder_levels for signed-out visitors (same result); rate-limited per IP."""
    _reader_builder(_ctx, "levels")
    return builder.levels(symbol)


def leaderboard_get(_ctx: Ctx, month: str | None = None):
    """Paper-trading leaderboard (no sign-in needed). `month` is a period: "YYYY-MM" for a month or
    "YYYY-Qn" for a calendar quarter; omitted, it is the running month, marked provisional. Nicknames, levels and ratios only, never personal data.
    Each ranked row carries its level's badges (Mentor from 7, Master from 9); `hall_of_fame` lists
    opted-in Level 10 players with the date they got there.
    Signed out, only while the owner keeps the leaderboard on for readers."""
    app_settings.require_reader(_ctx.user, "leaderboard")
    return leaderboard.get(month)


def auth_me(_ctx: Ctx):
    """The signed-in user with their saved theme and palette, or null when signed out. `sell_levels`
    gives the level naked sales and strangles unlock at, or null when the strategy gate doesn't apply."""
    return auth.me(_ctx.user_id) if _ctx.user else None


def auth_logout(_ctx: Ctx):
    """Ends this session and clears the session cookie."""
    if _ctx.user:
        auth.audit("logout", actor_id=_ctx.user_id, target_user_id=_ctx.user_id, ip=_ctx.ip)
    auth.end_session(_ctx.token)
    _ctx.clear_cookie = True
    return {"ok": True}


def auth_change_password(_ctx: Ctx, current_password: str, new_password: str):
    """Changes the password and clears the temporary-password flag. Other sessions are signed out;
    this one stays."""
    return auth.change_password(_ctx.user_id, current_password, new_password, _ctx.token, ip=_ctx.ip)


def profile_set(_ctx: Ctx, nickname: str | None = None, leaderboard_opt_in: bool | None = None):
    """Sets the public nickname (3-20 letters, digits or _, unique) and/or leaderboard opt-in; an
    omitted field keeps its value. Returns the signed-in user."""
    return auth.set_profile(_ctx.user_id, nickname, leaderboard_opt_in)


def admin_get_overrides(_ctx: Ctx, target_id: int):
    """Owner only: one account's per-user feature overrides (grant or deny)."""
    return permissions.overrides(target_id)


def admin_set_override(_ctx: Ctx, target_id: int, feature: str, mode: str, months: int | None = None):
    """Owner only: grant or deny one feature for one account, or `clear` to go back to its role and
    level. A grant with `months` (1-12) lapses on its own. Audited; applies on that user's next request."""
    return permissions.set_override(_ctx.user_id, target_id, feature, mode, ip=_ctx.ip, months=months)


def admin_get_settings(_ctx: Ctx):
    """Owner only: the app switches (such as auto_approve) with their values and descriptions."""
    return app_settings.all_settings()


def admin_set_setting(_ctx: Ctx, key: str, value: bool):
    """Owner only: changes one app switch. Audited; applies at once."""
    return app_settings.set_value(_ctx.user_id, key, value, ip=_ctx.ip)


def admin_set_brand_name(_ctx: Ctx, name: str):
    """Owner only: renames the app everywhere it is shown (pages, emails, share cards). Audited."""
    was = brand.name()
    value = brand.set_name(_ctx.user_id, name)
    auth.audit("brand_changed", actor_id=_ctx.user_id, ip=_ctx.ip, field="name", was=was, value=value)
    return brand.info()


def admin_reset_logo(_ctx: Ctx):
    """Owner only: drops the uploaded logo and favicon and goes back to the built-in ones. Audited.
    Uploading a logo is POST /brand/logo (see doc/api/README.md)."""
    brand.reset_logo()
    auth.audit("brand_changed", actor_id=_ctx.user_id, ip=_ctx.ip, field="logo", value=None)
    return brand.info()


def prefs_set(_ctx: Ctx, theme: str | None = None, palette: str | None = None, email_nudges: bool | None = None):
    """Saves the theme (light or dark), colour palette and/or the day-before email nudges (on or
    off) to the account; an omitted field keeps its value. Returns the saved prefs."""
    return auth.set_prefs(_ctx.user_id, theme, palette, email_nudges)


def admin_list_users(_ctx: Ctx):
    """Every account past email confirmation, waiting requests first. Each lists the other accounts
    that share its browser or network, its level, and `live_eligible` from Level 8 (a tag for the
    owner's decision; it never grants real trading)."""
    rows = auth.list_users()
    # The owner's Level 10 sign-off (#146): flag who is waiting for it.
    for r in rows:
        r["final_ready"] = r["status"] == "active" and progress.final_ready(r["id"])
    return rows


def admin_approve_final(_ctx: Ctx, target_id: int):
    """Owner only: signs off the Level 10 final assessment for a Level 9 user who has passed every
    other check, which moves them up at once. Audited."""
    return progress.approve_final(_ctx.user_id, target_id, ip=_ctx.ip)


def admin_user_grants(_ctx: Ctx, target_id: int):
    """Owner only: every capital grant an account has earned, with whether each is revoked or can
    be (#194)."""
    return capital.admin_grants(target_id)


def admin_revoke_grant(_ctx: Ctx, target_id: int, grant_id: int, reason: str):
    """Owner only: takes one capital grant back, for example after abuse. The task can't be paid
    again, the amount comes off the account's capital, and the revoke is audited with the reason.
    A coin exchange can't be revoked."""
    return capital.revoke(_ctx.user_id, target_id, grant_id, reason, ip=_ctx.ip)


def admin_set_status(_ctx: Ctx, target_id: int, status: str):
    """Approves (active), rejects or disables an account. Any status but active signs the user out
    everywhere. Refused for the caller's own account."""
    return auth.set_status(_ctx.user_id, target_id, status, ip=_ctx.ip)


def admin_list_blocked(_ctx: Ctx):
    """Sign-ups not confirmed within CONFIRM_DAYS, newest first."""
    return auth.list_blocked()


def admin_unblock_signup(_ctx: Ctx, target_id: int):
    """Gives a blocked sign-up a fresh CONFIRM_DAYS and emails a new code. `sent` is false when the
    email failed. The person still confirms the email, then waits for approval."""
    return auth.unblock_signup(_ctx.user_id, target_id, ip=_ctx.ip)


def admin_reset_password(_ctx: Ctx, target_id: int):
    """Issues a one-time temporary password, returned once. The user is signed out everywhere and
    must set a new password on their next sign-in."""
    return auth.reset_password(_ctx.user_id, target_id, ip=_ctx.ip)


def admin_set_role(_ctx: Ctx, target_id: int, role: str):
    """Changes an account's role to sub_admin, beta or user. Only the owner grants or removes
    sub-admin; others move lower-ranked accounts between beta and user. Nobody can be made owner."""
    return auth.set_role(_ctx.user_id, target_id, role, ip=_ctx.ip)


def admin_get_features(_ctx: Ctx):
    """Owner only: which features each role (sub_admin, beta, user) has, and the feature list."""
    return permissions.matrix()


def admin_set_feature(_ctx: Ctx, role: str, feature: str, enabled: bool):
    """Owner only: turns one feature on or off for a role. Applies on the role's next request."""
    return permissions.set_feature(_ctx.user_id, role, feature, enabled, ip=_ctx.ip)


def admin_audit_log(_ctx: Ctx, limit: int = 100):
    """The newest `limit` audit events (sign-ins, admin actions, broker events) with actor, target
    account and IP."""
    with db.tx() as c:
        return c.all("SELECT l.id, l.ts, l.action, host(l.ip) AS ip, l.detail, a.email AS actor, t.email AS target "
                     "FROM audit_log l LEFT JOIN users a ON a.id = l.actor_id "
                     "LEFT JOIN users t ON t.id = l.target_user_id ORDER BY l.id DESC LIMIT :n", n=limit)


# ---------- real broker (phase 1: Zerodha; roles with live_trading, owner-only by default) ----------
# Only Zerodha is connectable right now, so the broker name isn't a client-supplied param yet;
# a second broker later adds it back once there's a real choice to make.


def broker_connect_url(user_id: int):
    """Starts connecting the caller's Zerodha account: the Kite login URL and a one-time `state` to
    pass back to broker_exchange_token. Needs the live_trading feature."""
    return broker.connect_url(user_id)


def broker_exchange_token(user_id: int, request_token: str, state: str):
    """Finishes connecting Zerodha: swaps Kite's one-time request_token for an access token, stored
    encrypted. `state` must be the one broker_connect_url returned. One active connection per user.
    Needs the live_trading feature."""
    return broker.exchange_token(user_id, request_token, state)


# ---------- method tables ----------
# Who may call what:
#   PUBLIC   anyone; the handler gets the request context
#   ACCOUNT  signed in; context (needs the session token or the user)
#   METHODS  signed in; shared market data, same answer for every user
#   USER     signed in; first argument is the acting user's id, supplied by the server.
#            rpc_guard refuses a client-sent `user_id`, so no request can act for someone else.
#   ADMIN    signed in with the feature REQUIRES names for it; context
#
# REQUIRES maps a method to the feature (engine/permissions.py) its caller's role must have, or
# "owner". Every ADMIN method must be listed. Checked on every call, so a toggle applies at once.

PUBLIC_METHODS = {"auth_register": auth_register, "auth_login": auth_login, "auth_me": auth_me,
                  "auth_verify_email": auth_verify_email, "auth_resend_code": auth_resend_code,
                  "auth_forgot_password": auth_forgot_password, "auth_reset_password": auth_reset_password,
                  "lessons_list": lessons_list, "lessons_get": lessons_get, "app_info": app_info,
                  "leaderboard_get": leaderboard_get, "reader_universe": reader_universe,
                  "reader_chain": reader_chain, "reader_levels": reader_levels, "levels_overview": levels_overview}

ACCOUNT_METHODS = {"auth_logout": auth_logout, "auth_change_password": auth_change_password, "prefs_set": prefs_set,
                   "profile_set": profile_set}

METHODS = {
    "get_screened_candidates": get_screened_candidates,
    "get_trade_detail": get_trade_detail,
    "get_config": get_config,
    "get_market_calendar": get_market_calendar,
    "calc_margin": calc_margin,
    "builder_chain": builder_chain,
    "builder_levels": builder_levels,
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
    # Learning path: quizzes need an account (answers are checked server-side).
    "lesson_submit_quiz": lessons.submit_quiz,
    "lesson_progress": lessons.progress,
    "progress_get": progress.evaluate,
    "progress_history": progress.history,
    "capital_status": capital.status,
    "coins_status": coins.status,
    "habits_get": habits.get,
    "season_titles": leaderboard.titles,
    "cohort_get": cohort.get,
    "payout_news": capital.news,
    "va_place_stop": virtual.place_stop,
    "va_charges": rms.charges,
    "coins_exchange": coins.exchange,
    "card_create": cards.create,
    # Saved builder strategies (#150): need `saved_strategies` (Level 5).
    "strategy_save": strategies.save,
    "strategy_list": strategies.list_saved,
    "strategy_delete": strategies.delete,
    "referral_get": auth.referral,
    # Auto-trade (virtual account only)
    "va_get_autotrade": autotrade.get_settings,
    "va_set_autotrade": autotrade.set_settings,
    "va_autotrade_runs": autotrade.get_runs,
    "va_autotrade_run_now": va_autotrade_run_now,
    # Real broker (phase 1: Zerodha). Connecting, previewing and placing need live_trading
    # (REQUIRES below); the rest act on the caller's own connection, like the va_* ones above.
    "broker_connect_url": broker_connect_url,
    "broker_exchange_token": broker_exchange_token,
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
    "admin_set_role": admin_set_role,
    "admin_get_features": admin_get_features,
    "admin_set_feature": admin_set_feature,
    "admin_get_settings": admin_get_settings,
    "admin_set_brand_name": admin_set_brand_name,
    "admin_approve_final": admin_approve_final,
    "admin_user_grants": admin_user_grants,
    "admin_revoke_grant": admin_revoke_grant,
    "admin_reset_logo": admin_reset_logo,
    "admin_get_overrides": admin_get_overrides,
    "admin_set_override": admin_set_override,
    "admin_set_setting": admin_set_setting,
}

REQUIRES = {
    "admin_list_users": "manage_users", "admin_set_status": "manage_users",
    "admin_reset_password": "manage_users", "admin_audit_log": "manage_users",
    "admin_list_blocked": "manage_users", "admin_unblock_signup": "manage_users",
    "admin_set_role": "manage_roles",
    "admin_get_features": "owner", "admin_set_feature": "owner",
    "admin_user_grants": "owner", "admin_revoke_grant": "owner",
    "admin_get_settings": "owner", "admin_set_setting": "owner",
    "admin_set_brand_name": "owner", "admin_reset_logo": "owner", "admin_approve_final": "owner",
    "admin_get_overrides": "owner", "admin_set_override": "owner",
    "broker_connect_url": "live_trading", "broker_exchange_token": "live_trading",
    "broker_preview_order": "live_trading", "broker_place_order": "live_trading",
    "va_set_autotrade": "autotrade", "va_autotrade_run_now": "autotrade",
    "get_market_calendar": "market_calendar",
    "get_screened_candidates": "screener", "get_trade_detail": "screener",
    "strategy_save": "saved_strategies", "strategy_list": "saved_strategies", "strategy_delete": "saved_strategies",
}
assert set(ADMIN_METHODS) <= set(REQUIRES), "every admin method needs a REQUIRES entry"

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
    resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers.setdefault("Cache-Control", "no-store")
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


# ---------- public share cards (#126) ----------
# Plain GET pages, not RPC: WhatsApp and X fetch them without cookies or JavaScript.
CARD_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{big} · {site}</title>
<meta name="description" content="{small}. {label}.">
<meta property="og:type" content="website"><meta property="og:site_name" content="{site}">
<meta property="og:title" content="{big}"><meta property="og:description" content="{small}. {label}.">
<meta property="og:url" content="{url}"><meta property="og:image" content="{url}.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<style>body{{margin:0;font:16px/1.5 system-ui,sans-serif;background:#0f1720;color:#e6edf3;display:grid;place-items:center;min-height:100vh}}
main{{max-width:640px;padding:24px 16px;text-align:center}}img{{width:100%;height:auto;border-radius:12px}}
a.cta{{display:inline-block;margin-top:20px;padding:12px 22px;border-radius:8px;background:#2bb673;color:#0f1720;font-weight:700;text-decoration:none}}
p{{color:#9fb0c0}}</style></head><body><main>
<img src="/c/{slug}.png" alt="{big}. {small}." width="1200" height="630">
<h1>{small}</h1><p>Learn to sell options on Nifty 50 stocks with a virtual account. {label}, no real money.</p>
<a class="cta" href="{base}/register?ref={ref}">Start paper trading free</a></main></body></html>"""


def _card(slug: str) -> dict:
    p = cards.get(slug) if len(slug) <= 32 else None
    if p is None:
        abort(404)
    return p


@app.get("/c/<slug>")
def card_page(slug: str):
    p = _card(slug)
    app_name = brand.name()
    big, small = cards.headline(p, app_name)
    base = auth.public_url()
    html = CARD_PAGE.format(big=escape(big), small=escape(small), label=escape(cards.LABEL), site=escape(app_name),
                            url=escape(f"{base}/c/{slug}"), base=escape(base), slug=escape(slug),
                            ref=escape(auth.ref_code(cards.owner(slug))))
    resp = Response(html, mimetype="text/html")
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.get("/c/<slug>.png")
def card_png(slug: str):
    # The card's facts are frozen when made; the brand on it follows the current name and logo.
    site = auth.public_url().split("://", 1)[-1]
    logo = brand.asset("logo")
    resp = Response(cards.png(_card(slug), site, brand.name(), logo and logo[0]), mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.get("/brand/<kind>.png")
def brand_png(kind: str):
    """The owner's uploaded logo, touch icon or favicon. 404 while the built-in ones are used."""
    found = brand.asset(kind) if kind in brand.SIZES else None
    if found is None:
        abort(404)
    data, sha = found
    if request.if_none_match.contains(sha):
        return Response(status=304)
    resp = Response(data, mimetype="image/png")
    resp.set_etag(sha)
    # Pages ask for ?v=<sha>, so a new upload is a new URL.
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return resp


@app.post("/brand/logo")
def brand_upload():
    """Owner only: the raw PNG or WebP body becomes the new logo. Outside /rpc because a logo is
    far larger than the RPC body limit; the same Origin, session and owner checks apply."""
    if request.headers.get("Origin") not in ALLOWED_ORIGINS:
        return _error(None, FORBIDDEN, "Requests from this origin are not allowed", 403)
    if request.mimetype not in ("image/png", "image/webp"):
        return _error(None, -32000, "Upload a PNG or WebP image", 415)
    ctx = Ctx()
    if not ctx.user:
        return _error(None, NOT_SIGNED_IN, "Sign in to continue", 401)
    if ctx.user["must_change_password"] or not permissions.user_allowed(ctx.user, "owner"):
        return _error(None, FORBIDDEN, "You don't have access to this", 403)
    request.max_content_length = brand.MAX_UPLOAD
    try:
        brand.set_logo(ctx.user_id, request.get_data(cache=False))
    except brand.BrandError as e:
        return _error(None, -32000, str(e), 400)
    auth.audit("brand_changed", actor_id=ctx.user_id, ip=ctx.ip, field="logo")
    return jsonify({"jsonrpc": "2.0", "id": None, "result": brand.info()})


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
        need = REQUIRES.get(name)
        if need and not permissions.user_allowed(ctx.user, need):
            return _error(req_id, FORBIDDEN, "You don't have access to this")

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
