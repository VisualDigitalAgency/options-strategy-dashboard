> A seat belt doesn't stop the crash; it limits the damage. A **spread** does that for a sold option: you sell one option and buy another of the same type further out, so a big move can only cost so much.

## The three shapes

- **Bull put spread:** sell a put, buy a put further down. You profit if the stock stays above the sold strike.
- **Bear call spread:** sell a call, buy a call further up. You profit if the stock stays below the sold strike.
- **Iron condor:** both together, so you profit while the stock stays between the two sold strikes.

::visual payoff-put-spread

## Working out the risk

- **Most you can keep:** the net premium (what you sold for minus what you paid).
- **Most you can lose:** the gap between the strikes × lot size, minus the net premium.
- Example: sell the 900 put at ₹6, buy the 850 put at ₹2, lot 100. You keep up to ₹400 and can lose at most (50 × 100) − 400 = ₹4,600. Without the bought put, a crash has no floor.

## Choosing the gap

- **Narrow gap:** the hedge is close, so the bought leg costs more and you keep less, but the worst case is small.
- **Wide gap:** cheaper protection and more premium kept, but a bigger worst case.
- A useful rule: choose the gap so the worst case is a loss you would accept on one trade, then check the credit is still worth the risk.

## Why the margin is lower

The exchange's margin covers the worst case. With the loss capped, the worst case is smaller, so less margin is blocked. In the builder you can see this: add the protective leg and watch "Margin needed" fall.

## The rules here

Until Level 6, every buy must protect a sell exactly like this: same type, further out of the money, and no more lots than sold. The builder's templates (bull put, bear call, iron condor) follow the rule for you.
