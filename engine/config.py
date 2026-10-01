# Strategy configuration — all thresholds live here, not scattered in logic.

NIFTY50_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"

# Used only if the live NSE constituent CSV can't be fetched. Snapshot: 2026-09-24.
NIFTY50_FALLBACK = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "ITC", "INFY", "INDIGO", "JSWSTEEL", "JIOFIN", "KOTAKBANK",
    "LT", "M&M", "MARUTI", "MAXHEALTH", "NTPC", "NESTLEIND", "ONGC", "POWERGRID",
    "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN", "SUNPHARMA", "TCS", "TATACONSUM",
    "TMPV", "TATASTEEL", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

PCR_MIN = 0.4
PCR_MAX = 0.7

MIN_DTE = 30  # the strategy's entry floor: auto-trade only opens cycles at least this far out, and
              # the Screener's Expiry slider starts here

# Expiry cycles screened per stock: every monthly expiry between these bounds (the Expiry
# slider's range), nearest first, capped so a data anomaly can't multiply NSE calls.
SCREEN_DTE_FLOOR = 20
SCREEN_DTE_CEIL = 90
SCREEN_MAX_EXPIRY_CYCLES = 4
# Cycles are screened month by month (every stock's nearest cycle, then the next, ...). A cycle that
# came back SKIP is reused, not refetched, until it is this old; actionable, errored and new cycles
# are refetched every run. The Refresh button refetches everything.
SCREEN_SKIP_REFRESH_SECONDS = 3600

DELTA_MAX_ABS = 0.15  # strike must have |delta| below this on both CE and PE

# Illiquid-strike gate (#80, engine/pricing.py): a strike failing any check is passed over by the
# screener (the next-highest-OI strike is tried), needs an explicit confirm on a manual order, and is
# skipped by auto-trade. Spread and LTP gap are % of the bid/ask mid.
LIQUIDITY_MIN_OI = 500
LIQUIDITY_MAX_SPREAD_PCT = 10
LIQUIDITY_MAX_LTP_GAP_PCT = 15    # LTP this far outside the book = no recent trades (stale)
# The order ticket defaults a limit to the touch (bid for a sell) on a tight book; wider than this,
# to the mid, so the spread isn't given away the moment the order fills.
TICKET_MID_SPREAD_PCT = 3

RISK_FREE_RATE = 0.065  # approx India 10Y-adjacent short rate, update periodically

# Swing S/R detection
SR_LOOKBACK_DAYS = 180       # ~6 months of daily candles
SR_FRACTAL_N = 5             # N candles either side to confirm a swing point
SR_ZONE_WIDTH_PCT = 1.5      # cluster swing points within this % into one zone
SR_MIN_TOUCHES = 2           # a zone needs 2+ touches to count as real S/R

# Sentiment: (PE OI chg - CE OI chg) / total |chg| beyond this counts as a signal
SENTIMENT_OI_BIAS = 0.2

# NSE extreme-loss (exposure) margin for stock options: higher of this % of
# notional or 1.5 x the stock's 6-month daily volatility. Verify against your broker.
EXPOSURE_MIN_PCT = 3.5
EXPOSURE_SIGMA_MULT = 1.5

# Batch screening: stocks per batch, parallel NSE workers inside a batch, pause between batches.
# Keep workers low; NSE blocks sessions that burst requests.
SCREEN_BATCH_SIZE = 10
SCREEN_WORKERS = 3
SCREEN_BATCH_PAUSE_SECONDS = 1.0
# Pacing for every nseindia.com API call (option chains, expiry lists), shared by all threads in a
# process: at least NSE_MIN_GAP_SECONDS plus up to NSE_GAP_JITTER_SECONDS of random delay between two
# requests. A full screen (~50 expiry lists + up to ~150 chains) takes ~3 min at these settings.
NSE_MIN_GAP_SECONDS = 0.7
NSE_GAP_JITTER_SECONDS = 0.3
NSE_TIMEOUT_SECONDS = 10          # per request: a hung connection fails instead of stalling a screen thread
NSE_RETRY_BACKOFF_SECONDS = 3     # wait before the one retry after a rejected/empty response

