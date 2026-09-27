"""Accounts, passwords, sessions and the audit log.

- Passwords: argon2id (64 MB, 3 passes). Plain passwords never reach logs, Redis or the DB.
- Sessions: a random 256-bit token in an HttpOnly cookie. Redis keeps only its SHA-256
  (`sess:{hash}`), so a Redis dump holds no usable cookies. 7-day sliding expiry, 30-day cap.
  `user_sess:{id}` lists a user's sessions so disable, reject or a password change ends all.
- Login limits: 5 failures per email + IP pair and 30 per IP in 15 minutes. Keyed on the pair so
  a stranger can't lock the admin out by guessing wrong. No sleep-based delay: with 12 request
  slots, a handful of parallel slow logins would stall the site for everyone.
- Sign-in never reveals whether an email is registered or what state it is in until the
  correct password is given. Sign-up does say an email is taken: one account per person
  matters more here than hiding who has signed up.
"""

import hashlib
import json
import re
import secrets
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.exc import IntegrityError

from . import cache, db, users

_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
_DUMMY_HASH = _ph.hash(secrets.token_hex(16))  # verify against this for unknown emails: same timing

SESSION_DAYS, SESSION_CAP_DAYS = 7, 30
FAIL_WINDOW = 15 * 60
FAILS_PER_PAIR, FAILS_PER_IP = 5, 30
SIGNUPS_PER_IP = 5  # per hour
MIN_PASSWORD = 10
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$")
STATUSES = ("pending", "active", "rejected", "disabled")
WRONG = "Email or password is wrong"


class AuthError(ValueError):
    """A message safe to show the user. Subclass of ValueError, so the RPC layer shows it."""


# ---------- passwords ----------

def _word_list(name: str) -> set[str]:
    """A bundled list, one entry per line. Drop a bigger list into the same file to extend it."""
    try:
        text = (Path(__file__).parent / name).read_text(encoding="utf-8")
        return {w.strip().lower() for w in text.splitlines() if w.strip() and not w.startswith("#")}
    except OSError:
        return set()


COMMON = _word_list("common_passwords.txt")
DISPOSABLE = _word_list("disposable_domains.txt")
TAKEN = "An account with this email already exists. Sign in instead, or ask the admin to reset your password"


