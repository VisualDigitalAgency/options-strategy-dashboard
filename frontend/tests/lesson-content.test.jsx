// Every lesson file in content/lessons renders with the markdown subset: each "::visual" name exists,
// no raw markdown is left over, and every diagram has a caption and an accessible label.
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { default: Markdown } = await import('../src/components/Markdown.jsx')
const { VISUAL_NAMES } = await import('../src/components/LessonVisuals.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

// Tests run bundled from a cache folder, so find the content from the working directory instead.
const dir = [join(process.cwd(), 'content/lessons'), join(process.cwd(), '../content/lessons')].find(existsSync)
const files = readdirSync(dir).filter((f) => f.endsWith('.md')).sort()
check('eleven lesson files', files.length === 11, files.length)
document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
const root = createRoot(document.getElementById('r'))
const used = new Set()
for (const f of files) {
  const src = readFileSync(join(dir, f), 'utf8')
  const names = [...src.matchAll(/^::visual (.+)$/gm)].map((m) => m[1].trim())
  names.forEach((n) => used.add(n))
  await act(async () => root.render(h(Markdown, { source: src })))
  const figs = [...document.querySelectorAll('figure.lesson-visual')]
  const text = document.querySelector('.md').textContent
  check(`${f}: every visual exists and renders`, names.length > 0 && names.every((n) => VISUAL_NAMES.includes(n)) && figs.length === names.length, names)
  check(`${f}: diagrams labelled and captioned`, figs.every((fg) => fg.querySelector('svg[role=img]')?.getAttribute('aria-label') && fg.querySelector('figcaption')?.textContent))
  check(`${f}: no raw markdown left`, !/\*|::visual|^## |^> /m.test(text))
  check(`${f}: opens with an everyday comparison`, document.querySelector('.md > aside.md-tip:first-child') !== null)
}
check('every diagram is used by some lesson', VISUAL_NAMES.every((n) => used.has(n)), VISUAL_NAMES.filter((n) => !used.has(n)))
process.exit(ok ? 0 : 1)
