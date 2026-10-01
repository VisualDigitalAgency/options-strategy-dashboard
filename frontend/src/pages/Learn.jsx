import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, Clock, GraduationCap, Lock, XCircle } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'
import Markdown from '../components/Markdown'
import { useTitle } from '../brand'

const LEVEL = {
  1: 'Level 1 · Learner', 2: 'Level 2 · Apprentice', 3: 'Level 3 · Seller', 4: 'Level 4 · Disciplined',
  5: 'Level 5 · Consistent', 6: 'Level 6 · Risk manager', 7: 'Level 7 · Strategist', 8: 'Level 8 · Expert', 9: 'Level 9 · Master',
}
// Levels with no lessons are practice (#161): say so, so the course doesn't seem to skip a step.
const PRACTICE = {
  4: 'No lessons at this level: it is practice. Hold 3 profitable months in a row and never sell a short leg at delta 0.15 or more, using what Levels 1–3 taught. Lessons continue at Level 5.',
  7: 'No lessons from here on: Levels 7–9 are about your track record. Keep profitable months coming with a small drawdown; your Progress page shows each check.',
}
const DISCLAIMER = 'Educational content, not investment advice. Practise with paper trading only.'

// Signed-in users see which quizzes they've passed; signed-out visitors see the course only.
// null until loaded, so a lock never flashes up before the record arrives.
function useProgress(user, slug) {
  const [done, setDone] = useState(null)
  useEffect(() => {
    if (!user) return
    rpc('lesson_progress').then((rows) => setDone(Object.fromEntries(rows.map((r) => [r.slug, r])))).catch(() => {})
  }, [user, slug]) // refetched per lesson, so passing one unlocks the next
  return done
}

export function Learn() {
  const { user } = useAuth()
  const [list, setList] = useState(null)
  const [error, setError] = useState(null)
  const done = useProgress(user)
  useTitle('Learn option selling')
  useEffect(() => { rpc('lessons_list').then(setList).catch((e) => setError(e.message)) }, [])

  const levels = list ? [...new Set([...list.map((l) => l.level), ...Object.keys(PRACTICE).map(Number)])].sort((a, b) => a - b) : []
  const passed = Object.values(done ?? {}).filter((d) => d.passed_at).length
  // Quizzes unlock in course order (#161): every lesson after the first unpassed one is locked.
  const locked = new Set()
  if (user && done && list) {
    list.forEach((l, i) => { if (i > 0 && !done[l.slug]?.passed_at && !done[list[i - 1].slug]?.passed_at) locked.add(l.slug) })
  }
  return (
    <div className="detail learn">
      <header className="page-head">
        <div>
          <h1 className="display"><GraduationCap size={26} aria-hidden /> Learn option selling</h1>
          <p className="lede">Short lessons with a quiz each, from what an option is to managing a short strangle.
            {user && list ? ` You've passed ${passed} of ${list.length}.` : ''}</p>
        </div>
      </header>
      {error && <div className="alert" role="alert"><AlertCircle size={18} aria-hidden /> {error}</div>}
      {levels.map((lv) => (
        <section key={lv} className="learn-level" aria-labelledby={`lv-${lv}`}>
          <h2 id={`lv-${lv}`}>{LEVEL[lv] ?? `Level ${lv}`}</h2>
          {PRACTICE[lv] && <p className="muted learn-practice">{PRACTICE[lv]}</p>}
          <div className="learn-grid">
            {list.filter((l) => l.level === lv).map((l) => (
              <Link key={l.slug} to={`/learn/${l.slug}`} className={`card learn-card${locked.has(l.slug) ? ' locked' : ''}`}>
                <b>{l.title}</b>
                <span className="muted small">{l.summary}</span>
                <span className="learn-meta small">
                  <span><Clock size={13} aria-hidden /> {l.minutes} min · {l.questions} questions</span>
                  {done?.[l.slug]?.passed_at && <span className="learn-passed"><CheckCircle2 size={13} aria-hidden /> Passed</span>}
                  {locked.has(l.slug) && <span className="learn-locked"><Lock size={13} aria-hidden /> Locked</span>}
                </span>
              </Link>
            ))}
          </div>
        </section>
      ))}
      <p className="muted small learn-disclaimer">{DISCLAIMER}</p>
    </div>
  )
}

