"""Can a new account place its first trade? Prices a 1-lot credit spread on every Nifty 50 stock.

Below Level 3 the strategy gate allows only protected sells (spreads, condors), and RMS refuses an
order that takes margin used to RMS_WARN_PCT of account value. This builds, per stock, the spread a
Level 1 user would place on the first expiry the builder opens: sell the out-of-the-money strike
nearest the money with |delta| < DELTA_MAX_ABS, buy the next strike further out, 1 lot each. It prints the margin and whether it fits the starting capital.

Needs live NSE data and the SPAN file, so run it where the app runs:
    docker compose exec api python scripts/check_l1_margin.py [--capital 200000] [--side PE|CE|both]
Exits 1 if any stock's cheapest spread doesn't fit.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import builder, config, risk_rules, virtual  # noqa: E402


def spread(chain: dict, side: str) -> list[dict] | None:
    """Sell the OTM strike nearest the money under the delta limit; buy the next one further out."""
    spot = chain["spot"]
    rows = [r for r in chain["rows"] if r[side] and (r["strike"] < spot if side == "PE" else r["strike"] > spot)]
    rows.sort(key=lambda r: r["strike"], reverse=(side == "PE"))  # nearest the money first
    for i, r in enumerate(rows[:-1]):
        d = r[side]["delta"]
        if d is not None and abs(d) < config.DELTA_MAX_ABS:
            lot = chain["lot_size"]
            buy = rows[i + 1]
            return [{"side": side, "strike": r["strike"], "qty": -lot, "price": r[side]["bid"]},
                    {"side": side, "strike": buy["strike"], "qty": lot, "price": buy[side]["ask"]}]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capital", type=float, default=config.STARTING_CAPITAL)
    ap.add_argument("--side", choices=("PE", "CE", "both"), default="both")
    a = ap.parse_args()
    limit = a.capital * config.RMS_WARN_PCT / 100
    sides = ("PE", "CE") if a.side == "both" else (a.side,)
    print(f"Capital ₹{a.capital:,.0f}; RMS refuses above ₹{limit:,.0f} margin ({config.RMS_WARN_PCT}%)\n")
    print(f"{'symbol':<12}{'expiry':<12}{'lot':>6}  {'side':<4}{'strikes':>18}{'margin':>12}  fits")
    misfits, errors = [], []
    for sym in sorted(risk_rules.get_universe()):
        try:
            ch = builder.chain(sym)
        except Exception as e:  # one bad chain shouldn't stop the report
            errors.append(f"{sym}: {e}")
            continue
        best = None
        for side in sides:
            legs = spread(ch, side)
            if not legs:
                continue
            try:
                m = virtual.group_margin(sym, ch["expiry"], legs, ch["spot"])["total"]
            except ValueError as e:
                errors.append(f"{sym} {side}: {e}")
                continue
            ok = m <= limit
            strikes = f"{legs[0]['strike']:g}/{legs[1]['strike']:g}"
            print(f"{sym:<12}{ch['expiry']:<12}{ch['lot_size']:>6}  {side:<4}{strikes:>18}{m:>12,.0f}  {'yes' if ok else 'NO'}")
            best = m if best is None else min(best, m)
        if best is not None and best > limit:
            misfits.append(sym)
    print(f"\n{len(misfits)} stock(s) with no spread that fits: {', '.join(misfits) or 'none'}")
    for e in errors:
        print("skipped", e)
    return 1 if misfits else 0


if __name__ == "__main__":
    sys.exit(main())
