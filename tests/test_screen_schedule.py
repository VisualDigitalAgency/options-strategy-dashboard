"""Scheduled screens: every 10 min inside the weekday window, one catch-up after the close, then nothing
overnight or over the weekend until the next pre-open."""
import sys
from datetime import datetime

from engine import config, virtual
from engine.worker import next_screen_at

fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


def ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=virtual.IST).timestamp()


def show(t):
    return datetime.fromtimestamp(t, virtual.IST).strftime("%a %d %H:%M") if t else t


# 2026-09-29 is a Tuesday; 10-02 Fri, 10-03 Sat, 10-05 Mon.
check("never screened -> due now", next_screen_at(None, ts(2026, 10, 3, 2, 0)) == 0, None)
got = next_screen_at(ts(2026, 9, 29, 11, 0), ts(2026, 9, 29, 11, 5))
check("market hours -> +10 min", got == ts(2026, 9, 29, 11, 0) + config.SCREEN_REFRESH_MARKET_SECONDS, show(got))
got = next_screen_at(ts(2026, 9, 29, 15, 40), ts(2026, 9, 29, 15, 50))
check("screen before the close -> one catch-up at the close", got == ts(2026, 9, 29, 15, 45), show(got))
got = next_screen_at(ts(2026, 9, 29, 15, 46), ts(2026, 9, 29, 21, 0))
check("after the catch-up -> next pre-open", got == ts(2026, 9, 30, 9, 0), show(got))
got = next_screen_at(ts(2026, 9, 29, 15, 46), ts(2026, 9, 30, 3, 0))
check("after midnight -> same day's pre-open", got == ts(2026, 9, 30, 9, 0), show(got))
got = next_screen_at(ts(2026, 10, 2, 15, 50), ts(2026, 10, 3, 12, 0))
check("weekend -> Monday pre-open", got == ts(2026, 10, 5, 9, 0), show(got))
got = next_screen_at(ts(2026, 10, 2, 14, 0), ts(2026, 10, 4, 12, 0))
check("missed Friday's close -> catch up now", got == ts(2026, 10, 2, 15, 45), show(got))
got = next_screen_at(ts(2026, 10, 2, 15, 50), ts(2026, 10, 5, 9, 0))
check("Monday 09:00 -> due", got <= ts(2026, 10, 5, 9, 0), show(got))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
