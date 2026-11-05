import { Check, Copy, ExternalLink, Hourglass, Lock, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router";
import { ProposalCard } from "../components/ProposalCard";
import { ActorTag, AppShell, Button, Chip, cx, ErrorNote, Eyebrow, Loading, Mono, SampleArt, TotalBreakdown } from "../components/ui";
import { describeActivity } from "../lib/activity";
import { api, ApiError, type ChangeOrder, type Milestone, type Project, type Proposal } from "../lib/api";
import { formatDate, formatMoney, formatTime, percent } from "../lib/format";
import { ART, milestoneArt } from "../lib/art";
import { copyText, useProject, useProjectMutation } from "../lib/hooks";
import { paypalStatus } from "../lib/status";

export function ProjectPage() {
  const { id = "" } = useParams();
  const query = useProject(id);
  const project = query.data;
  return (
    <AppShell projectId={id}>
      {query.isPending && <Loading label="Loading project…" />}
      {query.isError && query.error instanceof ApiError && query.error.status === 404 ? (
        <MissingProject />
      ) : (
        query.isError && <ErrorNote error={query.error} />
      )}
      {project && <ProjectView project={project} />}
    </AppShell>
  );
}

/** The free host restarts and forgets demo data; Judge Mode seeds a new project on demand. */
export function MissingProject() {
  const navigate = useNavigate();
  const session = useMutation({
    mutationFn: api.demoSession,
    onSuccess: (data) => navigate(`/projects/${data.project.id}`),
  });
  return (
    <div className="py-12">
      <h1 className="font-display text-[30px]">This project is no longer available</h1>
      <p className="mt-2 max-w-[40em] text-muted">
        It was erased by Start over, the free demo server restarted and forgot it, or this link belongs to
        another visitor. We can't tell from here whether invoices were sent for it. Any invoice that was
        already sent stays in the PayPal sandbox; open it from the PayPal sandbox account to check. Open
        your current demo project to continue.
      </p>
      <div className="mt-4">
        <Button pending={session.isPending} onClick={() => session.mutate()}>
          Open my current demo project
        </Button>
      </div>
      <div className="mt-3"><ErrorNote error={session.error} /></div>
    </div>
  );
}

function DemoJumps({ project }: { project: Project }) {
  const info = useQuery({ queryKey: ["demoInfo"], queryFn: api.demoInfo, staleTime: Infinity });
  const jump = useProjectMutation(project.id, (target: "deposit_paid" | "sketch_shared") =>
    api.demoJump(project.id, target),
  );
  const fresh = project.invoices.length === 0 && ["DRAFT", "AWAITING_ACCEPTANCE", "AGREED"].includes(project.status);
  if (!info.data?.judge_mode || !fresh) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-dashed border-line-strong px-4 py-3 text-[15px]">
      <span className="font-medium">Judge shortcuts</span>
      {(["deposit_paid", "sketch_shared"] as const).map((target) => (
        <button
          key={target}
          type="button"
          disabled={jump.isPending}
          onClick={() => jump.mutate(target)}
          className="font-medium text-link underline disabled:opacity-60"
        >
          {target === "deposit_paid" ? "Jump to: deposit paid" : "Jump to: sketch shared"}
        </button>
      ))}
      <span className="text-muted">
        Fills sample terms, then uses a previously paid sandbox invoice. PayPal is asked live; nothing is shown as paid unless PayPal confirms it.
      </span>
      {jump.data && (
        <p role="status" className="basis-full font-medium">
          {jump.data.message}
        </p>
      )}
      <ErrorNote error={jump.error} />
    </div>
  );
}

