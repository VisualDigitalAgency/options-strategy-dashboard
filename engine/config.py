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

MIN_DTE = 30

DELTA_MAX_ABS = 0.15  # strike must have |delta| below this on both CE and PE

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

# Stop-loss rules
SL_GRACE_DAYS = 15           # no SL active before this many days into the trade
TIME_EXIT_DTE = 7            # close every leg once fewer than this many days remain: stock options
                             # settle by physical delivery, and NSE delivery margins climb into expiry
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
SCREEN_REFRESH_OFF_SECONDS = 3600       # hourly outside market hours; prices barely move
POSITIONS_REFRESH_MARKET_SECONDS = 60   # open positions re-priced every minute while NSE is open
POSITIONS_REFRESH_OFF_SECONDS = 900     # every 15 min outside market hours

# New virtual accounts start with this much capital (₹10,00,000); editable per user on reset.
STARTING_CAPITAL = 1_000_000
