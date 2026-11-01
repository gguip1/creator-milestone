import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

export function Landing() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  return (
    <main className="mx-auto max-w-3xl px-4 py-16">
      <p className="text-sm font-medium text-accent">CreatorMilestone</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
        Your AI back office for cross-border freelance work.
      </h1>
      <p className="mt-4 text-lg text-muted">
        Turn messy client chats into agreed scope, guard that scope, and bill every stage through
        PayPal. The agent proposes; you approve; PayPal executes.
      </p>

      <section className="mt-10 rounded-lg border border-line bg-white p-4 text-sm">
        <h2 className="font-medium">System status</h2>
        {health.isPending && <p className="mt-2 text-muted">Checking backend…</p>}
        {health.isError && <p className="mt-2 text-red-700">Backend unreachable.</p>}
        {health.data && (
          <ul className="mt-2 space-y-1 text-muted">
            <li>Backend: {health.data.status}</li>
            <li>
              PayPal {health.data.paypal.environment.toLowerCase()}:{" "}
              {health.data.paypal.configured ? "configured" : "not configured"}
            </li>
          </ul>
        )}
      </section>
    </main>
  );
}
