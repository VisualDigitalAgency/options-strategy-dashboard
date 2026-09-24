# Theta Desk: options selling screener

Screens all Nifty 50 stocks for 30+ DTE option-selling setups and shows one-click order tickets. Broker execution is not wired yet, so the Confirm button stays disabled.

## Run

```bash
python -m pip install -r requirements.txt
python server.py
```

In a second terminal:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Open http://localhost:5173. The first load takes about a minute because it fetches 50 option chains plus the NSE SPAN file. Results are cached for 10 minutes; **Refresh** forces a new fetch. Click any stock for its detail page (`/stock/SYMBOL`). The wallet in the top bar shows your virtual account's free funds; set the max margin % per trade there.

## Rules (edit in `engine/config.py`)

| Rule | Value |
|---|---|
| Universe | Nifty 50, read live from NSE's constituent CSV (falls back to a saved list if unreachable) |
| PCR (OI) | 0.4 – 0.7 |
| Expiry | First expiry with 30+ DTE |
| Strike | Highest-OI OTM strike with \|delta\| < 0.15 (Black-Scholes from NSE IV) |
| Max Pain | Shown as distance from the strike, used for confirmation only |
| S/R | 6-month daily swings (5-candle fractal), zones ±1.5%, 2+ touches. A strike inside a zone drops that leg |
| Stop loss | None for the first 15 days, then buy back at the original premium collected |
| Sentiment | +1/-1 for price vs 20 & 50 DMA trend, +1/-1 for today's PE vs CE OI change. Score ≥1 Bullish, ≤-1 Bearish, else Neutral. Display only; it doesn't filter trades, but flags single-leg sells that go against it |

## Trade metrics

| Metric | How it's calculated |
|---|---|
| Breakeven | Strangle: PE strike − total credit and CE strike + total credit. Single leg: strike ∓ its premium |
| POP | Probability price at expiry ends between the breakevens (lognormal, NSE IV per side) |
| Max profit probability | Probability price at expiry ends between the short strikes, so all premium is kept |
| Touch probability | About 2× the chance of expiring past the strike: odds price touches it before expiry |
| Lot size | NSE `fo_mktlots.csv`, column for the expiry month |
| SPAN margin | Worst of the 16 SPAN scenarios for the combined short position, from NSE's latest SPAN 4.0 risk file (`nsccl.YYYYMMDD.iN.zip`). Strangles get the real offset between legs |
| Exposure margin | Per short leg: higher of 3.5% of notional or 1.5 × 6-month daily volatility |
| Lots suggested | floor(min(account value × max % per trade, free funds) ÷ margin per lot) |

## Strategy lab (stock detail page)

| Control / figure | How it works |
|---|---|
| Strike sliders | Step through the live NSE strikes on the out-of-the-money side. Warns when a strike breaks the delta < 0.15 rule or sits in an S/R zone |
| Days slider | Values each leg on any day to expiry with Black-Scholes at today's IV, calibrated so day 0 equals the market premium; spot held constant |
| Intrinsic / time value | Intrinsic = how far the option is in the money; time value = premium − intrinsic (all of it for OTM strikes) |
| Risk : reward | Reward = premium collected. Risk = expiry loss after a 2σ move against you (a naked short has no fixed max loss) |
| 1σ / 2σ | Expected move by expiry, spot × e^(±nσ√t) from the legs' IV; shaded on both payoff charts. Each strike shows how many σ it sits from spot |
| Margin | Real SPAN + exposure for the chosen strikes (`calc_margin` RPC) |

## Wallet

The top-bar wallet shows the virtual account's free funds, refreshed every 30s and after every order, exit or reset. Lot suggestions use `min(account value × max % per trade, free funds)`; set the % in the wallet panel.

## Portfolio & virtual account

Paper trading with live NSE prices, stored in `engine/data/virtual.db` (SQLite, git-ignored). Starts at ₹10 lakh; reset any time from **Virtual account** with a custom amount.

| Feature | Behaviour |
|---|---|
| Order fills | Sells fill at the live bid, buys at the ask. If there's no bid/ask (market closed), the last traded price is used and the order is tagged with a note |
| Margin | SPAN (from the NSE risk file, long and short legs netted) + exposure on short legs, per stock/expiry. Orders are rejected if free funds can't cover the extra margin |
| Positions | Netted per contract; opposite trades reduce or close the position and book realised P&L |
| Stop loss | Per short leg, three modes: **Auto exit** (buys back at the ask once it reaches the premium collected, from day 15), **Alert only** (flags the leg for you to act), **Off**. The account default applies to new legs; change any leg on the Portfolio page |
| Monitor | Background thread checks stop losses every minute during market hours (9:15–15:30 IST) and settles expired contracts at intrinsic value, as long as `server.py` is running |
| Portfolio | Positions grouped by stock and expiry: live P&L, margin, Greeks, payoff at expiry, exit leg or exit all |

## Layout

- `engine/` — data fetch (NSE v3 option chain, lot sizes, yfinance), SPAN parser (`span.py`), filters, Greeks/probabilities/Max Pain/S-R, rule engine
- `engine/batch.py` — background batch screener (10 stocks per batch, 3 NSE workers, one yfinance call per batch)
- `engine/virtual.py` — virtual trading account, order fills, SL monitor
- `server.py` — JSON-RPC 2.0 endpoint at `POST /rpc`: screener (`get_screened_candidates`, `get_trade_detail`, `get_config`, `calc_margin`) and virtual trading (`va_get_account`, `va_get_positions`, `va_get_orders`, `va_get_closed`, `va_preview_order`, `va_place_order`, `va_exit_position`, `va_exit_group`, `va_set_sl_mode`, `va_dismiss_alert`, `va_reset`)
- `frontend/` — React (Vite) dashboard: `pages/Overview.jsx`, `pages/StockDetail.jsx`, `pages/Portfolio.jsx`, `pages/VirtualAccount.jsx`, charts in `components/Charts.jsx` (Recharts). Responsive from 320px: wide tables turn into stacked cards below 1024px

## Known limits

- NSE's option-chain API is unofficial. It can change or block requests without notice (it already moved from `option-chain-equities` to `option-chain-v3`).
- Delta is computed locally with a fixed 6.5% risk-free rate and no dividend adjustment.
- The SL rule is display-only until position tracking and broker integration are added (Phase 2).
- Exposure margin is charged on each leg of a strangle. Some brokers charge it differently, so compare with your broker's margin calculator before relying on it.
- Probabilities assume a lognormal price at expiry using today's IV. They are model estimates, not guarantees, and they ignore gap risk.
