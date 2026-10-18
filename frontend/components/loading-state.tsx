/** Spinning film reel used by every loader in the app. */
export function Reel({ className = "loading-reel" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="10"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" />
      {[0, 72, 144, 216, 288].map((angle) => (
        <circle
          key={angle}
          cx={12 + 5.4 * Math.cos((angle * Math.PI) / 180)}
          cy={12 + 5.4 * Math.sin((angle * Math.PI) / 180)}
          r="2.1"
          fill="currentColor"
        />
      ))}
    </svg>
  );
}

/** Inline loading message shown where content is about to appear. */
export function LoadingState({
  label,
  className = "",
}: {
  label: string;
  className?: string;
}) {
  return (
    <p className={`loading-state ${className}`} role="status">
      <Reel />
      <span>{label}</span>
    </p>
  );
}
