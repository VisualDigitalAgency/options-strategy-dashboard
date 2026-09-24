import { shortDate, rupee2 } from '../format'

const days = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000)

export default function SLTimeline({ sl }) {
  const total = days(sl.entry, sl.expiry) || 1
  const graceShare = Math.min(1, days(sl.entry, sl.activates_on) / total) * 100
  return (
    <div className="timeline">
      <div className="tl-track" aria-hidden>
        <div className="tl-grace" style={{ width: `${graceShare}%` }} />
        <div className="tl-active" style={{ width: `${100 - graceShare}%` }} />
        <span className="tl-mark" style={{ left: 0 }} />
        <span className="tl-mark" style={{ left: `${graceShare}%` }} />
        <span className="tl-mark" style={{ left: '100%' }} />
      </div>
      <div className="tl-labels">
        <div style={{ left: 0 }}>
          <b>Entry</b>
          <span className="mono">{shortDate(sl.entry)}</span>
        </div>
        <div style={{ left: `${graceShare}%` }} className="center">
          <b>SL goes live</b>
          <span className="mono">{shortDate(sl.activates_on)}</span>
        </div>
        <div style={{ left: '100%' }} className="end">
          <b>Expiry</b>
          <span className="mono">{shortDate(sl.expiry)}</span>
        </div>
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
            <b>Day 15 onward: buy back at premium collected.</b>{' '}
            {Object.entries(sl.levels).map(([side, px]) => `${side} at ${rupee2(px)}`).join(', ')}.
          </p>
        </div>
      </div>
    </div>
  )
}
