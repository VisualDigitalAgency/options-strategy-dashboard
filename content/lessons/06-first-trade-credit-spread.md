> Your first trade should have a worst case you know before you place it. A **credit spread** is a sold option with a bought option behind it as a floor: you collect premium, and the most you can lose is fixed on day one.

## Why start here

- **Capped loss.** However far the stock moves, the loss stops at the bought strike. A naked sold option has no such floor.
- **Small margin.** The exchange blocks roughly the worst case, so a spread fits a ₹2 lakh account where a naked sale often doesn't.
- **The same skills.** You still sell below delta 0.15, keep the stop-loss on, and let time decay work for you.

## The two spreads

- **Bull put spread:** sell a put below the price, buy a put further down. You keep the premium if the stock stays above the sold strike.
- **Bear call spread:** sell a call above the price, buy a call further up. You keep the premium if the stock stays below the sold strike.

::visual payoff-put-spread

## The numbers, before you click

- **Credit:** what you sold for minus what you paid.
- **Worst case:** gap between the strikes × lot size, minus the credit.
- Example, lot 250: sell the 1,200 put at ₹10, buy the 1,180 put at ₹4. Credit = ₹6 × 250 = ₹1,500. Worst case = (20 × 250) − 1,500 = ₹3,500.

Ask one question: is ₹1,500 worth risking ₹3,500 over the next month? If the answer is no, pick different strikes or skip the trade.

## Placing it

1. In the builder, pick a stock and an expiry at least 30 days out.
2. Choose **Bull put** or **Bear call** (turn on **Rule-safe** so the sold strike is below delta 0.15).
3. Check the margin, credit and worst case, then place it with the stop-loss on.

## The rule at Levels 1 and 2

Every sold option must have a bought option of the same type behind it. That is what makes your first trades survivable while you learn.
