import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, X } from "lucide-react";
import { useParams } from "react-router";
import { Button, Chip, ErrorNote, Eyebrow, Loading, Mono, NextCallout, SampleArt, SandboxBanner, TotalBreakdown } from "../components/ui";
import { api, type ClientChangeOrder, type ClientMilestone, type ClientView } from "../lib/api";
import { ART, isOutfit, milestoneArt } from "../lib/art";
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
      <main className="mx-auto max-w-[720px] px-4 pt-8 pb-44 sm:pb-16">
        {query.isPending && <Loading />}
        {query.isError && (
          <div className="py-12">
            <h1 className="font-display text-[30px]">This page is not available</h1>
            <p className="mt-2 text-muted">The link may be wrong or out of date. Ask the artist to send it again.</p>
          </div>
        )}
        {view && (
          <>
            <Eyebrow>From {view.seller_display_name}</Eyebrow>
            <h1 className="mt-3 font-display text-[32px] leading-[1.1] sm:text-[36px] sm:leading-10">{view.title}</h1>
            <div className="mt-5 flex items-baseline justify-between gap-4 border-y border-line py-3">
              <p className="font-mono text-[14px] text-neutral">Scope v{view.scope_version}</p>
              <Mono className="text-[22px]">
                {formatMoney((view.total_minor_units ?? 0) + view.change_order_total_minor_units, view.currency_code)}{" "}
                <span className="text-[14px] text-muted">{view.currency_code}</span>
              </Mono>
            </div>

            <ClientNext view={view} />

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
                <p key={c.id} className="mt-5 flex items-center gap-2 rounded-lg border border-accent bg-success-soft p-4 text-ink">
                  <Check size={18} aria-hidden className="shrink-0 text-accent" /> You approved change order #{c.number}, {formatMoney(c.total_minor_units, view.currency_code)}.
                  The scope is now v{view.scope_version}.
                </p>
              ))}
            {view.change_orders
              .filter((c) => c.status === "DECLINED")
              .map((c) => (
                <p key={c.id} className="mt-5 flex items-center gap-2 rounded-lg border border-line bg-fill p-4 text-neutral">
                  <X size={18} aria-hidden className="shrink-0" /> You declined change order #{c.number}. Nothing will be billed for it.
                </p>
              ))}

            <h2 className="eyebrow mt-10">What you and {view.seller_display_name} agree on</h2>
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
                  <dd className="text-right">{value || "—"}</dd>
                </div>
              ))}
            </dl>

            <h2 className="eyebrow mt-10">Milestones and payment</h2>
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

