import { describe, expect, it } from "vitest";
import type { Project } from "./api";
import { projectSteps } from "./steps";

type Inv = { milestone_id: string; paypal_status: string | null };
function project(p: {
  status?: string;
  messages?: ("intake" | "follow_up")[];
  invoices?: Inv[];
  changeOrders?: string[];
}): Project {
  return {
    status: p.status ?? "DRAFT",
    messages: (p.messages ?? []).map((kind) => ({ kind })),
    milestones: [{ id: "m1", kind: "plan" }, { id: "m2", kind: "plan" }, { id: "m3", kind: "plan" }],
    invoices: p.invoices ?? [],
    change_orders: (p.changeOrders ?? []).map((status) => ({ status })),
  } as unknown as Project;
}
const states = (p: Project): string => projectSteps("x", p).map((s) => s.state).join(",");
const PAID = [{ milestone_id: "m1", paypal_status: "PAID" }];

describe("projectSteps across the demo", () => {
  it("fresh project: read the request now, everything else locked", () => {
    expect(states(project({}))).toBe("current,locked,locked,locked");
  });
  it("intake analyzed, scope not agreed: agree is next", () => {
    expect(states(project({ messages: ["intake"] }))).toBe("done,current,locked,locked");
    expect(states(project({ status: "AWAITING_ACCEPTANCE", messages: ["intake"] }))).toBe("done,current,locked,locked");
  });
  it("agreed, nothing paid: bill is current, guard stays locked", () => {
    expect(states(project({ status: "AGREED", messages: ["intake"] }))).toBe("done,done,current,locked");
  });
  it("a sent but unpaid invoice does not count as billed", () => {
    const sent = [{ milestone_id: "m1", paypal_status: "SENT" }];
    expect(states(project({ status: "AGREED", messages: ["intake"], invoices: sent }))).toBe("done,done,current,locked");
  });
  it("deposit paid: bill is done and guard is next", () => {
    expect(states(project({ status: "IN_PROGRESS", messages: ["intake"], invoices: PAID }))).toBe("done,done,done,current");
  });
  it("a change order still awaiting a decision is not guarded yet", () => {
    const p = project({ status: "IN_PROGRESS", messages: ["intake", "follow_up"], invoices: PAID, changeOrders: ["DRAFT"] });
    expect(states(p)).toBe("done,done,done,current");
    expect(states(project({ status: "IN_PROGRESS", messages: ["intake", "follow_up"], invoices: PAID, changeOrders: ["SELLER_APPROVED"] }))).toBe("done,done,done,current");
  });
  it("change order decided: guard is done", () => {
    expect(states(project({ status: "IN_PROGRESS", messages: ["intake", "follow_up"], invoices: PAID, changeOrders: ["CLIENT_APPROVED"] }))).toBe("done,done,done,done");
    expect(states(project({ status: "IN_PROGRESS", messages: ["intake", "follow_up"], invoices: PAID, changeOrders: ["DECLINED"] }))).toBe("done,done,done,done");
  });
  it("a message with nothing billable also counts as guarded", () => {
    expect(states(project({ status: "IN_PROGRESS", messages: ["intake", "follow_up"], invoices: PAID }))).toBe("done,done,done,done");
  });
  it("never shows a later step as done while an earlier one is not", () => {
    // A follow-up and an approved change order exist, but nothing is paid yet.
    const p = project({ status: "AGREED", messages: ["intake", "follow_up"], changeOrders: ["CLIENT_APPROVED"] });
    expect(states(p)).toBe("done,done,current,locked");
  });
  it("a shortcut-agreed project without an intake message still reads as read", () => {
    expect(states(project({ status: "AGREED" }))).toBe("done,done,current,locked");
  });
  it("only one step is ever current, and a locked step is never done", () => {
    const cases: Project[] = [
      project({}),
      project({ messages: ["intake"] }),
      project({ status: "AGREED", messages: ["intake"] }),
      project({ status: "COMPLETED", messages: ["intake", "follow_up"], invoices: PAID, changeOrders: ["CLIENT_APPROVED"] }),
    ];
    for (const c of cases) {
      const steps = projectSteps("x", c);
      expect(steps.filter((x) => x.state === "current").length).toBeLessThanOrEqual(1);
      // Once a step is not done, no later step may be done.
      const firstOpen = steps.findIndex((x) => x.state !== "done");
      if (firstOpen >= 0) expect(steps.slice(firstOpen).every((x) => x.state !== "done")).toBe(true);
    }
  });
});
