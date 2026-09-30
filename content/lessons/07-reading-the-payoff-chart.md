A **payoff chart** shows your profit or loss (up the side) for every possible stock price (along the bottom). It is the fastest way to see what a trade can do before you place it.

## At expiry

On the expiry line, an option is worth only its intrinsic value, so the chart is made of straight lines:

- **Short call**: flat at +premium below the strike, then falling one-for-one above it.
- **Short put**: flat at +premium above the strike, then falling one-for-one below it.
- **Short strangle**: flat at +total credit between the two strikes, falling on both sides. It looks like a flat-topped hill.

Where the line crosses zero are the **breakevens**.

## Before expiry

Theta Desk's Strategy lab also draws the curve for any day before expiry, using Black–Scholes at today's implied volatility. That curve is smoother and lower than the expiry line, because the option still has time value you would have to pay to buy it back. As days pass, it bends up towards the expiry line: that is theta working for you.

## 1σ and 2σ moves

The shaded bands show the **expected move** by expiry, from the options' implied volatility:

- About **68%** of the time the stock should finish inside **1σ**.
- About **95%** of the time inside **2σ**.

A well-placed strangle has both strikes outside the 1σ band. If a strike sits inside 1σ, the market expects the stock to reach it more than a third of the time.

## Risk : reward on Theta Desk

- **Reward** = the premium collected.
- **Risk** = the expiry loss after a 2σ move against you. A naked short has no fixed maximum loss, so a 2σ move is used as a realistic bad case, not the worst case.

## Probability of profit (POP)

POP is the model's chance the stock ends between the breakevens at expiry. A high POP is good, but always read it next to the risk: a 90% POP trade whose 2σ loss is 8× the premium is still dangerous.
