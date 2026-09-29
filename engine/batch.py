"""Background batch screener.

Splits the universe into batches. Per batch: one yfinance call for all price
histories, then NSE option chains with a small worker pool. Results are published
as each batch finishes, so the dashboard can render progressively.

`ScreenJob` runs only in the worker. It publishes to Redis (`screen:latest` holds the rows,
`screen:meta` the small progress record). The API reads through `ScreenReader`, which never
fetches from NSE itself; it asks the worker for an early refresh via `screen:force`.
"""

import json
import secrets
import threading
import time

import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import cache, config, data_fetch, risk_rules, span

CACHE_FILE = Path(__file__).parent / "cache" / "screen.json"
LATEST, META, FORCE = "screen:latest", "screen:meta", "screen:force"
STATE_KEYS = ("running", "done", "total", "batch", "batches", "pass", "passes", "started_at", "finished_at", "span_source", "error")


def _empty_state() -> dict:
    return {"running": False, "done": 0, "total": 0, "batch": 0, "batches": 0, "pass": 0, "passes": 0,
            "started_at": None, "finished_at": None, "span_source": None, "error": None}


def _as_lists(results: dict) -> dict[str, list[dict]]:
    """Screens saved before multi-expiry screening hold one dict per stock, not a list of cycles."""
    return {s: r if isinstance(r, list) else [r] for s, r in (results or {}).items()}


def _flatten(order: list[str], results: dict[str, list[dict]]) -> list[dict]:
    return [row for s in order if s in results for row in results[s]]


def _all_error(rows: list[dict]) -> bool:
    return all(r.get("action") == "ERROR" for r in rows)


def _reusable(row: dict | None) -> bool:
    """A SKIP row screened recently enough to reuse; actionable and ERROR rows are always refetched."""
    return bool(row and row.get("action") == "SKIP" and not row.get("legs")
                and time.time() - (row.get("screened_at") or 0) < config.SCREEN_SKIP_REFRESH_SECONDS)


def _read_file() -> dict | None:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


