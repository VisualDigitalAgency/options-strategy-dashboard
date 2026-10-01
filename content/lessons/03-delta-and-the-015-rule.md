> Think of a weather forecast. "15% chance of rain" means it usually stays dry. **Delta** is like a weather forecast for your option: a delta of 0.15 means about a 15% chance the price ends past your line.

## Delta, part 1: how fast the price moves

Delta tells you how much the option's price changes when the stock moves ₹1.

- A call with delta 0.30 goes up about ₹0.30 when the stock goes up ₹1.
- A put has a minus sign. A put with delta −0.30 goes up about ₹0.30 when the stock goes *down* ₹1.
- Near the price: delta around 0.5. Far away: delta close to 0.

## Delta, part 2: the chance of trouble

Ignore the minus sign, and delta is roughly the chance the option ends in the money. A 0.15-delta option has about a 15% chance, so about an 85% chance of ending worthless and letting you keep the fee.

::visual delta-odds

It is a forecast, not a promise. It changes every day as the price and the market's mood change.

## Our rule: sell below 0.15

The screener only picks lines with delta below 0.15. That puts your line far enough away that a normal month's move doesn't reach it. Among those lines, it picks one many traders are using (high open interest) that is easy to trade.

## The trade-off

Farther away (lower delta) means:

- **More** chance of keeping the fee.
- **Smaller** fee.
- The **same** big danger if the stock makes a huge move.

## Watch delta grow

If the stock moves towards your line, delta goes up. A 0.12 put can become 0.35 after a sharp fall. Rising delta is a warning light: the danger is getting closer.
