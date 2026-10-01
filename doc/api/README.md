# JSON-RPC API

The browser app talks to the backend through one endpoint, `POST /rpc`, using JSON-RPC 2.0. This page covers the protocol, errors, the Origin (CSRF) check, cookies, and example calls. The method list with every parameter is generated from the code: [rpc.md](rpc.md).

## Requests

```http
POST /rpc
Content-Type: application/json
Origin: https://theta.example.com

{"jsonrpc": "2.0", "id": 1, "method": "va_get_positions", "params": {}}
```

- `params` is an object of named arguments. Positional arrays are refused. It can be left out when a method takes none.
- The body is at most 64 KB.
- Every response carries `Cache-Control: no-store`. Numbers that aren't finite (a quote with no IV, for example) come back as `null`, since browsers can't parse `NaN`.
- `GET /healthz` is for container health checks. It returns `{"postgres": bool, "redis": bool, "worker": bool}` with status 200, or 503 when Postgres is down. The API keeps serving without Redis or a worker, but not without Postgres.

## Origin check (CSRF)

Every `/rpc` call must send an `Origin` header listed in `ALLOWED_ORIGINS` (comma-separated; the default is the Vite dev server, `http://localhost:5173,http://127.0.0.1:5173`). Any other origin, or no `Origin` at all, gets HTTP 403 with error `-32003`. Browsers always send `Origin` on a cross-site POST, so another site can't make a signed-in browser call the API.

In production the page and the API share one origin: Caddy serves the app and proxies `/rpc`. On Coolify, `PUBLIC_URL` must exactly match the public HTTPS origin, or every call gets this 403. Behind a proxy, `TRUST_PROXY=1` takes the client IP and scheme from exactly one proxy hop (Werkzeug's ProxyFix). The IP feeds the sign-in limits and the audit log.

## Cookies

| Cookie | Holds | Lifetime |
|---|---|---|
| `__Host-theta` (`SESSION_COOKIE`) | the session token; only its SHA-256 is stored | a new token on every sign-in. It expires after `SESSION_DAYS` without use and `SESSION_CAP_DAYS` at most (see [Limits](rpc.md#limits)) |
| `__Host-theta-dev` (`DEVICE_COOKIE`) | a random id for this browser; only its hash is stored | 2 years, kept after sign-out |

Both are `HttpOnly`, `SameSite=Lax` and `Path=/`, and `Secure` whenever the name starts with `__Host-` (browsers insist on it) or `COOKIE_SECURE` is `1`, the default. So they need HTTPS. The device cookie grants no access; it only lets sign-up spot a browser that already has an account.

Signing out, changing the password, or an admin disabling the account or issuing a temporary password ends sessions server-side. The cookie alone is then worthless. While an account has a temporary password, only `auth_me`, `auth_logout` and `auth_change_password` work; everything else gets `-32004`.

## Errors

| Code | HTTP | Meaning |
|---|---|---|
| `-32000` | 200 | A message written for the user: insufficient margin, wrong password, a stale screen. The handler raised `ValueError` or `TimeoutError`, or NSE failed ("Market data from NSE isn't available right now…"). Show `message` as is. |
| `-32001` | 200 | Not signed in (no session, or it expired or was ended). |
| `-32003` | 403 / 200 | Origin not allowed (403), or a method whose feature (`REQUIRES`) the caller's role lacks (200). |
| `-32004` | 200 | The account has a temporary password; set a new one first. |
| `-32005` | 200 | The email isn't confirmed yet. The client shows the code form. |
| `-32600` | 4xx / 200 | Not a JSON-RPC 2.0 request, not `application/json` (415), or an HTTP-level error (404, 405, 413). |
| `-32601` | 200 | No such method. |
| `-32602` | 200 | Params refused by `rpc_guard.validate`; `message` starts with "Invalid params:". The rules are in [rpc.md](rpc.md#parameter-rules). |
| `-32603` | 200 / 500 | A bug or unexpected failure. The client only gets "Something went wrong on the server (ref abc123)"; the traceback is in the server log under that ref. |

Handlers raise `ValueError` (or `TimeoutError`) with a message meant for the user. Anything else is logged with a ref id, and its details never reach the client.

## Examples

The virtual-account and broker responses below are captured from real calls against a test database. Market data is stubbed (spot 1,000, every option bid 5.00 and ask 5.10) and the broker is a fake adapter. Tokens and ids are replaced with placeholders. The screen examples list the real fields with illustrative values, because a screen needs live NSE data.

### Sign in

```json
{"jsonrpc": "2.0", "id": 1, "method": "auth_login",
 "params": {"email": "trader@example.com", "password": "correct-horse-battery-9"}}
```

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "id": 1, "name": "Asha Trader", "email": "trader@example.com", "role": "owner", "status": "active",
  "must_change_password": false, "created_at": "2026-09-30 10:28:03",
  "features": ["manage_users", "manage_roles", "live_trading", "autotrade", "market_calendar"],
  "prefs": {"theme": null, "palette": null}}}
```

The response sets `__Host-theta=<token>; Max-Age=2592000; Secure; HttpOnly; Path=/; SameSite=Lax`. A wrong password:

```json
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "Email or password is wrong"}}
```

### Screen

`get_screened_candidates` returns the worker's last screen straight away and never waits on NSE. `force_refresh: true` asks for an early refresh, at most once per `FORCE_SCREEN_EVERY` for everyone; the cached rows come back either way.

```json
{"jsonrpc": "2.0", "id": 1, "method": "get_screened_candidates", "params": {}}
```

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "generated_at": 1790000000.0, "next_refresh_at": 1790003600.0, "refreshing": false,
  "refresh_throttled_s": 0, "span_source": "<latest NSE SPAN file>",
  "progress": {"running": false, "done": 50, "total": 50, "batch": 5, "batches": 5, "pass": 1, "passes": 1, "error": null},
  "candidates": [{
    "symbol": "SBIN", "expiry": "2026-11-24", "dte": 55, "action": "SELL STRANGLE", "spot": 1000.0,
    "pcr": 0.55, "max_pain": 990.0, "lot_size": 750, "screened_at": 1790000000.0,
    "legs": [{"side": "CE", "strike": 1100.0, "premium": 5.0, "bid": 5.0, "ask": 5.1, "iv": 20.0, "oi": 120000,
              "delta": 0.14, "prob_itm": 12.1, "prob_touch": 24.2, "distance_pct": 10.0, "…": "…"}],
    "strategy": {"credit_per_share": 10.0, "breakeven_lower": 890.0, "breakeven_upper": 1110.0, "pop": 78.4,
                 "margin": 150000.0, "roi_pct": 5.0, "roi_annual_pct": 33.2, "…": "…"},
    "checks": [{"rule": "PCR filter", "status": "pass", "detail": "PCR 0.55 is inside 0.4-0.7"}],
    "sentiment": {"label": "Neutral", "…": "…"}, "sl": {"activates_on": "2026-10-15", "time_exit_on": "2026-11-18", "…": "…"},
    "prev_close": 998.4, "atm_iv": 19.8, "sr_near": [{"level": 1080.0, "type": "resistance"}],
    "events": [{"date": "2026-10-09", "type": "results", "…": "…"}]}]}}
```

