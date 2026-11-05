// One mapping for every PayPal invoice status (PRD §11.3). The UI never shows "Paid via PayPal"
// unless PayPal's status is PAID, and "Marked paid (outside PayPal)" is never green.

export type Tone = "neutral" | "accent" | "success" | "warn" | "danger";
export type IconName = "circle" | "send" | "clock" | "check" | "alert" | "undo" | "x" | "file" | "help" | "banknote";

export type StatusView = { label: string; tone: Tone; icon: IconName; paid: boolean; awaiting: boolean };

const MAP: Record<string, StatusView> = {
  DRAFT: { label: "Draft (not sent)", tone: "neutral", icon: "file", paid: false, awaiting: false },
  SCHEDULED: { label: "Scheduled", tone: "neutral", icon: "clock", paid: false, awaiting: false },
  SENT: { label: "Sent — awaiting payment", tone: "neutral", icon: "send", paid: false, awaiting: true },
  UNPAID: { label: "Sent — awaiting payment", tone: "neutral", icon: "send", paid: false, awaiting: true },
  PAYMENT_PENDING: { label: "Payment pending", tone: "neutral", icon: "clock", paid: false, awaiting: true },
  PARTIALLY_PAID: {
    label: "Partially paid (unexpected; partial disabled)",
    tone: "warn",
    icon: "alert",
    paid: false,
    awaiting: true,
  },
  PAID: { label: "Paid via PayPal", tone: "success", icon: "check", paid: true, awaiting: false },
  MARKED_AS_PAID: { label: "Marked paid (outside PayPal)", tone: "neutral", icon: "banknote", paid: false, awaiting: false },
  CANCELLED: { label: "Cancelled", tone: "neutral", icon: "x", paid: false, awaiting: false },
  REFUNDED: { label: "Refunded", tone: "warn", icon: "undo", paid: false, awaiting: false },
  PARTIALLY_REFUNDED: { label: "Refunded", tone: "warn", icon: "undo", paid: false, awaiting: false },
  MARKED_AS_REFUNDED: { label: "Refunded", tone: "warn", icon: "undo", paid: false, awaiting: false },
};

export function paypalStatus(raw: string | null | undefined): StatusView {
  if (!raw) return { label: "Not created yet", tone: "neutral", icon: "circle", paid: false, awaiting: false };
  return (
    MAP[raw] ?? { label: `Unknown (${raw})`, tone: "neutral", icon: "help", paid: false, awaiting: false }
  );
}

export const CLASSIFICATION: Record<string, { label: string; tone: Tone; icon: IconName }> = {
  in_scope: { label: "In scope", tone: "success", icon: "check" },
  out_of_scope: { label: "Out of scope", tone: "warn", icon: "help" },
  exceeds_limit: { label: "Exceeds limit", tone: "warn", icon: "alert" },
  question: { label: "Question, not billed", tone: "neutral", icon: "help" },
};

export const CLAUSE_LABEL: Record<string, string> = {
  deliverables: "Deliverables",
  file_formats: "Files",
  revisions: "Revisions",
  deadline: "Deadline",
  usage_rights: "Usage",
};
