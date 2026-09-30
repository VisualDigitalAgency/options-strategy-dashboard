// Renders the small markdown subset lesson files use (content/lessons/*.md): "## " headings,
// "- " and "1. " lists, paragraphs, **bold** / *italic* inline, "> " tip boxes, and "::visual name"
// for a diagram from LessonVisuals. Output is React elements only, never
// HTML strings, so lesson text can't inject markup (the CSP forbids inline scripts anyway).
import LessonVisual from './LessonVisuals'

function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.length > 2 && part.startsWith('*') && part.endsWith('*')) return <em key={i}>{part.slice(1, -1)}</em>
    return part
  })
}

export default function Markdown({ source }) {
  const blocks = source.trim().split(/\n\s*\n/)
  return (
    <div className="md">
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        if (block.startsWith('::visual ')) return <LessonVisual key={i} name={block.slice(9).trim()} />
        if (block.startsWith('## ')) return <h2 key={i}>{inline(block.slice(3))}</h2>
        if (lines.every((l) => l.startsWith('> '))) {
          return <aside key={i} className="md-tip">{inline(lines.map((l) => l.slice(2)).join(' '))}</aside>
        }
        if (lines.every((l) => l.startsWith('- '))) {
          return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.slice(2))}</li>)}</ul>
        }
        if (lines.every((l) => /^\d+\. /.test(l))) {
          return <ol key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\d+\. /, ''))}</li>)}</ol>
        }
        return <p key={i}>{inline(lines.join(' '))}</p>
      })}
    </div>
  )
}
