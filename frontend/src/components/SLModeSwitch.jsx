import { BellRing, ShieldOff, Zap } from 'lucide-react'

export const SL_MODES = [
  { value: 'auto', label: 'Auto exit', icon: Zap, help: 'From day 15, when the price of any leg reaches the premium collected, every leg of that position is bought back.' },
  { value: 'alert', label: 'Alert only', icon: BellRing, help: 'Flags the position when a leg hits its stop. You decide whether to exit it.' },
  { value: 'off', label: 'Off', icon: ShieldOff, help: 'No stop loss on this leg. The 7-day time exit still closes the position before expiry.' },
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
