import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, X } from "lucide-react";
import { useParams } from "react-router";
import { Button, Chip, ErrorNote, Loading, Mono, SandboxBanner, TotalBreakdown } from "../components/ui";
import { api, type ClientChangeOrder, type ClientMilestone, type ClientView } from "../lib/api";
import { formatDate, formatMoney } from "../lib/format";
import { CLAUSE_LABEL, paypalStatus } from "../lib/status";

export function ClientPage() {
  const { token = "" } = useParams();
  const queryClient = useQueryClient();
  const key = ["client", token];
  const query = useQuery({
    queryKey: key,
    queryFn: () => api.clientView(token),
    refetchInterval: (q) =>
      q.state.data?.milestones.some((m) => m.invoice && paypalStatus(m.invoice.paypal_status).awaiting) ? 15000 : false,
  });
  const update = { onSettled: () => queryClient.invalidateQueries({ queryKey: key }) };
  const accept = useMutation({ mutationFn: (v: number) => api.clientAccept(token, v), ...update });
  const approveMilestone = useMutation({ mutationFn: (id: string) => api.clientApproveMilestone(token, id), ...update });
  const approveCO = useMutation({ mutationFn: (id: string) => api.clientApproveChangeOrder(token, id), ...update });
  const declineCO = useMutation({ mutationFn: (id: string) => api.clientDeclineChangeOrder(token, id), ...update });
  const view = query.data;

  return (
    <>
      <SandboxBanner />
      <main className="mx-auto max-w-[720px] px-4 pt-6 pb-40 sm:pb-16">
        {query.isPending && <Loading />}
        {query.isError && (
          <div className="py-12">
            <h1 className="font-display text-[32px]">This page is not available</h1>
            <p className="mt-2 text-muted">The link may be wrong or out of date. Ask the artist to send it again.</p>
          </div>
        )}
        {view && (
          <>
            <p className="text-muted">From {view.seller_display_name}</p>
            <h1 className="mt-1 font-display text-[36px] leading-[1.1] sm:text-[44px]">{view.title}</h1>
            <div className="mt-4 flex items-center justify-between gap-4">
              <Chip className="border border-ink bg-transparent text-ink" icon="file">
                Scope v{view.scope_version}
              </Chip>
              <Mono className="text-[22px]">
                {formatMoney((view.total_minor_units ?? 0) + view.change_order_total_minor_units, view.currency_code)}{" "}
                {view.currency_code}
              </Mono>
            </div>

            {view.change_orders
              .filter((c) => c.can_decide)
              .map((c) => (
                <ChangeOrderCard
                  key={c.id}
                  co={c}
                  view={view}
                  onApprove={() => approveCO.mutate(c.id)}
                  onDecline={() => declineCO.mutate(c.id)}
                  pending={approveCO.isPending || declineCO.isPending}
                  error={approveCO.error ?? declineCO.error}
                />
              ))}
            {view.change_orders
              .filter((c) => c.status === "CLIENT_APPROVED")
              .map((c) => (
                <p key={c.id} className="mt-5 flex items-center gap-2 rounded-[10px] bg-success-soft p-4 font-semibold text-success">
                  <Check size={18} aria-hidden className="shrink-0" /> You approved change order #{c.number}, {formatMoney(c.total_minor_units, view.currency_code)}.
                  The scope is now v{view.scope_version}.
                </p>
              ))}
            {view.change_orders
              .filter((c) => c.status === "DECLINED")
              .map((c) => (
                <p key={c.id} className="mt-5 flex items-center gap-2 rounded-[10px] bg-neutral-soft p-4 font-semibold text-neutral">
                  <X size={18} aria-hidden className="shrink-0" /> You declined change order #{c.number}. Nothing will be billed for it.
                </p>
              ))}

            <h2 className="mt-8 font-display text-[28px]">What you and {view.seller_display_name} agree on</h2>
            <dl className="mt-3 border-t border-line">
              {[
                ["Deliverable", view.deliverables.join("; ")],
                ["Files", view.file_formats.join(", ")],
                ["Revisions", view.revisions_included === null ? "" : `${view.revisions_included} included`],
                ["Usage", view.usage_rights],
                ["Delivery", view.deadline_date ? formatDate(view.deadline_date) : ""],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-6 border-b border-line py-3">
                  <dt className="text-muted">{label}</dt>
                  <dd className="text-right font-semibold">{value || "—"}</dd>
                </div>
              ))}
            </dl>

            <h2 className="mt-8 font-display text-[28px]">Milestones and payment</h2>
            <TotalBreakdown
              className="mt-3"
              base={view.total_minor_units ?? 0}
              changeOrders={view.change_order_total_minor_units}
              currency={view.currency_code}
            />
            <ul className="mt-3 border-t border-line">
              {view.milestones.map((m) => (
                <MilestoneRow key={m.id} m={m} currency={view.currency_code} onApprove={() => approveMilestone.mutate(m.id)} pending={approveMilestone.isPending} />
              ))}
            </ul>
            <div className="mt-3"><ErrorNote error={approveMilestone.error} /></div>

            <AcceptBar view={view} onAccept={() => accept.mutate(view.scope_version)} pending={accept.isPending} error={accept.error} />
          </>
        )}
      </main>
    </>
  );
}

