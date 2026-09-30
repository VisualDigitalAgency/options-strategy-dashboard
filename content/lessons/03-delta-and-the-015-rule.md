**Delta** tells you how much an option's premium moves when the stock moves ₹1. It also works as a rough estimate of the chance the option finishes in the money.

## Delta as a price sensitivity

- A call with delta 0.30 gains about ₹0.30 when the stock rises ₹1.
- A put has a negative delta: a put with delta −0.30 gains about ₹0.30 when the stock *falls* ₹1.
- Deep ITM options have delta near 1 (or −1); far OTM options have delta near 0.

## Delta as a probability

A quick rule of thumb: an option's delta, ignoring the sign, is roughly the market's estimate of the chance it expires in the money. A 0.15 delta call has about a 15% chance of finishing ITM, so about an 85% chance of expiring worthless.

It is an approximation from the Black–Scholes model using the market's implied volatility. It is not a guarantee, and it changes every day as the stock and volatility move.

## Theta Desk's rule: sell below 0.15 delta

The screener only picks strikes with |delta| < 0.15. That keeps each short leg far enough away that a normal month's move doesn't reach it. Among the strikes that pass, it picks the one with the highest open interest that is actually tradable (enough open interest, a tight bid–ask spread, and a recent trade).

## The trade-off

Lower delta means:

- **Higher** chance of keeping the premium.
- **Smaller** premium per lot.
- The same **uncapped** risk if the stock makes a very large move.

Going closer to the money for a bigger premium feels attractive, but each step closer raises the odds of a loss. The 0.15 line is where Theta Desk strikes that balance.

## Delta moves

If the stock moves towards your strike, your short option's delta rises. A 0.12 delta put can become 0.35 after a sharp fall. That is a warning sign that the position is getting dangerous, which is where the stop-loss lesson comes in.
