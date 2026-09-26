import { Check, Palette } from 'lucide-react'
import { PALETTES, usePalette } from '../palette'

/** Half of a preview tile: page, a panel with an accent bar, and profit/loss ticks. */
function Mini({ sw }) {
  const [bg, surface, accent, up, down] = sw
  return (
    <span className="pal-mini" style={{ background: bg }}>
      <span className="pal-panel" style={{ background: surface }}>
        <span className="pal-bar" style={{ background: accent }} />
        <span className="pal-ticks">
          <i style={{ background: up }} />
          <i style={{ background: down }} />
          <i style={{ background: up, opacity: 0.5 }} />
        </span>
      </span>
    </span>
  )
}

export default function PalettePicker() {
  const [palette, setPalette] = usePalette()
  return (
    <section className="card">
      <header className="card-head">
        <h2><Palette size={16} aria-hidden />Appearance</h2>
        <span className="muted small">Colour palette. The switch in the top bar picks dark or light.</span>
      </header>
      <div className="pal-grid" role="radiogroup" aria-label="Colour palette">
        {PALETTES.map((p) => {
          const on = p.id === palette
          return (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={on}
              className={`pal-tile ${on ? 'on' : ''}`}
              onClick={() => setPalette(p.id)}
            >
              <span className="pal-preview" aria-hidden>
                <Mini sw={p.dark} />
                <Mini sw={p.light} />
              </span>
              <span className="pal-name">
                {p.name}
                {on && <Check size={15} aria-hidden />}
              </span>
              <span className="pal-note">{p.note}</span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
