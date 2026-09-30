A **short strangle** sells an OTM call *and* an OTM put on the same stock and expiry. You profit if the stock stays between the two strikes until you exit.

## How it's built on Theta Desk

- Sell a call above the stock price and a put below it, each with |delta| < 0.15.
- Both legs collect premium, so the total credit is bigger than either leg alone.
- SPAN gives a margin offset, so a strangle often uses little more margin than one leg.

## Breakevens

- **Upper breakeven** = call strike + total credit.
- **Lower breakeven** = put strike − total credit.

Example: stock at ₹2,000. Sell the 2,200 CE for ₹6 and the 1,800 PE for ₹5. Total credit ₹11.

- Upper breakeven: 2,200 + 11 = **₹2,211**.
- Lower breakeven: 1,800 − 11 = **₹1,789**.

Between those two prices at expiry, the trade makes money.

## When it fits

- The stock has no known event before expiry (no results, no big dividend). Check the Market Calendar.
- There is no strong trend. Theta Desk shows a sentiment score; a strong bullish or bearish reading suggests selling only the side the trend is moving away from.
- Implied volatility is reasonable. High IV pays more premium but usually means the market expects a big move.

## What can go wrong

- **A big one-way move**: one leg goes deep ITM. The other leg's small profit doesn't come close to covering it.
- **Two stop-losses in a row**: a sharp move up hits the call, then a reversal hits the put.
- **Ignoring events**: a results day can gap the stock past a strike overnight, before any stop-loss can act.

## Managing it

Each leg has its own stop-loss from day 15. When one side is stopped out, the other side keeps running on its own. The group's profit exit (90% of premium decayed) and time exit (under 7 days to expiry) apply to the whole strangle.
