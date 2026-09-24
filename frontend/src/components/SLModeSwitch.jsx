import { BellRing, ShieldOff, Zap } from 'lucide-react'

export const SL_MODES = [
  { value: 'auto', label: 'Auto exit', icon: Zap, help: 'From day 15, buys the leg back automatically once its price reaches the premium collected.' },
  { value: 'alert', label: 'Alert only', icon: BellRing, help: 'Flags the leg when the stop is hit. You decide whether to exit.' },
  { value: 'off', label: 'Off', icon: ShieldOff, help: 'No stop loss. The leg stays open until you exit or it expires.' },
]

export default function SLModeSwitch({ value, onChange, compact = false, disabled = false, label = 'Stop-loss mode' }) {
  return (
    <div className={`segmented sl-switch ${compact ? 'small' : ''}`} role="radiogroup" aria-label={label}>
      {SL_MODES.map(({ value: v, label: l, icon: Icon, help }) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={value === v}
          className={value === v ? `active sl-${v}` : ''}
          onClick={() => value !== v && onChange(v)}
          disabled={disabled}
          title={help}
        >
          <Icon size={compact ? 13 : 15} aria-hidden />
          {compact ? l.split(' ')[0] : l}
        </button>
      ))}
    </div>
  )
}

export const slHelp = (mode) => SL_MODES.find((m) => m.value === mode)?.help ?? ''
