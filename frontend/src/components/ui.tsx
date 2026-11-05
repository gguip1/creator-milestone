import {
  AlertTriangle,
  Banknote,
  Check,
  CheckCircle2,
  Circle,
  CircleHelp,
  Clock,
  FileText,
  Loader2,
  Lock,
  Send,
  Undo2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router";
import { api, ApiError } from "../lib/api";
import { formatMoney } from "../lib/format";
import { projectSteps } from "../lib/steps";
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
  neutral: "border-line-strong text-neutral",
  accent: "border-accent text-accent",
  success: "border-accent bg-accent-soft text-accent",
  warn: "border-warn/60 bg-warn-soft text-warn",
  danger: "border-danger/60 bg-danger-soft text-danger",
};

/** A pill, reserved for a real status. Always carries a text label and an icon, never color alone. */
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
        "inline-flex w-fit max-w-full items-center gap-1.5 rounded-full border px-3 py-[3px] text-[14px] leading-5 font-medium",
        TONES[tone],
        className,
      )}
    >
      {Icon ? <Icon size={14} aria-hidden className="shrink-0" /> : icon}
      <span>{children}</span>
    </span>
  );
}

/** Tracked uppercase label above a section. */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cx("eyebrow", className)}>{children}</p>;
}

/**
 * Thumbnail of the AI-generated sample art, shown where the commission's work is delivered.
 * Alt text says what it shows; the caption always says it is sample art.
 */
