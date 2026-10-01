> You learnt spreads at Level 1 as trades you open on purpose. This lesson is about the moment a trade you **already hold** starts to worry you, and adding a protective buy to it, part way through.

## When to add protection to a held trade

- **An event appears** before your expiry that wasn't there when you opened (results moved, a dividend announced).
- **The stock is drifting towards your sold strike**, your reason for the trade still holds, and you'd rather cap the risk than close.
- **Margin is getting tight**, and capping the worst case frees some.

If none of these apply, a hedge just costs premium. Leave the trade alone.

::visual payoff-put-spread

## How to add it here

1. In the Strategy builder, open the same stock and expiry.
2. Buy one option of the same type, further out of the money than your sold strike, no more lots than you sold.
3. The order joins your existing group: the buy rule checks it against what you already hold, so a protective buy is allowed before Level 6.

## Hedge or close?

- Work out the cost of the hedge against the premium still left in your sold leg.
- If the hedge costs most of what you could still keep, **close** instead: it's simpler and frees all the margin.
- If the hedge is cheap compared with the loss it caps, add it and let the trade run under your rules.

## Don't

- Don't hedge *after* the stop is hit to avoid booking the loss. The stop decides.
- Don't buy more lots than you sold to "make it back". That is a new bet, not a hedge.
