import {
  Check,
  CircleDashed,
  Copy,
  ExternalLink,
  Hourglass,
  Lock,
  PenLine,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { ProposalCard } from "../components/ProposalCard";
import { ActorTag, AppShell, Button, Chip, cx, ErrorNote, Loading, Mono } from "../components/ui";
import { describeActivity } from "../lib/activity";
import { api, type ChangeOrder, type Milestone, type Project, type Proposal } from "../lib/api";
import { formatDate, formatMoney, formatTime, percent } from "../lib/format";
import { copyText, useProject, useProjectMutation } from "../lib/hooks";
import { paypalStatus } from "../lib/status";

export function ProjectPage() {
  const { id = "" } = useParams();
  const query = useProject(id);
  const project = query.data;
  return (
    <AppShell projectId={id}>
      {query.isPending && <Loading label="Loading project…" />}
      {query.isError && <ErrorNote error={query.error} />}
      {project && <ProjectView project={project} />}
    </AppShell>
  );
}

function Summary({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[14px] text-muted">{label}</dt>
      <dd className="text-[16px] font-semibold">{children}</dd>
    </div>
  );
}

function ProjectView({ project }: { project: Project }) {
  const accepted =
    project.seller_accepted_version === project.scope_version &&
    project.client_accepted_version === project.scope_version;
  const sellerOnly = project.seller_accepted_version === project.scope_version && !accepted;
  const total = (project.total_minor_units ?? 0) + project.change_order_total_minor_units;
  const logRevision = useProjectMutation(project.id, () => api.logRevision(project.id));
  const [copied, setCopied] = useState(false);
  const clientUrl = `${window.location.origin}${project.client_path}`;
  const active = ["AGREED", "IN_PROGRESS"].includes(project.status);

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-2 border-b border-line pb-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-2">
          <h1 className="font-display text-[32px] leading-tight sm:text-[40px]">
            {project.title || "Untitled commission"}
          </h1>
          <Chip
            className="border border-ink bg-transparent text-ink"
            icon="file"
          >
            Scope v{project.scope_version}
            <span className="ml-1 font-normal text-muted">
              {accepted ? "accepted by both" : sellerOnly ? "waiting for client" : "draft"}
            </span>
          </Chip>
        </div>
        <p className="ml-auto flex items-baseline gap-3">
          <span className="text-muted">Total</span>
          <Mono className="text-[28px] leading-none sm:text-[36px]">
            {formatMoney(total, project.currency_code)} {project.currency_code}
          </Mono>
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-line py-3 md:grid-cols-3 xl:grid-cols-6">
        <Summary label="Deliverable">{project.deliverables.join("; ") || "—"}</Summary>
        <Summary label="Files">{project.file_formats.join(", ") || "—"}</Summary>
        <Summary label="Revisions">
          {project.revisions_included ?? "—"} included, {project.revisions_used} of {project.revisions_included ?? "—"} used
          {active && (
            <button
              type="button"
              onClick={() => logRevision.mutate()}
              disabled={logRevision.isPending}
              className="ml-2 whitespace-nowrap text-[14px] font-semibold text-accent-deep underline"
            >
              Log a revision
            </button>
          )}
        </Summary>
        <Summary label="Usage">{project.usage_rights || "—"}</Summary>
        <Summary label="Deadline">{formatDate(project.deadline_date)}</Summary>
        <Summary label="Client">
          {project.client_display_name || "Client"}
          {project.source_language && `, ${project.source_language === "en" ? "English" : project.source_language}`}
        </Summary>
      </dl>
      <div className="mt-5 grid gap-x-10 gap-y-10 min-[1100px]:grid-cols-[minmax(0,500px)_minmax(0,1fr)]">
        <div className="order-2 min-w-0 min-[1100px]:order-1">
          <Milestones project={project} />
<div className="flex flex-wrap items-center gap-3 mt-6 border-t border-line pt-3 text-[15px]">
        <span className="text-muted">Client page:</span>
        <a href={project.client_path} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-semibold text-accent-deep underline">
          Open <ExternalLink size={14} aria-hidden />
        </a>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 font-semibold text-accent-deep underline"
          onClick={async () => setCopied(await copyText(clientUrl))}
        >
          <Copy size={14} aria-hidden /> {copied ? "Link copied" : "Copy link"}
        </button>
        <ErrorNote error={logRevision.error} />
      </div>
          <Activity project={project} />
        </div>
        <div className="order-1 min-w-0 min-[1100px]:order-2">
          <AgentPanel project={project} />
        </div>
      </div>
    </>
  );
}

