An **option** is a contract that gives its buyer a right, but not an obligation, to buy or sell a stock at a fixed price on or before a fixed date. The seller of the option takes the other side: they receive money up front and accept the obligation.

## Calls and puts

- A **call (CE)** gives the buyer the right to *buy* the stock at the strike price. Buyers of calls want the stock to rise.
- A **put (PE)** gives the buyer the right to *sell* the stock at the strike price. Buyers of puts want the stock to fall.

The seller of a call is betting the stock will **not** rise above the strike. The seller of a put is betting the stock will **not** fall below it.

## The words you will see everywhere

- **Strike**: the fixed price in the contract, for example RELIANCE 3,000 CE.
- **Expiry**: the last day the contract exists. Nifty 50 stock options expire on the last Tuesday of each month (the exchange can change this day, so always read the expiry date shown).
- **Premium**: the price of the option. The buyer pays it; the seller keeps it if the option expires worthless.
- **Lot size**: options trade in fixed lots, not single shares. If the lot size is 500 and the premium is ₹10, one lot costs the buyer ₹5,000 and pays the seller ₹5,000.
- **In the money (ITM)**: a call whose strike is below the stock price, or a put whose strike is above it. It has real value at expiry.
- **Out of the money (OTM)**: a call above the stock price, or a put below it. If it stays OTM until expiry, it expires worthless.

## A worked example

INFY trades at ₹1,500. You sell one lot (400 shares) of the 1,650 CE for ₹8.

- You receive ₹8 × 400 = **₹3,200** today.
- If INFY stays below ₹1,650 until expiry, the call expires worthless and you keep the whole ₹3,200.
- If INFY closes at ₹1,700 on expiry, the call is worth ₹50. You owe ₹50 × 400 = ₹20,000, minus the ₹3,200 you received: a **loss of ₹16,800**.

That asymmetry, a small fixed gain against a large possible loss, is the heart of option selling. The rest of this course is about managing it.

## Stock options settle by delivery

Stock options in India settle by **physical delivery**: an ITM position left open at expiry turns into an obligation to buy or sell the actual shares. Theta Desk closes every leg once fewer than 7 days remain, so paper positions never reach that point.
