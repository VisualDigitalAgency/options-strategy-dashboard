// Payout toast helpers (issue #192).

/** One line per reward: the rupees and the coins that came with the same achievement go together. */
export function groupItems(items) {
  const by = new Map()
  for (const i of items) {
    const g = by.get(i.label) ?? { label: i.label, rupees: 0, coins: 0 }
    if (i.kind === 'capital') g.rupees += i.amount
    else g.coins += i.amount
    by.set(i.label, g)
  }
  return [...by.values()]
}
