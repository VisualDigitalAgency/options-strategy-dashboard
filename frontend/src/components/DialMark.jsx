export default function DialMark() {
  return (
    <svg className="dial-mark" viewBox="0 0 32 32" aria-hidden>
      <circle cx="16" cy="16" r="14.5" className="dm-ring" />
      <path d="M5 11 C 12 11.5, 20 14, 26.5 25" className="dm-curve" />
      <line x1="16" y1="16" x2="16" y2="5.5" className="dm-hand" />
      <circle cx="16" cy="16" r="2" className="dm-pin" />
    </svg>
  )
}