def check_password(password: str, email: str = "", name: str = "") -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AuthError(f"Use at least {MIN_PASSWORD} characters")
    if len(password) > 256:
        raise AuthError("Use at most 256 characters")
    low = password.lower()
    if low in COMMON or re.sub(r"[\d\W_]+$", "", low) in COMMON:
        raise AuthError("That password is on the list of common passwords; pick another")
    if len(set(low)) < 4:
        raise AuthError("Use more different characters")
    local = email.split("@")[0].lower()
    if (len(local) >= 4 and local in low) or (name and len(name) >= 4 and name.lower().replace(" ", "") in low):
        raise AuthError("Leave your name and email out of the password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def _verify(stored: str | None, password: str) -> bool:
    try:
        return _ph.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


# ---------- audit ----------

def audit(action: str, actor_id: int | None = None, target_user_id: int | None = None,
          ip: str | None = None, **detail) -> None:
    with db.tx() as c:
        c.run("INSERT INTO audit_log (actor_id, action, target_user_id, ip, detail) "
              "VALUES (:a, :act, :t, CAST(:ip AS inet), CAST(:d AS jsonb))",
              a=actor_id, act=action, t=target_user_id, ip=ip, d=json.dumps(detail))


# ---------- sessions ----------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _store(h: str, sess: dict) -> None:
    left = sess["created"] + SESSION_CAP_DAYS * 86400 - time.time()
    cache.set_json(f"sess:{h}", sess, ttl=max(1, min(SESSION_DAYS * 86400, left)))


def new_session(user_id: int, ip: str | None, ua: str | None) -> str:
    """Returns the raw token for the cookie. Only its hash is stored."""
    if not cache.up():
        raise AuthError("Sign-in is unavailable right now; try again in a minute")
    token = secrets.token_urlsafe(32)
    h = _hash(token)
    now = time.time()
    _store(h, {"user_id": user_id, "created": now, "seen": now, "ip": ip, "ua": (ua or "")[:200]})
    cache._call(lambda r: r.sadd(f"user_sess:{user_id}", h))
    return token


def session_user(token: str | None) -> int | None:
    """The user a cookie belongs to, sliding its expiry. None if missing, expired or ended."""
    if not token or len(token) > 100:
        return None
    h = _hash(token)
    sess = cache.get_json(f"sess:{h}")
    if not sess:
        return None
    if time.time() - sess.get("seen", 0) > 60:  # write at most once a minute per session
        sess["seen"] = time.time()
        _store(h, sess)
    return sess["user_id"]


def end_session(token: str | None) -> None:
    if not token:
        return
    h = _hash(token)
    sess = cache.get_json(f"sess:{h}")
    cache.delete(f"sess:{h}")
    if sess:
        cache._call(lambda r: r.srem(f"user_sess:{sess['user_id']}", h))


def end_all_sessions(user_id: int, keep: str | None = None) -> int:
    keep_h = _hash(keep) if keep else None
    hashes = cache._call(lambda r: r.smembers(f"user_sess:{user_id}"), set()) or set()
    ended = 0
    for h in hashes:
        if h != keep_h:
            cache.delete(f"sess:{h}")
            cache._call(lambda r, h=h: r.srem(f"user_sess:{user_id}", h))
            ended += 1
    return ended


# ---------- login limits ----------

def _fail_keys(email: str, ip: str | None) -> tuple[str, str]:
    return f"rl:login:{_hash(email + '|' + (ip or '-'))}", f"rl:loginip:{ip or '-'}"


def _count(key: str) -> int:
    return int(cache._call(lambda r: r.get(key), 0) or 0)


def _reserve_attempt(email: str, ip: str | None) -> None:
    """Counts this attempt before the password is checked, then refuses if it is over a limit.
    Checking first and counting only failures let parallel requests all pass the check before
    any of them was counted, so a burst could try far more than FAILS_PER_PAIR passwords."""
    counts = []
    for key in _fail_keys(email, ip):
        n = cache._call(lambda r, k=key: r.incr(k))
        cache._call(lambda r, k=key: r.expire(k, FAIL_WINDOW, nx=True))
        counts.append(int(n or 0))
    pair, per_ip = counts
    if pair > FAILS_PER_PAIR or per_ip > FAILS_PER_IP:
        raise AuthError("Too many failed sign-ins. Wait 15 minutes and try again")


def _release_attempt(email: str, ip: str | None) -> None:
    """A successful sign-in isn't a failure: clear the pair and give the IP its attempt back."""
    pair, per_ip = _fail_keys(email, ip)
    cache.delete(pair)
    cache._call(lambda r: r.decr(per_ip) if (int(r.get(per_ip) or 0)) > 0 else None)


# ---------- account flows ----------

def _clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address")
    return email


def device_owners(device: str | None) -> list[dict]:
    """Users who registered or signed in from this browser."""
    if not device:
        return []
    with db.tx() as c:
        return c.all("SELECT u.id, u.name, u.status FROM user_devices d JOIN users u ON u.id = d.user_id "
                     "WHERE d.device_hash=:d", d=device)


def see_device(user_id: int, device: str | None, ip: str | None) -> None:
    if device:
        with db.tx() as c:
            c.run("INSERT INTO user_devices (user_id, device_hash, last_ip) VALUES (:u, :d, CAST(:ip AS inet)) "
                  "ON CONFLICT (user_id, device_hash) DO UPDATE SET last_seen=now(), last_ip=EXCLUDED.last_ip",
                  u=user_id, d=device, ip=ip)


def register(name: str, email: str, password: str, ip: str | None = None, device: str | None = None) -> dict:
    """Creates a pending account. One account per person:
      - an email already registered is refused, including other spellings of the same
        mailbox (Gmail dots, +tags)
      - throwaway inbox domains are refused
      - a browser that already holds an account can't request another
    Accounts that share a network with another are flagged for the admin (list_users)."""
    email = _clean_email(email)
    name = " ".join((name or "").split())[:80]
    if len(name) < 2:
        raise AuthError("Enter your name")
    if email.split("@")[1] in DISPOSABLE:
        raise AuthError("Use a permanent email address, not a temporary inbox")
    with db.tx() as c:
        existing = c.value("SELECT id FROM users WHERE email_canonical=:ce", ce=users.canonical_email(email))
    if existing:
        audit("register_duplicate", target_user_id=existing, ip=ip, email=email)
        raise AuthError(TAKEN)
    owners = device_owners(device)
    if owners:
        audit("register_same_device", ip=ip, email=email, existing=[o["id"] for o in owners])
        raise AuthError("This browser already has an account. Sign in with it, or ask the admin for help")
    check_password(password, email, name)
    # Counted only once the form is valid, so typos never lock anyone out.
    key = f"rl:register:{ip or '-'}"
    if _count(key) >= SIGNUPS_PER_IP:
        raise AuthError("Too many sign-ups from this network. Try again in an hour")
    cache._call(lambda r: (r.incr(key), r.expire(key, 3600, nx=True)))
    try:
        uid = users.create_user(email, name, status="pending", ip=ip)
    except IntegrityError:  # the same mailbox registered a moment ago, between the check and here
        raise AuthError(TAKEN)
    with db.tx() as c:
        c.run("UPDATE users SET password_hash=:h WHERE id=:u", h=hash_password(password), u=uid)
    see_device(uid, device, ip)
    audit("register", target_user_id=uid, ip=ip)
    return {"message": "Thanks. Your request is waiting for approval. Sign in once an admin has approved it."}


def login(email: str, password: str, ip: str | None = None, ua: str | None = None,
          device: str | None = None) -> tuple[str, dict]:
    email = (email or "").strip().lower()
    _reserve_attempt(email, ip)
    with db.tx() as c:
        u = c.one("SELECT id, name, email, role, status, password_hash, must_change_password "
                  "FROM users WHERE email=:e", e=email)
    if not _verify(u["password_hash"] if u else None, password or ""):
        audit("login_failed", target_user_id=u["id"] if u else None, ip=ip)
        raise AuthError(WRONG)
    _release_attempt(email, ip)
    # Correct password: only now is it safe to say what state the account is in.
    if u["status"] != "active":
        audit("login_blocked", target_user_id=u["id"], ip=ip, status=u["status"])
        raise AuthError({"pending": "Your account is waiting for approval",
                         "rejected": "This sign-up request was not approved",
                         "disabled": "This account is disabled. Contact the admin"}[u["status"]])
    if _ph.check_needs_rehash(u["password_hash"]):
        with db.tx() as c:
            c.run("UPDATE users SET password_hash=:h WHERE id=:u", h=hash_password(password), u=u["id"])
    token = new_session(u["id"], ip, ua)
    see_device(u["id"], device, ip)
    with db.tx() as c:
        c.run("UPDATE users SET last_login_at=now() WHERE id=:u", u=u["id"])
    audit("login", actor_id=u["id"], target_user_id=u["id"], ip=ip)
    return token, me(u["id"])


def me(user_id: int) -> dict:
    with db.tx() as c:
        u = c.one("SELECT id, name, email, role, status, must_change_password, created_at FROM users WHERE id=:u",
                  u=user_id)
    with db.tx(user_id) as c:
        prefs = c.one("SELECT theme, palette FROM user_prefs WHERE user_id=:u", u=user_id) or {}
    return {**u, "prefs": {"theme": prefs.get("theme"), "palette": prefs.get("palette")}}


def active_user(user_id: int | None) -> dict | None:
    """Loaded on every request, so a disabled user is out on their very next click."""
    if user_id is None:
        return None
    with db.tx() as c:
        u = c.one("SELECT id, role, status, must_change_password FROM users WHERE id=:u", u=user_id)
    return u if u and u["status"] == "active" else None


def change_password(user_id: int, current: str, new: str, token: str | None, ip: str | None = None) -> dict:
    with db.tx() as c:
        u = c.one("SELECT email, name, password_hash FROM users WHERE id=:u", u=user_id)
    if not _verify(u["password_hash"], current or ""):
        audit("password_change_failed", actor_id=user_id, target_user_id=user_id, ip=ip)
        raise AuthError("Current password is wrong")
    if new == current:
        raise AuthError("Pick a password you haven't used here")
    check_password(new, u["email"], u["name"])
    with db.tx() as c:
        c.run("UPDATE users SET password_hash=:h, must_change_password=false WHERE id=:u",
              h=hash_password(new), u=user_id)
    ended = end_all_sessions(user_id, keep=token)  # other devices sign in again with the new password
    audit("password_changed", actor_id=user_id, target_user_id=user_id, ip=ip, other_sessions_ended=ended)
    return me(user_id)


def set_prefs(user_id: int, theme: str | None, palette: str | None) -> dict:
    if theme is not None and theme not in ("light", "dark"):
        raise AuthError("Theme must be light or dark")
    if palette is not None and not re.fullmatch(r"[a-z]{2,20}", palette):
        raise AuthError("Unknown palette")
    with db.tx(user_id) as c:
        c.run("INSERT INTO user_prefs (user_id, theme, palette) VALUES (:u, :t, :p) "
              "ON CONFLICT (user_id) DO UPDATE SET theme=COALESCE(:t, user_prefs.theme), "
              "palette=COALESCE(:p, user_prefs.palette)", u=user_id, t=theme, p=palette)
    return me(user_id)["prefs"]


# ---------- admin ----------

def list_users() -> list[dict]:
    """Every user, pending first. Each carries `links`: other accounts that share a browser or a
    network with it, so the admin sees a likely second account before approving it."""
    with db.tx() as c:
        rows = c.all("SELECT u.id, u.name, u.email, u.role, u.status, u.created_at, u.approved_at, "
                     "u.last_login_at, u.must_change_password, a.name AS approved_by_name "
                     "FROM users u LEFT JOIN users a ON a.id = u.approved_by "
                     "ORDER BY CASE u.status WHEN 'pending' THEN 0 ELSE 1 END, u.created_at DESC")
        same_device = c.all("SELECT DISTINCT a.user_id AS id, b.user_id AS other FROM user_devices a "
                            "JOIN user_devices b ON a.device_hash = b.device_hash AND a.user_id <> b.user_id")
        # Networks: the sign-up IP plus every IP the user signed in from.
        same_ip = c.all("""
            WITH ips AS (
              SELECT id AS user_id, signup_ip AS ip FROM users WHERE signup_ip IS NOT NULL
              UNION SELECT user_id, last_ip FROM user_devices WHERE last_ip IS NOT NULL
              UNION SELECT target_user_id, ip FROM audit_log WHERE action = 'login' AND ip IS NOT NULL)
            SELECT DISTINCT a.user_id AS id, b.user_id AS other, host(a.ip) AS ip FROM ips a
            JOIN ips b ON a.ip = b.ip AND a.user_id <> b.user_id""")
    names = {r["id"]: r["name"] for r in rows}
    links: dict[int, list] = {}
    for kind, pairs in (("browser", same_device), ("network", same_ip)):
        for p in pairs:
            have = links.setdefault(p["id"], [])
            if not any(e["kind"] == kind and e["user_id"] == p["other"] for e in have):
                have.append({"kind": kind, "user_id": p["other"], "name": names.get(p["other"], "?"), "ip": p.get("ip")})
    for r in rows:
        r["links"] = links.get(r["id"], [])
    return rows


def set_status(admin_id: int, target_id: int, status: str, ip: str | None = None) -> dict:
    if status not in STATUSES or status == "pending":
        raise AuthError("Status must be active, rejected or disabled")
    if target_id == admin_id:
        raise AuthError("You can't change your own status")
    with db.tx() as c:
        old = c.value("SELECT status FROM users WHERE id=:u", u=target_id)
        if old is None:
            raise AuthError("User not found")
        c.run("UPDATE users SET status=:s, approved_by=CASE WHEN :s='active' THEN :a ELSE approved_by END, "
              "approved_at=CASE WHEN :s='active' AND approved_at IS NULL THEN now() ELSE approved_at END "
              "WHERE id=:u", s=status, a=admin_id, u=target_id)
    ended = end_all_sessions(target_id) if status != "active" else 0
    audit(f"user_{status}", actor_id=admin_id, target_user_id=target_id, ip=ip, was=old, sessions_ended=ended)
    return {"id": target_id, "status": status, "sessions_ended": ended}


def reset_password(admin_id: int, target_id: int, ip: str | None = None) -> dict:
    """One-time temporary password, shown to the admin once. The user must change it on sign-in."""
    temp = "-".join(secrets.token_urlsafe(4) for _ in range(3))
    with db.tx() as c:
        n = c.run("UPDATE users SET password_hash=:h, must_change_password=true WHERE id=:u",
                  h=hash_password(temp), u=target_id)
    if not n:
        raise AuthError("User not found")
    ended = end_all_sessions(target_id)
    audit("password_reset", actor_id=admin_id, target_user_id=target_id, ip=ip, sessions_ended=ended)
    return {"id": target_id, "temporary_password": temp}
