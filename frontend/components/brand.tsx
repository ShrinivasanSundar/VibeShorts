import Image from "next/image";

export function Brand({ compact = false }: { compact?: boolean }) {
  return <span className={`brand${compact ? " brand-compact" : ""}`}>
    <Image className="brand-logo" src="/vibeshortsai-logo.png" alt="" width={44} height={44} priority />
    <span>VibeShorts<span className="brand-ai">AI</span></span>
  </span>;
}
