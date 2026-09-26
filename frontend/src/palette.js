import { useEffect, useState } from 'react'
import { savePref } from './auth'

// Colour palettes. Each has a dark and a light variant in index.css under
// :root[data-palette='<id>']; the dark/light switch still picks the variant.
// Swatches are [background, surface, accent, profit, loss] for the picker preview.
export const PALETTES = [
  {
    id: 'dial', name: 'Dial', note: 'Navy watch dial, brass hands',
    dark: ['#0b1422', '#16243a', '#c9a15a', '#4fb98a', '#e0685e'],
    light: ['#e4e8ee', '#f6f7f9', '#8c6a2a', '#1f8a5e', '#c2453b'],
  },
  {
    id: 'terminal', name: 'Terminal', note: 'Ember black, flame-red signal',
    dark: ['#1d1410', '#2d221c', '#ff5533', '#4fb98a', '#ff4d8d'],
    light: ['#fffaf6', '#ffffff', '#ff2a00', '#1f8a5e', '#c2185b'],
  },
  {
    id: 'bankers', name: "Banker's Lamp", note: 'Green glass shade, ledger gold',
    dark: ['#0c1712', '#172a21', '#d6bb5c', '#6ad49a', '#ee7466'],
    light: ['#e3e9e4', '#f5f8f5', '#7a6414', '#1a8052', '#c2453b'],
  },
  {
    id: 'ultraviolet', name: 'Ultraviolet', note: 'Indigo night, cyan signal',
    dark: ['#100f24', '#1e1c3d', '#5ee0e6', '#53c79a', '#f0707a'],
    light: ['#e7e6f3', '#f7f6fc', '#0e7c86', '#1f8a5e', '#c23b4f'],
  },
  {
    id: 'petrol', name: 'Petrol', note: 'Deep teal water, ice-blue glint',
    dark: ['#0a1a1d', '#152c31', '#8fd3ff', '#5cc79a', '#ee7a6c'],
    light: ['#e2ecec', '#f5f9f9', '#1d6fa3', '#1c8058', '#bf4438'],
  },
]

const KEY = 'options-screener-palette'
const valid = (id) => PALETTES.some((p) => p.id === id)

export function savedPalette() {
  try {
    const p = localStorage.getItem(KEY)
    return valid(p) ? p : 'dial'
  } catch {
    return 'dial'
  }
}

export function usePalette() {
  const [palette, setPalette] = useState(() => document.documentElement.dataset.palette || savedPalette())
  useEffect(() => {
    document.documentElement.dataset.palette = palette
    try {
      localStorage.setItem(KEY, palette)
    } catch {
      /* storage blocked: the palette lasts for this page only */
    }
  }, [palette])
  const choose = (id) => {
    if (!valid(id)) return
    setPalette(id)
    savePref({ palette: id })
  }
  return [palette, choose]
}