class ScreenJob:
    """Results are served from memory at all times. A refresh overwrites each stock as its batch
    finishes, so readers see the last good data until the new data replaces it. The last complete
    screen is saved to disk, so a restart serves it immediately instead of starting empty."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.results: dict[str, list[dict]] = {}  # symbol -> one row per expiry cycle, nearest first
        self.order: list[str] = []
        self.state = _empty_state()
        self._version = ""
        self._load_cache()

    def _load_cache(self) -> None:
        saved = _read_file()
        if saved:
            self.results, self.order = _as_lists(saved["results"]), saved["order"]
            self.state.update(finished_at=saved["finished_at"], span_source=saved["span_source"],
                              done=len(self.order), total=len(self.order))
            self._publish(rows=True)

    def _save_cache(self) -> None:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"finished_at": self.state["finished_at"], "span_source": self.state["span_source"],
                                   "order": self.order, "results": self.results}, default=str), encoding="utf-8")
        tmp.replace(CACHE_FILE)  # atomic: a crash mid-write never leaves a half file

    def _publish(self, rows: bool) -> None:
        """Rows go out after each batch; the small meta record on every progress step."""
        if rows:
            # Unique across worker restarts: a counter would restart at 1, and an API process still
            # holding an old version with the same number would keep serving stale rows.
            self._version = f"{time.time_ns():x}-{secrets.token_hex(3)}"
            cache.set_json(LATEST, {"version": self._version, "order": self.order, "results": self.results})
        cache.set_json(META, {**{k: self.state[k] for k in STATE_KEYS}, "version": self._version})

    def ensure(self, force: bool = False, ttl: float = 600, full: bool = False) -> None:
        """Start a screen unless one is running or the last one is still fresh. `full` refetches
        every cycle, including skips that are still fresh enough to reuse."""
        with self._lock:
            if self.state["running"]:
                return
            finished = self.state["finished_at"]
            if not force and finished and time.time() - finished < ttl:
                return
            self.state.update(running=True, done=0, batch=0, error=None, started_at=time.time())
            self._publish(rows=False)
            self._thread = threading.Thread(target=self._run, args=(full,), daemon=True)
            self._thread.start()

    def _run(self, full: bool = False) -> None:
        """Step 0 fetches every stock's expiry list (one cheap call each) and price history. Then
        pass 1 screens every stock's nearest cycle, pass 2 the next one, and so on, so each month is
        complete for all stocks before the next starts. Fresh SKIP rows are reused (see
        SCREEN_SKIP_REFRESH_SECONDS); a stock's old rows stay visible until their pass replaces them."""
        try:
            symbols = risk_rules.get_universe()
            size = config.SCREEN_BATCH_SIZE
            today = pd.Timestamp.today().normalize()
            self.order = symbols
            self.results = {s: r for s, r in self.results.items() if s in symbols}
            old = {s: {r.get("expiry"): r for r in rows} for s, rows in self.results.items()}
            try:
                self.state["span_source"] = span.load(symbols)["source"]
            except Exception as e:
                self.state["span_source"] = f"unavailable: {e}"

            # ---- step 0: expiry lists and price histories
            histories: dict[str, pd.DataFrame] = {}
            cycles: dict[str, list] = {}
            chunks = [symbols[i : i + size] for i in range(0, len(symbols), size)]
            self.state.update(total=len(symbols), batches=len(chunks), passes=0)
            for n, chunk in enumerate(chunks, start=1):
                self.state["batch"] = n
                try:
                    got = data_fetch.fetch_price_history_batch([f"{s}.NS" for s in chunk], config.SR_LOOKBACK_DAYS)
                    histories.update({s: got[f"{s}.NS"] for s in chunk if f"{s}.NS" in got})
                except Exception:
                    pass  # price_history() falls back to a per-stock fetch
                with ThreadPoolExecutor(max_workers=config.SCREEN_WORKERS) as pool:
                    futures = {s: pool.submit(risk_rules.screen_cycles, s, today) for s in chunk}
                    for s, f in futures.items():
                        try:
                            cycles[s] = f.result()
                            if not cycles[s]:
                                self.results[s] = [risk_rules._no_expiry(s)]
                        except Exception as e:
                            # No expiry list: keep the last good rows rather than an error.
                            if s not in self.results or _all_error(self.results[s]):
                                self.results[s] = [risk_rules._error_row(s, e)]
                        self.state["done"] += 1
                if n < len(chunks):
                    time.sleep(config.SCREEN_BATCH_PAUSE_SECONDS)

            fresh: dict[str, dict] = {s: {} for s in cycles}

            def merge(s: str) -> None:
                """In-range cycles only, nearest first: this run's row where fetched, else the old one."""
                keys = [e.strftime("%Y-%m-%d") for e in cycles[s]]
                self.results[s] = [fresh[s].get(k) or old.get(s, {}).get(k) for k in keys
                                   if fresh[s].get(k) or old.get(s, {}).get(k)]

            for s in cycles:
                if cycles[s]:
                    merge(s)
            self._publish(rows=True)

            def task(s: str, expiry: pd.Timestamp) -> dict:
                try:
                    histories[s] = risk_rules.price_history(f"{s}.NS", histories.get(s))
                except Exception as e:
                    return risk_rules._error_row(s, e, expiry, (expiry - today).days)
                return risk_rules.evaluate_cycle(s, expiry, today, histories[s])

            # ---- passes: nearest cycle of every stock, then the next, ...
            passes = max((len(c) for c in cycles.values()), default=0)
            plan = [[s for s in symbols if len(cycles.get(s) or []) > k] for k in range(passes)]
            self.state.update(passes=passes, done=0, total=sum(len(p) for p in plan),
                              batches=sum(-(-len(p) // size) for p in plan), batch=0)
            for k, stocks in enumerate(plan):
                self.state["pass"] = k + 1
                for chunk in (stocks[i : i + size] for i in range(0, len(stocks), size)):
                    self.state["batch"] += 1
                    fetched = False
                    with ThreadPoolExecutor(max_workers=config.SCREEN_WORKERS) as pool:
                        futures = {}
                        for s in chunk:
                            expiry = cycles[s][k]
                            key = expiry.strftime("%Y-%m-%d")
                            prev = old.get(s, {}).get(key)
                            if not full and _reusable(prev):
                                fresh[s][key] = prev
                            else:
                                futures[s] = (key, prev, pool.submit(task, s, expiry))
                        for s, (key, prev, f) in futures.items():
                            row = f.result()
                            fetched = True
                            # A failed fetch keeps the last good row rather than replacing it with an error.
                            keep = row.get("action") == "ERROR" and prev and prev.get("action") != "ERROR"
                            fresh[s][key] = prev if keep else row
                    for s in chunk:
                        merge(s)
                        self.state["done"] += 1
                    self._publish(rows=True)
                    if fetched:
                        time.sleep(config.SCREEN_BATCH_PAUSE_SECONDS)
        except Exception as e:
            self.state["error"] = str(e)
        finally:
            self.state.update(running=False, finished_at=time.time())
            self._publish(rows=True)
            try:
                self._save_cache()
            except Exception:
                pass

    def snapshot(self) -> list[dict]:
        return _flatten(self.order, self.results)

    def get(self, symbol: str, expiry: str | None = None) -> dict | None:
        return risk_rules.pick_cycle(self.results.get(symbol), expiry)


class ScreenReader:
    """The API's view of the worker's screen. Parses the big row blob only when its version
    changes. With Redis down it serves the last screen saved on disk."""

    def __init__(self):
        self._rows = {"version": None, "order": [], "results": {}}

    @property
    def state(self) -> dict:
        meta = cache.get_json(META)
        if meta:
            return meta
        saved = _read_file() or {}
        return {**_empty_state(), "finished_at": saved.get("finished_at"), "span_source": saved.get("span_source"),
                "done": len(saved.get("order", [])), "total": len(saved.get("order", [])), "version": "file"}

    def _load(self) -> dict:
        version = self.state.get("version")
        if version != self._rows["version"]:
            data = cache.get_json(LATEST) if version != "file" else None
            data = data or _read_file() or {}
            self._rows = {"version": version, "order": data.get("order", []),
                          "results": _as_lists(data.get("results", {}))}
        return self._rows

    def snapshot(self) -> list[dict]:
        rows = self._load()
        return _flatten(rows["order"], rows["results"])

    def get(self, symbol: str, expiry: str | None = None) -> dict | None:
        return risk_rules.pick_cycle(self._load()["results"].get(symbol), expiry)

    def request_refresh(self) -> None:
        """Asks the worker for an early refresh; it picks this up within a few seconds."""
        cache.set_json(FORCE, time.time(), ttl=600)