export function SampleArt({
  src,
  alt,
  className,
  compact,
}: {
  src: string;
  alt: string;
  className?: string;
  compact?: boolean;
}) {
  return (
    <figure className={cx(compact ? "flex items-end gap-2.5" : "w-[96px] shrink-0 sm:w-[112px]", className)}>
      <img
        src={src}
        alt={alt}
        width={480}
        height={640}
        loading="lazy"
        className={cx("aspect-[3/4] rounded-md border border-line object-cover", compact ? "w-[56px] shrink-0" : "w-full")}
      />
      <figcaption className={cx("text-[12px] leading-4 text-muted", !compact && "mt-1.5")}>Sample art (AI-generated)</figcaption>
    </figure>
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
    ? "border border-line bg-fill text-muted cursor-not-allowed"
    : variant === "primary"
      ? "border border-accent bg-accent text-on-accent hover:bg-accent-deep active:bg-accent-deep"
      : variant === "secondary"
        ? "border border-line-strong bg-transparent text-ink hover:bg-fill"
        : "border border-transparent bg-transparent text-muted hover:text-ink";
  return (
    <button
      type="button"
      {...rest}
      disabled={inert}
      aria-busy={pending || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md px-5 py-3 text-[16px] leading-tight font-medium transition-colors",
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

function JudgeNote() {
  const info = useQuery({ queryKey: ["demoInfo"], queryFn: api.demoInfo, staleTime: Infinity, retry: 2 });
  if (!info.data?.judge_mode) return null;
  return <p className="text-[14px] text-neutral">Paying the sandbox invoice: see the testing instructions in the submission.</p>;
}

function WakingNotice() {
  if (!useWaking()) return null;
  return (
    <p role="status" className="border-b border-line bg-fill px-4 py-2 text-center text-[15px] text-neutral">
      <Loader2 size={15} className="mr-1.5 inline animate-spin" aria-hidden />
      The free demo server was asleep and is waking up. This takes about a minute; it will continue by itself.
    </p>
  );
}

export function SandboxBanner({ notice = true }: { notice?: boolean }) {
  return (
    <>
      <div className="border-b border-line bg-fill">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-4 gap-y-0.5 px-4 py-2 text-[14px] sm:px-10">
          <span className="flex items-center gap-2.5">
            <span aria-hidden className="size-2 rounded-full bg-warn" />
            <span className="eyebrow !text-warn">Sandbox only</span>
            <span className="text-neutral">No real money moves</span>
          </span>
          {notice && <span className="hidden text-muted lg:inline">PayPal sandbox test invoices</span>}
          <span className="sm:ml-auto">
            <JudgeNote />
          </span>
        </div>
      </div>
      <WakingNotice />
    </>
  );
}

export function Wordmark({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="text-[18px] leading-none font-medium tracking-[-0.01em] text-ink">
      CreatorMilestone
    </Link>
  );
}

const STEP_ICON = { done: Check, current: null, todo: null, locked: Lock } as const;

/** The demo flow as numbered steps. Done, current, and locked are shown by icon and text, not color alone. */
function StepNav({ id }: { id: string }) {
  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.project(id) });
  const steps = projectSteps(id, project.data);
  return (
    <nav aria-label="Demo steps" className="border-t border-line">
      <ol className="mx-auto grid max-w-[1440px] grid-cols-2 gap-x-4 px-4 sm:grid-cols-4 sm:px-10">
        {steps.map((s) => {
          const Icon = STEP_ICON[s.state];
          const body = (
            <>
              <span
                aria-hidden
                className={cx(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border font-mono text-[12px]",
                  s.state === "done" && "border-accent bg-accent text-on-accent",
                  s.state === "current" && "border-accent text-accent",
                  s.state === "todo" && "border-line-strong text-muted",
                  s.state === "locked" && "border-line text-muted",
                )}
              >
                {Icon ? <Icon size={12} /> : s.n}
              </span>
              <span className="min-w-0">
                <span className={cx("block text-[14px] leading-5", s.state === "current" ? "text-ink" : s.state === "locked" ? "text-muted" : "text-neutral")}>
                  {s.label}
                </span>
                <span className="block text-[12px] leading-4 text-muted">
                  {s.state === "done" ? "Done" : s.state === "current" ? "Do this now" : s.state === "locked" ? "Locked until the earlier step" : "Available"}
                </span>
              </span>
            </>
          );
          const base = cx(
            "flex items-start gap-2.5 border-b-2 py-3",
            s.state === "current" ? "border-accent" : "border-transparent",
          );
          return (
            <li key={s.n}>
              {s.state === "locked" ? (
                <span className={cx(base, "cursor-not-allowed")} aria-disabled="true">{body}</span>
              ) : (
                <Link to={s.to} aria-current={s.state === "current" ? "step" : undefined} className={cx(base, "hover:bg-fill")}>{body}</Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function AppHeader({ projectId }: { projectId?: string | null }) {
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex max-w-[1440px] items-center gap-x-8 px-4 py-3 sm:px-10">
        <Wordmark to={projectId ? `/projects/${projectId}` : "/"} />
        <span className="ml-auto hidden text-[14px] text-muted sm:block">Jiwoo, seller</span>
        <Link to="/settings" className="text-[14px] text-muted underline decoration-line-strong underline-offset-4 hover:text-ink">
          Settings
        </Link>
      </div>
      {projectId && <StepNav id={projectId} />}
    </header>
  );
}

export function AppShell({ projectId, children }: { projectId?: string | null; children: ReactNode }) {
  return (
    <>
      <SandboxBanner />
      <AppHeader projectId={projectId} />
      <main className="mx-auto max-w-[1440px] px-4 pt-8 pb-16 sm:px-10">{children}</main>
    </>
  );
}

const ACTORS = {
  agent: { label: "Agent", style: "text-accent" },
  seller: { label: "Seller", style: "text-neutral" },
  client: { label: "Client", style: "text-neutral" },
  paypal: { label: "PayPal", style: "text-neutral" },
  system: { label: "System", style: "text-muted" },
} as const;

/** Plain label for who did something in the activity log. Text only; the agent's is the one in green. */
export function ActorTag({ actor }: { actor: keyof typeof ACTORS }) {
  const { label, style } = ACTORS[actor];
  return <span className={cx("w-[64px] shrink-0 pt-0.5 font-mono text-[13px] leading-5 uppercase", style)}>{label}</span>;
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("font-mono", className)}>{children}</span>;
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
    <p role="alert" className="flex items-start gap-2 text-[14px] leading-5 font-medium text-danger">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden /> {describeError(error)}
    </p>
  );
}

/** Live length against the server's limit. Shown instead of silently cutting pasted text. */
export function CharCount({ length, limit }: { length: number; limit: number }) {
  const over = length > limit;
  return (
    <p className={cx("text-[14px]", over ? "font-medium text-danger" : "text-muted")} role={over ? "alert" : undefined}>
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
    <div role="status" aria-live="polite" className="mt-3 rounded-lg border border-line bg-fill p-4 text-[15px]">
      <p className="font-medium">{task}</p>
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

/** What to do now and why, with the primary action beside it. One per screen. */
export function NextCallout({
  title,
  why,
  children,
  className,
}: {
  title: string;
  why: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section aria-label="Next step" className={cx("mb-8 flex flex-wrap items-center justify-between gap-x-8 gap-y-4 rounded-lg border border-line bg-fill px-5 py-4", className)}>
      <div className="min-w-0 max-w-[62ch]">
        <p className="eyebrow !text-accent">Next step</p>
        <p className="mt-1 text-[18px] leading-7 text-ink">{title}</p>
        <p className="mt-0.5 text-[15px] leading-6 text-muted">{why}</p>
      </div>
      {children && <div className="flex flex-wrap items-center gap-3">{children}</div>}
    </section>
  );
}

/** A labeled example the person can choose to fill in. It never submits anything. */
export function ExampleRow({
  children,
  button,
  onUse,
  className,
}: {
  children: ReactNode;
  button?: string;
  onUse?: () => void;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-md border border-dashed border-line-strong px-3 py-2.5", className)}>
      <p className="min-w-0 flex-1 basis-[16rem] text-[14px] leading-5 text-muted">
        <span className="eyebrow mr-2 !text-[12px] !tracking-[0.14em] !text-neutral">Example</span>
        {children}
      </p>
      {button && onUse && (
        <Button variant="secondary" className="px-3 py-1.5 text-[14px]" onClick={onUse}>
          {button}
        </Button>
      )}
    </div>
  );
}

export function PageTitle({ title, eyebrow, children }: { title: string; eyebrow?: string; children?: ReactNode }) {
  return (
    <div className="mb-8">
      {eyebrow && <Eyebrow className="mb-3">{eyebrow}</Eyebrow>}
      <h1 className="font-display text-[32px] sm:text-[36px] sm:leading-10">{title}</h1>
      {children && <p className="mt-3 max-w-[60ch] text-[16px] text-muted">{children}</p>}
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
    <dl className={cx("rounded-lg border border-line bg-fill px-4 py-3 text-[15px]", className)}>
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Original scope (the percentages apply to this)</dt>
        <dd><Mono className="text-[14px]">{money(base)}</Mono></dd>
      </div>
      <div className="flex justify-between gap-4">
        <dt className="text-muted">Change orders</dt>
        <dd><Mono>+ {money(changeOrders)}</Mono></dd>
      </div>
      <div className="mt-1 flex justify-between gap-4 border-t border-line-strong pt-1 font-medium">
        <dt>Total</dt>
        <dd><Mono>{money(base + changeOrders)}</Mono></dd>
      </div>
    </dl>
  );
}

export const CheckIcon = Check;