function Summary({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="eyebrow !text-[12px] !tracking-[0.14em]">{label}</dt>
      <dd className="mt-1 text-[15px] leading-6">{children}</dd>
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
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3 border-b border-line pb-5">
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-2">
          <h1 className="font-display text-[30px] leading-9 sm:text-[36px] sm:leading-10">
            {project.title || "Untitled commission"}
          </h1>
          <p className="font-mono text-[14px] text-neutral">
            Scope v{project.scope_version}
            <span className="ml-2 font-sans text-muted">
              {accepted ? "accepted by both" : sellerOnly ? "waiting for client" : "draft"}
            </span>
          </p>
        </div>
        <p className="ml-auto flex items-baseline gap-3">
          <Eyebrow>Total</Eyebrow>
          <Mono className="text-[24px] leading-none sm:text-[28px]">
            {formatMoney(total, project.currency_code)} {project.currency_code}
          </Mono>
        </p>
      </div>

      <DemoJumps project={project} />
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 border-b border-line py-5 md:grid-cols-3 xl:grid-cols-6">
        <Summary label="Deliverable">{project.deliverables.join("; ") || "—"}</Summary>
        <Summary label="Files">{project.file_formats.join(", ") || "—"}</Summary>
        <Summary label="Revisions">
          {project.revisions_included ?? "—"} included, {project.revisions_used} of {project.revisions_included ?? "—"} used
          {active && (
            <button
              type="button"
              onClick={() => logRevision.mutate()}
              disabled={logRevision.isPending}
              className="ml-2 whitespace-nowrap text-[14px] font-medium text-link underline"
            >
              Log a revision
            </button>
          )}
        </Summary>
        <Summary label="Usage">{project.usage_rights || "—"}</Summary>
        <Summary label="Deadline">{formatDate(project.deadline_date)}</Summary>
        <Summary label="Client">
          {project.client_display_name || "Client"}
          {project.source_language && `, ${new Intl.DisplayNames(["en"], { type: "language" }).of(project.source_language) ?? project.source_language}`}
        </Summary>
      </dl>
      <div className="mt-5 grid gap-x-10 gap-y-10 min-[1100px]:grid-cols-[minmax(0,500px)_minmax(0,1fr)]">
        <div className="order-2 min-w-0 min-[1100px]:order-1">
          <Milestones project={project} />
<div className="flex flex-wrap items-center gap-3 mt-6 border-t border-line pt-3 text-[15px]">
        <span className="text-muted">Client page:</span>
        <a href={project.client_path} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-medium text-link underline">
          Open <ExternalLink size={14} aria-hidden />
        </a>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 font-medium text-link underline"
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
        "z-10 flex size-8 shrink-0 items-center justify-center rounded-full border",
        tone === "success" && "border-accent bg-accent text-on-accent",
        tone === "accent" && "border-accent bg-canvas text-accent",
        tone === "neutral" && "border-line-strong bg-canvas text-muted",
      )}
    >
      {children}
    </span>
  );
}