function ChangeOrderCard({
  co,
  view,
  onApprove,
  onDecline,
  pending,
  error,
}: {
  co: ClientChangeOrder;
  view: ClientView;
  onApprove: () => void;
  onDecline: () => void;
  pending: boolean;
  error: unknown;
}) {
  return (
    <section aria-label={`Change order ${co.number}`} className="mt-6 overflow-hidden rounded-[14px] border-2 border-accent bg-surface">
      <div className="p-5">
        <Chip tone="accent" icon="help">Waiting for your approval</Chip>
        <div className="mt-3 flex items-baseline justify-between gap-4">
          <h2 className="font-display text-[30px]">Change order #{co.number}</h2>
          <Mono className="text-[26px]">{formatMoney(co.total_minor_units, view.currency_code)}</Mono>
        </div>
        <p className="mt-1 text-[17px] text-muted">{view.seller_display_name} priced what you asked for after the sketch.</p>
        <ul className="mt-3 border-t border-line">
          {co.lines.map((line) => (
            <li key={line.id} className="flex items-start justify-between gap-4 border-b border-line py-3">
              <div>
                <p className="text-[17px] font-semibold">{line.request_summary ?? line.name}</p>
                <p className="text-[15px] text-muted">
                  {line.clause_ref && line.clause_text ? `${CLAUSE_LABEL[line.clause_ref] ?? line.clause_ref}: ${line.clause_text}. ` : ""}
                  {line.name} × {line.quantity}.
                </p>
              </div>
              <Mono className="text-[17px]">{formatMoney(line.amount_minor_units, view.currency_code)}</Mono>
            </li>
          ))}
          {co.not_billed.map((item) => (
            <li key={item.request_summary} className="flex items-start justify-between gap-4 border-b border-line py-3">
              <div>
                <p className="text-[17px] font-semibold">{item.request_summary}</p>
                <p className="text-[15px] text-muted">Not billed. Nothing is charged for this request.</p>
              </div>
              <span className="shrink-0 text-[17px] font-semibold text-muted">Not billed</span>
            </li>
          ))}
        </ul>
        <p className="flex justify-between border-t-2 border-ink pt-3 text-[18px] font-semibold">
          Total <Mono>{formatMoney(co.total_minor_units, view.currency_code)}</Mono>
        </p>
      </div>
      <div className="space-y-3 bg-paper-deep p-5">
        <p className="text-[15px] text-muted">
          If you approve, the scope becomes v{view.scope_version + 1} and {view.seller_display_name} sends one PayPal invoice for {formatMoney(co.total_minor_units, view.currency_code)}.
        </p>
        <Button block icon={<Check size={18} aria-hidden />} pending={pending} onClick={onApprove}>Approve change order</Button>
        <Button block variant="secondary" icon={<X size={18} aria-hidden />} disabled={pending} onClick={onDecline}>Decline</Button>
        <ErrorNote error={error} />
      </div>
    </section>
  );
}

