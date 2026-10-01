> A stop-loss is a smoke alarm: it reacts once something happens. On **results day** the fire can start overnight, and by the morning the price may already be far past your stop. Protection has to be in place **before** the event.

## Why events break stops

- Results and big announcements usually come outside market hours.
- The next morning the stock can **open** far from the last price. There is no trade in between for a stop to act on.
- A sold option can open at several times its premium. That loss is booked at the opening price, not at your stop.

::visual event-gap

## Three ways to handle an event

1. **Avoid it.** Choose an expiry that ends before the event, or a stock without one. The builder warns you when results fall before your expiry.
2. **Close before it.** If you already hold a sold leg and results are coming, take the profit or small loss now.
3. **Hedge it.** Add a bought option of the same type further out, turning the naked leg into a spread. The loss now has a floor even if the open jumps.

## What a hedge costs

- The bought leg costs premium, and around events options are more expensive (higher IV), so protection costs more than usual.
- Compare the cost with the loss it prevents. Paying ₹2 to cap a possible ₹40 loss is usually worth it; paying ₹6 to protect a ₹7 credit is not. Then closing is better.

## A routine

Every week, check the events in the builder's warnings for each stock you hold. For any results before expiry, choose: close, hedge, or accept the gap risk on purpose and keep the size small.