function Quiz({ lesson, onDone }) {
  const [answers, setAnswers] = useState(() => lesson.questions.map(() => null))
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const complete = answers.every((a) => a !== null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await rpc('lesson_submit_quiz', { slug: lesson.slug, answers })
      setResult(r)
      onDone?.(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card quiz" aria-labelledby="quiz-h">
      <h2 id="quiz-h">Quiz</h2>
      <p className="muted small">Score {result?.pass_pct ?? 80}% or more to pass. After a failed attempt you can try again in 24 hours.</p>
      <ol className="quiz-list">
        {lesson.questions.map((q, i) => {
          const res = result?.results[i]
          return (
            <li key={i} className={res ? (res.correct ? 'right' : 'wrong') : ''}>
              <fieldset disabled={!!result}>
                <legend>{q.q}</legend>
                {q.options.map((opt, j) => (
                  <label key={j} className={res?.answer === j ? 'quiz-answer' : ''}>
                    <input type="radio" name={`q${i}`} checked={answers[i] === j}
                      onChange={() => setAnswers((a) => a.map((v, k) => (k === i ? j : v)))} />
                    {opt}
                  </label>
                ))}
              </fieldset>
              {res && (
                <p className="quiz-why small">
                  {res.correct ? <CheckCircle2 size={14} aria-hidden /> : <XCircle size={14} aria-hidden />} {res.why}
                </p>
              )}
            </li>
          )
        })}
      </ol>
      {error && <div className="alert" role="alert"><AlertCircle size={18} aria-hidden /> {error}</div>}
      {result ? (
        <p className={`quiz-score ${result.passed ? 'pass' : 'fail'}`} role="status">
          {result.passed ? `Passed with ${result.score}%.` : `${result.score}%: not a pass yet. Review the lesson and try again after 24 hours.`}
          {result.first_pass && ' Well done, this counts towards your level.'}
        </p>
      ) : (
        <button className="btn primary" disabled={!complete || busy} onClick={submit}>
          {busy ? 'Checking…' : complete ? 'Submit answers' : `Answer all ${lesson.questions.length} questions`}
        </button>
      )}
    </section>
  )
}

export function Lesson() {
  const { slug } = useParams()
  const { user } = useAuth()
  const done = useProgress(user, slug)
  // Keyed by slug, so moving to the next lesson never shows the previous one's text or error.
  const [loaded, setLoaded] = useState({})
  const lesson = loaded.slug === slug ? loaded.data : null
  const error = loaded.slug === slug ? loaded.error : null
  useTitle(lesson?.title)
  useEffect(() => {
    rpc('lessons_get', { slug }).then((data) => setLoaded({ slug, data }))
      .catch((e) => setLoaded({ slug, error: e.message }))
  }, [slug])

  if (error) {
    return (
      <div className="detail learn">
        <div className="alert" role="alert"><AlertCircle size={18} aria-hidden /> {error}</div>
        <Link to="/learn" className="btn ghost"><ArrowLeft size={15} aria-hidden /> All lessons</Link>
      </div>
    )
  }
  if (!lesson) return <div className="detail learn"><p className="muted">Loading…</p></div>
  return (
    <article className="detail learn lesson">
      <Link to="/learn" className="muted small back-link"><ArrowLeft size={14} aria-hidden /> All lessons</Link>
      <header className="page-head">
        <div>
          <span className="chip">{LEVEL[lesson.level] ?? `Level ${lesson.level}`}</span>
          <h1 className="display">{lesson.title}</h1>
          <p className="lede">{lesson.summary}</p>
        </div>
      </header>
      <Markdown source={lesson.body} />
      <p className="muted small learn-disclaimer">{DISCLAIMER}</p>
      {user ? (!done ? null : lesson.prev && !done[lesson.slug]?.passed_at && !done[lesson.prev]?.passed_at ? (
        <section className="card quiz-cta" role="status">
          <h2><Lock size={18} aria-hidden /> Quiz locked</h2>
          <p>Lessons unlock in order. Pass the previous lesson's quiz to unlock this one.</p>
          <div className="quiz-cta-actions">
            <Link to={`/learn/${lesson.prev}`} className="btn primary"><ArrowLeft size={15} aria-hidden /> Previous lesson</Link>
          </div>
        </section>
      ) : <Quiz key={lesson.slug} lesson={lesson} />) : (
        <section className="card quiz-cta">
          <h2>Take the quiz and practise for free</h2>
          <p>Create a free account to take this quiz, track your progress through the levels, and practise
            option selling on a ₹10 lakh paper-trading account with live NSE prices.</p>
          <div className="quiz-cta-actions">
            <Link to="/register" className="btn primary">Join free</Link>
            <Link to={`/login?next=${encodeURIComponent(`/learn/${lesson.slug}`)}`} className="btn ghost">Sign in</Link>
          </div>
        </section>
      )}
      <nav className="lesson-nav" aria-label="Lessons">
        {lesson.prev ? <Link to={`/learn/${lesson.prev}`} className="btn ghost"><ArrowLeft size={15} aria-hidden /> Previous</Link> : <span />}
        {lesson.next && <Link to={`/learn/${lesson.next}`} className="btn ghost">Next <ArrowRight size={15} aria-hidden /></Link>}
      </nav>
    </article>
  )
}
