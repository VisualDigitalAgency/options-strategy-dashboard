A buyer pays the premium and can never lose more. A seller can lose far more than they receive, so the exchange makes sellers set aside **margin**: money blocked in the account as a safety deposit.

## The two parts of margin in India

- **SPAN margin**: NSE's risk system tests your position against 16 price and volatility scenarios and blocks the worst-case loss. Theta Desk reads NSE's own daily SPAN risk file to compute it.
- **Exposure margin**: an extra buffer on each short leg, a percentage of the contract's value.

**Total margin = SPAN + exposure.** For a Nifty 50 stock, one short lot often blocks ₹1 lakh or more, while collecting only a few thousand rupees of premium.

## Return on margin

Because margin is large and premium is small, judge a trade by **premium ÷ margin**, not by the premium alone. ₹4,000 of premium on ₹1,00,000 of margin is a 4% return on the capital you tied up, for about a month, if it works.

## Strangles get an offset

A short strangle sells a call and a put on the same stock. Both can't lose at the same time, since the stock can only go one way, so SPAN gives a margin benefit. A strangle usually needs much less than the two legs' margin added together.

## Margin can grow

Margin is recalculated every day. If the stock moves against you or volatility jumps, the blocked amount rises. If your free funds can't cover it, a real broker will ask for more money or close your position for you, often at the worst moment.

## How Theta Desk keeps you safe

- **Max % per trade**: the wallet setting caps how much of your account one trade may use.
- The virtual account checks margin again at the moment of booking, so two orders can't both spend the same free funds.
- A good habit is to keep a healthy share of the account free, so a margin increase never forces an exit.

Overloading margin is the most common way new sellers lose an account: not because the trade was wrong, but because they couldn't hold it.
