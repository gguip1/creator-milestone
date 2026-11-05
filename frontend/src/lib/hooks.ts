import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, type Project } from "./api";
import { paypalStatus } from "./status";

export const POLL_MS = 20_000;

export function awaitingPayment(project: Project | undefined): boolean {
  return !!project?.invoices.some((i) => i.is_active && paypalStatus(i.paypal_status).awaiting);
}

/** The seller's project. While an invoice awaits payment, ask PayPal (via the backend) every 20 s. */
export function useProject(id: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.project(id),
    // A proposal that is APPROVED is running somewhere; look again soon.
    refetchInterval: (q) =>
      q.state.data?.proposals.some((p) => p.status === "APPROVED") ? 2000 : false,
  });
  const waiting = awaitingPayment(query.data);
  const invoiceIds = query.data?.invoices.filter((i) => i.is_active && paypalStatus(i.paypal_status).awaiting).map((i) => i.id);
  const key = invoiceIds?.join(",") ?? "";
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(async () => {
      await Promise.allSettled(key.split(",").map((invoiceId) => api.refreshInvoice(invoiceId)));
      queryClient.invalidateQueries({ queryKey: ["project", id] });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, key, id, queryClient]);
  useEffect(() => {
    if (id) {
      try {
        localStorage.setItem("lastProjectId", id);
      } catch {
        /* storage may be blocked */
      }
    }
  }, [id]);
  return query;
}

export function lastProjectId(): string | null {
  try {
    return localStorage.getItem("lastProjectId");
  } catch {
    return null;
  }
}

/** A mutation that refetches the project afterwards, even on failure (state may have moved). */
export function useProjectMutation<A, R>(projectId: string, fn: (arg: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
  });
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}
