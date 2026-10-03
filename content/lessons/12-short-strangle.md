> Think of two fences, one above today's price and one below. You get paid as long as the price stays in the field between them. That's a **short strangle**.

You sell a far-away call (the top fence) and a far-away put (the bottom fence) on the same stock and date.

::visual payoff-strangle

## How we build it

- Sell a call above the price and a put below it, both with delta below 0.15.
- You collect two fees, so the total is bigger than one leg alone.
- The price can't break both fences at once, so the deposit (margin) is smaller than two separate trades.

## Where you start losing: breakevens

- **Top breakeven** = call strike + total fee.
- **Bottom breakeven** = put strike − total fee.

Example: stock at ₹2,000. Sell the 2,200 CE for ₹6 and the 1,800 PE for ₹5. Total fee ₹11.

- Top breakeven: 2,200 + 11 = **₹2,211**.
- Bottom breakeven: 1,800 − 11 = **₹1,789**.

If the price ends anywhere between those two, you make money.

## When it's a good fit

- No big events before the end date (no results, no big dividend). Check the Market Calendar.
- The stock isn't racing up or down. If it is, selling only the fence it's moving away from is safer.
- The market isn't expecting a huge move. Very high fees usually mean a big move is expected.

## What can go wrong

- **A big one-way move** breaks one fence. The other side's small profit can't cover it.
- **A wobble**: a move up hits the call's stop-loss, then a fall hits the put's.
- **An event**: results can make the price jump over a fence overnight.

## Looking after it

Each leg has its own stop-loss from day 15. If one side is stopped out, the other keeps running. The profit exit (90% melted) and time exit (under 7 days) apply to both together.
