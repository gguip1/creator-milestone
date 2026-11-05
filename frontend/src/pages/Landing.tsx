import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AlertTriangle, ArrowRight, Check, Pencil, X } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { Button, Chip, ErrorNote, Eyebrow, Mono, SandboxBanner, Wordmark } from "../components/ui";
import { api } from "../lib/api";
import { lastProjectId } from "../lib/hooks";

function ExampleCard() {
  return (
    <div aria-hidden className="rounded-lg border-2 border-accent p-5 sm:p-6">
      <p className="eyebrow flex items-center gap-2 !text-accent">
        <span className="size-2 rounded-full bg-accent" /> Proposed by agent <span className="text-muted">/ Scope Guard</span>
      </p>
      <div className="mt-3 flex items-baseline justify-between gap-4">
        <p className="font-display text-[22px] leading-7">Change order #1</p>
        <Mono className="text-[24px]">$100.00</Mono>
      </div>
      <p className="mt-1 text-[14px] text-muted">The client asked for more after the sketch. Checked against the agreement.</p>
      <ul className="mt-4 divide-y divide-line border-t border-line">
        {[
          ["“a second outfit”", <Chip key="a" tone="warn" icon="help">Out of scope</Chip>, "$80.00"],
          ["“one more pass on the face”", <Chip key="b" tone="warn" icon="alert">Exceeds limit: 2/2 used</Chip>, "$20.00"],
          ["“I might use it on merch”", <Chip key="c" icon="help">Question, not billed</Chip>, "Not billed"],
        ].map(([quote, chip, amount], i) => (
          <li key={i} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
            <span className="quote">{quote}</span>
            <span className="flex items-center gap-4">
              {chip}
              <Mono className="text-[14px]">{amount}</Mono>
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-3 border-t border-line pt-4">
        <span className="inline-flex items-center gap-2 rounded-md bg-accent px-5 py-2.5 font-medium text-on-accent">
          <Check size={17} /> Approve
        </span>
        <span className="inline-flex items-center gap-2 rounded-md border border-line-strong px-5 py-2.5">
          <Pencil size={16} /> Edit
        </span>
        <span className="inline-flex items-center gap-2 px-3 py-2.5 text-muted">
          <X size={16} /> Dismiss
        </span>
      </div>
    </div>
  );
}

function Step({ n, title, children, sample }: { n: string; title: string; children: string; sample: React.ReactNode }) {
  return (
    <li className="flex flex-col">
      <p className="font-mono text-[14px] text-muted">{n}</p>
      <h3 className="mt-2 font-display text-[28px] leading-8">{title}</h3>
      <p className="mt-3 text-[16px] text-muted">{children}</p>
      <div className="mt-auto pt-6">
        <div className="rounded-lg border border-line bg-fill p-4">{sample}</div>
      </div>
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
      <header className="mx-auto flex max-w-[1440px] items-center justify-between px-4 py-5 sm:px-16">
        <Wordmark />
        <p className="hidden text-[14px] text-muted sm:block">PayPal AI Hackathon 2026 entry</p>
      </header>
      <main>
        <section className="mx-auto grid max-w-[1440px] items-start gap-12 px-4 pt-10 pb-20 sm:px-16 sm:pt-16 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
          <div>
            <Eyebrow>For commission artists with clients abroad</Eyebrow>
            <h1 className="font-display mt-5 text-[40px] sm:text-[60px] sm:leading-[60px]">
              One more change? Check it against what you agreed.
            </h1>
            <p className="mt-8 max-w-[34em] text-[17px] leading-7 text-muted">
              The AI checks the request against the scope you both agreed to, prices the extras from your rate card,
              and turns what you both approve into a PayPal invoice. Nothing is sent until you approve it.
            </p>
            {hasProgress && existing ? (
              <div className="mt-8">
                <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
                  <Link
                    to={`/projects/${existing.project_id}`}
                    className="inline-flex items-center gap-2 rounded-md bg-accent px-7 py-3.5 text-[16px] leading-tight font-medium text-on-accent hover:bg-accent-deep"
                  >
                    Continue your project <ArrowRight size={18} aria-hidden />
                  </Link>
                  <Button variant="secondary" className="px-6 py-3.5" onClick={() => setConfirming((v) => !v)} aria-expanded={confirming}>
                    Start over
                  </Button>
                </div>
                <p className="mt-3 text-muted">
                  You have a demo project{existing.title ? ` (“${existing.title}”)` : ""} in progress. It stays as you left it.
                </p>
                {confirming && (
                  <div role="alertdialog" aria-label="Confirm start over" className="mt-4 max-w-[34em] rounded-lg border border-warn bg-warn-soft p-4">
                    <p className="flex items-start gap-2 font-medium text-warn">
                      <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden /> Start over erases this demo project
                    </p>
                    <p className="mt-2 text-[15px]">
                      Your scope, timeline, and proposals here are deleted and the project link stops working.
                      {existing.invoices_at_paypal > 0 &&
                        ` ${existing.invoices_at_paypal} invoice${existing.invoices_at_paypal === 1 ? " was" : "s were"} already created at PayPal${existing.invoices_paid > 0 ? ` (${existing.invoices_paid} paid)` : ""}. They stay in the PayPal sandbox and are not cancelled or refunded.`}
                      {existing.invoices_at_paypal === 0 && " No invoices have been created at PayPal for this project."}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-3">
                      <Button variant="secondary" className="!border-warn !text-warn hover:!bg-warn-soft" pending={demo.isPending} onClick={() => demo.mutate("reset")}>
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
              <div className="mt-9 flex flex-wrap items-center gap-x-5 gap-y-3">
                <Button className="px-7 py-3.5" pending={demo.isPending} onClick={() => demo.mutate("open")}>
                  Try the demo
                </Button>
                <span className="text-[14px] text-muted">Opens a seeded sample project. No sign-up.</span>
              </div>
            )}
            {resume && !existing && (
              <p className="mt-4 text-[15px]">
                <Link to={`/projects/${resume}`} className="inline-flex items-center gap-1 text-link underline">
                  Back to your last project <ArrowRight size={14} aria-hidden />
                </Link>
              </p>
            )}
            <div className="mt-3">
              <ErrorNote error={demo.error} />
            </div>
          </div>
          <ExampleCard />
        </section>

        <section className="border-t border-line">
          <div className="mx-auto grid max-w-[1440px] gap-12 px-4 py-16 sm:px-16 lg:grid-cols-2 lg:gap-16">
            <div>
              <Eyebrow>Who it is for</Eyebrow>
              <p className="mt-4 max-w-[34em] text-[20px] leading-8 tracking-[-0.01em]">
                Illustrators and character artists who take commissions from clients in other countries and get
                paid by invoice.
              </p>
            </div>
            <div>
              <Eyebrow>The problem</Eyebrow>
              <p className="mt-4 max-w-[34em] text-[16px] text-muted">
                The terms live in a chat: “maybe two rounds of revisions”, “around the 25th”. Weeks later the
                client asks for a second outfit, and nobody remembers what was agreed. Billing gets sorted out by
                direct message, in a language one of you is translating.
              </p>
            </div>
          </div>
        </section>

        <section aria-labelledby="how-h" className="border-t border-line">
          <div className="mx-auto max-w-[1440px] px-4 py-16 sm:px-16">
            <Eyebrow>How it works</Eyebrow>
            <h2 id="how-h" className="font-display mt-4 text-[32px] sm:text-[36px] sm:leading-10">Agree → Bill → Guard</h2>
            <ol className="mt-10 grid gap-12 lg:grid-cols-3">
              <Step n="01" title="Agree" sample={
                <>
                  <p className="quote">“Maybe two rounds of revisions?”</p>
                  <Chip tone="warn" icon="alert" className="mt-3">Needs confirmation</Chip>
                </>
              }>
                The agent reads the client's message, quotes the words behind each term, flags what is unclear, and drafts a reply with a translation for you. Tested with English and Korean.
              </Step>
              <Step n="02" title="Bill" sample={
                <>
                  <p className="flex justify-between gap-3">Bill deposit <Mono className="text-[14px]">$90.00</Mono></p>
                  <Chip tone="success" icon="check" className="mt-3">Paid via PayPal</Chip>
                </>
              }>
                When a stage is due, rules propose a PayPal invoice with the agreed terms inside. You approve it, the backend sends it to PayPal, and the status comes back from PayPal.
              </Step>
              <Step n="03" title="Guard" sample={
                <>
                  <p className="flex justify-between gap-3">One more pass on the face <Mono className="text-[14px]">$20.00</Mono></p>
                  <Chip tone="warn" icon="alert" className="mt-3">Exceeds limit: 2/2 revisions used</Chip>
                </>
              }>
                When the client asks for more, the AI compares it with the agreement and cites a clause, code prices extras from your rate card, and you review before anything is billed.
              </Step>
            </ol>
          </div>
        </section>

        <section aria-labelledby="demo-h" className="border-t border-line">
          <div className="mx-auto max-w-[1440px] px-4 py-16 sm:px-16">
            <Eyebrow>The demo</Eyebrow>
            <h2 id="demo-h" className="font-display mt-4 max-w-[20em] text-[32px] sm:text-[36px] sm:leading-10">
              Walk through a sample commission, start to finish.
            </h2>
            <p className="mt-4 max-w-[40em] text-[16px] text-muted">
              You play the artist and the client. Paste the client's message, approve the scope, send a PayPal
              invoice, then paste a follow-up request and see what the agent bills for.
            </p>
            <p className="mt-6 max-w-[40em] rounded-lg border border-line bg-fill p-4 text-[15px] leading-6 text-neutral">
              <span className="eyebrow mr-2 !text-warn">Sandbox only</span>
              Invoices are created in the PayPal sandbox. No real money moves, and nothing here is escrow, a
              marketplace, or a payment guarantee.
            </p>
          </div>
        </section>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1440px] flex-wrap justify-between gap-2 px-4 py-6 text-[14px] text-muted sm:px-16">
          <p>Demo acceptance is a click: it does not verify identity or provide an e-signature.</p>
          <p>Demo artwork is AI-generated.</p>
        </div>
      </footer>
    </>
  );
}
