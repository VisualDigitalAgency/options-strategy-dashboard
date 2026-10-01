"""Accounts, passwords, sessions and the audit log.

- Passwords: argon2id (64 MB, 3 passes). Plain passwords never reach logs, Redis or the DB.
- Sessions: a random 256-bit token in an HttpOnly cookie. Redis keeps only its SHA-256
  (`sess:{hash}`), so a Redis dump holds no usable cookies. 7-day sliding expiry, 30-day cap.
  `user_sess:{id}` lists a user's sessions so disable, reject or a password change ends all.
  Expired hashes are pruned at each sign-in, and the set expires with the 30-day cap.
- Login limits: 5 failures per email + IP pair and 30 per IP in 15 minutes. Keyed on the pair so
  a stranger can't lock the admin out by guessing wrong. No sleep-based delay: with 12 request
  slots, a handful of parallel slow logins would stall the site for everyone.
- Sign-up email check (#45): a new account is `unverified` until the 6-digit code emailed to it
  is entered, then `pending` for the admin. Codes are stored hashed, expire in 10 minutes and
  allow 5 wrong guesses; at most 5 codes per account per day, and throttled per IP (engine/mail.py
  sends). The admin only sees confirmed requests. Unconfirmed after 14 days: blocked, row kept.
- Sign-in never reveals whether an email is registered or what state it is in until the
  correct password is given. Sign-up does say an email is taken: one account per person
  matters more here than hiding who has signed up.
"""

import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.exc import IntegrityError

from . import app_settings, cache, db, mail, permissions, users

_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
_DUMMY_HASH = _ph.hash(secrets.token_hex(16))  # verify against this for unknown emails: same timing

SESSION_DAYS, SESSION_CAP_DAYS = 7, 30
FAIL_WINDOW = 15 * 60
FAILS_PER_PAIR, FAILS_PER_IP = 5, 30
SIGNUPS_PER_IP = 5  # per hour
MIN_PASSWORD = 10
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$")
STATUSES = ("unverified", "pending", "active", "rejected", "disabled")
CODE_TTL = 10 * 60  # sign-up email code lifetime
CODE_TRIES = 5  # wrong guesses per code
RESEND_GAP = 60  # seconds between codes for one account
CODES_PER_IP = 10  # code sends per hour
CODES_PER_DAY = 5  # code sends per account per 24 hours, sign-up code included
CONFIRM_DAYS = 14  # an account not confirmed by then is blocked (kept for reference)
VERIFY_PER_IP = 30  # code checks per 15 minutes
WRONG = "Email or password is wrong"
RESET_TTL = 24 * 3600  # password reset link lifetime (#79)
RESET_GAP = 60  # seconds between reset emails for one account
RESET_PER_IP = 10  # reset requests per hour, per IP


class AuthError(ValueError):
    """A message safe to show the user. Subclass of ValueError, so the RPC layer shows it."""


class EmailUnverified(AuthError):
    """Right password, but the email isn't verified yet: the client shows the code form."""


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
    _index_session(user_id, h)
    return token


def _index_session(user_id: int, h: str) -> None:
    """Adds h to user_sess:{id}, drops hashes whose session already expired, and lets the set
    itself expire with the 30-day cap: no session in it can outlive the newest one."""
    key = f"user_sess:{user_id}"

    def run(r):
        dead = [x for x in r.smembers(key) if not r.exists(f"sess:{x}")]
        p = r.pipeline()
        if dead:
            p.srem(key, *dead)
        p.sadd(key, h).expire(key, SESSION_CAP_DAYS * 86400)
        p.execute()
    cache._call(run)


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
        uid = users.create_user(email, name, status="unverified", ip=ip)
    except IntegrityError:  # the same mailbox registered a moment ago, between the check and here
        raise AuthError(TAKEN)
    with db.tx() as c:
        c.run("UPDATE users SET password_hash=:h WHERE id=:u", h=hash_password(password), u=uid)
    see_device(uid, device, ip)
    audit("register", target_user_id=uid, ip=ip)
    sent = _send_code(uid, email, ip)
    return {"verify": True, "email": email, "message": (
        f"We've emailed a 6-digit code to {email}. Enter it below to confirm your address." if sent else
        "We couldn't send the code just now. Try \"Send a new code\" in a minute.")}


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
    if u["status"] == "unverified":
        audit("login_blocked", target_user_id=u["id"], ip=ip, status=u["status"])
        _maybe_resend(u["id"], ip)  # raises BLOCKED once the CONFIRM_DAYS window has closed
        raise EmailUnverified("Confirm your email to continue. Enter the 6-digit code we emailed you")
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


