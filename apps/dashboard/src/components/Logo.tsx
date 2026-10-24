// Jikimi mark: a shield holding an always-open eye (지킴이 = the one who keeps watch).
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} role="img" aria-label="Jikimi AI">
      <defs>
        <linearGradient id="jk-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2dd4bf" />
          <stop offset="1" stopColor="#0f766e" />
        </linearGradient>
      </defs>
      <path d="M32 4 54 12v18c0 14.5-9.4 25.4-22 30-12.6-4.6-22-15.5-22-30V12L32 4Z" fill="url(#jk-g)" />
      <path d="M32 9.5 49 15.6V30c0 11.6-7.2 20.5-17 24.6C22.2 50.5 15 41.6 15 30V15.6L32 9.5Z" fill="#042f2e" opacity=".35" />
      <path d="M14.5 32c4.4-7.2 10.4-10.8 17.5-10.8S45.1 24.8 49.5 32c-4.4 7.2-10.4 10.8-17.5 10.8S18.9 39.2 14.5 32Z" fill="#f0fdfa" />
      <circle cx="32" cy="32" r="7.2" fill="#0f766e" />
      <circle cx="32" cy="32" r="3.2" fill="#042f2e" />
      <circle cx="34.4" cy="29.6" r="1.4" fill="#f0fdfa" />
    </svg>
  );
}
