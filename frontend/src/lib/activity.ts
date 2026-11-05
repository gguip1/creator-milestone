import type { Activity } from "./api";
import { formatMoney } from "./format";
import { paypalStatus } from "./status";

const KIND: Record<string, string> = {
  BILL_MILESTONE: "the invoice draft",
  SEND_INVOICE: "sending the invoice",
  SEND_REMINDER: "a payment reminder",
  CHANGE_ORDER: "the change order",
  CANCEL_INVOICE: "cancelling the invoice",
};

const str = (v: unknown): string => (v === undefined || v === null ? "" : String(v));

/** Plain-English line for one activity-log row. Unknown actions fall back to a readable form. */
export function describeActivity(a: Activity): string {
  const d = a.details;
  const kind = KIND[str(d.kind)] ?? "a proposal";
  switch (a.action) {
    case "project_created":
      return "Project created.";
    case "intake_analyzed":
      return `Analyzed the client's first message${d.source === "cached" ? " (saved result)" : ""}.`;
    case "scope_edited":
      return "Edited the scope.";
    case "scope_accepted":
      return `${a.actor === "client" ? "Accepted" : "Accepted and shared"} scope v${str(d.scope_version)}.`;
    case "proposal_created":
      return `Proposed ${kind}. ${str(d.rationale)}`.trim();
    case "proposal_approved":
      return `Approved ${kind}.`;
    case "proposal_executed":
      return `Finished ${kind}.`;
    case "proposal_failed":
      return `Could not complete ${kind}. Nothing was lost; it can be retried.`;
    case "proposal_stale":
      return `Marked ${kind} as outdated. ${str(d.reason)}`.trim();
    case "proposal_dismissed":
      return `Dismissed ${kind}.`;
    case "proposal_edited":
      return `Edited ${kind}.`;
    case "scope_guard_checked":
      return `Checked ${str(d.items)} request(s) against the agreed scope; ${str(d.billable)} billable.`;
    case "change_order_proposed":
      return `Proposed change order #${str(d.number)}, ${formatMoney(Number(d.total_minor_units))}.`;
    case "change_order_approved":
      return a.actor === "client"
        ? `Approved change order #${str(d.number)}; scope is now v${str(d.scope_version)}.`
        : `Approved change order #${str(d.number)}.`;
    case "change_order_declined":
      return `Declined change order #${str(d.number)}.`;
    case "change_order_superseded":
      return `Replaced change order #${str(d.number)} with a newer one.`;
    case "revision_logged":
      return `Logged a revision: ${str(d.revisions_used)} of ${str(d.revisions_included)} used.`;
    case "demo_revisions_logged":
      return `Demo shortcut: recorded ${str(d.revisions_used)} of ${str(d.revisions_included)} revisions as used in the sketch round.`;
    case "milestone_unlocked":
      return `Unlocked “${str(d.milestone)}”.`;
    case "milestone_delivered":
      return `Logged “${str(d.milestone)}” as shared with the client.`;
    case "milestone_approved":
      return `Approved “${str(d.milestone)}”.`;
    case "milestone_billed":
      if (d.reused_paid_invoice) {
        return `“${str(d.milestone)}” counted as billed by reusing a previously paid sandbox invoice (${str(d.paypal_invoice_id)}). No new invoice was created.`;
      }
      return `Billed “${str(d.milestone)}”, $${str(d.amount)}, ${str(d.invoice_number)}.`;
    case "milestone_settled":
      return `“${str(d.milestone)}” settled.`;
    case "milestone_reopened":
      return `“${str(d.milestone)}” is ready to bill again.`;
    case "invoice_draft_created":
    case "invoice_adopted":
      return `Draft invoice ${str(d.invoice_number)} created at PayPal.`;
    case "invoice_status_changed":
      return `Status read from PayPal: ${paypalStatus(str(d.status)).label}, ${str(d.invoice_number)}.`;
    case "invoice_reminder_sent":
      return `Reminder sent for ${str(d.invoice_number)}.`;
    case "demo_jump_agreed":
      return "Demo shortcut: filled the sample terms and recorded both acceptances.";
    case "demo_paid_invoice_adopted":
      return `Demo shortcut: adopted a previously paid sandbox invoice (${str(d.paypal_invoice_id)}) after PayPal confirmed it as paid.`;
    case "commission_cancelled":
      return "Commission cancelled.";
    case "commission_completed":
      return "Commission completed.";
    default:
      return a.action.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) + ".";
  }
}
