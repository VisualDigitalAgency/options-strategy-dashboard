> A position under pressure has three honest choices: hold it under your rules, close it, or **roll** it. Rolling means closing the leg in trouble and opening a new one further away, or in a later expiry.

## When rolling makes sense

- The stock moved towards your sold strike, but your reason for the trade still holds.
- The new leg can be sold **below delta 0.15**, at least 30 days out, with no results date before expiry.
- You can afford the margin of the new leg **after** paying to buy the old one back.

If any of these fail, rolling is just hoping with extra steps. Close the trade instead.

::visual roll-out

## How to roll here

1. Close the leg that is under pressure from Portfolio. That books the loss on it.
2. Open the new leg in the Strategy builder: same type (CE or PE), a strike further out of the money, or a later expiry.
3. The new leg starts its own 15-day wait before its stop-loss works.

## The trap: rolling to never take a loss

Every roll books a loss on the old leg. A trader who rolls again and again is collecting smaller fees while carrying the same risk, and calling it "not losing". Set a limit before you start: **one roll per trade**. After that, the stop-loss decides.

## Rolling and your stop-loss

Rolling is not a way around the stop. If the old leg has already reached its stop, close it. Roll only before the stop is hit, while the trade still fits your rules.