function MilestoneRow({ m, currency, onApprove, pending }: { m: ClientMilestone; currency: string; onApprove: () => void; pending: boolean }) {
  const status = m.invoice ? paypalStatus(m.invoice.paypal_status) : null;
  let chip: React.ReactNode;
  if (status && m.invoice) chip = <Chip tone={status.tone} icon={status.icon}>{status.label}</Chip>;
  else if (m.workflow_state === "LOCKED") chip = <Chip icon="x">Locked</Chip>;
  else if (m.workflow_state === "DELIVERED") chip = <Chip icon="clock">Shared, needs your approval</Chip>;
  else if (m.workflow_state === "AWAITING_DELIVERY") chip = <Chip icon="clock">In progress</Chip>;
  else chip = <Chip icon="circle">Not billed yet</Chip>;
  return (
    <li className="border-b border-line py-4">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="text-[20px] font-semibold">
          {m.title}
          {m.kind === "change_order" && <span className="ml-2 text-[15px] font-normal text-muted">added to original scope</span>}
        </h3>
        <Mono className="text-[18px]">{formatMoney(m.amount_minor_units, currency)}</Mono>
      </div>
      <div className="mt-2">{chip}</div>
      {m.evidence_note && <p className="mt-2 text-[15px] text-muted">{m.evidence_note}</p>}
      {m.evidence_url && (
        <a href={m.evidence_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 font-semibold text-accent-deep underline">
          View delivery <ExternalLink size={14} aria-hidden />
        </a>
      )}
      {m.can_approve && (
        <div className="mt-3">
          <Button block variant="secondary" icon={<Check size={18} aria-hidden />} pending={pending} onClick={onApprove}>
            Approve {m.title.toLowerCase()}
          </Button>
        </div>
      )}
      {m.invoice?.payer_link && status?.awaiting && (
        <a
          href={m.invoice.payer_link}
          target="_blank"
          rel="noreferrer"
          className="mt-3 flex items-center justify-center gap-2 rounded-lg border border-line-strong px-5 py-3 font-semibold hover:bg-paper-deep"
        >
          <ExternalLink size={17} aria-hidden /> Open the PayPal invoice ({m.invoice.invoice_number})
        </a>
      )}
    </li>
  );
}

function AcceptBar({ view, onAccept, pending, error }: { view: ClientView; onAccept: () => void; pending: boolean; error: unknown }) {
  if (view.client_accepted) {
    return (
      <p className="mt-8 flex items-center gap-2 rounded-[10px] bg-success-soft p-4 font-semibold text-success">
        <Check size={18} aria-hidden className="shrink-0" /> You accepted scope v{view.scope_version}. {view.seller_display_name} will bill each stage through PayPal.
      </p>
    );
  }
  if (!view.can_accept) {
    return (
      <p className="mt-8 rounded-[10px] bg-neutral-soft p-4 text-neutral">
        {view.seller_display_name} is still preparing this scope. Come back when they share it.
      </p>
    );
  }
  return (
    <div className="fixed inset-x-0 bottom-0 border-t border-line bg-paper px-4 pt-4 pb-5 sm:static sm:mt-8 sm:border-0 sm:bg-transparent sm:p-0">
      <div className="mx-auto max-w-[720px]">
        <p className="text-[15px] text-muted">
          You pay each stage through a PayPal invoice. Accepting sends no money and is not a legal contract.
        </p>
        <div className="mt-3">
          <Button block icon={<Check size={18} aria-hidden />} pending={pending} onClick={onAccept}>
            Accept scope v{view.scope_version}
          </Button>
        </div>
        <ErrorNote error={error} />
      </div>
    </div>
  );
}
