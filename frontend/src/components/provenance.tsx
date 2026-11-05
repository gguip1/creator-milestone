import { CircleHelp, Flag, Lightbulb, Quote, type LucideIcon } from "lucide-react";
import type { ExtractedField } from "../lib/api";
import type { Tone } from "../lib/status";
import { cx } from "./ui";

export type ProvKind = "explicit" | "inferred" | "needs" | "unknown";

const STYLE: Record<ProvKind, { label: string; tone: Tone; icon: LucideIcon; chip: string; mark: string }> = {
  explicit: { label: "Explicit", tone: "success", icon: Quote, chip: "bg-success-soft text-success", mark: "bg-success-soft" },
  inferred: { label: "Inferred", tone: "neutral", icon: Lightbulb, chip: "bg-neutral-soft text-neutral", mark: "bg-neutral-soft" },
  needs: { label: "Needs confirmation", tone: "warn", icon: Flag, chip: "bg-warn-soft text-warn", mark: "bg-warn-soft ring-2 ring-warn" },
  unknown: { label: "Unknown", tone: "warn", icon: CircleHelp, chip: "bg-warn-soft text-warn", mark: "bg-warn-soft" },
};

/** Maps the backend's provenance and needs_confirmation to the four design states. */
export function provKind(field: ExtractedField | undefined): ProvKind {
  if (!field || field.provenance === "unknown" || (!field.value && !field.quote)) return "unknown";
  if (field.needs_confirmation) return "needs";
  return field.provenance === "inferred" ? "inferred" : "explicit";
}

export function ProvChip({ kind, className }: { kind: ProvKind; className?: string }) {
  const { label, icon: Icon, chip } = STYLE[kind];
  return (
    <span className={cx("inline-flex w-fit items-center gap-1.5 rounded-md px-2.5 py-[5px] text-[14px] font-semibold", chip, className)}>
      <Icon size={15} aria-hidden /> {label}
    </span>
  );
}

export const provMark = (kind: ProvKind) => STYLE[kind].mark;

export function Marker({ n }: { n: number }) {
  return (
    <span aria-label={`field ${n}`} className="ml-1 inline-flex size-[22px] items-center justify-center rounded-full bg-ink text-[13px] font-semibold text-white">
      {n}
    </span>
  );
}