function NodeIcon({ tone, children }: { tone: "success" | "accent" | "neutral"; children: React.ReactNode }) {
  return (
    <span
      aria-hidden
      className={cx(
        "z-10 flex size-[38px] shrink-0 items-center justify-center rounded-full border-2",
        tone === "success" && "border-success-soft bg-success-soft text-success",
        tone === "accent" && "border-accent bg-surface text-accent",
        tone === "neutral" && "border-line bg-paper-deep text-neutral",
      )}
    >
      {children}
    </span>
  );
}

type Row = {
  key: string;
  title: string;
  share: string;
  amount: number;
  tone: "success" | "accent" | "neutral";
  icon: React.ReactNode;
  chip: React.ReactNode;
  detail: string;
  action?: React.ReactNode;
};

function Milestones({ project }: { project: Project }) {
  const deliver = useProjectMutation(project.id, (milestoneId: string) => api.deliver(milestoneId));
  const bring = useProjectMutation(project.id, (milestoneId: string) => api.proposeBill(milestoneId));
  const refresh = useProjectMutation(project.id, (invoiceId: string) => api.refreshInvoice(invoiceId));
  const livePending = (m: Milestone) =>
    project.proposals.some(
      (p) =>
        ["PENDING", "APPROVED", "FAILED"].includes(p.status) &&
        ["BILL_MILESTONE", "SEND_INVOICE"].includes(p.kind) &&
        (p.payload.milestone_id === m.id),
    );

  const rows: Row[] = project.milestones.map((m) => {
    const invoice = project.invoices.find((i) => i.id === m.active_invoice_id) ??
      [...project.invoices].reverse().find((i) => i.milestone_id === m.id && i.paypal_status);
    const status = invoice?.paypal_status ? paypalStatus(invoice.paypal_status) : null;
    const share = m.kind === "plan" ? percent(m.percentage_basis_points) : "";
    let chip: React.ReactNode = null;
    let detail = "";
    let icon: React.ReactNode = <CircleDashed size={18} />;
    let tone: Row["tone"] = "neutral";
    let action: React.ReactNode;

    if (status && invoice) {
      chip = <Chip tone={status.tone} icon={status.icon}>{status.label}</Chip>;
      detail = `Invoice ${invoice.invoice_number}, billed under scope v${invoice.billed_scope_version}`;
      if (status.paid) {
        icon = <Check size={19} />;
        tone = "success";
      }
      if (status.awaiting) {
        action = (
          <Button variant="ghost" className="px-2 py-1 text-[14px]" icon={<RefreshCw size={14} aria-hidden />} pending={refresh.isPending} onClick={() => refresh.mutate(invoice.id)}>
            Check PayPal now
          </Button>
        );
      }
    } else {
      switch (m.workflow_state) {
        case "LOCKED":
          chip = <Chip icon={<Lock size={15} aria-hidden />}>Locked</Chip>;
          detail = "Unlocks when the previous milestone is paid";
          icon = <Lock size={17} />;
          break;
        case "AWAITING_DELIVERY":
          chip = <Chip icon={<Hourglass size={15} aria-hidden />}>Waiting for you to deliver</Chip>;
          detail = "Log it as shared so the client can approve.";
          action = (
            <Button variant="secondary" className="px-3 py-1.5 text-[14px]" pending={deliver.isPending} onClick={() => deliver.mutate(m.id)}>
              Log as shared with client
            </Button>
          );
          icon = <PenLine size={17} />;
          break;
        case "DELIVERED":
          chip = <Chip icon={<Hourglass size={15} aria-hidden />}>Shared, awaiting client approval</Chip>;
          detail = "Agent proposes the invoice when the client approves";
          icon = <PenLine size={17} />;
          break;
        default:
          if (livePending(m)) {
            chip = <Chip tone="accent" icon="help">Waiting for your approval</Chip>;
            detail = "The agent's card is in the panel.";
            tone = "accent";
            icon = <Sparkles size={17} />;
          } else if (["APPROVED", "READY_TO_BILL"].includes(m.workflow_state)) {
            chip = <Chip icon="clock">Ready to bill</Chip>;
            detail = "No card is open for this stage.";
            action = (
              <Button variant="secondary" className="px-3 py-1.5 text-[14px]" pending={bring.isPending} onClick={() => bring.mutate(m.id)}>
                Bring back the billing card
              </Button>
            );
          } else {
            chip = <Chip icon="clock">{m.workflow_state === "SETTLED" ? "Settled" : "Billed"}</Chip>;
          }
      }
    }
    if (m.flagged) {
      chip = (
        <span className="flex flex-wrap gap-2">
          {chip}
          <Chip tone="warn" icon="alert">Needs your attention</Chip>
        </span>
      );
    }
    return {
      key: m.id,
      title: m.title,
      share,
      amount: m.amount_minor_units,
      tone,
      icon,
      chip,
      detail,
      action,
    };
  });

  // A change order the seller or client has not finished approving is not a milestone yet.
  const pendingCOs: ChangeOrder[] = project.change_orders.filter(
    (co) =>
      ["DRAFT", "SELLER_APPROVED"].includes(co.status) &&
      !project.milestones.some((m) => m.change_order_id === co.id),
  );
  for (const co of pendingCOs) {
    rows.push({
      key: co.id,
      title: `Change order #${co.number}`,
      share: "",
      amount: co.total_minor_units,
      tone: "accent",
      icon: <Sparkles size={17} />,
      chip:
        co.status === "DRAFT" ? (
          <Chip tone="accent" icon="help">Waiting for your approval</Chip>
        ) : (
          <Chip tone="accent" icon="clock">Waiting for the client</Chip>
        ),
      detail:
        co.status === "DRAFT"
          ? `Becomes a milestone and scope v${co.base_scope_version + 1} after the client approves`
          : "Share the client page so they can approve it.",
    });
  }

  return (
    <section aria-labelledby="milestones-h">
      <h2 id="milestones-h" className="font-display text-[28px]">Milestones</h2>
      <ol className="relative mt-4 space-y-6">
        {rows.length > 1 && <span aria-hidden className="absolute top-5 bottom-5 left-[18px] w-0.5 bg-line-strong/60" />}
        {rows.map((row) => (
          <li key={row.key} className="relative flex gap-4">
            <NodeIcon tone={row.tone}>{row.icon}</NodeIcon>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-[20px] font-semibold">
                  {row.title} {row.share && <span className="text-[17px] font-normal text-muted">{row.share}</span>}
                </h3>
                <Mono className="text-[18px]">{formatMoney(row.amount, project.currency_code)}</Mono>
              </div>
              <div className="mt-1.5">{row.chip}</div>
              {row.detail && <p className="mt-1.5 text-[15px] text-muted">{row.detail}</p>}
              {row.action && <div className="mt-1.5">{row.action}</div>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Activity({ project }: { project: Project }) {
  const items = [...project.activity].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 14);
  return (
    <section aria-labelledby="activity-h" className="mt-12">
      <h2 id="activity-h" className="font-display text-[28px]">Activity</h2>
      <ul className="mt-3 border-t border-line">
        {items.map((a) => (
          <li key={a.id} className="flex items-start gap-3 border-b border-line py-3">
            <Mono className="w-12 shrink-0 pt-0.5 text-[14px] text-muted">{formatTime(a.created_at)}</Mono>
            <ActorTag actor={a.actor} />
            <p className="min-w-0 text-[15px]">{describeActivity(a)}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AgentPanel({ project }: { project: Project }) {
  const open = project.proposals.filter((p) => ["PENDING", "APPROVED", "FAILED", "STALE"].includes(p.status));
  const order = { PENDING: 0, FAILED: 1, APPROVED: 2, STALE: 3 } as Record<string, number>;
  open.sort((a, b) => order[a.status] - order[b.status] || b.created_at.localeCompare(a.created_at));
  const waiting = project.proposals.filter((p) => p.status === "PENDING").length;
  const executed = project.proposals
    .filter((p) => p.status === "EXECUTED")
    .sort((a, b) => (b.executed_at ?? "").localeCompare(a.executed_at ?? ""));

  // A sent invoice that is still unpaid deserves the full green card, not a one-line row.
  const featured = executed.filter((p) => {
    if (!["SEND_INVOICE", "SEND_REMINDER"].includes(p.kind)) return false;
    const inv = project.invoices.find((i) => i.id === p.payload.invoice_id);
    return !!inv && paypalStatus(inv.paypal_status).awaiting;
  });
  const earlier = executed.filter((p) => !featured.includes(p));

  return (
    <section aria-labelledby="agent-h">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 id="agent-h" className="flex items-center gap-2 font-display text-[28px]">
          <Sparkles size={22} className="text-accent" aria-hidden />
          Agent: {waiting === 0 ? "nothing waiting" : `${waiting} proposal${waiting === 1 ? "" : "s"} waiting`}
        </h2>
        <p className="text-[15px] font-semibold text-muted">AI proposes. You approve. PayPal executes.</p>
      </div>

      <div className="mt-4 space-y-4">
        {project.billing_disabled_code && (
          <p role="alert" className="rounded-[10px] border border-danger bg-danger-soft p-4 text-danger">
            <strong>Billing is paused.</strong> PayPal refused the last request for this account
            ({project.billing_disabled_code}). Fix the PayPal app permissions, then approve a card to resume.
          </p>
        )}
        {project.status === "DRAFT" && <NextStep title="Review the client's request" to={`/projects/${project.id}/intake`} cta="Go to intake">
          Paste the client's first message, check what the agent found, then accept scope v{project.scope_version}.
        </NextStep>}
        {project.status === "AWAITING_ACCEPTANCE" && (
          <NextStep title="Waiting for the client" to={project.client_path} cta="Open the client page" external>
            You accepted scope v{project.scope_version}. Billing starts when the client accepts on their page.
          </NextStep>
        )}
        {open.map((p) => (
          <ProposalCard key={p.id} proposal={p} project={project} />
        ))}
        {featured.map((p) => (
          <ProposalCard key={p.id} proposal={p} project={project} />
        ))}
        {open.length === 0 && featured.length === 0 && ["AGREED", "IN_PROGRESS", "COMPLETED"].includes(project.status) && (
          <p className="rounded-[10px] border border-line bg-surface p-5 text-muted">
            Nothing needs your approval. When the client sends a new message,{" "}
            <Link className="font-semibold text-accent-deep underline" to={`/projects/${project.id}/messages/new`}>
              paste it here
            </Link>{" "}
            and the agent checks it against the agreement.
          </p>
        )}
        {earlier.map((p) => (
          <EarlierRow key={p.id} proposal={p} project={project} />
        ))}
      </div>
    </section>
  );
}

function NextStep({ title, children, to, cta, external }: { title: string; children: React.ReactNode; to: string; cta: string; external?: boolean }) {
  return (
    <div className="rounded-[14px] border border-line bg-surface p-5">
      <h3 className="font-display text-[24px]">{title}</h3>
      <p className="mt-1 text-muted">{children}</p>
      <div className="mt-3">
        {external ? (
          <a href={to} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-3 font-semibold text-white hover:bg-accent-deep">
            {cta} <ExternalLink size={16} aria-hidden />
          </a>
        ) : (
          <Link to={to} className="inline-flex rounded-lg bg-accent px-5 py-3 font-semibold text-white hover:bg-accent-deep">
            {cta}
          </Link>
        )}
      </div>
    </div>
  );
}

function EarlierRow({ proposal: p, project }: { proposal: Proposal; project: Project }) {
  const invoice =
    project.invoices.find((i) => i.id === p.payload.invoice_id) ??
    project.invoices.find((i) => i.milestone_id === p.payload.milestone_id && i.is_active);
  const status = invoice?.paypal_status ? paypalStatus(invoice.paypal_status) : null;
  const names: Record<string, string> = {
    BILL_MILESTONE: `Bill ${(p.payload.milestone_title ?? "").toLowerCase()}`,
    SEND_INVOICE: `Send ${(p.payload.milestone_title ?? "").toLowerCase()} invoice`,
    SEND_REMINDER: "Payment reminder",
    CANCEL_INVOICE: "Cancel invoice",
    CHANGE_ORDER: `Change order #${p.payload.number}`,
  };
  const detail: Record<string, string> = {
    BILL_MILESTONE: `Approved by ${project.seller_display_name}, draft created at PayPal with terms v${p.payload.scope_version ?? p.scope_version}`,
    SEND_INVOICE: `Approved by ${project.seller_display_name}, sent through PayPal`,
    SEND_REMINDER: `Approved by ${project.seller_display_name}`,
    CANCEL_INVOICE: `Approved by ${project.seller_display_name}`,
    CHANGE_ORDER: `Approved by ${project.seller_display_name}; the client decides next`,
  };
  const amount = p.payload.amount_minor_units ?? 0;
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-[14px] border border-line bg-surface px-6 py-4">
      <div className="min-w-0">
        <p className="text-[17px] font-semibold">Earlier: {names[p.kind]}</p>
        <p className="text-[15px] text-muted">{detail[p.kind]}</p>
      </div>
      <div className="flex items-center gap-4">
        <Mono className="text-[18px]">{formatMoney(amount, p.payload.currency_code ?? project.currency_code)}</Mono>
        {p.kind === "CHANGE_ORDER" ? (
          <Chip icon="check" tone="neutral">Approved by you</Chip>
        ) : status ? (
          <Chip tone={status.tone} icon={status.icon}>{status.label}</Chip>
        ) : (
          <Chip icon="check">Done</Chip>
        )}
      </div>
    </div>
  );
}
