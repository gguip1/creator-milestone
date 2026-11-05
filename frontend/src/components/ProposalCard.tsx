import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ExternalLink,
  Landmark,
  MessageSquare,
  Pencil,
  PenLine,
  RotateCw,
  Sparkles,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { api, ApiError, type Project, type Proposal } from "../lib/api";
import { formatMoney, moneyInput, parseMoney } from "../lib/format";
import { copyText, useProjectMutation } from "../lib/hooks";
import { paypalStatus } from "../lib/status";
import { EvidenceTable, type EvidenceRow } from "./evidence";
import { Button, Chip, cx, ErrorNote, Mono } from "./ui";

const lowerFirst = (s: string) => (s.length > 1 && s[1] === s[1].toLowerCase() ? s[0].toLowerCase() + s.slice(1) : s);

const KICKER: Record<string, string> = {
  BILL_MILESTONE: "Billing rule",
  SEND_INVOICE: "Send",
  SEND_REMINDER: "Reminder rule",
  CANCEL_INVOICE: "Cancel",
  CHANGE_ORDER: "Scope Guard",
};

function titleFor(p: Proposal, working: boolean): string {
  const milestone = lowerFirst(p.payload.milestone_title ?? "invoice");
  switch (p.kind) {
    case "BILL_MILESTONE":
      return working ? "Creating draft" : `Bill ${milestone}`;
    case "SEND_INVOICE":
      return working ? "Sending to PayPal" : "Send this invoice?";
    case "SEND_REMINDER":
      return working ? "Sending reminder" : "Send a payment reminder?";
    case "CANCEL_INVOICE":
      return working ? "Cancelling at PayPal" : "Cancel this invoice?";
    case "CHANGE_ORDER": {
      const lines = p.payload.lines ?? [];
      return `Change order #${p.payload.number}: ${working ? "approving" : `bill ${lines.length === 2 ? "two" : lines.length} extra${lines.length === 1 ? "" : "s"}`}`;
    }
  }
}

const APPROVE_LABEL: Record<string, string> = {
  BILL_MILESTONE: "Approve",
  SEND_INVOICE: "Send invoice",
  SEND_REMINDER: "Send reminder",
  CANCEL_INVOICE: "Cancel invoice",
  CHANGE_ORDER: "Approve",
};

const WORKING_LABEL: Record<string, string> = {
  BILL_MILESTONE: "Creating draft…",
  SEND_INVOICE: "Sending…",
  SEND_REMINDER: "Sending…",
  CANCEL_INVOICE: "Cancelling…",
  CHANGE_ORDER: "Approving…",
};

const NEXT_NOTE: Record<string, string> = {
  BILL_MILESTONE: "Approving creates a draft at PayPal. Nothing reaches the client yet.",
  SEND_INVOICE: "Sending gives the client a sandbox payment link.",
  SEND_REMINDER: "PayPal emails the client a reminder.",
  CANCEL_INVOICE: "PayPal cancels the invoice; the stage can be billed again.",
  CHANGE_ORDER: "Next, the client approves on their page. Then you approve the PayPal invoice.",
};

function Fact({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line py-2.5 last:border-b-0">
      <dt className="text-muted">{label}</dt>
      <dd className={cx("text-right font-semibold", mono && "font-mono text-[14px]")}>{children}</dd>
    </div>
  );
}

function changeOrderRows(p: Proposal): EvidenceRow[] {
  const billed: EvidenceRow[] = (p.payload.lines ?? []).map((line) => ({
    key: line.id,
    quote: line.quote,
    classification: line.classification,
    clauseRef: line.clause_ref,
    clauseText: line.clause_text,
    rate: `${line.name} × ${line.quantity}`,
    amount: line.amount_minor_units,
    needsPrice: line.needs_price,
  }));
  const notBilled: EvidenceRow[] = (p.payload.not_billed ?? []).map((item, i) => ({
    key: `nb-${i}`,
    quote: item.quote,
    classification: item.classification,
    clauseRef: item.clause_ref,
    clauseText: null,
    rate: "Asked in the reply",
    amount: null,
  }));
  return [...billed, ...notBilled];
}