/** What the client should do now, read from the page's real state. */
function ClientNext({ view }: { view: ClientView }) {
  const co = view.change_orders.find((c) => c.can_decide);
  const toApprove = view.milestones.find((m) => m.can_approve);
  const toPay = view.milestones.find((m) => m.invoice?.payer_link && paypalStatus(m.invoice.paypal_status).awaiting);
  let n: { title: string; why: string };
  if (co) n = { title: `Review change order #${co.number}`, why: "It lists what you asked for, what each item costs, and what is not billed. Approve or decline it below." };
  else if (toApprove) n = { title: `Approve the ${toApprove.title.toLowerCase()}`, why: "Check the shared work below. Your approval lets the artist bill this stage." };
  else if (toPay) n = { title: "Pay the PayPal invoice", why: "It opens in PayPal's sandbox, so no real money moves. Paying is what marks the stage as paid." };
  else if (!view.client_accepted && view.can_accept) n = { title: `Read and accept scope v${view.scope_version}`, why: "Below is what you and the artist agree on. Accepting sends no money; you pay each stage by PayPal invoice later." };
  else if (!view.can_accept && !view.client_accepted) n = { title: "Wait for the artist", why: `${view.seller_display_name} is still preparing this scope.` };
  else n = { title: "Nothing to do right now", why: `${view.seller_display_name} will send the next step. Come back to this page when you hear from them.` };
  return <NextCallout className="mt-6 mb-0" title={n.title} why={n.why} />;
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
    <section aria-label={`Change order ${co.number}`} className="mt-6 overflow-hidden rounded-lg border-2 border-accent">
      <div className="p-5">
        <Chip tone="accent" icon="help">Waiting for your approval</Chip>
        <div className="mt-3 flex items-baseline justify-between gap-4">
          <h2 className="font-display text-[24px] leading-8">Change order #{co.number}</h2>
          <Mono className="text-[22px]">{formatMoney(co.total_minor_units, view.currency_code)}</Mono>
        </div>
        <p className="mt-2 text-[15px] text-muted">{view.seller_display_name} priced what you asked for after the sketch.</p>
        <ul className="mt-3 border-t border-line">
          {co.lines.map((line) => (
            <li key={line.id} className="flex items-start justify-between gap-4 border-b border-line py-3">
              <div>
                <p className="text-[16px]">{line.request_summary ?? line.name}</p>
                <p className="text-[14px] leading-5 text-muted">
                  {line.clause_ref && line.clause_text ? `${CLAUSE_LABEL[line.clause_ref] ?? line.clause_ref}: ${line.clause_text}. ` : ""}
                  {line.name} × {line.quantity}.
                </p>
                {isOutfit(line.name, line.request_summary) && <SampleArt compact {...ART.hoodie} className="mt-3" />}
              </div>
              <Mono className="text-[16px]">{formatMoney(line.amount_minor_units, view.currency_code)}</Mono>
            </li>
          ))}
          {co.not_billed.map((item) => (
            <li key={item.request_summary} className="flex items-start justify-between gap-4 border-b border-line py-3">
              <div>
                <p className="text-[16px]">{item.request_summary}</p>
                <p className="text-[14px] leading-5 text-muted">Not billed. Nothing is charged for this request.</p>
              </div>
              <span className="shrink-0 text-[15px] text-muted">Not billed</span>
            </li>
          ))}
        </ul>
        <p className="flex justify-between border-t border-line-strong pt-3 text-[17px] font-medium">
          Total <Mono>{formatMoney(co.total_minor_units, view.currency_code)}</Mono>
        </p>
      </div>
      <div className="space-y-3 border-t border-line bg-fill p-5">
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
        <h3 className="text-[18px] leading-7">
          {m.title}
          {m.kind === "change_order" && <span className="ml-2 text-[15px] font-normal text-muted">added to original scope</span>}
        </h3>
        <Mono className="text-[16px]">{formatMoney(m.amount_minor_units, currency)}</Mono>
      </div>
      <div className="mt-2">{chip}</div>
      {m.evidence_note && <p className="mt-2 text-[15px] text-muted">{m.evidence_note}</p>}
      {m.delivered_at && milestoneArt(m.title) && (
        <SampleArt
          compact
          {...ART[milestoneArt(m.title)!]}
          alt={`${ART[milestoneArt(m.title)!].alt}, shared for your review`}
          className="mt-3"
        />
      )}
      {m.evidence_url && (
        <a href={m.evidence_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-link underline">
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
          className="mt-3 flex items-center justify-center gap-2 rounded-md border border-line-strong px-5 py-3 font-medium hover:bg-fill"
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
      <p className="mt-8 flex items-center gap-2 rounded-lg border border-accent bg-success-soft p-4 text-ink">
        <Check size={18} aria-hidden className="shrink-0 text-accent" /> You accepted scope v{view.scope_version}. {view.seller_display_name} will bill each stage through PayPal.
      </p>
    );
  }
  if (!view.can_accept) {
    return (
      <p className="mt-8 rounded-lg border border-line bg-fill p-4 text-neutral">
        {view.seller_display_name} is still preparing this scope. Come back when they share it.
      </p>
    );
  }
  return (
    <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-canvas px-4 pt-4 pb-5 sm:static sm:mt-8 sm:border-0 sm:bg-transparent sm:p-0">
      <div className="mx-auto max-w-[720px]">
        <p className="text-[14px] leading-5 text-muted">
          You pay each stage through a PayPal invoice. Accepting sends no money. In this demo it is a click: it does not verify identity or act as an e-signature.
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