# Stop-loss rules
SL_GRACE_DAYS = 15           # no SL active before this many days into the trade
TIME_EXIT_DTE = 7            # close every leg once fewer than this many days remain: stock options
                             # settle by physical delivery, and NSE delivery margins climb into expiry
LONG_SL_PCT = 50             # a bought leg with no sell to protect closes once its value falls this % (#137)
PROFIT_TARGET_DECAY_PCT = 90  # close the whole group once this % of the premium collected has decayed
SL_TARGET = "original_premium"  # breakeven-style SL from day 15 onward
# Real (broker) legs: on day SL_GRACE_DAYS a Kite ATO alert is installed that buys the leg back when
# its LTP reaches the stop. The BUY is a limit this far above the stop, so a fast move still fills
# without an unbounded market order.
BROKER_SL_LIMIT_BUFFER_PCT = 10
BROKER_SL_RETRY_SECONDS = 3600  # a failed alert install is retried at most this often
# A limit typed on a real-order ticket must be within this % of the current bid (or LTP when there
# is no bid), so a slipped digit (5 instead of 50) can't reach the broker.
BROKER_LIMIT_BAND_PCT = 20

# Background refresh: the backend fetches on these timers and the dashboard only reads the cache.
SCREEN_REFRESH_MARKET_SECONDS = 600     # option chains every 10 min while NSE is open (NSE rate-limits harder polling)
SCREEN_REFRESH_OFF_SECONDS = 3600       # freshness TTL auto-trade asks for outside market hours
# Scheduled screens run only in this weekday IST window (pre-open to a little after the close), plus one
# catch-up after it. NSE chains are frozen overnight and on weekends, so refetching them is wasted calls.
SCREEN_WINDOW_OPEN = (9, 0)
SCREEN_WINDOW_CLOSE = (15, 45)
# Market calendar (holidays + corporate events): refreshed once a day outside the window above.
CALENDAR_REFRESH_SECONDS = 20 * 3600
CALENDAR_DAYS_AHEAD = 120   # corporate actions fetched this far ahead (covers the 90-day screen ceiling)
POSITIONS_REFRESH_MARKET_SECONDS = 60   # open positions re-priced every minute while NSE is open
POSITIONS_REFRESH_OFF_SECONDS = 900     # every 15 min outside market hours

STARTING_CAPITAL = 200_000  # every new account (#47); more only by completing CAPITAL_TASKS
# Task milestones that add virtual capital (#47): key -> (reward ₹, how many times it can pay).
# Each is checked by engine/capital.py from data the server holds; each pays once per ref.
CAPITAL_TASKS = {
    "l1_lessons": (25_000, 1),       # pass every Level 1 lesson quiz
    "first_sl_trade": (25_000, 1),   # close a short trade with its stop-loss on
    "five_sl_trades": (50_000, 1),   # 5 closed trades, every short leg with its stop-loss on
    "profit_month": (50_000, 6),     # a complete calendar month (IST) with realised profit
    "low_delta_20": (50_000, 1),     # 20 closed short legs sold below DELTA_MAX_ABS
    "adjustments": (50_000, 1),      # pass the Adjustments course (Level 6 lessons)
    "invite_trades": (50_000, 10),   # someone you invited verified their email and closed a trade
    "invite_level3": (50_000, 10),   # someone you invited reached Level 3
    "share_card": (25_000, 2),       # share a level-up or course card (once per kind)
}
# Coins (#47): a second reward on top of the capital grants, exchanged one way into capital.
COIN_RUPEES = 100  # 1 coin = ₹100
# The same tasks as CAPITAL_TASKS, in coins: key -> (coins, how many times it can pay).
COIN_TASKS = {
    "l1_lessons": (25, 1), "first_sl_trade": (25, 1), "five_sl_trades": (50, 1), "profit_month": (50, 6),
    "low_delta_20": (50, 1), "adjustments": (50, 1), "share_card": (25, 2),
    "invite_trades": (25, 3), "invite_level3": (25, 3),
}
COIN_LEVEL = {2: 25, 3: 25, 4: 25, 5: 50, 6: 50, 7: 50, 8: 100, 9: 100, 10: 100}
# A profitable closed short leg pays only when it was traded with discipline: stop-loss on, sold
# below DELTA_MAX_ABS, held this long, with at least this much profit; at most this many a month.
COIN_TRADE = 2
COIN_TRADE_MIN_DAYS = 7
COIN_TRADE_MIN_PNL = 500
COIN_TRADE_PER_MONTH = 10
COIN_XP_STEP, COIN_XP = 250, 10  # every 250 XP pays 10 coins
# Reaching level n adds this much (#47).
LEVEL_CAPITAL = {2: 100_000, 3: 150_000, 4: 200_000, 5: 250_000, 6: 500_000, 7: 500_000, 8: 500_000,
                 9: 500_000, 10: 500_000}


