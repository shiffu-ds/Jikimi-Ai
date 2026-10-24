// "지킴이" drawn as strokes, so it renders on machines without a Korean font (no tofu boxes).
export function HangulMark({ className, title = "지킴이" }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 300 100" className={className} role="img" aria-label={title} fill="none" stroke="currentColor" strokeWidth={9} strokeLinecap="round" strokeLinejoin="round">
      <title>{title}</title>
      {/* 지 */}
      <path d="M14 22H58M36 24C34 46 26 62 12 78M37 46L60 76M80 10V92" />
      {/* 킴 */}
      <path d="M110 14H152C152 32 144 44 128 52M114 33H150M176 8V56M120 64H168V94H120Z" />
      {/* 이 */}
      <circle cx="234" cy="51" r="22" />
      <path d="M276 10V92" />
    </svg>
  );
}