The list view leaves out each row's heavy fields (`history`, `chain`, `sr_zones`). `get_trade_detail` returns one row with all of them:

```json
{"jsonrpc": "2.0", "id": 1, "method": "get_trade_detail", "params": {"symbol": "SBIN", "expiry": "2026-11-24"}}
```

The result is the row above plus `history` (daily closes), `chain` (strikes within ±25% of spot) and `sr_zones`. When the stock hasn't been screened yet, it is evaluated on demand, at most once per `DETAIL_EVAL_EVERY` per stock; inside that gap the call gets a `-32000` "still being screened" error.

### Preview and place a virtual order

```json
{"jsonrpc": "2.0", "id": 1, "method": "va_preview_order", "params": {
  "symbol": "SBIN", "expiry": "2026-11-24",
  "legs": [{"side": "CE", "strike": 1100, "action": "SELL", "lots": 1},
           {"side": "PE", "strike": 900, "action": "SELL", "lots": 1}]}}
```

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "symbol": "SBIN", "expiry": "2026-11-24", "lot_size": 100, "market_open": true,
  "fills": [
    {"side": "CE", "strike": 1100.0, "action": "SELL", "lots": 1, "qty": 100, "bid": 5.0, "ask": 5.1, "ltp": 5.0,
     "spot": 1000.0, "limit": 5.0, "price": 5.0, "fills_now": true},
    {"side": "PE", "strike": 900.0, "action": "SELL", "lots": 1, "qty": 100, "bid": 5.0, "ask": 5.1, "ltp": 5.0,
     "spot": 1000.0, "limit": 5.0, "price": 5.0, "fills_now": true}],
  "premium": 1000.0, "margin_after": {"span": 200000.0, "exposure": 0.0, "total": 200000.0},
  "margin_change": 200000.0, "available_margin": 1000000.0, "sufficient": true,
  "illiquid": [], "waiting": [], "notes": [], "sl_mode_default": "auto"}}
```

`va_place_order` takes the same params, plus optional `sl_mode`, `confirm_waiting` and `confirm_illiquid`. It prices the fills again from live quotes and never trusts the preview's numbers:

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "filled": [{"side": "CE", "strike": 1100.0, "price": 5.0, "qty": 100, "fills_now": true, "…": "…"},
             {"side": "PE", "strike": 900.0, "price": 5.0, "qty": 100, "fills_now": true, "…": "…"}],
  "open": [], "open_ids": [], "premium": 1000.0, "notes": []}}
```

Legs that can't fill now (market shut, or a limit away from the touch) come back in `open` as resting limit orders. Not enough margin:

```json
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "Insufficient margin: needs ₹50,000,000, available ₹799,990"}}
```

### Positions

