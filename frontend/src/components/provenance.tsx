import { CircleHelp, Flag, Lightbulb, Quote, type LucideIcon } from "lucide-react";
import type { ExtractedField } from "../lib/api";
import type { Tone } from "../lib/status";
import { cx } from "./ui";

export type ProvKind = "explicit" | "inferred" | "needs" | "unknown";

// Where a term came from. Shown as a small text label with an icon (never color alone) and
// deliberately not as a pill: pills are kept for real statuses.
const STYLE: Record<ProvKind, { label: string; tone: Tone; icon: LucideIcon; text: string; mark: string }> = {
  explicit: { label: "Explicit", tone: "success", icon: Quote, text: "text-neutral", mark: "bg-accent/20 underline decoration-accent decoration-1 underline-offset-4" },
  inferred: { label: "Inferred", tone: "neutral", icon: Lightbulb, text: "text-muted", mark: "bg-white/10 underline decoration-line-strong decoration-dashed underline-offset-4" },
  needs: { label: "Needs confirmation", tone: "warn", icon: Flag, text: "text-warn", mark: "bg-warn/20 underline decoration-warn decoration-2 underline-offset-4" },
  unknown: { label: "Unknown", tone: "warn", icon: CircleHelp, text: "text-warn", mark: "bg-warn/10" },
};

/** Maps the backend's provenance and needs_confirmation to the four design states. */
export function provKind(field: ExtractedField | undefined): ProvKind {
  if (!field || field.provenance === "unknown" || (!field.value && !field.quote)) return "unknown";
  if (field.needs_confirmation) return "needs";
  return field.provenance === "inferred" ? "inferred" : "explicit";
}

export function ProvChip({ kind, className }: { kind: ProvKind; className?: string }) {
  const { label, icon: Icon, text } = STYLE[kind];
  return (
    <span className={cx("inline-flex w-fit items-center gap-1.5 text-[13px] leading-5 font-medium", text, className)}>
      <Icon size={13} aria-hidden /> {label}
    </span>
  );
}

export const provMark = (kind: ProvKind) => STYLE[kind].mark;

export function Marker({ n }: { n: number }) {
  return (
    <span aria-label={`field ${n}`} className="ml-1 inline-flex size-[20px] items-center justify-center rounded-full border border-line-strong font-sans text-[12px] font-medium text-ink">
      {n}
    </span>
  );
}
