const Line = ({ w, h = 14, style }) => <span className="skeleton" style={{ width: w, height: h, ...style }} />

function SkCard({ height, title = 140 }) {
  return (
    <section className="card">
      <header className="card-head">
        <Line w={title} h={18} />
        <Line w={180} h={12} />
      </header>
      <span className="skeleton" style={{ height, borderRadius: 8 }} />
    </section>
  )
}

export default function DetailSkeleton() {
  return (
    <div className="detail" aria-busy="true" aria-label="Loading stock detail">
      <Line w={90} h={14} />
      <section className="hero">
        <div className="hero-main">
          <Line w={180} h={34} />
          <div className="hero-tags">
            <span className="skeleton sk-pill" />
            <span className="skeleton sk-pill" style={{ width: 84 }} />
          </div>
          <Line w={420} h={12} style={{ maxWidth: '80vw' }} />
        </div>
        <span className="skeleton" style={{ width: 160, height: 48, borderRadius: 6 }} />
      </section>
      <section className="stats">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="stat">
            <Line w="50%" h={12} />
            <Line w="70%" h={24} style={{ margin: '4px 0' }} />
            <Line w="85%" h={10} />
          </div>
        ))}
      </section>
      <div className="two-col wide-left">
        <SkCard height={300} />
        <SkCard height={300} title={110} />
      </div>
      <SkCard height={140} />
    </div>
  )
}
