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
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, NavLink } from "react-router";
import type { IconName, Tone } from "../lib/status";

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

export function SandboxBanner({ notice = true }: { notice?: boolean }) {
  return (
    <div className="bg-ink text-white">
      <div className="mx-auto flex max-w-[1440px] items-center gap-3 px-4 py-2 text-[16px] sm:px-10">
        <FlaskConical size={18} aria-hidden />
        <span className="font-semibold">Sandbox only — no real money</span>
        {notice && <span className="hidden text-white/80 sm:inline">PayPal sandbox test invoices</span>}
      </div>
    </div>
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

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Something went wrong. Try again.";
  return (
    <p role="alert" className="flex items-start gap-2 text-[14px] font-semibold text-danger">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden /> {message}
    </p>
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

export const CheckIcon = Check;
