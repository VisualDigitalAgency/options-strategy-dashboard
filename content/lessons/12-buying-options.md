> Selling an option is like running an insurance company: many small fees, a rare large claim. **Buying** one is like buying the insurance policy, or a lottery ticket: a small, known cost for a chance at a large payout that usually doesn't come.

## The buyer's side of the trade

- You pay the premium up front. That is the **most you can lose**.
- You make money only if the price moves **past strike + premium** (for a call) **before expiry**. Being right about the direction is not enough; it must move far enough, soon enough.
- Every day that passes, the option loses time value. The same melting that pays a seller is a cost for a buyer.

::visual payoff-long-call

## Why most bought options lose

Far out-of-the-money options are cheap because they rarely pay. A strike at delta 0.10 finishes in the money roughly 1 time in 10. Buying it again and again is paying a small fee 9 times to win once, and the one win has to cover all nine.

## When a buy makes sense

- **As protection** for a sold option: it caps the loss (the spread lessons from Level 1).
- **As a defined-risk view**: you expect a big move, you accept losing the whole premium if it doesn't come, and you size it small.
- **Never** as a way to "win back" a loss quickly.

## The rules here

- Until Level 6, a buy must protect a sold leg: same type, further out of the money, and no more lots than sold.
- From Level 6 you may buy on its own. A bought leg with nothing to protect closes once it has lost **half** of what you paid, so one bad bet can't drain the account.
- A buy blocks its full premium as margin: you pay for it up front.
