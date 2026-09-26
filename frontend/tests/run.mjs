// Bundles each tests/*.test.jsx with rolldown (JSX, app imports) and runs it in Node with a
// happy-dom document. A test prints PASS/FAIL lines and exits non-zero on failure.
//   npm test                     every test
//   npm test -- pivot-levels     only files whose name contains the filter
import { spawnSync } from 'node:child_process'
import { readdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { rolldown } from 'rolldown'

const here = dirname(fileURLToPath(import.meta.url))
const out = join(here, '..', 'node_modules', '.cache', 'ui-tests')
const filter = process.argv[2] ?? ''
const files = readdirSync(here).filter((f) => f.endsWith('.test.jsx') && f.includes(filter)).sort()
rmSync(out, { recursive: true, force: true })

const results = []
for (const f of files) {
  const bundle = await rolldown({
    input: join(here, f),
    platform: 'node',
    external: ['happy-dom', '@happy-dom/global-registrator'],
    logLevel: 'silent',
  })
  const dir = join(out, f.replace(/\.test\.jsx$/, ''))
  const { output } = await bundle.write({ dir, format: 'esm', entryFileNames: '[name].mjs' })
  await bundle.close()
  console.log(`\n===== ${f}`)
  const r = spawnSync(process.execPath, [join(dir, output[0].fileName)], { stdio: 'inherit', timeout: 60_000 })
  results.push([f, r.status === 0])
}
console.log('\n===== summary')
for (const [f, ok] of results) console.log(`${ok ? 'PASS' : 'FAIL'}  ${f}`)
process.exit(results.length && results.every(([, ok]) => ok) ? 0 : 1)
