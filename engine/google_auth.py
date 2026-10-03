"""Sign in with Google, straight against Google's OAuth 2.0 / OpenID Connect endpoints (no auth
provider in between, no Google script on our pages, so the CSP stays as it is).

The browser goes to /auth/google/start; we redirect it to Google with a one-time `state`, a
`nonce` and a PKCE challenge, kept in Redis for STATE_TTL and bound to this browser by a short
cookie. Google sends it back to /auth/google/callback with a code, which we swap for an ID token
over TLS directly with Google's token endpoint. A token received that way may skip the signature
check (OpenID Connect Core 3.1.3.7); we still check issuer, audience, expiry, nonce and that Google
has verified the email. auth.google_login then signs the user in, links or creates the account.

Off unless GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set (or *_FILE) and the owner turns on
the `google_login` switch. The owner account never signs in this way.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import requests

from . import app_settings, auth, cache, settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
STATE_TTL = 600
STARTS_PER_IP = 30  # per hour


def client() -> tuple[str | None, str | None]:
    return settings.secret("GOOGLE_CLIENT_ID"), settings.secret("GOOGLE_CLIENT_SECRET")


def configured() -> bool:
    return all(client())


def enabled() -> bool:
    return configured() and app_settings.get("google_login")


def redirect_uri() -> str:
    return f"{auth.public_url()}/auth/google/callback"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def start(ref: str | None, ip: str | None) -> tuple[str, str]:
    """(Google's sign-in URL, the browser binding to set as a cookie)."""
    if not enabled():
        raise auth.AuthError("Sign in with Google is turned off")
    key = f"rl:google:{ip or '-'}"
    if auth._count(key) >= STARTS_PER_IP:
        raise auth.AuthError("Too many tries. Wait an hour and try again")
    cache._call(lambda r: (r.incr(key), r.expire(key, 3600, nx=True)))
    state, nonce, verifier, browser = (secrets.token_urlsafe(32) for _ in range(4))
    cache.set_json(f"google:{state}", {"nonce": nonce, "verifier": verifier, "browser": auth._hash(browser),
                                       "ref": (ref or "")[:32] or None}, ttl=STATE_TTL)
    url = AUTH_URL + "?" + urlencode({
        "client_id": client()[0], "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"})
    return url, browser


def _claims(id_token: str) -> dict:
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise auth.AuthError("Google sign-in failed. Try again")


def finish(state: str | None, code: str | None, browser: str | None, ip: str | None = None,
           ua: str | None = None, device: str | None = None) -> tuple[str | None, dict]:
    """Checks Google's answer and signs the user in: (session token or None, auth.google_login's answer)."""
    failed = auth.AuthError("Google sign-in failed or expired. Try again")
    if not enabled():
        raise auth.AuthError("Sign in with Google is turned off")
    st = cache.pop_json(f"google:{state}") if state else None  # one use only
    if not st or not code or not browser or not secrets.compare_digest(st["browser"], auth._hash(browser)):
        raise failed
    cid, csecret = client()
    r = requests.post(TOKEN_URL, data={"code": code, "client_id": cid, "client_secret": csecret,
                                       "redirect_uri": redirect_uri(), "grant_type": "authorization_code",
                                       "code_verifier": st["verifier"]}, timeout=15)
    if r.status_code != 200 or "id_token" not in r.json():
        raise failed
    c = _claims(r.json()["id_token"])
    if (c.get("iss") not in ISSUERS or c.get("aud") != cid or float(c.get("exp") or 0) < time.time()
            or not secrets.compare_digest(str(c.get("nonce") or ""), st["nonce"]) or not c.get("sub")):
        raise failed
    if c.get("email_verified") is not True or not c.get("email"):
        raise auth.AuthError("Your Google account's email isn't verified")
    return auth.google_login(str(c["sub"]), c["email"], c.get("name") or "", ip=ip, ua=ua, device=device, ref=st["ref"])