function replyDraftFor(project: Project, p: Proposal): string | null {
  const co = project.change_orders.find((c) => c.id === p.payload.change_order_id);
  const message = project.messages.find((m) => m.id === co?.message_id);
  const draft = message?.analysis?.reply_draft_client;
  return typeof draft === "string" && draft ? draft : null;
}

export function ProposalCard({ proposal: p, project }: { proposal: Proposal; project: Project }) {
  const queryClient = useQueryClient();
  const refetch = () => queryClient.invalidateQueries({ queryKey: ["project", project.id] });
  const approve = useProjectMutation(project.id, () => api.approveProposal(p.id));
  const dismiss = useProjectMutation(project.id, () => api.dismissProposal(p.id));
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [fullDraft, setFullDraft] = useState(false);

  const working = approve.isPending || p.status === "APPROVED";
  const failed = p.status === "FAILED" && !approve.isPending;
  const stale = p.status === "STALE";
  const blocked = p.status === "PENDING" && !p.can_approve && p.blockers.length > 0;
  const waiting = p.status === "PENDING" && !blocked;
  const executed = p.status === "EXECUTED";
  const currency = p.payload.currency_code ?? project.currency_code;
  const amount = p.payload.amount_minor_units ?? 0;
  const invoice = project.invoices.find((i) => i.id === p.payload.invoice_id) ??
    project.invoices.find((i) => i.milestone_id === p.payload.milestone_id && i.is_active);
  const status = paypalStatus(invoice?.paypal_status);
  const draft = p.kind === "CHANGE_ORDER" ? replyDraftFor(project, p) : null;

  const border = failed || blocked
    ? "border-[1.5px] border-danger"
    : executed
      ? "border-[1.5px] border-success"
      : waiting
        ? "border-2 border-accent"
        : "border border-line";

  const approveError =
    approve.error instanceof ApiError && !approve.error.proposalFailed ? approve.error : null;

  const kicker = executed ? (
    <span className="flex items-center gap-1.5 text-success">
      <Landmark size={15} aria-hidden /> PayPal accepted the invoice
    </span>
  ) : failed ? (
    <span className="flex items-center gap-1.5 text-danger">
      <Landmark size={15} aria-hidden /> PayPal said no
    </span>
  ) : working ? (
    <span className="flex items-center gap-1.5 text-muted">
      <PenLine size={15} aria-hidden /> Approved by {project.seller_display_name}
    </span>
  ) : (
    <span className="flex items-center gap-1.5 text-accent-deep">
      <Sparkles size={15} aria-hidden /> Agent proposes · {KICKER[p.kind]}
    </span>
  );

  return (
    <article
      aria-label={titleFor(p, false)}
      className={cx("overflow-hidden rounded-[14px] bg-surface", border)}
    >
      <div className="px-5 pt-4 pb-4 sm:px-8">
        <p className="text-[14px] font-semibold">{kicker}</p>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
          <h3 className="font-display text-[26px] leading-tight sm:text-[34px]">
            {failed ? "PayPal could not complete this step" : executed && p.kind === "SEND_INVOICE" ? "Invoice sent" : titleFor(p, working)}
          </h3>
          <Mono className="text-[30px] leading-none sm:text-[44px]">{formatMoney(amount, currency)}</Mono>
        </div>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
          <p className="max-w-[56ch] text-[16px] text-muted">
            {failed ? (p.error_message ?? "PayPal could not complete this step.") : p.rationale}
          </p>
          <div>
            {waiting && <Chip tone="accent" icon="help">Waiting for your approval</Chip>}
            {blocked && <Chip tone="danger" icon="alert">Blocked: {p.blockers[0].message}</Chip>}
            {working && <Chip icon="clock">Working</Chip>}
            {failed && <Chip tone="danger" icon="x">Failed</Chip>}
            {stale && <Chip icon="clock">Outdated</Chip>}
            {executed && <Chip tone={status.tone} icon={status.icon}>{status.label}</Chip>}
          </div>
        </div>
      </div>

      {p.kind === "CHANGE_ORDER" ? (
        <div className="px-5 pb-4 sm:px-8">
          <EvidenceTable
            rows={changeOrderRows(p)}
            total={amount}
            currency={currency}
            revisions={{ used: project.revisions_used, included: project.revisions_included }}
            footnote="Priced from your rate card. AI never sets a price."
          />
        </div>
      ) : (
        <dl className="mx-5 border-t border-line text-[16px] sm:mx-8">
          {p.payload.invoice_number && (
            <Fact label="Invoice" mono>
              {p.payload.invoice_number}
            </Fact>
          )}
          <Fact label="Recipient">{p.payload.recipient_email ?? "—"}</Fact>
          <Fact label="Amount" mono>
            {formatMoney(amount, currency)}
          </Fact>
          <Fact label="Currency">{currency}</Fact>
          <Fact label="Terms">
            {p.kind === "BILL_MILESTONE"
              ? `Terms v${p.payload.scope_version ?? p.scope_version} attached`
              : `Terms v${p.payload.billed_scope_version ?? p.scope_version}`}
          </Fact>
        </dl>
      )}

      {failed && p.error_code && (
        <div className="mt-2 bg-paper-deep px-5 py-3 sm:px-8">
          <p className="text-[14px] text-muted">PayPal code</p>
          <p className="font-mono text-[14px] break-all">{p.error_code}</p>
        </div>
      )}

      {draft && (
        <div className="bg-paper-deep px-5 py-3 sm:px-8">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="flex items-center gap-2 font-semibold">
              <MessageSquare size={16} aria-hidden /> Reply draft ready to copy
            </p>
            <Button
              variant="secondary"
              className="px-3 py-1.5 text-[14px]"
              onClick={async () => {
                setCopied(await copyText(draft));
              }}
            >
              {copied ? "Copied" : "Copy reply"}
            </Button>
          </div>
          <p className={cx("mt-1 text-[15px] text-muted", !fullDraft && "line-clamp-2")}>“{draft}”</p>
          <button type="button" onClick={() => setFullDraft(!fullDraft)} className="mt-1 text-[14px] font-semibold text-accent-deep underline">
            {fullDraft ? "Show less" : "Show the full reply"}
          </button>
        </div>
      )}

      {editing && (
        <EditPanel proposal={p} project={project} onDone={() => { setEditing(false); refetch(); }} />
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-4 sm:flex-nowrap sm:px-8">
        {working && (
          <Button pending block className="sm:w-full">
            {WORKING_LABEL[p.kind]}
          </Button>
        )}
        {(waiting || blocked) && !working && (
          <>
            <Button
              icon={<Check size={18} aria-hidden />}
              blocked={blocked}
              onClick={() => approve.mutate()}
            >
              {blocked ? "Approve (blocked)" : APPROVE_LABEL[p.kind]}
            </Button>
            <Button variant="secondary" icon={<Pencil size={17} aria-hidden />} onClick={() => setEditing(!editing)}>
              Edit
            </Button>
            <Button variant="ghost" icon={<X size={17} aria-hidden />} pending={dismiss.isPending} onClick={() => dismiss.mutate()}>
              Dismiss
            </Button>
            {blocked ? (
              <Link to={`/projects/${project.id}/intake`} className="ml-auto text-[14px] font-semibold text-accent-deep underline">
                Edit scope
              </Link>
            ) : (
              <p className="text-[14px] text-muted sm:ml-auto sm:max-w-[30ch] sm:text-right">{NEXT_NOTE[p.kind]}</p>
            )}
          </>
        )}
        {failed && (
          <>
            <Button variant="secondary" icon={<Pencil size={17} aria-hidden />} onClick={() => setEditing(!editing)}>
              Edit recipient
            </Button>
            <Button variant="ghost" icon={<RotateCw size={17} aria-hidden />} onClick={() => approve.mutate()}>
              Try again
            </Button>
            <Button variant="ghost" icon={<X size={17} aria-hidden />} pending={dismiss.isPending} onClick={() => dismiss.mutate()}>
              Dismiss
            </Button>
          </>
        )}
        {stale && (
          <Button variant="ghost" icon={<X size={17} aria-hidden />} pending={dismiss.isPending} onClick={() => dismiss.mutate()}>
            Dismiss
          </Button>
        )}
        {executed && invoice?.payer_link && (
          <a
            href={invoice.payer_link}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-lg border border-line-strong px-5 py-3 font-semibold hover:bg-paper-deep"
          >
            <ExternalLink size={17} aria-hidden /> Open PayPal invoice
          </a>
        )}
        {executed && !invoice?.payer_link && p.kind === "CHANGE_ORDER" && (
          <p className="text-[14px] text-muted">The client can now approve on their page.</p>
        )}
        {stale && <p className="text-[14px] text-muted">Scope or invoice changed since this was proposed.</p>}
      </div>
      {(approveError || dismiss.error) && (
        <div className="px-5 pb-4 sm:px-8">
          <ErrorNote error={approveError ?? dismiss.error} />
        </div>
      )}
    </article>
  );
}

/** Edit the parts the backend allows: note/subject on invoice cards, quantity and price on change orders. */
function EditPanel({ proposal: p, project, onDone }: { proposal: Proposal; project: Project; onDone: () => void }) {
  const [note, setNote] = useState(p.payload.note ?? "");
  const [subject, setSubject] = useState(p.payload.subject ?? "");
  const [email, setEmail] = useState(p.payload.recipient_email ?? "");
  const [lines, setLines] = useState(
    (p.payload.lines ?? []).map((l) => ({
      id: l.id,
      name: l.name,
      quantity: String(l.quantity),
      price: moneyInput(l.unit_price_minor_units, project.currency_code),
      removed: false,
    })),
  );
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (p.status === "FAILED") {
        if (email !== (p.payload.recipient_email ?? "")) {
          await api.patchProject(project.id, { client_email: email });
        }
      } else if (p.kind === "CHANGE_ORDER") {
        const edits = lines
          .filter((l) => !l.removed)
          .map((l) => {
            const price = parseMoney(l.price, project.currency_code);
            return { id: l.id, quantity: Number(l.quantity), ...(price ? { unit_price_minor_units: price } : {}) };
          });
        await api.editProposal(p.id, {
          lines: edits,
          remove_line_ids: lines.filter((l) => l.removed).map((l) => l.id),
        });
      } else {
        await api.editProposal(p.id, {
          ...(p.kind !== "BILL_MILESTONE" && subject ? { subject } : {}),
          note,
        });
      }
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  }

  const input = "w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-[16px]";
  return (
    <div className="space-y-3 border-t border-line bg-paper px-5 py-4 sm:px-8">
      {p.status === "FAILED" ? (
        <label className="block text-[14px] font-semibold">
          Client's PayPal email
          <input className={cx(input, "mt-1 font-normal")} value={email} onChange={(e) => setEmail(e.target.value)} type="email" />
        </label>
      ) : p.kind === "CHANGE_ORDER" ? (
        lines.map((l, i) => (
          <div key={l.id} className="flex flex-wrap items-end gap-3">
            <span className="min-w-[8rem] flex-1 font-semibold">{l.name}</span>
            <label className="text-[14px] font-semibold">
              Quantity
              <input
                className={cx(input, "mt-1 w-20 font-normal")}
                inputMode="numeric"
                value={l.quantity}
                disabled={l.removed}
                onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))}
              />
            </label>
            <label className="text-[14px] font-semibold">
              Unit price
              <input
                className={cx(input, "mt-1 w-28 font-mono font-normal")}
                inputMode="decimal"
                value={l.price}
                disabled={l.removed}
                onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, price: e.target.value } : x)))}
              />
            </label>
            <Button
              variant="ghost"
              onClick={() => setLines(lines.map((x, j) => (j === i ? { ...x, removed: !x.removed } : x)))}
            >
              {l.removed ? "Keep line" : "Remove line"}
            </Button>
          </div>
        ))
      ) : (
        <>
          {p.kind !== "BILL_MILESTONE" && (
            <label className="block text-[14px] font-semibold">
              Subject
              <input className={cx(input, "mt-1 font-normal")} value={subject} onChange={(e) => setSubject(e.target.value)} />
            </label>
          )}
          <label className="block text-[14px] font-semibold">
            Note on the invoice
            <textarea className={cx(input, "mt-1 font-normal")} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </>
      )}
      {p.status !== "FAILED" && (
        <p className="text-[14px] text-muted">The amount and recipient are never editable here; the agent computes them.</p>
      )}
      <ErrorNote error={error} />
      <div className="flex gap-3">
        <Button pending={saving} onClick={save}>
          Save changes
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
