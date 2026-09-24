"""Background batch screener.

Splits the universe into batches. Per batch: one yfinance call for all price
histories, then NSE option chains with a small worker pool. Results are published
as each batch finishes, so the dashboard can render progressively.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, data_fetch, risk_rules, span


class ScreenJob:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.results: dict[str, dict] = {}
        self.order: list[str] = []
        self.state = {
            "running": False, "done": 0, "total": 0, "batch": 0, "batches": 0,
            "started_at": None, "finished_at": None, "span_source": None, "error": None,
        }

    def ensure(self, force: bool = False, ttl: float = 600) -> None:
        """Start a screen unless one is running or the last one is still fresh."""
        with self._lock:
            if self.state["running"]:
                return
            finished = self.state["finished_at"]
            if not force and finished and time.time() - finished < ttl:
                return
            self.state.update(running=True, done=0, batch=0, error=None, started_at=time.time())
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            symbols = risk_rules.get_universe()
            size = config.SCREEN_BATCH_SIZE
            batches = [symbols[i : i + size] for i in range(0, len(symbols), size)]
            self.order = symbols
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
                        self.results[s] = f.result()
                        self.state["done"] += 1
                if n < len(batches):
                    time.sleep(config.SCREEN_BATCH_PAUSE_SECONDS)
        except Exception as e:
            self.state["error"] = str(e)
        finally:
            self.state.update(running=False, finished_at=time.time())

    def snapshot(self) -> list[dict]:
        return [self.results[s] for s in self.order if s in self.results]

    def get(self, symbol: str) -> dict | None:
        return self.results.get(symbol)
