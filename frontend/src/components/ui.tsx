import type { ReactNode } from "react";

export function Card({ title, right, children, className = "", pad = true }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between border-b border-sage-pale px-3 py-2">
          <h2 className="text-[13px] font-semibold text-slate-deep">{title}</h2>
          <div className="flex items-center gap-2">{right}</div>
        </header>
      )}
      <div className={pad ? "p-3" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone, tip }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: "warn" | "danger" | "good"; tip?: string;
}) {
  const color = tone === "danger" ? "text-danger" : tone === "warn" ? "text-warn" : tone === "good" ? "text-green-slate" : "";
  return (
    <div className="card px-3 py-2" title={tip}>
      <div className="text-[11px] font-medium uppercase tracking-wide text-green-slate">
        {label}
        {tip && <span className="ml-1 cursor-help text-sage">ⓘ</span>}
      </div>
      <div className={`mt-0.5 text-[20px] font-semibold tabular-nums ${color}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate/70">{sub}</div>}
    </div>
  );
}

const SEGMENT_STYLE: Record<string, string> = {
  nudge: "bg-[#E3EEE6] text-[#3D6B4F]",
  plan: "bg-[#E6ECF2] text-[#3E5A73]",
  visit: "bg-warn-soft text-[#7A5A1E]",
  sensitive: "bg-danger-soft text-danger",
};

export function Segment({ value }: { value?: string | null }) {
  if (!value) return null;
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold capitalize ${SEGMENT_STYLE[value] ?? ""}`}>
      {value}
    </span>
  );
}

export function Badge({ children, tone = "neutral", title }: {
  children: ReactNode; tone?: "neutral" | "good" | "warn" | "danger" | "dark"; title?: string;
}) {
  const cls = {
    neutral: "bg-[#EEF1EC] text-slate-deep",
    good: "bg-[#E3EEE6] text-[#3D6B4F]",
    warn: "bg-warn-soft text-[#7A5A1E]",
    danger: "bg-danger-soft text-danger",
    dark: "bg-slate text-white",
  }[tone];
  return (
    <span title={title} className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium ${cls}`}>
      {children}
    </span>
  );
}

export const SampleTag = () => (
  <Badge tone="warn" title="Fictional sample data, not a real lender's book">Sample data</Badge>
);
export const SimulatedTag = () => (
  <Badge tone="warn" title="Produced by running the engine over sample data; not real results">Simulated</Badge>
);
export const DraftTag = () => <Badge tone="warn">Draft, needs native review</Badge>;

export function PageHeader({ question, children }: { question: string; children?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h1 className="text-[17px] font-semibold text-slate">{question}</h1>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export const Loading = () => <div className="p-6 text-sage">Loading…</div>;
export const ErrorBox = ({ error }: { error?: string }) =>
  error ? <div className="rounded border border-danger/30 bg-danger-soft p-2 text-danger">{error}</div> : null;

export function Tip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span title={text} className="cursor-help border-b border-dotted border-sage">
      {children}
    </span>
  );
}

export function TenpaiMark({ size = 16 }: { size?: number }) {
  // Placeholder until the supplied SVG: three stacked rounded cards, sage square in front.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <rect x="7" y="2" width="14" height="10" rx="2.5" fill="#CAD2C5" />
      <rect x="5" y="6" width="14" height="10" rx="2.5" fill="#84A98C" />
      <rect x="3" y="10" width="14" height="11" rx="2.5" fill="#E6EAE3" stroke="#2F3E46" strokeWidth="1" />
      <rect x="5.5" y="13" width="3.5" height="3.5" rx=".8" fill="#84A98C" />
    </svg>
  );
}

export function LenderLogo({ brand, size = 28 }: { brand: Record<string, any>; size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-md font-semibold text-white"
      style={{ width: size, height: size, background: brand?.colors?.primary ?? "#2F3E46", fontSize: size * 0.5 }}
    >
      {brand?.logo_text ?? brand?.lender_name?.[0] ?? "?"}
    </span>
  );
}
