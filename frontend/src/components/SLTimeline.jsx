import { shortDate, rupee2 } from '../format'

const days = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000)

export default function SLTimeline({ sl }) {
  const total = days(sl.entry, sl.expiry) || 1
  const at = (d) => Math.min(1, Math.max(0, days(sl.entry, d) / total)) * 100
  const grace = at(sl.activates_on)
  const exit = sl.time_exit_on ? at(sl.time_exit_on) : 100
  return (
    <div className="timeline">
      <div className="tl-track" aria-hidden>
        <div className="tl-grace" style={{ width: `${grace}%` }} />
        <div className="tl-active" style={{ width: `${exit - grace}%` }} />
        <div className="tl-closed" style={{ width: `${100 - exit}%` }} />
        <span className="tl-mark" style={{ left: 0 }} />
        <span className="tl-mark" style={{ left: `${grace}%` }} />
        <span className="tl-mark exit" style={{ left: `${exit}%` }} />
        <span className="tl-mark" style={{ left: '100%' }} />
      </div>
      <div className="tl-labels">
        <div style={{ left: 0 }}>
          <b>Entry</b>
          <span className="mono">{shortDate(sl.entry)}</span>
        </div>
        <div style={{ left: `${grace}%` }} className="center">
          <b>SL goes live</b>
          <span className="mono">{shortDate(sl.activates_on)}</span>
        </div>
        {sl.time_exit_on && (
          <div style={{ left: `${exit}%` }} className="end tl-exit-label">
            <b>Time exit</b>
            <span className="mono">{shortDate(sl.time_exit_on)}</span>
          </div>
        )}
      </div>
      <div className="tl-phases">
        <div>
          <span className="phase-dot grace" aria-hidden />
          <p>
            <b>Days 1–15: no stop loss.</b> Theta decay does the work. Gap risk is open, so watch for results and
            macro events.
          </p>
        </div>
        <div>
          <span className="phase-dot active" aria-hidden />
          <p>
            <b>Day 15 onward: group stop loss.</b> If any leg reaches its premium collected (
            {Object.entries(sl.levels).map(([side, px]) => `${side} ${rupee2(px)}`).join(', ')}), every leg is bought back together.
          </p>
        </div>
        <div>
          <span className="phase-dot target" aria-hidden />
          <p>
            <b>Any day: take profit at 90%.</b> Once 90% of the premium collected has decayed, every leg is bought
            back. The last 10% isn't worth the gap risk.
          </p>
        </div>
        {sl.time_exit_on && (
          <div>
            <span className="phase-dot closed" aria-hidden />
            <p>
              <b>From {shortDate(sl.time_exit_on)}: everything closes.</b> Stock options settle by physical delivery,
              so the position exits with under 7 days left, before expiry {shortDate(sl.expiry)}.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
