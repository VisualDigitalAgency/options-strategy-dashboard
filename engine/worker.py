"""Background worker: the only process that runs scheduled work.

    python -m engine.worker            # run
    python -m engine.worker --check    # exit 0 if a worker is alive (health check)

Runs the screen refresher, the SL / time-exit / profit-target monitor (which also re-prices
every user's snapshot) and the auto-trade scheduler. The API processes never start these, so
running several API processes can't fire an order twice.

A Redis leader lock (`lock:worker`) makes a second worker wait on standby. The holder renews
it every RENEW_EVERY seconds; if it can't renew, it exits at once rather than risk another
worker taking over while its own loops are still placing orders.
"""

import logging
import os
import sys
import threading
import time

from . import autotrade, cache, config, users, virtual
from .batch import FORCE, ScreenJob
from .brokers.poller import start_poller as start_broker_poller

LOCK_TTL = 60
RENEW_EVERY = 15
RENEW_RETRIES = 4  # at most 4 x 1.5 s timeouts + 3 x 3 s pauses: renewed within ~30 s, well inside LOCK_TTL
HEARTBEAT = "worker:heartbeat"
log = logging.getLogger("theta.worker")


def screen_interval() -> int:
    near_market = virtual.market_open() or virtual.market_window()
    return config.SCREEN_REFRESH_MARKET_SECONDS if near_market else config.SCREEN_REFRESH_OFF_SECONDS


def start_screen_refresher(job: ScreenJob) -> None:
    def loop():
        while True:
            try:
                if cache.exists(FORCE) and not job.state["running"]:
                    cache.delete(FORCE)
                    job.ensure(force=True, ttl=0, full=True)  # the Refresh button refetches everything
                finished = job.state["finished_at"]
                if not job.state["running"] and (not finished or time.time() - finished >= screen_interval()):
                    job.ensure(force=True, ttl=0)
            except Exception:
                log.exception("screen refresher pass failed")
            time.sleep(5)

    threading.Thread(target=loop, daemon=True, name="screen-refresher").start()


def fresh_screen(job: ScreenJob, timeout: float = 900) -> list[dict]:
    """Blocks until a complete screen no older than the refresh interval exists, then returns it."""
    job.ensure(ttl=screen_interval())
    start = time.time()
    while job.state["running"]:
        if time.time() - start > timeout:
            raise TimeoutError("Screen did not finish in time")
        time.sleep(2)
    return job.snapshot()


def _hold(lock: cache.Lock) -> None:
    """Renews the leader lock and heartbeat. Losing the lock ends the process."""
    while True:
        time.sleep(RENEW_EVERY)
        # A renew answers 0 either because another worker owns the lock (exit now) or because Redis
        # hiccupped. The lock lasts LOCK_TTL, so a few quick retries are still safely inside it.
        for _ in range(RENEW_RETRIES):
            if lock.renew():
                break
            time.sleep(3)
        else:
            log.critical("lost the worker lock; exiting so two workers never trade at once")
            os._exit(1)
        cache.set_json(HEARTBEAT, {"at": time.time(), "pid": os.getpid()}, ttl=LOCK_TTL)


def healthy() -> bool:
    """Container health check: a worker holds the lock and renewed its heartbeat recently."""
    beat = cache.get_json(HEARTBEAT)
    return bool(beat) and time.time() - beat["at"] < LOCK_TTL


def main() -> None:
    if "--check" in sys.argv:
        sys.exit(0 if healthy() else 1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    lock = cache.Lock("worker", LOCK_TTL)
    waited = False
    while not lock.acquire():
        if not waited:
            log.info("another worker holds the lock (or Redis is unreachable); standing by")
            waited = True
        time.sleep(10)
    cache.set_json(HEARTBEAT, {"at": time.time(), "pid": os.getpid()}, ttl=LOCK_TTL)
    log.info("worker lock acquired (pid %s)", os.getpid())

    users.bootstrap_local_user()
    job = ScreenJob()
    start_screen_refresher(job)
    virtual.start_monitor()
    autotrade.start_scheduler(lambda: fresh_screen(job))
    start_broker_poller()
    _hold(lock)


if __name__ == "__main__":
    main()
