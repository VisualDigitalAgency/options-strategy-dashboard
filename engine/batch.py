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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import cache, config, data_fetch, risk_rules, span

CACHE_FILE = Path(__file__).parent / "cache" / "screen.json"
LATEST, META, FORCE = "screen:latest", "screen:meta", "screen:force"
STATE_KEYS = ("running", "done", "total", "batch", "batches", "started_at", "finished_at", "span_source", "error")


def _empty_state() -> dict:
    return {"running": False, "done": 0, "total": 0, "batch": 0, "batches": 0,
            "started_at": None, "finished_at": None, "span_source": None, "error": None}


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
        self.results: dict[str, dict] = {}
        self.order: list[str] = []
        self.state = _empty_state()
        self._version = ""
        self._load_cache()

    def _load_cache(self) -> None:
        saved = _read_file()
        if saved:
            self.results, self.order = saved["results"], saved["order"]
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

    def ensure(self, force: bool = False, ttl: float = 600) -> None:
        """Start a screen unless one is running or the last one is still fresh."""
        with self._lock:
            if self.state["running"]:
                return
            finished = self.state["finished_at"]
            if not force and finished and time.time() - finished < ttl:
                return
            self.state.update(running=True, done=0, batch=0, error=None, started_at=time.time())
            self._publish(rows=False)
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            symbols = risk_rules.get_universe()
            size = config.SCREEN_BATCH_SIZE
            batches = [symbols[i : i + size] for i in range(0, len(symbols), size)]
            # Keep old rows visible during the refresh; drop only stocks that left the index.
            self.order = symbols
            self.results = {s: r for s, r in self.results.items() if s in symbols}
            self.state.update(total=len(symbols), batches=len(batches))
            try:
                self.state["span_source"] = span.load(symbols)["source"]
            except Exception as e:
                self.state["span_source"] = f"unavailable: {e}"

            for n, batch in enumerate(batches, start=1):
                self.state["batch"] = n
                yf_syms = [f"{s}.NS" for s in batch]
                try:
                    histories = data_fetch.fetch_price_history_batch(yf_syms, config.SR_LOOKBACK_DAYS)
                except Exception:
                    histories = {}  # evaluate_symbol falls back to a per-stock fetch
                with ThreadPoolExecutor(max_workers=config.SCREEN_WORKERS) as pool:
                    futures = {s: pool.submit(risk_rules.safe_evaluate, s, histories.get(f"{s}.NS")) for s in batch}
                    for s, f in futures.items():
                        r = f.result()
                        # A failed fetch keeps the last good result rather than replacing it with an error.
                        if r.get("action") != "ERROR" or s not in self.results or self.results[s].get("action") == "ERROR":
                            self.results[s] = r
                        self.state["done"] += 1
                self._publish(rows=True)
                if n < len(batches):
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
        return [self.results[s] for s in self.order if s in self.results]

    def get(self, symbol: str) -> dict | None:
        return self.results.get(symbol)


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
            self._rows = {"version": version, "order": data.get("order", []), "results": data.get("results", {})}
        return self._rows

    def snapshot(self) -> list[dict]:
        rows = self._load()
        return [rows["results"][s] for s in rows["order"] if s in rows["results"]]

    def get(self, symbol: str) -> dict | None:
        return self._load()["results"].get(symbol)

    def request_refresh(self) -> None:
        """Asks the worker for an early refresh; it picks this up within a few seconds."""
        cache.set_json(FORCE, time.time(), ttl=600)
