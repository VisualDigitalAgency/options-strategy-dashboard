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
from datetime import datetime, timedelta

from . import autotrade, cache, config, leaderboard, market_calendar, nifty, nudges, prizes, progress, recap, users, virtual
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


def _session_bounds(day: datetime) -> tuple[datetime, datetime]:
    """The screen window (pre-open to a little after the close) on `day`, in IST."""
    at = lambda h, m: day.replace(hour=h, minute=m, second=0, microsecond=0)
    return at(*config.SCREEN_WINDOW_OPEN), at(*config.SCREEN_WINDOW_CLOSE)


def next_screen_at(finished: float | None, now: float | None = None, holidays: set[str] | None = None) -> float:
    """When the next scheduled screen is due. Inside the trading-day window: every SCREEN_REFRESH_MARKET_SECONDS.
    Outside it the chains are frozen, so one screen after the close and then nothing until the next
    pre-open (weekends and NSE holidays skipped). The Refresh button still works any time."""
    if not finished:
        return 0.0
    now = time.time() if now is None else now
    if holidays is None:
        holidays = market_calendar.holiday_dates()
    closed = lambda d: d.weekday() >= 5 or d.strftime("%Y-%m-%d") in holidays
    today = datetime.fromtimestamp(now, virtual.IST)
    opens, closes = _session_bounds(today)
    if not closed(today) and opens <= today < closes:
        return finished + config.SCREEN_REFRESH_MARKET_SECONDS
    # Last close at or before now: catch up once if the screen predates it.
    day = today
    while closed(day) or _session_bounds(day)[1] > today:
        day -= timedelta(days=1)
    last_close = _session_bounds(day)[1].timestamp()
    if finished < last_close:
        return last_close
    day = today if today < opens else today + timedelta(days=1)
    while closed(day):
        day += timedelta(days=1)
    return _session_bounds(day)[0].timestamp()


def start_screen_refresher(job: ScreenJob) -> None:
    def loop():
        while True:
            try:
                if cache.exists(FORCE) and not job.state["running"]:
                    cache.delete(FORCE)
                    job.ensure(force=True, ttl=0, full=True)  # the Refresh button refetches everything
                if not job.state["running"] and time.time() >= next_screen_at(job.state["finished_at"]):
                    job.ensure(force=True, ttl=0)
            except Exception:
                log.exception("screen refresher pass failed")
            time.sleep(5)

    threading.Thread(target=loop, daemon=True, name="screen-refresher").start()


def start_progress_evaluator() -> None:
    """Learning-path levels (#122): every active user once a night, after the session (18:00 IST).
    Levels also update whenever a user opens their progress, so this only catches the quiet ones."""
    def loop():
        done = None
        while True:
            now = datetime.now(virtual.IST)
            if now.hour >= 18 and done != now.date():
                try:
                    log.info("progress: %s users levelled up", progress.evaluate_all())
                except Exception:
                    log.exception("progress evaluation failed")
                done = now.date()
            time.sleep(600)

    threading.Thread(target=loop, daemon=True, name="progress-evaluator").start()


def start_nudger() -> None:
    """Day-before email nudges (retention plan, phase 1): once a day from NUDGE_HOUR_IST."""
    def loop():
        done = None
        while True:
            now = datetime.now(virtual.IST)
            if now.hour >= config.NUDGE_HOUR_IST and done != now.date():
                try:
                    log.info("nudges: %s emails sent", nudges.send_all(now.date()))
                except Exception:
                    log.exception("nudges failed")
                done = now.date()
            time.sleep(600)

    threading.Thread(target=loop, daemon=True, name="nudger").start()


def start_leaderboard_finalizer() -> None:
    """Monthly leaderboard (#125): freezes the month just ended, from the 1st (IST) on. Checked every
    10 minutes, so a worker that was down on the 1st catches up when it returns."""
    def loop():
        done = None
        while True:
            month = leaderboard.previous_month()
            if done != month:
                try:
                    if month not in leaderboard.finalized_months():
                        log.info("leaderboard: %s rows for %s", leaderboard.finalize(month), month)
                        log.info("season: %s champions given Pro", leaderboard.award_champions(month))
                        log.info("prize draw: winners %s", prizes.draw(month))  # no-op while the setting is off
                        log.info("recap: %s emails for %s", recap.send_all(month), month)
                    done = month
                except Exception:
                    log.exception("leaderboard finalize failed")
            time.sleep(600)

    threading.Thread(target=loop, daemon=True, name="leaderboard-finalizer").start()


def start_calendar_refresher() -> None:
    """Holidays and corporate events, once a day outside the market window (a few paced NSE calls)."""
    def loop():
        while True:
            try:
                # Outside the window, or right away when there's no copy at all (e.g. first deploy).
                if market_calendar.due() and (not virtual.market_window() or not market_calendar.load()["fetched_at"]):
                    market_calendar.refresh()
            except Exception:
                log.exception("market calendar refresh failed")
            time.sleep(300)

    threading.Thread(target=loop, daemon=True, name="calendar-refresher").start()


def start_nifty_refresher() -> None:
    """Nifty's monthly ranges for the Level 6 gate (#146): one yfinance call a day."""
    def loop():
        while True:
            try:
                if nifty.due():
                    nifty.refresh()
            except Exception:
                log.exception("nifty refresh failed")
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name="nifty-refresher").start()


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
    start_calendar_refresher()
    start_nifty_refresher()
    start_progress_evaluator()
    start_leaderboard_finalizer()
    start_nudger()
    virtual.start_monitor()
    autotrade.start_scheduler(lambda: fresh_screen(job))
    start_broker_poller()
    _hold(lock)


if __name__ == "__main__":
    main()
