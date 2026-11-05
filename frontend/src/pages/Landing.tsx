import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AlertTriangle, ArrowRight, Check, Pencil, Sparkles, X } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { Button, Chip, ErrorNote, Mono, SandboxBanner, Wordmark } from "../components/ui";
import { api } from "../lib/api";
import { lastProjectId } from "../lib/hooks";

function HeroCard() {
  return (
    <div
      aria-hidden
      className="rounded-[14px] border-2 border-accent bg-surface p-5 shadow-[0_12px_32px_rgba(37,99,235,0.12)] sm:p-7"
    >
      <p className="flex items-center gap-1.5 text-[14px] font-semibold text-accent-deep">
        <Sparkles size={15} /> Agent proposes · Scope Guard
      </p>
      <div className="mt-1 flex items-baseline justify-between gap-4">
        <p className="font-display text-[28px]">Change order #1</p>
        <Mono className="text-[36px]">$100.00</Mono>
      </div>
      <ul className="mt-4 divide-y divide-line border-t border-line">
        {[
          ["“a second outfit”", <Chip key="a" tone="warn" icon="help">Out of scope</Chip>, "$80.00"],
          ["“one more pass on the face”", <Chip key="b" tone="warn" icon="alert">Exceeds limit: 2/2 used</Chip>, "$20.00"],
          ["“I might use it on merch”", <Chip key="c" icon="help">Question, not billed</Chip>, "Not billed"],
        ].map(([quote, chip, amount], i) => (
          <li key={i} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3">
            <span className="font-display text-[17px] italic">{quote}</span>
            <span className="flex items-center gap-4">
              {chip}
              <Mono className="text-[15px]">{amount}</Mono>
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-3 border-t border-line pt-4">
        <span className="inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-3 font-semibold text-white">
          <Check size={18} /> Approve
        </span>
        <span className="inline-flex items-center gap-2 rounded-lg border border-line-strong px-5 py-3 font-semibold">
          <Pencil size={17} /> Edit
        </span>
        <span className="inline-flex items-center gap-2 px-3 py-3 font-semibold text-muted">
          <X size={17} /> Dismiss
        </span>
      </div>
    </div>
  );
}

function Step({ n, title, children, sample }: { n: number; title: string; children: string; sample: React.ReactNode }) {
  return (
    <li>
      <h3 className="flex items-center gap-3 font-display text-[28px]">
        <span aria-hidden className="flex size-9 items-center justify-center rounded-full bg-ink font-sans text-[16px] font-semibold text-white">
          {n}
        </span>
        {title}
      </h3>
      <p className="mt-3 text-[17px] text-muted">{children}</p>
      <div className="mt-5 rounded-[10px] border border-line bg-surface p-4">{sample}</div>
    </li>
  );
}

export function Landing() {
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const status = useQuery({ queryKey: ["demoStatus"], queryFn: api.demoStatus, retry: 1 });
  const existing = status.data?.has_project ? status.data : null;
  const hasProgress = !!existing?.has_progress;
  // Start over wipes; "Try the demo" without progress only opens what is already there (or seeds one).
  const demo = useMutation({
    mutationFn: (mode: "open" | "reset") => (mode === "reset" ? api.demoReset() : api.demoSession()),
    onSuccess: (data) => {
      try {
        if (data.suggested_client_email) localStorage.setItem("suggestedEmail", data.suggested_client_email);
        else localStorage.removeItem("suggestedEmail");
      } catch {
        /* storage may be blocked; the seller types the email instead */
      }
      navigate(`/projects/${data.project.id}/intake`);
    },
  });
  const resume = lastProjectId();

  return (
    <>
      <SandboxBanner />
      <header className="mx-auto flex max-w-[1440px] items-center justify-between px-4 py-6 sm:px-16">
        <Wordmark />
        <p className="hidden text-muted sm:block">For commission artists with clients abroad</p>
      </header>
      <main>
        <section className="mx-auto grid max-w-[1440px] items-center gap-12 px-4 pt-6 pb-20 sm:px-16 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <h1 className="font-display text-[44px] leading-[1.05] sm:text-[68px]">
              Your AI back office for cross-border commission work.
            </h1>
            <p className="mt-8 max-w-[34em] text-[18px] text-muted">
              It turns messy client chats into agreed scope, guards that scope, and bills every stage through
              PayPal. Every money action waits for your approval.
            </p>
            {hasProgress && existing ? (
              <div className="mt-8">
                <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
                  <Link
                    to={`/projects/${existing.project_id}`}
                    className="inline-flex items-center gap-2 rounded-lg bg-accent px-8 py-4 text-[18px] leading-tight font-semibold text-white hover:bg-accent-deep"
                  >
                    Continue your project <ArrowRight size={18} aria-hidden />
                  </Link>
                  <Button variant="secondary" className="px-6 py-4" onClick={() => setConfirming((v) => !v)} aria-expanded={confirming}>
                    Start over
                  </Button>
                </div>
                <p className="mt-3 text-muted">
                  You have a demo project{existing.title ? ` (“${existing.title}”)` : ""} in progress. It stays as you left it.
                </p>
                {confirming && (
                  <div role="alertdialog" aria-label="Confirm start over" className="mt-4 max-w-[34em] rounded-[10px] border-2 border-warn bg-warn-soft p-4">
                    <p className="flex items-start gap-2 font-semibold text-warn">
                      <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden /> Start over erases this demo project
                    </p>
                    <p className="mt-2 text-[15px]">
                      Your scope, timeline, and proposals here are deleted and the project link stops working.
                      {existing.invoices_at_paypal > 0 &&
                        ` ${existing.invoices_at_paypal} invoice${existing.invoices_at_paypal === 1 ? " was" : "s were"} already created at PayPal${existing.invoices_paid > 0 ? ` (${existing.invoices_paid} paid)` : ""}. They stay in the PayPal sandbox and are not cancelled or refunded.`}
                      {existing.invoices_at_paypal === 0 && " No invoices have been created at PayPal for this project."}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-3">
                      <Button pending={demo.isPending} onClick={() => demo.mutate("reset")}>
                        Erase and start over
                      </Button>
                      <Button variant="ghost" onClick={() => setConfirming(false)}>
                        Keep my project
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-3">
                <Button className="px-8 py-4 text-[18px]" pending={demo.isPending} onClick={() => demo.mutate("open")}>
                  Try the demo
                </Button>
                <span className="text-muted">Opens a seeded project. No sign-up.</span>
              </div>
            )}
            {resume && !existing && (
              <p className="mt-4 text-[15px]">
                <Link to={`/projects/${resume}`} className="inline-flex items-center gap-1 font-semibold text-accent-deep underline">
                  Back to your last project <ArrowRight size={14} aria-hidden />
                </Link>
              </p>
            )}
            <div className="mt-3">
              <ErrorNote error={demo.error} />
            </div>
          </div>
          <HeroCard />
        </section>

        <section aria-label="How it works" className="bg-paper-deep py-8">
          <p className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-center gap-x-8 gap-y-2 px-4 font-display text-[28px] sm:text-[40px]">
            <span>AI proposes</span> <ArrowRight aria-hidden className="text-muted" />
            <span>You approve</span> <ArrowRight aria-hidden className="text-muted" />
            <span>PayPal executes</span>
          </p>
        </section>

        <section className="mx-auto max-w-[1440px] px-4 py-16 sm:px-16">
          <h2 className="font-display text-[40px] sm:text-[48px]">Agree → Bill → Guard</h2>
          <ol className="mt-8 grid gap-10 lg:grid-cols-3">
            <Step n={1} title="Agree" sample={
              <>
                <p className="font-display text-[17px] italic">“Maybe two rounds of revisions?”</p>
                <Chip tone="warn" icon="alert" className="mt-2">Needs confirmation</Chip>
              </>
            }>
              The agent reads the client's message, quotes its evidence, flags what is unclear, and drafts a reply in the client's language with a translation for you.
            </Step>
            <Step n={2} title="Bill" sample={
              <>
                <p className="flex justify-between font-semibold">Bill deposit <Mono>$90.00</Mono></p>
                <Chip tone="success" icon="check" className="mt-2">Paid via PayPal</Chip>
              </>
            }>
              When a stage is due, the agent proposes the PayPal invoice with the agreed terms inside. You approve, and status comes back from PayPal.
            </Step>
            <Step n={3} title="Guard" sample={
              <>
                <p className="flex justify-between font-semibold">One more pass on the face <Mono>$20.00</Mono></p>
                <Chip tone="warn" icon="alert" className="mt-2">Exceeds limit: 2/2 revisions used</Chip>
              </>
            }>
              When the client asks for more, the agent checks the agreement, cites the clause, prices extras from your rate card, and drafts a polite reply.
            </Step>
          </ol>
        </section>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1440px] flex-wrap justify-between gap-2 px-4 py-6 text-[15px] text-muted sm:px-16">
          <p>Not escrow, a marketplace, a payment guarantee, or a legal contract.</p>
          <p>PayPal AI Hackathon 2026 entry</p>
        </div>
      </footer>
    </>
  );
}
