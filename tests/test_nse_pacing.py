"""NSE requests are spaced out across threads, and a rejected response backs off, refreshes the
session cookies once (in one thread only) and retries."""
import sys
import threading
import time

from engine import config, data_fetch

fails = []


def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name, "->", got)
    if not cond:
        fails.append(name)


class Resp:
    def __init__(self, code=200, text='{"ok": 1}'):
        self.status_code, self.text = code, text

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"ok": 1}


stamps, homepage = [], []


class FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        if url == data_fetch.NSE_BASE:
            homepage.append(time.monotonic())
            return Resp()
        stamps.append(time.monotonic())
        return plan.pop(0) if plan else Resp()


data_fetch.requests.Session = FakeSession
data_fetch.time.sleep = time.sleep
config.NSE_MIN_GAP_SECONDS, config.NSE_GAP_JITTER_SECONDS, config.NSE_RETRY_BACKOFF_SECONDS = 0.1, 0.05, 0.2
plan = []

# ---- six calls from three threads: never closer than the minimum gap
threads = [threading.Thread(target=lambda: [data_fetch._nse_get("https://x/api", {}) for _ in range(2)]) for _ in range(3)]
[t.start() for t in threads]
[t.join() for t in threads]
gaps = [round(b - a, 3) for a, b in zip(stamps, stamps[1:])]
check("six requests made", len(stamps) == 6, len(stamps))
check("every gap >= NSE_MIN_GAP_SECONDS", min(gaps) >= 0.1 - 0.005, gaps)
check("jitter bounded", max(gaps) <= 0.15 + 0.05, gaps)
check("one cookie fetch for all threads", len(homepage) == 1, len(homepage))

# ---- a rejected response: back off, fresh cookies, retry once
stamps.clear(); homepage.clear()
plan = [Resp(403, "")]
out = data_fetch._nse_get("https://x/api", {})
check("retry succeeds", out == {"ok": 1}, out)
check("backed off before the retry", stamps[1] - stamps[0] >= 0.2, round(stamps[1] - stamps[0], 3))
check("cookies refreshed once", len(homepage) == 1, len(homepage))

print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
