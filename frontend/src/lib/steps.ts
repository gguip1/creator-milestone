// The demo flow as four steps, derived from real project state (never hardcoded).
import type { Project } from "./api";
import { paypalStatus } from "./status";

export type StepState = "done" | "current" | "todo" | "locked";
export type Step = { n: number; label: string; to: string; state: StepState };

const AGREED = ["AGREED", "IN_PROGRESS", "COMPLETED"];

/** The facts each step depends on. Each is read from the project on its own. */
export function stepFacts(project: Project | undefined) {
  const agreed = !!project && AGREED.includes(project.status);
  // A scope that was agreed implies its request was read, even when a shortcut skipped the intake message.
  const read = !!project?.messages.some((m) => m.kind === "intake") || agreed;
  const billed = !!project?.milestones.some(
    (m) => m.kind === "plan" && project.invoices.some((i) => i.milestone_id === m.id && paypalStatus(i.paypal_status).paid),
  );
  // Guarding means a follow-up message was checked and every change order it produced has been decided.
  const checked = !!project?.messages.some((m) => m.kind === "follow_up");
  const undecided = !!project?.change_orders.some((c) => c.status === "DRAFT" || c.status === "SELLER_APPROVED");
  const guarded = checked && !undecided;
  return { read, agreed, billed, guarded };
}

export function projectSteps(id: string, project: Project | undefined): Step[] {
  const f = stepFacts(project);
  // A step is locked until the one before it holds, and is never Done while locked.
  const raw: { label: string; to: string; done: boolean; locked: boolean }[] = [
    { label: "Read the request", to: `/projects/${id}/intake`, done: f.read, locked: false },
    { label: "Agree the scope", to: f.agreed ? `/projects/${id}` : `/projects/${id}/intake`, done: f.agreed, locked: !f.read },
    { label: "Bill a milestone", to: `/projects/${id}`, done: f.billed, locked: !f.agreed },
    { label: "Guard the scope", to: `/projects/${id}/messages/new`, done: f.guarded, locked: !f.billed },
  ];
  let currentSet = false;
  return raw.map((r, i) => {
    let state: StepState = r.locked ? "locked" : r.done ? "done" : "todo";
    if (state === "todo" && !currentSet) {
      state = "current";
      currentSet = true;
    }
    return { n: i + 1, label: r.label, to: r.to, state };
  });
}
