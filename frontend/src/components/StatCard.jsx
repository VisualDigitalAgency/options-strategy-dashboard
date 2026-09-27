export default function StatCard({ label, value, sub, tone }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value mono ${tone ?? ''}`}>{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}