# ---------- learning path (#120, #122) ----------
# Leaving level n needs: total XP >= 100 * n^2, MIN_DAYS at the level, and the level's gate (engine/progress.py).
LEVEL_TITLES = {1: "Learner", 2: "Apprentice", 3: "Seller", 4: "Disciplined", 5: "Consistent",
                6: "Risk manager", 7: "Strategist", 8: "Expert", 9: "Master", 10: "Theta Master"}
LEVEL_MIN_DAYS = {1: 60, 2: 60, 3: 60, 4: 90, 5: 90, 6: 90, 7: 90, 8: 90, 9: 90}
XP_TRADE_OK = 20         # short leg closed with its stop-loss on and sold below DELTA_MAX_ABS
XP_NO_SL = -30           # short leg closed with the stop-loss off
XP_HIGH_DELTA = -20      # short leg sold at |delta| >= DELTA_MAX_ABS
XP_PROFIT_BONUS = 5      # per profitable leg, capped per calendar month
XP_PROFIT_CAP = 100
XP_LESSON = 10           # per lesson quiz passed (first pass only)
QUICK_FLIP_MINUTES = 5   # legs opened and closed faster than this score nothing

# Features each level unlocks (#123), on top of the role's own toggles. A key that isn't in
# engine/permissions.FEATURES yet (the feature hasn't shipped) is ignored until it exists.
LEVEL_FEATURES = {3: ("market_calendar",), 4: ("leaderboard",), 5: ("saved_strategies", "alerts"), 6: ("hedges",)}
# Gates for Levels 6-9 (#146). Leaving 9 also needs the owner's final-assessment sign-off.
VOLATILE_SWING_PCT = 3.0          # L6: a month whose Nifty high-low range is at least this % of its open
L7_PROFIT_MONTHS = (6, 8)         # L7: profitable months out of the last N complete months
L7_MAX_DD_PCT = 10.0
L8_RET_DD_12M = 2.0               # L8: return / drawdown over the last 12 months
L8_TOP_PCT = 20                   # L8: in the top this % of their band...
L8_TOP_MONTHS = 2                 # ...in at least this many finalised monthly boards
L9_PROFIT_MONTHS = (9, 12)        # L9: profitable months out of the last 12, with 12-month drawdown...
L9_MAX_DD_PCT = 10.0
L9_MENTEES = 3                    # ...and this many people they invited reached MENTEE_LEVEL
MENTEE_LEVEL = 3
L9_TRACK_MONTHS = 18              # ...over a track record at least this long, then the owner's sign-off
# Strategy gate (#170): margin-ascending path. Below NAKED_LEVEL every sold leg needs a protecting
# buy (spreads, condors); below STRANGLE_LEVEL only one side may be sold without one.
NAKED_LEVEL = 3
STRANGLE_LEVEL = 5
BETA_LEVEL = 6           # reaching this level moves a `user` to `beta`, once; never higher