const Dot = ({ filled }: { filled?: boolean }) => (
  <span className={cx("size-2 rounded-full", filled ? "bg-accent" : "border border-current")} />
);

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
  art?: keyof typeof ART | null;
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
    const hasChangeOrders = project.change_order_total_minor_units > 0;
    const share =
      m.kind === "plan"
        ? hasChangeOrders
          ? `${percent(m.percentage_basis_points)} of original scope`
          : percent(m.percentage_basis_points)
        : "";
    let chip: React.ReactNode = null;
    let detail = "";
    let icon: React.ReactNode = <Dot />;
    let tone: Row["tone"] = "neutral";
    let action: React.ReactNode;

    if (status && invoice) {
      chip = <Chip tone={status.tone} icon={status.icon}>{status.label}</Chip>;
      detail = invoice.adopted
        ? `Previously paid sandbox invoice ${invoice.paypal_invoice_id}, confirmed as paid by PayPal just now`
        : `Invoice ${invoice.invoice_number}, billed under scope v${invoice.billed_scope_version}`;
      if (status.paid) {
        icon = <Check size={16} />;
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
          icon = <Lock size={14} />;
          break;
        case "AWAITING_DELIVERY":
          chip = <Chip icon={<Hourglass size={15} aria-hidden />}>Waiting for you to deliver</Chip>;
          detail = "Log it as shared so the client can approve.";
          action = (
            <Button variant="secondary" className="px-3 py-1.5 text-[14px]" pending={deliver.isPending} onClick={() => deliver.mutate(m.id)}>
              Log as shared with client
            </Button>
          );
          icon = <Dot />;
          break;
        case "DELIVERED":
          chip = <Chip icon={<Hourglass size={15} aria-hidden />}>Shared, awaiting client approval</Chip>;
          detail = "Agent proposes the invoice when the client approves";
          icon = <Dot />;
          break;
        default:
          if (livePending(m)) {
            chip = <Chip tone="accent" icon="help">Waiting for your approval</Chip>;
            detail = "The agent's card is in the panel.";
            tone = "accent";
            icon = <Dot filled />;
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
      art: m.delivered_at ? milestoneArt(m.title) : null,
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
      icon: <Dot filled />,
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
      <h2 id="milestones-h" className="eyebrow">Milestones</h2>
      <TotalBreakdown
        className="mt-3"
        base={project.total_minor_units ?? 0}
        changeOrders={project.change_order_total_minor_units}
        currency={project.currency_code}
      />
      <ol className="relative mt-5 space-y-7">
        {rows.length > 1 && <span aria-hidden className="absolute top-5 bottom-5 left-[15.5px] w-px bg-line" />}
        {rows.map((row) => (
          <li key={row.key} className="relative flex gap-4">
            <NodeIcon tone={row.tone}>{row.icon}</NodeIcon>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-[18px] leading-7">
                  {row.title} {row.share && <span className="text-[15px] text-muted">{row.share}</span>}
                </h3>
                <Mono className="text-[16px]">{formatMoney(row.amount, project.currency_code)}</Mono>
              </div>
              <div className="mt-1.5">{row.chip}</div>
              {row.detail && <p className="mt-1.5 text-[15px] text-muted">{row.detail}</p>}
              {row.action && <div className="mt-1.5">{row.action}</div>}
              {row.art && (
                <SampleArt
                  compact
                  {...ART[row.art]}
                  alt={row.art === "sketch" ? `${ART.sketch.alt}, shared for review` : `${ART.final.alt}, final delivery`}
                  className="mt-3"
                />
              )}
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
      <h2 id="activity-h" className="eyebrow">Activity</h2>
      <ul className="mt-3 border-t border-line">
        {items.map((a) => (
          <li key={a.id} className="flex items-start gap-3 border-b border-line py-3">
            <Mono className="w-12 shrink-0 pt-0.5 text-[13px] leading-5 text-muted">{formatTime(a.created_at)}</Mono>
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
      <h2 id="agent-h" className="eyebrow">Agent</h2>
      <p className="mt-1 font-display text-[24px] leading-8">
        {waiting === 0 ? "Nothing waiting for you" : `${waiting} proposal${waiting === 1 ? "" : "s"} waiting for your approval`}
      </p>

      <div className="mt-5 space-y-4">
        {project.billing_disabled_code && (
          <p role="alert" className="rounded-lg border border-danger bg-danger-soft p-4 text-danger">
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
          <p className="rounded-lg border border-line p-5 text-muted">
            Nothing needs your approval. When the client sends a new message,{" "}
            <Link className="font-medium text-link underline" to={`/projects/${project.id}/messages/new`}>
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
    <div className="rounded-lg border-2 border-accent p-5">
      <h3 className="font-display text-[22px] leading-7">{title}</h3>
      <p className="mt-1 text-muted">{children}</p>
      <div className="mt-3">
        {external ? (
          <a href={to} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-md bg-accent px-5 py-3 font-medium text-on-accent hover:bg-accent-deep">
            {cta} <ExternalLink size={16} aria-hidden />
          </a>
        ) : (
          <Link to={to} className="inline-flex rounded-md bg-accent px-5 py-3 font-medium text-on-accent hover:bg-accent-deep">
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
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-lg border border-line px-5 py-4">
      <div className="min-w-0">
        <p className="text-[16px]">Earlier: {names[p.kind]}</p>
        <p className="text-[15px] text-muted">{detail[p.kind]}</p>
      </div>
      <div className="flex items-center gap-4">
        <Mono className="text-[16px]">{formatMoney(amount, p.payload.currency_code ?? project.currency_code)}</Mono>
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
