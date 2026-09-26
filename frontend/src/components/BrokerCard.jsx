export default function BrokerCard({ b }) {
  return (
    <div className="broker-card">
      <span className="chip broker-soon">Coming soon</span>
      <div className="broker-logo"><img src={b.logo} alt="" /></div>
      <b className="broker-name">{b.name}</b>
      <button className="btn small ghost" disabled>Connect</button>
    </div>
  )
}
