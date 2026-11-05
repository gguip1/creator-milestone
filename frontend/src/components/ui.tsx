import {
  AlertTriangle,
  Banknote,
  Check,
  CheckCircle2,
  Circle,
  CircleHelp,
  Clock,
  FileText,
  FlaskConical,
  Landmark,
  Loader2,
  MessageSquare,
  PenLine,
  Send,
  Sparkles,
  Undo2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, NavLink } from "react-router";
import { api, ApiError } from "../lib/api";
import { formatMoney } from "../lib/format";
import type { IconName, Tone } from "../lib/status";
import { useWaking } from "../lib/waking";

const ICONS: Record<IconName, LucideIcon> = {
  circle: Circle,
  send: Send,
  clock: Clock,
  check: CheckCircle2,
  alert: AlertTriangle,
  undo: Undo2,
  x: X,
  file: FileText,
  help: CircleHelp,
  banknote: Banknote,
};

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

const TONES: Record<Tone, string> = {
  neutral: "bg-neutral-soft text-neutral",
  accent: "bg-accent-soft text-accent-deep",
  success: "bg-success-soft text-success",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
};

export function Chip({
  tone = "neutral",
  icon,
  children,
  className,
}: {
  tone?: Tone;
  icon?: IconName | ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const Icon = typeof icon === "string" ? ICONS[icon as IconName] : null;
  return (
    <span
      className={cx(
        "inline-flex w-fit max-w-full items-center gap-1.5 rounded-md px-2.5 py-[5px] text-[14px] leading-tight font-semibold",
        TONES[tone],
        className,
      )}
    >
      {Icon ? <Icon size={15} aria-hidden className="shrink-0" /> : icon}
      <span>{children}</span>
    </span>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
  pending?: boolean;
  blocked?: boolean;
  icon?: ReactNode;
  block?: boolean;
};

export function Button({
  variant = "primary",
  pending,
  blocked,
  icon,
  block,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const inert = pending || blocked || disabled;
  const style = inert
    ? "bg-neutral-soft text-neutral cursor-not-allowed"
    : variant === "primary"
      ? "bg-accent text-white hover:bg-accent-deep active:bg-accent-deep"
      : variant === "secondary"
        ? "bg-surface text-ink border border-line-strong hover:bg-paper-deep"
        : "bg-transparent text-muted hover:text-ink";
  return (
    <button
      type="button"
      {...rest}
      disabled={inert}
      aria-busy={pending || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-[16px] leading-tight font-semibold transition-colors",
        block && "w-full",
        style,
        className,
      )}
    >
      {pending ? <Loader2 size={18} className="animate-spin" aria-hidden /> : blocked ? null : icon}
      {children}
    </button>
  );
}

function BuyerLogin() {
  const info = useQuery({ queryKey: ["demoInfo"], queryFn: api.demoInfo, staleTime: Infinity, retry: 2 });
  if (!info.data?.judge_mode) return null;
  const { email, password } = info.data.buyer_login;
  return (
    <p className="text-[14px] text-white/85">
      Pay as the sandbox buyer:{" "}
      {email && password ? (
        <>
          <span className="font-mono">{email}</span> / <span className="font-mono">{password}</span>
        </>
      ) : (
        "the login is in the submission's testing instructions."
      )}
    </p>
  );
}

function WakingNotice() {
  if (!useWaking()) return null;
  return (
    <p role="status" className="border-b border-line bg-accent-soft px-4 py-2 text-center text-[15px] text-accent-deep">
      <Loader2 size={15} className="mr-1.5 inline animate-spin" aria-hidden />
      The free demo server was asleep and is waking up. This takes about a minute; it will continue by itself.
    </p>
  );
}

export function SandboxBanner({ notice = true }: { notice?: boolean }) {
  return (
    <>
      <div className="bg-ink text-white">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-4 gap-y-0.5 px-4 py-2 text-[16px] sm:px-10">
          <span className="flex items-center gap-3">
            <FlaskConical size={18} aria-hidden />
            <span className="font-semibold">Sandbox only — no real money</span>
          </span>
          {notice && <span className="hidden text-white/80 lg:inline">PayPal sandbox test invoices</span>}
          <span className="sm:ml-auto">
            <BuyerLogin />
          </span>
        </div>
      </div>
      <WakingNotice />
    </>
  );
}

export function Wordmark({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="font-display text-[24px] leading-none text-ink">
      CreatorMilestone
    </Link>
  );
}

export function AppHeader({ projectId }: { projectId?: string | null }) {
  const link = ({ isActive }: { isActive: boolean }) =>
    cx("py-1 text-[16px]", isActive ? "font-semibold text-ink" : "text-muted hover:text-ink");
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-10">
        <Wordmark to={projectId ? `/projects/${projectId}` : "/"} />
        <nav aria-label="Main" className="flex flex-wrap items-center gap-x-6 gap-y-1">
          {projectId && (
            <>
              <NavLink end to={`/projects/${projectId}`} className={link}>
                Project
              </NavLink>
              <NavLink to={`/projects/${projectId}/intake`} className={link}>
                Intake
              </NavLink>
              <NavLink to={`/projects/${projectId}/messages/new`} className={link}>
                New message
              </NavLink>
            </>
          )}
          <NavLink to="/settings" className={link}>
            Settings
          </NavLink>
        </nav>
        <span className="ml-auto hidden items-center gap-2 text-muted sm:flex">
          <PenLine size={16} aria-hidden /> Jiwoo, seller
        </span>
      </div>
    </header>
  );
}

export function AppShell({ projectId, children }: { projectId?: string | null; children: ReactNode }) {
  return (
    <>
      <SandboxBanner />
      <AppHeader projectId={projectId} />
      <main className="mx-auto max-w-[1440px] px-4 pt-5 pb-16 sm:px-10">{children}</main>
    </>
  );
}

const ACTORS = {
  agent: { label: "Agent", icon: Sparkles, style: "bg-accent-soft text-accent-deep" },
  seller: { label: "Seller", icon: PenLine, style: "bg-neutral-soft text-neutral" },
  client: { label: "Client", icon: MessageSquare, style: "bg-neutral-soft text-neutral" },
  paypal: { label: "PayPal", icon: Landmark, style: "border border-line-strong bg-surface text-ink" },
  system: { label: "System", icon: Circle, style: "bg-neutral-soft text-neutral" },
} as const;

export function ActorTag({ actor }: { actor: keyof typeof ACTORS }) {
  const { label, icon: Icon, style } = ACTORS[actor];
  return (
    <span
      className={cx(
        "inline-flex w-[84px] shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[14px] leading-tight font-semibold",
        style,
      )}
    >
      <Icon size={15} aria-hidden /> {label}
    </span>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("font-mono font-medium", className)}>{children}</span>;
}

function retryHint(seconds: number): string {
  if (seconds < 90) return `about ${Math.max(5, Math.round(seconds / 5) * 5)} seconds`;
  if (seconds < 5400) return `about ${Math.round(seconds / 60)} minutes`;
  return `about ${Math.round(seconds / 3600)} hours`;
}

/** What the person should read for a failed call: the real limit, wait time, or service state. */
export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : "Something went wrong. Try again.";
  }
  const wait = Number(error.details?.retry_after_seconds);
  if (error.status === 429) {
    return `${error.message} This is a demo rate limit, not a failure. Nothing was changed${wait > 0 ? `; try again in ${retryHint(wait)}` : ""}.`;
  }
  if (error.code === "LLM_UNAVAILABLE" || (error.status === 503 && /AI service/i.test(error.message))) {
    return "The AI service is busy or unavailable right now. Nothing was changed. Wait a minute and try again.";
  }
  return error.message;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="flex items-start gap-2 text-[14px] font-semibold text-danger">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden /> {describeError(error)}
    </p>
  );
}

