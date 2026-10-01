// Diagrams for the lessons (content/lessons/*.md), placed with a line "::visual name". Plain SVG in
// theme colours (CSS variables), so they follow light and dark mode and need no image files.
// Every diagram has a caption and an aria-label that says what it shows in words.

const C = { up: 'var(--up)', down: 'var(--down)', main: 'var(--primary)', muted: 'var(--text-muted)', line: 'var(--border)', text: 'var(--text)' }
const T = ({ x, y, children, anchor = 'middle', size = 11, fill = C.text, weight }) => (
  <text x={x} y={y} textAnchor={anchor} fontSize={size} fill={fill} fontWeight={weight}>{children}</text>
)

function Figure({ label, caption, children, h = 180 }) {
  return (
    <figure className="lesson-visual">
      <svg viewBox={`0 0 340 ${h}`} role="img" aria-label={label}>{children}</svg>
      <figcaption>{caption}</figcaption>
    </figure>
  )
}

// Stock price on the x axis, profit/loss on the y axis. `pts` are [price, pnl] pairs in chart units.
// winX / loseX place the two zone labels clear of the strike lines in each chart.
function Payoff({ pts, xs, marks = [], zero = 90, winX = 36, loseX = 175 }) {
  const X = (p) => 30 + ((p - xs[0]) / (xs[1] - xs[0])) * 290
  const Y = (v) => zero - v
  const path = pts.map(([p, v], i) => `${i ? 'L' : 'M'}${X(p)},${Y(v)}`).join(' ')
  return (
    <>
      <line x1="30" x2="320" y1={zero} y2={zero} stroke={C.line} />
      <T x="325" y={zero + 4} anchor="start" size={9} fill={C.muted}>₹0</T>
      <path d={path} fill="none" stroke={C.main} strokeWidth="2.5" />
      <rect x="30" y="20" width="290" height={zero - 20} fill={C.up} opacity="0.06" />
      <rect x="30" y={zero} width="290" height={170 - zero} fill={C.down} opacity="0.06" />
      <T x={winX} y="32" anchor="start" size={10} fill={C.up}>you make money</T>
      <T x={loseX} y="164" size={10} fill={C.down}>you lose money</T>
      {marks.map(([p, text]) => (
        <g key={text}>
          <line x1={X(p)} x2={X(p)} y1="20" y2="170" stroke={C.muted} strokeDasharray="3 3" />
          <T x={X(p)} y="16" size={9} fill={C.muted}>{text}</T>
        </g>
      ))}
    </>
  )
}

