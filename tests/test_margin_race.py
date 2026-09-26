"""Two orders racing for the same free margin book only one; pressing Exit twice queues one exit."""
import multiprocessing as mp
import sys

from engine import db, virtual
from support import EXP, SYM, new_user, stub

mp = mp.get_context("fork")  # racers inherit the stubs and the fresh engine


def racer(uid, strike, barrier, out):
    db.engine().dispose(close=False)  # don't share the parent's pooled connections after fork
    stub(True)
    p = virtual.preview_order(uid, SYM, EXP, [{"side": "PE", "strike": strike, "action": "SELL", "lots": 1}])
    barrier.wait()
    try:
        virtual.execute_order(uid, p)
        out.put("placed")
    except ValueError as e:
        out.put(f"refused: {e}")


def main():
    ok = True
    # --- margin race: 1.5 lakh free, two 1-lakh orders previewed together, then booked together
    uid = new_user("race@test.example", 150_000)
    db.engine().dispose()
    barrier, out = mp.Barrier(2), mp.Queue()
    procs = [mp.Process(target=racer, args=(uid, k, barrier, out)) for k in (900.0, 950.0)]
    [p.start() for p in procs]
    [p.join() for p in procs]
    results = sorted(out.get() for _ in procs)
    with db.tx(uid) as c:
        n_open = c.value("SELECT COUNT(*) FROM positions WHERE user_id=:u AND status='open'", u=uid)
    print("race:", results, "open positions:", n_open)
    if n_open != 1:
        ok = False
        print("  FAIL: expected exactly 1 position on a 1.5 lakh account")

    # --- duplicate exits: short 1 lot, market closed, press Exit twice
    stub(True)
    uid2 = new_user("exit@test.example", 1_000_000)
    virtual.place_order(uid2, SYM, EXP, [{"side": "PE", "strike": 900.0, "action": "SELL", "lots": 1}])
    with db.tx(uid2) as c:
        pid = c.value("SELECT id FROM positions WHERE user_id=:u AND status='open'", u=uid2)
    stub(False)
    first = virtual.exit_position(uid2, pid)
    second = virtual.exit_position(uid2, pid)
    with db.tx(uid2) as c:
        pend = c.all("SELECT action, qty FROM pending_orders WHERE user_id=:u AND status='open'", u=uid2)
    print("exit #1:", [r["status"] for r in first], "exit #2:", [r["status"] for r in second], "open orders:", pend)
    if not (first[0]["status"] == "open" and second[0]["status"] == "already_open"
            and pend == [{"action": "BUY", "qty": 100}]):
        ok = False
        print("  FAIL: expected one BUY 100 exit order and 'already_open' on the second click")

    # --- market opens: an immediate exit closes the position and cancels the resting one
    stub(True)
    third = virtual.exit_position(uid2, pid)
    with db.tx(uid2) as c:
        pos = c.value("SELECT status FROM positions WHERE id=:i", i=pid)
        pend = c.value("SELECT COUNT(*) FROM pending_orders WHERE user_id=:u AND status='open'", u=uid2)
    virtual.match_pending(uid2)
    with db.tx(uid2) as c:
        n_open = c.value("SELECT COUNT(*) FROM positions WHERE user_id=:u AND status='open'", u=uid2)
    print("exit #3:", [r["status"] for r in third], "position:", pos, "open orders left:", pend,
          "open positions after matching:", n_open)
    if not (third[0]["status"] == "filled" and pos == "closed" and pend == 0 and n_open == 0):
        ok = False
        print("  FAIL: expected a filled exit, closed position, no resting orders and no flipped position")

    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