/** Live length against the server's limit. Shown instead of silently cutting pasted text. */
export function CharCount({ length, limit }: { length: number; limit: number }) {
  const over = length > limit;
  return (
    <p className={cx("text-[14px]", over ? "font-semibold text-danger" : "text-muted")} role={over ? "alert" : undefined}>
      {over
        ? `Too long: ${length.toLocaleString()} of ${limit.toLocaleString()} characters. Shorten it by ${(length - limit).toLocaleString()}.`
        : `${length.toLocaleString()} of ${limit.toLocaleString()} characters`}
    </p>
  );
}

/**
 * Staged progress for a slow AI call. Stages follow what the server does in order; they are
 * not a measured percentage, so none is shown.
 */
export function AiProgress({ active, stages, task }: { active: boolean; stages: string[]; task: string }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) {
      setSeconds(0);
      return;
    }
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [active]);
  if (!active) return null;
  // Move on every 6 s, and stay on the last stage rather than pretend to finish.
  const current = Math.min(stages.length - 1, Math.floor(seconds / 6));
  return (
    <div role="status" aria-live="polite" className="mt-3 rounded-[10px] border border-line bg-paper-deep p-4 text-[15px]">
      <p className="font-semibold">{task}</p>
      <ol className="mt-2 space-y-1">
        {stages.map((stage, i) => (
          <li key={stage} className={cx("flex items-center gap-2", i > current && "text-muted")}>
            {i < current ? (
              <Check size={15} className="text-success" aria-hidden />
            ) : i === current ? (
              <Loader2 size={15} className="animate-spin text-accent" aria-hidden />
            ) : (
              <span aria-hidden className="size-[15px] rounded-full border border-line-strong" />
            )}
            {stage}
          </li>
        ))}
      </ol>
      <p className="mt-2 text-muted">
        {seconds >= 12
          ? "The AI service is taking longer than usual. This can take up to a minute. Nothing has been saved yet."
          : "If the AI service is busy this can take up to a minute."}{" "}
        <span className="font-mono">{seconds}s</span>
      </p>
    </div>
  );
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="font-display text-[34px] leading-tight sm:text-[44px]">{title}</h1>
      {children && <p className="mt-1 text-[16px] text-muted">{children}</p>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="flex items-center gap-2 py-16 text-muted">
      <Loader2 size={18} className="animate-spin" aria-hidden /> {label}
    </p>
  );
}

/** Original scope plus change orders, so a stage's percentage is never read against the grown total. */
export function TotalBreakdown({
  base,
  changeOrders,
  currency,
  className,
}: {
  base: number;
  changeOrders: number;
  currency: string;
  className?: string;
}) {
  if (changeOrders <= 0) return null;
  const money = (n: number) => formatMoney(n, currency);
  return (
    <dl className={cx("rounded-[10px] bg-paper-deep px-4 py-3 text-[15px]", className)}>
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Original scope (the percentages apply to this)</dt>
        <dd><Mono>{money(base)}</Mono></dd>
      </div>
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Change orders</dt>
        <dd><Mono>+ {money(changeOrders)}</Mono></dd>
      </div>
      <div className="mt-1 flex justify-between gap-4 border-t-2 border-ink pt-1 font-semibold">
        <dt>Total</dt>
        <dd><Mono>{money(base + changeOrders)}</Mono></dd>
      </div>
    </dl>
  );
}

export const CheckIcon = Check;
