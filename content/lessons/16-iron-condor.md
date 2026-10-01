> An **iron condor** is two credit spreads at once: a bull put spread below the price and a bear call spread above it. You profit while the stock stays between the two sold strikes, and the loss is capped on both sides.

## How it is built

- **Put side:** sell a put below the price, buy one further down.
- **Call side:** sell a call above the price, buy one further up.
- Both sold strikes below delta 0.15, so the stock has room to move either way.

::visual payoff-iron-condor

## The numbers

- **Credit:** both spreads' credits added together.
- **Worst case:** the wider of the two gaps × lot size, minus the total credit. Only one side can lose at expiry, because the stock can't be below the puts and above the calls at once.
- **Margin:** usually close to one spread's, for two spreads' premium. That is why a condor is the next step up from a single spread.

## Reading it on the payoff chart

The chart is flat at the top between the sold strikes (you keep the credit), slopes down beyond each sold strike, and goes flat again at each bought strike (the floor). The two breakevens are the sold strikes plus and minus the total credit per share.

## When it goes wrong

A strong move tests one side. The stop-loss rule applies to each sold leg; when one is hit, that side closes and the other side keeps working. Don't widen or move a tested side to "give it room": that is how a capped loss becomes a bigger one.

## The rule at Levels 1 and 2

Every sold option needs its bought option. A condor meets that on both sides, so it is allowed from Level 2.
