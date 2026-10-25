import type { ReactNode } from "react";

export function Card({ title, action, children, className = "" }: {
  title: string; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-surface p-5 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

const TONES = {
  good: { icon: "✓", className: "text-good-text" },
  warning: { icon: "!", className: "text-foreground" },
  critical: { icon: "✕", className: "text-critical" },
  neutral: { icon: "•", className: "text-muted" },
} as const;

export type Tone = keyof typeof TONES;

/** A status label: always an icon and words, never colour alone. */
export function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  const t = TONES[tone];
  const dot = { good: "bg-good", warning: "bg-warning", critical: "bg-critical", neutral: "bg-subtle" }[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap ${t.className}`}>
      <span aria-hidden className={`inline-flex size-4 items-center justify-center rounded-full text-[10px] text-white ${dot} ${tone === "warning" ? "text-black" : ""}`}>
        {t.icon}
      </span>
      {children}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}
