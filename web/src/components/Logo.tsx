interface LogoProps {
  size?: number;
  wordmark?: boolean;
}

/** Filled dot with two arcs: inner arc is voice (blue), outer arc is sound (orange). */
export function LogoMark({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="9" cy="16" r="4" fill="var(--voice)" />
      <path d="M16 9.5a9 9 0 0 1 0 13" fill="none" stroke="var(--voice)" strokeWidth="3" strokeLinecap="round" />
      <path d="M21.5 5a15 15 0 0 1 0 22" fill="none" stroke="var(--sound)" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ size = 24, wordmark = true }: LogoProps) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      {wordmark && <span className="logo-word">EarShot</span>}
    </span>
  );
}