`va_get_positions` returns the cached snapshot the worker re-prices every minute. `va_refresh_positions` re-prices now, at most once per `REPRICE_EVERY` per user.

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "updated_at": "2026-09-30 10:28:03", "market_open": true,
  "account": {"starting_capital": 1000000.0, "account_value": 999990.0, "realized_pnl": 0.0, "unrealized_pnl": -10.0,
              "used_margin": 200000.0, "blocked_margin": 0.0, "available_margin": 799990.0, "return_pct": -0.0,
              "open_positions": 2, "open_orders": 0, "sl_mode_default": "auto", "created_at": "2026-09-30 10:28:03"},
  "groups": [{
    "symbol": "SBIN", "expiry": "2026-11-24", "dte": 55, "strategy": "Short strangle", "spot": 1000.0,
    "net_premium": 1000.0, "pnl": -10.0, "pnl_exit": -20.0, "time_exit_on": "2026-11-18", "error": null,
    "margin": {"span": 200000.0, "exposure": 0.0, "total": 200000.0},
    "greeks": {"delta": -8.0, "gamma": -0.453, "theta": 26.2, "vega": -136.6},
    "legs": [{"id": 1, "side": "CE", "strike": 1100.0, "qty": -100, "lots": 1, "lot_size": 100, "avg_price": 5.0,
              "bid": 5.0, "ask": 5.1, "ltp": 5.0, "mark": 5.05, "mark_src": "mid", "ltp_gap_pct": 0.0, "iv": 20.0,
              "pnl": -5.0, "pnl_exit": -10.0, "delta": -14.4, "gamma": -0.292, "theta": 18.5, "vega": -88.0,
              "sl_mode": "auto", "sl_price": 5.0, "sl_status": "waiting", "sl_activates_on": "2026-10-15",
              "sl_alert_at": null, "opened_at": "2026-09-30 10:28:03"}, "…"]}],
  "totals": {"pnl": -10.0, "pnl_exit": -20.0, "margin": 200000.0, "delta": -8.0, "gamma": -0.45, "theta": 26.2, "vega": -136.6}}}
```

`pnl` values each leg at `mark` (`mark_src` says whether that is the mid, the bid or the last trade); `pnl_exit` is what closing at the touch would realise.

### Connect Zerodha (roles with live trading, phase 1)

1. `broker_connect_url` returns the Kite login URL and a one-time `state`. The frontend keeps `state` in `sessionStorage`, because Kite's redirect doesn't carry custom params.

   ```json
   {"jsonrpc": "2.0", "id": 1, "result": {"url": "https://kite.zerodha.com/connect/login?api_key=<key>&v=3", "state": "<one-time state>"}}
   ```

2. Kite redirects back with a `request_token`. The frontend posts it with the saved `state`:

   ```json
   {"jsonrpc": "2.0", "id": 1, "method": "broker_exchange_token",
    "params": {"request_token": "<from the Kite redirect>", "state": "<one-time state>"}}
   ```

   ```json
   {"jsonrpc": "2.0", "id": 1, "result": {"status": "active", "broker": "zerodha"}}
   ```

### Preview and place a real order

`broker_preview_order` checks the margin against the broker's own available funds and returns a one-time `confirm_token`. Nothing reaches the broker yet.

```json
{"jsonrpc": "2.0", "id": 1, "method": "broker_preview_order", "params": {
  "symbol": "SBIN", "expiry": "2026-11-24", "legs": [{"side": "CE", "strike": 1100, "action": "SELL", "lots": 1}]}}
```

```json
{"jsonrpc": "2.0", "id": 1, "result": {
  "confirm_token": "<one-time token>", "expires_in": 60,
  "legs": [{"side": "CE", "strike": 1100.0, "qty": 100, "market_price": 5.0, "limit_price": 5.0}],
  "margin": {"span": 100000.0, "exposure": 0.0, "total": 100000.0}}}
```

`broker_place_order` redeems the token once, within `expires_in` seconds, and places each leg as a SELL LIMIT order:

```json
{"jsonrpc": "2.0", "id": 1, "method": "broker_place_order", "params": {"confirm_token": "<one-time token>"}}
```

```json
{"jsonrpc": "2.0", "id": 1, "result": {"placed": [{"id": 1, "leg_index": 0, "broker_order_id": "<Kite order id>"}]}}
```

### Upload the logo (owner only)

The logo is too big for an RPC call, so it has its own endpoint with the same Origin, session and owner checks. Send the raw image as the body; `Content-Type` must be `image/png` or `image/webp`, up to 1 MB. The reply is the same as `app_info`:

```
POST /brand/logo
Content-Type: image/png
Origin: https://your.domain
```

```json
{"jsonrpc": "2.0", "id": null, "result": {"name": "Theta Desk", "logo": "0936931b67d6bfb4"}}
```

`GET /brand/logo.png`, `/brand/touch.png` and `/brand/favicon.png` serve the re-encoded images (404 while the built-in mark is used); pages add `?v=<logo>` so a new upload is a new URL.

## Changing the API

Register the method in one table in `server.py`, give it a docstring, and run `make rpc-docs`. CI regenerates [rpc.md](rpc.md) and fails when the committed copy differs or any method lacks a docstring. [CONTRIBUTING.md](../../CONTRIBUTING.md) has the rest of the conventions.
