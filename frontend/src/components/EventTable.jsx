import { Link } from 'react-router-dom'
import { EVENT_LABEL, awayText, dayDate, eventNote } from '../events'

// Corporate events as a table: date, stock (optional), event, details, days away. Below 1024px each
// row folds into two lines (see .cal-table in index.css). `held` marks stocks with an open position.
export default function EventTable({ events, showStock = true, held, label }) {
  return (
    <table className={`cal-table ${showStock ? '' : 'no-stock'}`} aria-label={label}>
      <thead>
        <tr>
          <th scope="col">Date</th>
          {showStock && <th scope="col">Stock</th>}
          <th scope="col">Event</th>
          <th scope="col">Details</th>
          <th scope="col" className="num">In</th>
        </tr>
      </thead>
      <tbody>
        {events.map((e) => {
          const note = eventNote(e)
          return (
            <tr key={`${e.symbol}-${e.type}-${e.date}`} className={e.risky ? 'risky' : ''}>
              <td className="cal-date num">{dayDate(e.date)}</td>
              {showStock && (
                <td className="cal-stock">
                  <Link to={`/stock/${encodeURIComponent(e.symbol)}`} className="sym">{e.symbol}</Link>
                  {held?.has(e.symbol) && <span className="chip held-chip" title="You have an open position in this stock">Held</span>}
                </td>
              )}
              <td className="cal-type"><span className={`chip ev-chip ${e.risky ? 'risky' : ''}`}>{EVENT_LABEL[e.type] ?? e.type}</span></td>
              <td className="cal-note">{note}</td>
              <td className="cal-away num">{awayText(e.days_away)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
