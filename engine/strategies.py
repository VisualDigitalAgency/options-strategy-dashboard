"""Saved strategies (issue #150): a user's named builder strategies, private to them.

A saved strategy is the exact trade: stock, expiry and legs. Each leg also keeps the delta it had
when saved, so the builder can move a strategy whose expiry has passed to a live one by matching
deltas. Saving under an existing name (any case) replaces that strategy.
"""

import json
import re

from . import db

MAX_PER_USER = 50
MAX_LEGS = 8
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class StrategyError(ValueError):
    pass


def _clean_legs(legs: list) -> list[dict]:
    if not isinstance(legs, list) or not 1 <= len(legs) <= MAX_LEGS:
        raise StrategyError(f"A strategy needs 1 to {MAX_LEGS} legs")
    out = []
    for l in legs:
        try:
            leg = {"side": l["side"], "strike": float(l["strike"]), "action": l["action"], "lots": int(l["lots"])}
            delta = l.get("delta")
            leg["delta"] = None if delta is None else round(float(delta), 4)
        except (KeyError, TypeError, ValueError) as e:
            raise StrategyError("Each leg needs side, strike, action and lots") from e
        if leg["side"] not in ("CE", "PE") or leg["action"] not in ("BUY", "SELL") or leg["strike"] <= 0 \
                or not 1 <= leg["lots"] <= 50:
            raise StrategyError("Each leg needs side CE/PE, action BUY/SELL, a strike and 1 to 50 lots")
        out.append(leg)
    return out


def save(user_id: int, name: str, symbol: str, expiry: str, legs: list) -> dict:
    """Saves the builder's current strategy under `name`, replacing one with the same name."""
    name = " ".join(name.split())
    if not 1 <= len(name) <= 40:
        raise StrategyError("Give the strategy a name of 1 to 40 characters")
    if not DATE_RE.match(expiry):
        raise StrategyError("Expiry must look like 2026-12-29")
    clean = json.dumps(_clean_legs(legs))
    with db.tx(user_id) as c:
        old = c.value("SELECT id FROM saved_strategies WHERE user_id=:u AND lower(name)=lower(:n)", u=user_id, n=name)
        if old:
            c.run("UPDATE saved_strategies SET name=:n, symbol=:s, expiry=:e, legs=CAST(:l AS jsonb), updated_at=now() "
                  "WHERE id=:i AND user_id=:u", n=name, s=symbol, e=expiry, l=clean, i=old, u=user_id)
            sid = old
        else:
            if c.value("SELECT count(*) FROM saved_strategies WHERE user_id=:u", u=user_id) >= MAX_PER_USER:
                raise StrategyError(f"You can keep up to {MAX_PER_USER} strategies; delete one first")
            sid = c.value("INSERT INTO saved_strategies (user_id, name, symbol, expiry, legs) VALUES "
                          "(:u, :n, :s, :e, CAST(:l AS jsonb)) RETURNING id", u=user_id, n=name, s=symbol, e=expiry, l=clean)
    return {"id": sid, "name": name, "replaced": bool(old)}


def list_saved(user_id: int) -> list[dict]:
    """The user's strategies, newest first; `expired` is true once the expiry date has passed (IST)."""
    with db.tx(user_id) as c:
        return c.all("SELECT id, name, symbol, to_char(expiry, 'YYYY-MM-DD') AS expiry, legs, updated_at, "
                     "expiry < (now() AT TIME ZONE 'Asia/Kolkata')::date AS expired FROM saved_strategies "
                     "WHERE user_id=:u ORDER BY updated_at DESC, id DESC", u=user_id)


def delete(user_id: int, strategy_id: int) -> dict:
    """Deletes one of the user's saved strategies."""
    with db.tx(user_id) as c:
        n = c.run("DELETE FROM saved_strategies WHERE id=:i AND user_id=:u", i=strategy_id, u=user_id)
    if not n:
        raise StrategyError("Strategy not found")
    return {"deleted": strategy_id}
