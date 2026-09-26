"""Redis: shared caches, locks and throttles for the API processes and the worker.

Redis only ever holds data that can be rebuilt (screens, quotes, snapshots) plus locks.
Every helper fails soft: if Redis is down, reads return None and writes are dropped, so
callers fall back to Postgres or a live fetch. Locks are the exception: without Redis a
lock can't be taken, so work that needs one waits instead of running twice.

Connection settings: engine/settings.py.
"""

import json
import secrets
import time

import redis

from . import settings

REDIS_URL = settings.redis_url()

_client = None
_down_until = 0.0  # after a failure, skip Redis for a few seconds instead of timing out on every call


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, socket_timeout=1.5, socket_connect_timeout=1.5,
                                       health_check_interval=30, decode_responses=True)
    return _client


def _call(fn, default=None, *, bypass_breaker: bool = False):
    global _down_until
    if time.monotonic() < _down_until and not bypass_breaker:
        return default
    try:
        return fn(client())
    except redis.RedisError:
        _down_until = time.monotonic() + 5
        return default


def up() -> bool:
    return bool(_call(lambda r: r.ping(), False))


def get_json(key: str):
    raw = _call(lambda r: r.get(key))
    return json.loads(raw) if raw else None


def set_json(key: str, value, ttl: float | None = None) -> bool:
    raw = json.dumps(value, default=str)
    return bool(_call(lambda r: r.set(key, raw, px=int(ttl * 1000) if ttl else None), False))


def delete(key: str) -> None:
    _call(lambda r: r.delete(key))


def ttl_left(key: str) -> float:
    ms = _call(lambda r: r.pttl(key), -2)
    return max(0.0, ms / 1000) if ms and ms > 0 else 0.0


def exists(key: str) -> bool:
    return bool(_call(lambda r: r.exists(key), 0))


# ---------- locks ----------

_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_RENEW = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"


class Lock:
    """SET NX PX lock with an owner token, so only the holder can renew or release it."""

    def __init__(self, name: str, ttl: float):
        self.key, self.ttl_ms, self.token = f"lock:{name}", int(ttl * 1000), secrets.token_hex(16)

    def acquire(self) -> bool:
        return bool(_call(lambda r: r.set(self.key, self.token, nx=True, px=self.ttl_ms), False))

    def renew(self) -> bool:
        # Always really asks Redis: one slow write elsewhere in the process (which trips the
        # breaker) mustn't look like a lost lock.
        return bool(_call(lambda r: r.eval(_RENEW, 1, self.key, self.token, self.ttl_ms), 0, bypass_breaker=True))

    def release(self) -> None:
        _call(lambda r: r.eval(_RELEASE, 1, self.key, self.token))

    def held_by_anyone(self) -> bool:
        return exists(self.key)


# ---------- throttle ----------

_DOWN = object()


class Throttle:
    """Minimum gap between calls per key, shared by every API process. Falls back to an
    in-process table if Redis is down, so the limit still holds per process."""

    def __init__(self):
        self._local: dict[str, float] = {}

    def allow(self, key: str, every_seconds: float) -> bool:
        # SET NX answers None when the key exists, so "Redis down" needs its own marker.
        ok = _call(lambda r: r.set(f"rl:{key}", 1, nx=True, px=int(every_seconds * 1000)), _DOWN)
        if ok is not _DOWN:
            return bool(ok)
        now = time.monotonic()
        if now - self._local.get(key, -1e9) < every_seconds:
            return False
        self._local[key] = now
        return True

    def wait_left(self, key: str, every_seconds: float) -> int:
        if up():
            return int(round(ttl_left(f"rl:{key}")))
        return max(0, int(every_seconds - (time.monotonic() - self._local.get(key, -1e9))))
