// The demo flow as four steps, derived from real project state (never hardcoded).
import type { Project } from "./api";
import { paypalStatus } from "./status";

export type StepState = "done" | "current" | "todo" | "locked";
export type Step = { n: number; label: string; to: string; state: StepState };

const AGREED = ["AGREED", "IN_PROGRESS", "COMPLETED"];

export function projectSteps(id: string, project: Project | undefined): Step[] {
  const read = !!project?.messages.some((m) => m.kind === "intake");
  const agreed = !!project && AGREED.includes(project.status);
  const billed = !!project?.invoices.some((i) => paypalStatus(i.paypal_status).paid);
  const guarded = !!project && project.change_orders.length > 0;
  const raw: { label: string; to: string; done: boolean; locked: boolean }[] = [
    { label: "Read the request", to: `/projects/${id}/intake`, done: read, locked: false },
    { label: "Agree the scope", to: agreed ? `/projects/${id}` : `/projects/${id}/intake`, done: agreed, locked: !read },
    { label: "Bill a milestone", to: `/projects/${id}`, done: billed, locked: !agreed },
    { label: "Guard the scope", to: `/projects/${id}/messages/new`, done: guarded, locked: !agreed },
  ];
  // The current step is the first one that is neither done nor locked.
  let currentSet = false;
  return raw.map((r, i) => {
    let state: StepState = r.done ? "done" : r.locked ? "locked" : "todo";
    if (state === "todo" && !currentSet) {
      state = "current";
      currentSet = true;
    }
    return { n: i + 1, label: r.label, to: r.to, state };
  });
}
