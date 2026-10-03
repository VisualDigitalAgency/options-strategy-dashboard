"""Input checks and throttles for the JSON-RPC layer.

Every RPC call goes through `validate` before it reaches engine code:
  - params must be a JSON object; positional arrays are refused
  - only the function's public parameters are accepted (no names starting with "_", no
    `user_id`, no **kwargs), so internal arguments can never be set from a browser
  - required parameters must be present, and basic types must match the annotations
  - symbols, expiries and order legs are checked for shape and range
Engine functions stay free of web concerns; this module is the only trust boundary.
"""

import inspect
import math
import re
import types
import typing

SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
MAX_LEGS = 4
MAX_LOTS = 500
# No RPC takes a long string (tokens are ~40 chars, a name 80, a password at most 256).
MAX_STR = 1000
# Supplied by the server from the session; a client can never set these.
SERVER_ONLY = {"user_id"}


class InvalidParams(Exception):
    """Bad input from the client. Its message is safe to show."""


def _allowed(fn) -> tuple[dict, set]:
    sig = inspect.signature(fn)  # follows functools.wraps to the engine function
    params = {n: p for n, p in sig.parameters.items()
              if not n.startswith("_") and n not in SERVER_ONLY
              and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    required = {n for n, p in params.items() if p.default is p.empty}
    return params, required


def _base_types(annotation) -> tuple:
    """Plain Python types an annotation accepts: `str | None` -> (str, NoneType)."""
    if annotation is inspect.Parameter.empty:
        return ()
    is_union = typing.get_origin(annotation) in (typing.Union, types.UnionType)
    options = typing.get_args(annotation) if is_union else (annotation,)
    out = []
    for a in options:
        origin = typing.get_origin(a) or a
        if origin in (str, int, float, bool, list, dict, type(None)):
            out.append(origin)
    return tuple(out)


def _type_ok(value, types: tuple) -> bool:
    if not types:
        return True
    for t in types:
        if t is type(None) and value is None:
            return True
        if t is bool and isinstance(value, bool):
            return True
        if t is int and isinstance(value, int) and not isinstance(value, bool):
            return True
        # Python's JSON parser accepts NaN and Infinity. NaN slips past every range check (all its
        # comparisons are false) and Postgres NUMERIC stores it, so refuse non-finite numbers here.
        if t is float and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return True
        if t in (str, list, dict) and isinstance(value, t):
            return True
    return False


def _check_legs(legs, need_action: bool) -> None:
    if not isinstance(legs, list) or not 1 <= len(legs) <= MAX_LEGS:
        raise InvalidParams(f"legs must be a list of 1 to {MAX_LEGS} legs")
    for l in legs:
        if not isinstance(l, dict):
            raise InvalidParams("each leg must be an object")
        if l.get("side") not in ("CE", "PE"):
            raise InvalidParams("leg side must be CE or PE")
        strike = l.get("strike")
        if not _type_ok(strike, (float,)) or not 0 < strike < 1_000_000:
            raise InvalidParams("leg strike must be a positive number")
        if need_action:
            if l.get("action") not in ("BUY", "SELL"):
                raise InvalidParams("leg action must be BUY or SELL")
            lots = l.get("lots")
            if isinstance(lots, bool) or not isinstance(lots, int) or not 1 <= lots <= MAX_LOTS:
                raise InvalidParams(f"leg lots must be a whole number from 1 to {MAX_LOTS}")
        if need_action and l.get("price") is not None:
            px = l["price"]
            if not _type_ok(px, (float,)) or not 0 < px < 1_000_000:
                raise InvalidParams("leg price must be a positive number")
        # A saved strategy (#150) keeps each leg's delta; order methods ignore it.
        if l.get("delta") is not None and (not _type_ok(l["delta"], (float,)) or not -1 <= l["delta"] <= 1):
            raise InvalidParams("leg delta must be a number from -1 to 1")
        extra = set(l) - {"side", "strike", "action", "lots", "price", "delta"}
        if extra:
            raise InvalidParams(f"unknown leg field(s): {', '.join(sorted(extra))}")


def validate(fn, params, universe: typing.Callable[[], list[str]] | None = None) -> dict:
    """Returns the params unchanged if they are safe to pass as **kwargs, else raises InvalidParams."""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise InvalidParams("params must be an object")
    allowed, required = _allowed(fn)
    unknown = set(params) - set(allowed)
    if unknown:
        raise InvalidParams(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    missing = required - set(params)
    if missing:
        raise InvalidParams(f"missing parameter(s): {', '.join(sorted(missing))}")
    for name, value in params.items():
        if not _type_ok(value, _base_types(allowed[name].annotation)):
            raise InvalidParams(f"{name} has the wrong type")
        if isinstance(value, str) and len(value) > MAX_STR:
            raise InvalidParams(f"{name} is too long")

    if "symbol" in params:
        if not SYMBOL_RE.match(params["symbol"]):
            raise InvalidParams("symbol must be an NSE ticker like HDFCBANK")
        if universe is not None and params["symbol"] not in universe():
            raise InvalidParams(f"{params['symbol']} is not in the Nifty 50")
    if "expiry" in params and not DATE_RE.match(params["expiry"]):
        raise InvalidParams("expiry must be YYYY-MM-DD")
    if "run_at" in params and params["run_at"] is not None and not TIME_RE.match(str(params["run_at"])):
        raise InvalidParams("run_at must be HH:MM")
    if "legs" in params:
        _check_legs(params["legs"], need_action="lots" not in allowed)
    if "price" in params and not 0 < params["price"] < 1_000_000:
        raise InvalidParams("price must be a positive number")
    if "lots" in params and not 1 <= params["lots"] <= MAX_LOTS:
        raise InvalidParams(f"lots must be from 1 to {MAX_LOTS}")
    # A row-count `limit`. va_place_stop's `limit` is an SL limit price, checked by place_stop itself.
    if "limit" in params and allowed["limit"].annotation is int and not 1 <= params["limit"] <= 500:
        raise InvalidParams("limit must be from 1 to 500")
    return params
