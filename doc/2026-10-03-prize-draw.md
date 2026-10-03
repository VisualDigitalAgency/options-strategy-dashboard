# Monthly prize draw: what is built, and what must happen before it is switched on

Status: **built, switched off.** The owner's `prize_draw` setting defaults to off. While it is off,
nothing is drawn, nobody can enter, and no page mentions the draw.

This is not legal advice. It is the checklist to take to a lawyer, and the record of how the
feature was shaped to keep risk low.

## Why it is shaped this way

- **SEBI and real-time data (May 2024).** SEBI restricted sharing real-time price data with
  third-party virtual-trading, paper-trading and fantasy-game platforms; education is the main
  carve-out. A cash prize for paper-trading results can make the app look like such a game.
  So the prize is **never paid for returns**: entrants qualify by discipline, and winners are
  drawn at random.
- **Past performance (SEBI, 2025).** No real-money P&L is ranked or published. The draw does not
  rank anyone and announces no returns.
- **Online Gaming Act 2025.** It bans online money games, where users stake money to win money.
  The draw is **free to enter with no purchase**, which is the argument that it falls outside.
  A lawyer must confirm that.
- **Tax.** Prize winnings carry TDS at 30% (Income Tax Act s.194B). The app records the TDS on
  each win. Deduction, deposit and the TDS certificate happen outside the app.

## How it works

1. A user opts in explicitly on My progress (`prize_draw_opt_in`, off by default).
2. In a month, they qualify with at least `MIN_TRADES` (5) closed legs and a discipline score of at
   least `CHAMPION_DISCIPLINE` (80): the stop-loss on and sold below delta 0.15.
3. When the worker freezes the month's leaderboard, `prizes.draw(month)` picks `PRIZE_WINNERS` (1)
   at random. The draw is reproducible: winners come from SHA-256 of a stored random seed, the month
   and the sorted entrant ids, so the seed lets anyone re-check it.
4. The owner sees each win under Admin with the winner's name and email, does KYC (PAN) and payment
   **outside the app**, and marks it paid or void (audited). The app never stores a PAN or bank details.

Prize amount, winners and TDS rate are in `engine/config.py` (`PRIZE_RUPEES`, `PRIZE_WINNERS`,
`PRIZE_TDS_PCT`).

## Before switching it on (all required)

- [ ] A written legal opinion covering SEBI (real-time data, past performance), the Online Gaming
      Act 2025, state prize-competition laws (and any states to exclude), and tax.
- [ ] Contest terms and conditions written by the lawyer: eligibility (age 18+, residency,
      excluded states, staff), the qualification rule, the draw method, prize, TDS, KYC, the claim
      deadline, privacy and disputes. Link them from the opt-in.
- [ ] A KYC and payment process outside the app: PAN collection, TDS deduction and deposit,
      Form 16A.
- [ ] Whether a delay on market data is needed for the contest (the education carve-out).
- [ ] Then turn on `prize_draw` under Admin → Features → App settings.
