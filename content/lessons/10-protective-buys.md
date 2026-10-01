> A sold option has a small, known reward and a large, unknown risk. A **protective buy** caps that risk: you buy an option further out of the money, of the same type, so a big move can only cost so much.

## The shape

- **Sold put + bought put further down** = a bull put spread. Below the bought strike, losses stop growing.
- **Sold call + bought call further up** = a bear call spread.
- Both together = an **iron condor**.

The most you can lose is the gap between the strikes, times the lot size, minus the net premium you kept.

::visual payoff-put-spread

## The cost

- The bought option costs premium, so you keep less.
- It usually lowers the margin, because the worst case is capped.
- Far-away protection is cheap but only helps in a crash. Closer protection helps more and costs more.

## Rules in the builder

- Before Level 6, a buy must protect a sell: same type, further out of the money, and no more lots than you sold.
- From Level 6 you may also buy options on their own. A bought leg with no sell left to protect has its own stop: it closes once it has lost half of what you paid.

## When protection is worth it

- Around **results or big events**, when a gap could jump past your stop before it can act.
- When the margin it saves lets you trade the size you planned, instead of a riskier naked position.
- Not as a reason to sell strikes closer than your delta rule allows.
