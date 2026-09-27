import { rupee } from '../format'

/** Used-vs-free margin as a proportional stacked bar + legend, shared by VirtualAccount.jsx and
 *  BrokerAccount.jsx. `children` renders below the legend (e.g. a "view positions" link). */
export default function EquityBar({ used, free, usedLabel, freeLabel, children }) {
  return (
    <div className="equity" aria-label={`${usedLabel} ${rupee(used)}, ${freeLabel} ${rupee(free)}`}>
      <div className="equity-bar" aria-hidden>
        <span className="eq-used" style={{ flexGrow: Math.max(used, 0) || 0.0001 }} />
        <span className="eq-free" style={{ flexGrow: Math.max(free, 0) || 0.0001 }} />
      </div>
      <div className="equity-legend">
        <span><i className="eq-used" aria-hidden /> {usedLabel} <b className="num">{rupee(used)}</b></span>
        <span><i className="eq-free" aria-hidden /> {freeLabel} <b className="num">{rupee(free)}</b></span>
      </div>
      {children}
    </div>
  )
}