const VISUALS = {
  'option-ticket': () => (
    <Figure label="The buyer pays money to the seller today. The seller promises to pay out if the price crosses the line."
      caption="The buyer pays a small fee now. The seller keeps it, but promises to pay if the price crosses the line.">
      <rect x="20" y="50" width="100" height="70" rx="10" fill="none" stroke={C.main} strokeWidth="2" />
      <T x="70" y="80" weight="600">Buyer</T><T x="70" y="98" size={10} fill={C.muted}>wants a big move</T>
      <rect x="220" y="50" width="100" height="70" rx="10" fill="none" stroke={C.up} strokeWidth="2" />
      <T x="270" y="80" weight="600">Seller (you)</T><T x="270" y="98" size={10} fill={C.muted}>wants a quiet month</T>
      <path d="M122 70 H214" stroke={C.up} strokeWidth="2" markerEnd="url(#a1)" />
      <T x="170" y="40" size={10} fill={C.up}>pays ₹ premium now</T>
      <path d="M218 104 H126" stroke={C.down} strokeWidth="2" strokeDasharray="4 3" markerEnd="url(#a2)" />
      <T x="170" y="142" size={10} fill={C.down}>pays out only if the line is crossed</T>
      <defs>
        <marker id="a1" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill={C.up} /></marker>
        <marker id="a2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill={C.down} /></marker>
      </defs>
    </Figure>
  ),
  'call-put-ladder': () => (
    <Figure label="A price ladder. Today's price is in the middle. Call strikes sit above it, put strikes below it. Far away means out of the money."
      caption="Calls live above today's price, puts below. Far from today's price = out of the money (OTM).">
      {[0, 1, 2, 3, 4, 5, 6].map((i) => {
        const y = 20 + i * 22
        const price = 1650 - i * 50
        const mid = i === 3
        return (
          <g key={i}>
            <rect x="120" y={y} width="100" height="18" rx="4" fill={mid ? C.main : 'none'} opacity={mid ? 0.18 : 1} stroke={mid ? C.main : C.line} />
            <T x="170" y={y + 13} weight={mid ? '700' : undefined}>₹{price}{mid ? '  today' : ''}</T>
          </g>
        )
      })}
      <T x="60" y="50" fill={C.up} weight="600">CALLS</T><T x="60" y="64" size={10} fill={C.muted}>bet on UP</T>
      <T x="60" y="135" fill={C.down} weight="600">PUTS</T><T x="60" y="149" size={10} fill={C.muted}>bet on DOWN</T>
      <T x="280" y="35" size={10} fill={C.muted}>far = OTM</T><T x="280" y="49" size={10} fill={C.muted}>(safer to sell)</T>
      <T x="280" y="150" size={10} fill={C.muted}>far = OTM</T><T x="280" y="164" size={10} fill={C.muted}>(safer to sell)</T>
    </Figure>
  ),
  'theta-decay': () => (
    <Figure label="A curve of an option's time value. It falls slowly at first, then quickly in the last weeks before expiry."
      caption="Like an ice cube melting: slowly at first, then faster near expiry. The seller keeps what melts.">
      <line x1="40" y1="150" x2="320" y2="150" stroke={C.line} /><line x1="40" y1="20" x2="40" y2="150" stroke={C.line} />
      <path d="M40 30 C 180 40, 250 70, 320 148" fill="none" stroke={C.main} strokeWidth="2.5" />
      <T x="44" y="16" anchor="start" size={10} fill={C.muted}>option price</T>
      <T x="40" y="166" size={10} fill={C.muted}>start</T><T x="320" y="166" size={10} fill={C.muted}>expiry</T>
      <T x="130" y="58" size={10} fill={C.up}>slow melt</T><T x="238" y="128" size={10} fill={C.down}>fast melt</T>
    </Figure>
  ),
  'win-loss-bars': () => (
    <Figure label="Nine small green bars for winning months and one very tall red bar for a losing month that is bigger than all nine together."
      caption="Nine small wins can be wiped out by one big loss. Winning often is not enough; losses must stay small.">
      <line x1="20" x2="320" y1="90" y2="90" stroke={C.line} />
      {[...Array(9)].map((_, i) => <rect key={i} x={25 + i * 30} y="74" width="20" height="16" fill={C.up} rx="2" />)}
      <rect x="295" y="90" width="20" height="80" fill={C.down} rx="2" />
      <T x="140" y="66" size={10} fill={C.up}>9 small wins</T>
      <T x="250" y="140" size={10} fill={C.down}>1 big loss →</T>
    </Figure>
  ),
  'delta-odds': () => (
    <Figure h={170} label="A bell curve of where the price may end. Most of it is in the middle. The small tail beyond a 0.15 delta strike is about 15 percent."
      caption="Most months the price ends near the middle. A 0.15-delta strike sits out in the tail: about a 15% chance of being reached.">
      <path d="M20 150 C 110 150, 120 30, 170 30 C 220 30, 230 150, 320 150" fill={C.main} opacity="0.12" stroke={C.main} strokeWidth="2" />
      <path d="M262 127 C 285 142, 300 148, 320 150 L 262 150 Z" fill={C.down} opacity="0.5" />
      <line x1="262" x2="262" y1="20" y2="150" stroke={C.down} strokeDasharray="3 3" />
      <T x="262" y="14" size={10} fill={C.down}>your strike (delta 0.15)</T>
      <T x="170" y="100" weight="600">85%: price stays inside</T>
      <T x="296" y="120" size={10} fill={C.down}>15%</T>
      <T x="170" y="166" size={10} fill={C.muted}>where the price might be at expiry</T>
    </Figure>
  ),
  'margin-vs-premium': () => (
    <Figure h={150} label="A tall bar for about one lakh rupees of margin blocked, next to a tiny bar for about four thousand rupees of premium collected."
      caption="You lock up a big deposit (margin) to earn a small fee (premium). Judge a trade by fee ÷ deposit.">
      <rect x="70" y="20" width="70" height="110" fill={C.muted} opacity="0.35" rx="4" />
      <T x="105" y="80" weight="600">₹1,00,000</T><T x="105" y="145" size={10} fill={C.muted}>margin locked</T>
      <rect x="200" y="125" width="70" height="5" fill={C.up} rx="2" />
      <T x="235" y="115" weight="600" fill={C.up}>₹4,000</T><T x="235" y="145" size={10} fill={C.muted}>premium earned</T>
    </Figure>
  ),
  'stoploss-timeline': () => (
    <Figure h={130} label="A timeline. Days 1 to 14 have no stop-loss. From day 15 the stop-loss is on. The last 7 days before expiry, every position is closed."
      caption="Days 1–14: let it breathe. From day 15: exit if the price climbs back to what you sold it for. Last 7 days: always close.">
      <rect x="20" y="50" width="130" height="30" fill={C.muted} opacity="0.2" /><T x="85" y="69">no stop-loss</T>
      <rect x="150" y="50" width="120" height="30" fill={C.main} opacity="0.2" /><T x="210" y="69">stop-loss ON</T>
      <rect x="270" y="50" width="50" height="30" fill={C.down} opacity="0.25" /><T x="295" y="69" size={10}>close all</T>
      <T x="20" y="100" size={10} fill={C.muted}>day 1</T><T x="150" y="100" size={10} fill={C.muted}>day 15</T>
      <T x="270" y="100" size={10} fill={C.muted}>7 days left</T><T x="320" y="100" size={10} fill={C.muted}>expiry</T>
    </Figure>
  ),
  'loss-multiplier': () => (
    <Figure h={150} label="Bars showing a loss of 1 times, 4 times and 14 times the premium collected, getting much taller."
      caption="Sold for ₹8? If it climbs to ₹120 you lose 14 times what you earned. Exit early, while the loss is small.">
      {[[1, '₹16', '1×'], [4, '₹40', '4×'], [14, '₹120', '14×']].map(([m, p, l], i) => (
        <g key={l}>
          <rect x={50 + i * 95} y={130 - m * 8} width="50" height={m * 8} fill={C.down} opacity={0.4 + i * 0.2} rx="3" />
          <T x={75 + i * 95} y={124 - m * 8} weight="600" fill={C.down}>{l}</T>
          <T x={75 + i * 95} y="145" size={10} fill={C.muted}>price {p}</T>
        </g>
      ))}
    </Figure>
  ),
  'payoff-short-call': () => (
    <Figure label="Short call payoff: flat profit while the price stays below the strike, then a line falling down to the right."
      caption="Sell a call: keep the premium while the price stays below your strike. Above it, losses grow with every rupee.">
      <Payoff xs={[0, 10]} pts={[[0, 30], [6, 30], [10, -70]]} marks={[[6, 'strike']]} loseX={100} />
    </Figure>
  ),
  'payoff-short-put': () => (
    <Figure label="Short put payoff: a line rising from the lower left up to flat profit once the price is above the strike."
      caption="Sell a put: keep the premium while the price stays above your strike. Below it, losses grow.">
      <Payoff xs={[0, 10]} pts={[[0, -70], [4, 30], [10, 30]]} marks={[[4, 'strike']]} winX={180} loseX={250} />
    </Figure>
  ),
  'payoff-strangle': () => (
    <Figure label="Short strangle payoff: a flat-topped hill. Profit between the two strikes, losses on both sides beyond the breakevens."
      caption="A strangle is a flat-topped hill: you win while the price stays between the two breakevens.">
      <Payoff xs={[0, 12]} pts={[[0, -60], [3, 30], [9, 30], [12, -60]]} marks={[[2, 'breakeven'], [10, 'breakeven']]} winX={128} />
    </Figure>
  ),
  'payoff-long-call': () => (
    <Figure label="Long call payoff: a flat loss equal to the premium paid while the price stays below the strike, then a line rising to the right past the breakeven."
      caption="Buy a call: the most you can lose is what you paid. You only make money if the price rises past strike plus premium, before expiry.">
      <Payoff xs={[0, 10]} pts={[[0, -25], [5, -25], [10, 75]]} marks={[[5, 'strike'], [6.25, 'breakeven']]} winX={230} loseX={110} />
    </Figure>
  ),
  'payoff-put-spread': () => (
    <Figure label="Bull put spread payoff: flat profit above the sold strike, a falling line between the two strikes, then flat again below the bought strike, so the loss stops growing."
      caption="Sold put + bought put further down: below the bought strike the loss stops growing. The most you can lose is known before you trade.">
      <Payoff xs={[0, 10]} pts={[[0, -50], [3, -50], [5, 30], [10, 30]]} marks={[[3, 'bought'], [5, 'sold']]} winX={190} loseX={90} />
    </Figure>
  ),
  'roll-out': () => (
    <Figure h={150} label="A price line climbing towards a sold call strike; the leg is closed and a new call is sold at a higher strike, further from the price."
      caption="Rolling: close the call the price is closing in on, and sell a new one further out. The loss on the old one is booked.">
      <line x1="20" x2="320" y1="70" y2="70" stroke={C.down} strokeDasharray="4 3" />
      <T x="24" y="64" anchor="start" size={10} fill={C.down}>old strike (closed)</T>
      <line x1="200" x2="320" y1="30" y2="30" stroke={C.up} strokeDasharray="4 3" />
      <T x="316" y="24" anchor="end" size={10} fill={C.up}>new strike, further out</T>
      <path d="M20 130 L70 120 L120 112 L170 96 L200 84" fill="none" stroke={C.main} strokeWidth="2.5" />
      <path d="M200 84 L200 32" fill="none" stroke={C.muted} strokeWidth="1.5" strokeDasharray="2 3" />
      <T x="206" y="110" anchor="start" size={10} fill={C.muted}>roll here</T>
    </Figure>
  ),
  'sigma-bands': () => (
    <Figure h={150} label="A bell curve with a darker middle band marked 68 percent for one sigma and a wider band marked 95 percent for two sigma."
      caption="About 68 in 100 months the price ends inside 1σ, about 95 in 100 inside 2σ. Put your strikes outside 1σ.">
      <rect x="60" y="20" width="220" height="110" fill={C.main} opacity="0.07" />
      <rect x="115" y="20" width="110" height="110" fill={C.main} opacity="0.14" />
      <path d="M20 130 C 110 130, 120 25, 170 25 C 220 25, 230 130, 320 130" fill="none" stroke={C.main} strokeWidth="2" />
      <T x="170" y="80" weight="600">68%</T><T x="170" y="94" size={10} fill={C.muted}>1σ</T>
      <T x="87" y="34" size={10} fill={C.muted}>2σ: 95%</T><T x="253" y="34" size={10} fill={C.muted}>2σ: 95%</T>
    </Figure>
  ),
  'event-gap': () => (
    <Figure label="A price line moving calmly, then jumping overnight past the strike line on results day, skipping over the stop-loss."
      caption="On results day the price can jump overnight, straight past your strike. No stop-loss can catch a jump.">
      <line x1="20" x2="320" y1="60" y2="60" stroke={C.down} strokeDasharray="4 3" />
      <T x="24" y="54" anchor="start" size={10} fill={C.down}>your strike</T>
      <path d="M20 130 L60 125 L100 132 L140 122 L180 128 L200 124" fill="none" stroke={C.main} strokeWidth="2.5" />
      <path d="M200 124 L230 40" fill="none" stroke={C.down} strokeWidth="2" strokeDasharray="2 4" />
      <path d="M230 40 L270 44 L310 36" fill="none" stroke={C.main} strokeWidth="2.5" />
      <T x="215" y="100" anchor="start" size={10} fill={C.down}>overnight jump</T>
      <T x="215" y="165" size={10} fill={C.muted}>results day</T>
      <line x1="215" x2="215" y1="20" y2="150" stroke={C.muted} strokeDasharray="2 3" />
    </Figure>
  ),
}

export default function LessonVisual({ name }) {
  const V = VISUALS[name]
  return V ? <V /> : null
}

export const VISUAL_NAMES = Object.keys(VISUALS)