# ---------- email verification (#45) ----------
# A 6-digit code, stored only as a hash, valid CODE_TTL, CODE_TRIES wrong guesses. Verify and
# resend answer the same way whether or not the email has an unverified account.

BAD_CODE = "That code is wrong or has expired. Check the latest email, or send a new code"


def _code_hash(user_id: int, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def _send_code(user_id: int, email: str, ip: str | None) -> bool:
    code = f"{secrets.randbelow(10 ** 6):06d}"
    with db.tx() as c:
        c.run("UPDATE users SET email_code_hash=:h, email_code_attempts=0, email_code_sent_at=now(), "
              "email_code_expires_at=now() + make_interval(secs => :ttl) WHERE id=:u",
              h=_code_hash(user_id, code), ttl=CODE_TTL, u=user_id)
    try:
        mail.send(email, f"{code} is your Theta Desk code",
                  f"Your Theta Desk verification code is {code}\n\n"
                  f"It expires in {CODE_TTL // 60} minutes. If you didn't sign up, ignore this email.\n")
    except mail.MailError as e:
        audit("mail_failed", target_user_id=user_id, ip=ip, kind="verify_code", error=str(e)[:300])
        return False
    audit("email_code_sent", target_user_id=user_id, ip=ip)
    return True


BLOCKED = "This email is blocked: it wasn't confirmed within 14 days of signing up. Contact support"
DAILY_LIMIT = "Your daily resend limit is reached. Come back later"


def _code_state(user_id: int) -> dict | None:
    """The account's email, whether a new code may go out (RESEND_GAP), how many went out in the
    last 24 hours (sent or failed), and whether the CONFIRM_DAYS window has closed."""
    with db.tx() as c:
        return c.one(
            "SELECT email, status, coalesce(unblocked_at, created_at) < now() - make_interval(days => :d) AS expired, "
            "(email_code_sent_at IS NULL OR email_code_sent_at < now() - make_interval(secs => :g)) AS due, "
            "(SELECT count(*) FROM audit_log l WHERE l.target_user_id = u.id AND "
            " l.action IN ('email_code_sent', 'mail_failed') "
            " AND l.ts > greatest(now() - interval '1 day', coalesce(u.unblocked_at, '-infinity'))) AS today "
            "FROM users u WHERE id=:u", u=user_id, d=CONFIRM_DAYS, g=RESEND_GAP)


def _maybe_resend(user_id: int, ip: str | None, asked: bool = False) -> bool:
    """Sends a fresh code unless the account is blocked, over its daily limit, inside RESEND_GAP,
    or the IP is over its limit. When the user `asked` (the resend button), the daily limit is an
    error they see; on a sign-in it just means no new code. Blocked is always an error."""
    u = _code_state(user_id)
    if not u or u["status"] != "unverified":
        return False
    if u["expired"]:
        raise AuthError(BLOCKED)
    if u["today"] >= CODES_PER_DAY:
        if asked:
            raise AuthError(DAILY_LIMIT)
        return False
    key = f"rl:codes:{ip or '-'}"
    if not u["due"] or _count(key) >= CODES_PER_IP:
        return False
    cache._call(lambda r: (r.incr(key), r.expire(key, 3600, nx=True)))
    return _send_code(user_id, u["email"], ip)


def _unverified_id(email: str) -> int | None:
    with db.tx() as c:
        return c.value("SELECT id FROM users WHERE email=:e AND status='unverified'", e=(email or "").strip().lower())


def resend_code(email: str, ip: str | None = None) -> dict:
    uid = _unverified_id(email)
    if uid:
        _maybe_resend(uid, ip, asked=True)
    return {"message": "If that account is waiting for confirmation, a new code is on its way. "
                       "Codes can be resent once a minute"}


def verify_email(email: str, code: str, ip: str | None = None, ua: str | None = None,
                 device: str | None = None) -> tuple[str | None, dict]:
    """Returns (session token or None, answer). With auto_approve on (#121) a confirmed email is
    enough: the account becomes active and is signed in at once. Off, it waits in `pending`."""
    key = f"rl:verifyip:{ip or '-'}"
    n = cache._call(lambda r: r.incr(key))
    cache._call(lambda r: r.expire(key, FAIL_WINDOW, nx=True))
    if int(n or 0) > VERIFY_PER_IP:
        raise AuthError("Too many tries. Wait 15 minutes and try again")
    code = "".join((code or "").split())
    uid = _unverified_id(email)
    if uid and _code_state(uid)["expired"]:
        raise AuthError(BLOCKED)
    row = None
    if uid and re.fullmatch(r"\d{6}", code):
        with db.tx() as c:  # one UPDATE counts the guess, so parallel guesses can't exceed CODE_TRIES
            row = c.one("UPDATE users SET email_code_attempts = email_code_attempts + 1 "
                        "WHERE id=:u AND email_code_hash IS NOT NULL AND email_code_attempts < :t "
                        "AND email_code_expires_at > now() RETURNING email_code_hash", u=uid, t=CODE_TRIES)
    if not row or not secrets.compare_digest(row["email_code_hash"], _code_hash(uid, code)):
        if uid:
            audit("email_verify_failed", target_user_id=uid, ip=ip)
        raise AuthError(BAD_CODE)
    auto = app_settings.get("auto_approve")
    with db.tx() as c:
        n = c.run("UPDATE users SET status=:s, email_verified_at=now(), email_code_hash=NULL, email_code_expires_at=NULL, "
                  "approved_at=CASE WHEN :s='active' THEN now() END, last_login_at=CASE WHEN :s='active' THEN now() END "
                  "WHERE id=:u AND status='unverified'", s="active" if auto else "pending", u=uid)
    audit("email_verified", target_user_id=uid, ip=ip)
    if not auto or not n:
        return None, {"message": "Email confirmed. Your request is waiting for approval. Sign in once an admin has approved it."}
    audit("user_active", target_user_id=uid, ip=ip, auto=True)
    token = new_session(uid, ip, ua)
    see_device(uid, device, ip)
    audit("login", actor_id=uid, target_user_id=uid, ip=ip)
    return token, {"message": "Email confirmed. Welcome to Theta Desk!", "signed_in": True, "user": me(uid)}


# ---------- forgot password (#79) ----------
# A random, one-time token emailed as a link, valid RESET_TTL. Only its hash is stored,
# mirroring the sign-up code above. request_password_reset always answers the same way whether
# or not the email has an account, so the page can't be used to test which emails are registered.

RESET_BAD = "That reset link is wrong or has expired. Request a new one"


def _reset_token_hash(token: str) -> str:
    return hashlib.sha256(f"reset:{token}".encode()).hexdigest()


def public_url() -> str:
    """The site's public origin, for links that leave the app (reset emails, share cards)."""
    url = os.environ.get("PUBLIC_URL") or os.environ.get("ALLOWED_ORIGINS", "").split(",")[0]
    return (url or "http://localhost:5173").rstrip("/")


def request_password_reset(email: str, ip: str | None = None) -> dict:
    email = (email or "").strip().lower()
    message = {"message": "If that email has an active account, we've sent a link to reset the password. "
                          "It expires in 24 hours."}
    if not EMAIL_RE.match(email):
        return message
    key = f"rl:resetip:{ip or '-'}"
    if _count(key) >= RESET_PER_IP:
        return message
    token = secrets.token_urlsafe(32)
    with db.tx() as c:
        # The gap and status checks live in the WHERE clause, so a second request inside RESET_GAP
        # updates nothing rather than racing the first request's email.
        u = c.one(
            "UPDATE users SET password_reset_token_hash=:h, password_reset_sent_at=now(), "
            "password_reset_expires_at=now() + make_interval(secs => :ttl) "
            "WHERE email=:e AND status='active' AND (password_reset_sent_at IS NULL OR "
            "password_reset_sent_at < now() - make_interval(secs => :gap)) RETURNING id",
            h=_reset_token_hash(token), ttl=RESET_TTL, e=email, gap=RESET_GAP)
    if not u:
        return message
    cache._call(lambda r: (r.incr(key), r.expire(key, 3600, nx=True)))
    link = f"{public_url()}/reset-password?token={token}"
    try:
        mail.send(email, "Reset your Theta Desk password",
                  f"Someone asked to reset the password on this account.\n\n"
                  f"Reset it here (valid 24 hours): {link}\n\n"
                  f"If this wasn't you, ignore this email; your password stays unchanged.\n")
    except mail.MailError as e:
        audit("mail_failed", target_user_id=u["id"], ip=ip, kind="password_reset", error=str(e)[:300])
    else:
        audit("password_reset_requested", target_user_id=u["id"], ip=ip)
    return message


def confirm_password_reset(token: str, new_password: str, ip: str | None = None) -> dict:
    token = (token or "").strip()
    if not token:
        raise AuthError(RESET_BAD)
    with db.tx() as c:
        u = c.one("SELECT id, email, name FROM users WHERE password_reset_token_hash=:h "
                  "AND password_reset_expires_at > now()", h=_reset_token_hash(token))
    if not u:
        raise AuthError(RESET_BAD)
    check_password(new_password, u["email"], u["name"])
    with db.tx() as c:
        # The token is consumed in the same UPDATE that checks it, so a second use of the same
        # link (a race, or a stale tab) can't reset the password twice.
        n = c.run("UPDATE users SET password_hash=:h, must_change_password=false, "
                  "password_reset_token_hash=NULL, password_reset_expires_at=NULL WHERE id=:u "
                  "AND password_reset_token_hash=:th", h=hash_password(new_password), u=u["id"],
                  th=_reset_token_hash(token))
    if not n:
        raise AuthError(RESET_BAD)
    ended = end_all_sessions(u["id"])
    audit("password_reset_self", actor_id=u["id"], target_user_id=u["id"], ip=ip, sessions_ended=ended)
    return {"message": "Password changed. Sign in with your new password."}


def me(user_id: int) -> dict:
    with db.tx() as c:
        u = c.one("SELECT id, name, email, role, status, must_change_password, created_at, nickname, leaderboard_opt_in "
                  "FROM users WHERE id=:u",
                  u=user_id)
    with db.tx(user_id) as c:
        prefs = c.one("SELECT theme, palette FROM user_prefs WHERE user_id=:u", u=user_id) or {}
        level = c.value("SELECT level FROM user_levels WHERE user_id=:u", u=user_id) or 1
    return {**u, "level": level, "features": permissions.user_features(u["id"], u["role"]),
            "prefs": {"theme": prefs.get("theme"), "palette": prefs.get("palette")}}


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


NICKNAME_RE = re.compile(r"[A-Za-z0-9_]{3,20}")


def set_profile(user_id: int, nickname: str | None = None, leaderboard_opt_in: bool | None = None) -> dict:
    """First-login onboarding (#121) and later edits: the public nickname (3-20 letters, digits or _,
    unique ignoring case) and whether to appear on the leaderboard. Returns the updated user."""
    if nickname is not None:
        nickname = nickname.strip()
        if not NICKNAME_RE.fullmatch(nickname):
            raise AuthError("Nickname must be 3 to 20 letters, digits or _")
    try:
        with db.tx() as c:
            c.run("UPDATE users SET nickname=COALESCE(:n, nickname), "
                  "leaderboard_opt_in=COALESCE(:o, leaderboard_opt_in) WHERE id=:u",
                  n=nickname, o=leaderboard_opt_in, u=user_id)
    except IntegrityError:
        raise AuthError("That nickname is taken") from None
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
                     "u.last_login_at, u.must_change_password, u.email_verified_at, a.name AS approved_by_name "
                     "FROM users u LEFT JOIN users a ON a.id = u.approved_by WHERE u.status <> 'unverified' "
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


def _check_rank(c, actor_id: int, target_id: int) -> str:
    """Managers act only on accounts ranked below their own: a sub-admin never touches the owner or
    another sub-admin. Returns the target's role."""
    actor = c.value("SELECT role FROM users WHERE id=:u", u=actor_id)
    target = c.value("SELECT role FROM users WHERE id=:u AND status <> 'unverified'", u=target_id)
    if target is None:
        raise AuthError("User not found")
    if not permissions.outranks(actor, target):
        raise AuthError("You can only manage accounts ranked below yours")
    return target


def set_role(actor_id: int, target_id: int, role: str, ip: str | None = None) -> dict:
    """Owner: any account to sub_admin, beta or user. A sub-admin with manage_roles: beta <-> user
    only. Nobody is made owner, and nobody changes their own role."""
    if role not in ("sub_admin", "beta", "user"):
        raise AuthError("Role must be sub_admin, beta or user")
    if target_id == actor_id:
        raise AuthError("You can't change your own role")
    with db.tx() as c:
        old = _check_rank(c, actor_id, target_id)
        actor = c.value("SELECT role FROM users WHERE id=:u", u=actor_id)
        if "sub_admin" in (role, old) and actor != "owner":
            raise AuthError("Only the owner grants or removes sub-admin")
        c.run("UPDATE users SET role=:r WHERE id=:u", r=role, u=target_id)
    if old != role:
        audit("role_changed", actor_id=actor_id, target_user_id=target_id, ip=ip, was=old, role=role)
    return {"id": target_id, "role": role}


AUTO_ROLE = "beta"


def auto_promote(user_id: int, role: str, level: int) -> bool:
    """The only automatic role change (#123): a `user` who reached config.BETA_LEVEL becomes `beta`.
    Refuses any other target role outright, so no future caller can use it to hand out sub-admin
    or owner. Touches only accounts that are still `user`. Returns whether it promoted."""
    if role != AUTO_ROLE:
        raise ValueError("Automatic promotion only ever goes to beta")
    with db.tx() as c:
        n = c.run("UPDATE users SET role=:r WHERE id=:u AND role='user'", r=AUTO_ROLE, u=user_id)
    if n:
        audit("role_changed", target_user_id=user_id, was="user", role=AUTO_ROLE, auto=True, level=level)
    return bool(n)


def set_status(admin_id: int, target_id: int, status: str, ip: str | None = None) -> dict:
    if status not in STATUSES or status in ("pending", "unverified"):
        raise AuthError("Status must be active, rejected or disabled")
    if target_id == admin_id:
        raise AuthError("You can't change your own status")
    with db.tx() as c:
        _check_rank(c, admin_id, target_id)
        old = c.value("SELECT status FROM users WHERE id=:u", u=target_id)
        if old is None or old == "unverified":  # not in the admin's list until the email is confirmed
            raise AuthError("User not found")
        c.run("UPDATE users SET status=:s, approved_by=CASE WHEN :s='active' THEN :a ELSE approved_by END, "
              "approved_at=CASE WHEN :s='active' AND approved_at IS NULL THEN now() ELSE approved_at END "
              "WHERE id=:u", s=status, a=admin_id, u=target_id)
    ended = end_all_sessions(target_id) if status != "active" else 0
    audit(f"user_{status}", actor_id=admin_id, target_user_id=target_id, ip=ip, was=old, sessions_ended=ended)
    return {"id": target_id, "status": status, "sessions_ended": ended}


def list_blocked() -> list[dict]:
    """Sign-ups not confirmed within CONFIRM_DAYS, newest first, for the admin's unblock list."""
    with db.tx() as c:
        return c.all("SELECT id, name, email, created_at, unblocked_at FROM users WHERE status='unverified' "
                     "AND coalesce(unblocked_at, created_at) < now() - make_interval(days => :d) "
                     "ORDER BY created_at DESC", d=CONFIRM_DAYS)


def unblock_signup(admin_id: int, target_id: int, ip: str | None = None) -> dict:
    """For a person support has checked: a fresh CONFIRM_DAYS and daily code allowance, and a new
    code by email now. They still confirm the email, then wait for approval as usual."""
    with db.tx() as c:
        row = c.one("UPDATE users SET unblocked_at=now() WHERE id=:u AND status='unverified' "
                    "AND coalesce(unblocked_at, created_at) < now() - make_interval(days => :d) "
                    "RETURNING email", u=target_id, d=CONFIRM_DAYS)
    if not row:
        raise AuthError("That sign-up isn't blocked")
    audit("signup_unblocked", actor_id=admin_id, target_user_id=target_id, ip=ip)
    sent = _send_code(target_id, row["email"], ip)
    return {"id": target_id, "sent": sent}


def reset_password(admin_id: int, target_id: int, ip: str | None = None) -> dict:
    """One-time temporary password, shown to the admin once. The user must change it on sign-in."""
    temp = "-".join(secrets.token_urlsafe(4) for _ in range(3))
    with db.tx() as c:
        _check_rank(c, admin_id, target_id)
        n = c.run("UPDATE users SET password_hash=:h, must_change_password=true WHERE id=:u",
                  h=hash_password(temp), u=target_id)
    if not n:
        raise AuthError("User not found")
    ended = end_all_sessions(target_id)
    audit("password_reset", actor_id=admin_id, target_user_id=target_id, ip=ip, sessions_ended=ended)
    return {"id": target_id, "temporary_password": temp}
