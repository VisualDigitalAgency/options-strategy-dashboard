> Until now every option you sold had a bought one behind it. From Level 3 you may sell a single option **naked**: more premium and no bought leg to pay for, but no floor under the loss and much more margin blocked.

## What changes without the floor

- **The loss is open-ended.** A sold call loses more the higher the stock goes; a sold put loses more the further it falls (down to zero).
- **The margin is larger.** The exchange blocks for a big move, not a capped one: often several times a spread's margin.
- **The stop-loss is now your only floor.** It closes the leg when the premium has doubled; keeping it on is not optional.

::visual payoff-short-put

## When a single sale makes sense

- The stock has a clear support (for a put) or resistance (for a call) below or above the sold strike.
- No results or dividend before expiry (the Market Calendar shows them).
- The margin it blocks is a small part of your account, so one bad move can't decide your month.

## Sizing

Start with one lot. Check the margin against your capital before you place it: if one naked sale would block more than about a third of your account, it is too big for you yet. Sell a spread instead.

## The step after this

Selling both sides naked (the short strangle) comes at Level 5, once you have shown months of discipline with these.
