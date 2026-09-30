A short option has a capped gain and an uncapped loss. A **stop-loss** is the rule that caps the loss, decided *before* the trade, when you are calm.

## Theta Desk's stop-loss rule

- **Days 1–14: no stop-loss.** Early in the trade, premiums jump around on normal noise. A tight stop here gets triggered by moves that later reverse.
- **From day 15: buy back at the original premium collected.** If the option's price climbs back up to what you sold it for, you exit. The trade ends at roughly breakeven on that leg, before costs.
- The trigger uses the **mid** of the bid and ask, not the ask alone, and the exit is a limit order at the ask.

In the virtual account each short leg has three modes: **Auto exit** (the group closes for you), **Alert only** (you are told and act yourself), and **Off**. Levels reward trades where the stop-loss was on and respected.

## Why a missed stop-loss ends accounts

Losses on a short option can grow very fast once the stock moves past the strike:

- Premium ₹8 → ₹16 is a 1× loss of the premium.
- ₹8 → ₹40 is a 4× loss: four good months gone.
- ₹8 → ₹120 after a results gap is 14× the premium.

The hardest moment to exit is when the loss is already big, because it feels like "it will come back". Most blown-up accounts are not one bad trade but one bad trade that was held.

## Other exits Theta Desk uses

- **Profit exit**: close the whole group once 90% of the premium has decayed. The last 10% isn't worth holding the full risk for.
- **Time exit**: close every leg once fewer than 7 days remain, because stock options settle by physical delivery.

## Habits the levels reward

- Every trade has a stop-loss before it's placed.
- You never average down: selling more of a losing position to "improve the price" doubles the risk at the worst time.
- When a stop-loss fires, you accept it and move on.
