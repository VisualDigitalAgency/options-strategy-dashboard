import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'

const ICON = { pass: CheckCircle2, fail: XCircle, warn: AlertTriangle, info: Info }
const LABEL = { pass: 'Pass', fail: 'Fail', warn: 'Caution', info: 'Info' }

export default function Checklist({ checks, sentiment }) {
  return (
    <ul className="checklist">
      {checks.map((c, i) => {
        const Icon = ICON[c.status]
        return (
          <li key={i} className={`check check-${c.status}`}>
            <Icon size={18} aria-hidden />
            <div>
              <span className="check-rule">
                {c.rule} <span className="sr-only">: {LABEL[c.status]}</span>
              </span>
              <span className="check-detail">{c.detail}</span>
            </div>
          </li>
        )
      })}
      {sentiment?.signals.map((s, i) => (
        <li key={`s${i}`} className="check check-info">
          <Info size={18} aria-hidden />
          <div>
            <span className="check-rule">Sentiment signal</span>
            <span className="check-detail">{s}</span>
          </div>
        </li>
      ))}
    </ul>
  )
}
