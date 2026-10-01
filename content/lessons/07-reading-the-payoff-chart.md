> Think of a map that shows, for every place the price could end up, whether you win or lose and by how much. That map is a **payoff chart**.

Left to right is the stock price. Up means profit, down means loss. The flat line in the middle is ₹0.

## Selling a call

::visual payoff-short-call

Flat at your fee while the price stays **below** your strike. Above it, the line slides down: every rupee higher costs you more.

## Selling a put

::visual payoff-short-put

Flat at your fee while the price stays **above** your strike. Below it, the line slides down.

## Breakevens

Where the line crosses ₹0 is a **breakeven**. On one side you win, on the other you lose.

## Before the end date

Theta Desk's Strategy lab also draws the line for any day before expiry. That line is lower and smoother, because the option still has "hope" (time value) you'd have to pay to buy it back. Each day it bends closer to the final line. That's the ice cube melting in your favour.

## How far the price usually moves: 1σ and 2σ

::visual sigma-bands

- About **68** months in 100, the price ends inside the **1σ** band.
- About **95** months in 100, inside the **2σ** band.

A good strangle has both strikes outside 1σ. A strike inside 1σ gets reached more than 1 month in 3.

## Risk and reward on Theta Desk

- **Reward** = the fee you collect.
- **Risk** = what you'd lose if the price made a 2σ move against you. A plain sold option has no fixed worst case, so a 2σ move is used as a realistic bad month.

## Chance of profit (POP)

POP is the chance the price ends between your breakevens. High is good, but always look at the risk next to it. A 90% POP trade that can lose 8 fees in a bad month is still dangerous.
