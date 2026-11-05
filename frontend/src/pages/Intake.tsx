import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Languages, Lock, Shield, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { Marker, ProvChip, provKind, provMark, type ProvKind } from "../components/provenance";
import { AiProgress, AppShell, Button, CharCount, Chip, cx, ErrorNote, Loading, Mono, PageTitle } from "../components/ui";
import { api, ApiError, type ExtractedField, type IntakeAnalysis, type MilestonePlanEntry, type Project } from "../lib/api";
import { EXAMPLE_INTAKE } from "../lib/examples";
import { formatDate, formatMoney, moneyInput, parseMoney } from "../lib/format";
import { copyText, useProject } from "../lib/hooks";
import { MissingProject } from "./Project";

/** English name of an ISO 639-1 label from the analysis, never assumed to be English. */
function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** A firm term the client stated outright can fill the form; anything else stays the seller's choice. */
function firmValue(field: ExtractedField): string | null {
  return field.value && field.provenance === "explicit" && !field.needs_confirmation ? field.value : null;
}

const MAX_MESSAGE = 5000; // Same limit as the server; the server answers with it if this drifts.

type Row = { key: string; label: string; field?: ExtractedField; text: string; note?: string; kind: ProvKind };

function joinValues(fields: ExtractedField[]): string {
  return fields.map((f) => f.value).filter(Boolean).join(", ");
}

function buildRows(a: IntakeAnalysis): Row[] {
  const rows: Row[] = [];
  const add = (key: string, label: string, field: ExtractedField | undefined, value: string, opts?: { showValue?: boolean; note?: string }) => {
    const kind = provKind(field);
    let text: string;
    let note: string | undefined = opts?.note;
    if (kind === "unknown") {
      text = `${label}: unknown`;
      note = note ?? "Not in the message.";
    } else if (kind === "needs" && !opts?.showValue) {
      text = `${label}: not confirmed`;
      note = `“${field?.quote}” is a guess, not an agreement. You choose.`;
    } else {
      text = `${label}: ${value}`;
      if (kind === "needs") note = `Read from “${field?.quote}”. The reply asks the client to confirm.`;
    }
    rows.push({ key, label, field, text, note, kind });
  };
  add("title", "Title", a.title, a.title.value ?? "");
  add("deliverables", "Deliverables", a.deliverables.find((d) => d.value) ?? a.deliverables[0], joinValues(a.deliverables));
  add("file_formats", "File formats", a.file_formats.find((d) => d.value) ?? a.file_formats[0], joinValues(a.file_formats));
  add("deadline", "Deadline", a.deadline, a.deadline.value && /^\d{4}-\d{2}-\d{2}$/.test(a.deadline.value) ? formatDate(a.deadline.value) : (a.deadline.value ?? ""), { showValue: true });
  add("sketch", "Sketch review", a.sketch_review_requested, a.sketch_review_requested.value === "yes" ? "Before coloring" : (a.sketch_review_requested.value ?? ""));
  add("budget", "Budget", a.budget, a.budget.value ?? "");
  add("revisions", "Revisions", a.revisions, a.revisions.value ?? "");
  add("usage", "Usage rights", a.usage_rights, a.usage_rights.value ?? "", {
    note: a.usage_rights.value ? undefined : "The message does not say how the art will be used. Usage is never guessed from context.",
  });
  add("email", "Client email", a.client_email, a.client_email.value ?? "", { note: a.client_email.value ? undefined : "Not in the message. Needed before any invoice." });
  return rows;
}

type Segment = { text: string; row?: Row; n?: number };

/** Splits the message around each row's verbatim quote so highlights wrap naturally. */
function segments(message: string, rows: Row[]): { parts: Segment[]; numbers: Map<string, number> } {
  const hits: { start: number; end: number; row: Row }[] = [];
  const lower = message.toLowerCase();
  for (const row of rows) {
    const quote = row.field?.quote?.trim();
    if (!quote) continue;
    const start = lower.indexOf(quote.toLowerCase());
    if (start < 0) continue;
    const end = start + quote.length;
    if (hits.some((h) => start < h.end && end > h.start)) continue;
    hits.push({ start, end, row });
  }
  hits.sort((x, y) => x.start - y.start);
  const numbers = new Map<string, number>();
  [...hits].sort((x, y) => rows.indexOf(x.row) - rows.indexOf(y.row)).forEach((h, i) => numbers.set(h.row.key, i + 1));
  const parts: Segment[] = [];
  let cursor = 0;
  for (const h of hits) {
    if (h.start > cursor) parts.push({ text: message.slice(cursor, h.start) });
    parts.push({ text: message.slice(h.start, h.end), row: h.row, n: numbers.get(h.row.key) });
    cursor = h.end;
  }
  if (cursor < message.length) parts.push({ text: message.slice(cursor) });
  return { parts, numbers };
}

type Form = {
  title: string;
  deliverables: string;
  fileFormats: string;
  deadline: string;
  revisions: string;
  usage: string;
  email: string;
  price: string;
  clientName: string;
};

const EMPTY: Form = { title: "", deliverables: "", fileFormats: "", deadline: "", revisions: "", usage: "", email: "", price: "", clientName: "" };

function suggestedEmail(): string {
  try {
    return localStorage.getItem("suggestedEmail") ?? "";
  } catch {
    return "";
  }
}

function formFromAnalysis(a: IntakeAnalysis, project: Project): Form {
  const deadline = a.deadline.value && /^\d{4}-\d{2}-\d{2}$/.test(a.deadline.value) ? a.deadline.value : "";
  return {
    title: a.title.value ?? project.title,
    deliverables: a.deliverables.map((d) => d.value).filter(Boolean).join("; "),
    fileFormats: a.file_formats.map((d) => d.value).filter(Boolean).join(", "),
    deadline,
    // Only a firm, quote-verified statement fills these; a hedge ("maybe two") stays the seller's choice.
    revisions: /^\d+$/.test(firmValue(a.revisions) ?? "") ? firmValue(a.revisions)! : "",
    usage: firmValue(a.usage_rights) ?? "",
    email: a.client_email.value ?? project.client_email ?? suggestedEmail(),
    price: moneyInput(a.budget_minor_units, a.currency_code ?? "USD"),
    clientName: project.client_display_name,
  };
}

function formFromProject(p: Project): Form {
  return {
    title: p.title,
    deliverables: p.deliverables.join("; "),
    fileFormats: p.file_formats.join(", "),
    deadline: p.deadline_date ?? "",
    revisions: p.revisions_included === null ? "" : String(p.revisions_included),
    usage: p.usage_rights,
    email: p.client_email ?? "",
    price: moneyInput(p.total_minor_units, p.currency_code),
    clientName: p.client_display_name,
  };
}

const list = (text: string, sep: RegExp) => text.split(sep).map((s) => s.trim()).filter(Boolean);

function bpFromPercent(text: string): number | null {
  const m = /^\s*(\d{1,3})(?:\.(\d))?\s*%?\s*$/.exec(text);
  return m ? Number(m[1]) * 100 + Number(m[2] ?? "0") * 10 : null;
}

export function IntakePage() {
  const { id = "" } = useParams();
  const query = useProject(id);
  return (
    <AppShell projectId={id}>
      {query.isPending && <Loading label="Loading project…" />}
      {query.isError && query.error instanceof ApiError && query.error.status === 404 ? (
        <MissingProject />
      ) : (
        query.isError && <ErrorNote error={query.error} />
      )}
      {query.data && <IntakeView project={query.data} />}
    </AppShell>
  );
}

function IntakeView({ project }: { project: Project }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const stored = project.messages.find((m) => m.kind === "intake");
  const storedAnalysis = (stored?.analysis ?? null) as IntakeAnalysis | null;
  const [message, setMessage] = useState(stored?.body ?? "");
  const [analysis, setAnalysis] = useState<IntakeAnalysis | null>(storedAnalysis);
  const [analyzedText, setAnalyzedText] = useState(stored?.body ?? "");
  const [form, setForm] = useState<Form>(() => (stored ? formFromProject(project) : EMPTY));
  const [plan, setPlan] = useState(() =>
    project.milestones.filter((m) => m.kind === "plan").map((m) => ({ title: m.title, pct: String((m.percentage_basis_points ?? 0) / 100), trigger: m.billing_trigger as MilestonePlanEntry["billing_trigger"], amount: m.amount_minor_units })),
  );
  const [copied, setCopied] = useState(false);
  const locked = project.status !== "DRAFT" && project.status !== "AWAITING_ACCEPTANCE";

  useEffect(() => {
    // Keep the plan in step with the server after the price changes it.
    setPlan(project.milestones.filter((m) => m.kind === "plan").map((m) => ({ title: m.title, pct: String((m.percentage_basis_points ?? 0) / 100), trigger: m.billing_trigger as MilestonePlanEntry["billing_trigger"], amount: m.amount_minor_units })));
  }, [project.milestones]);

  const analyze = useMutation({
    mutationFn: () => api.analyze(message),
    onSuccess: (result) => {
      setAnalysis(result);
      setAnalyzedText(message);
      setForm(formFromAnalysis(result, project));
    },
  });

  const rows = useMemo(() => (analysis ? buildRows(analysis) : []), [analysis]);
  // Jiwoo reads Korean, so a Korean client's reply needs no second copy.
  const showTranslation =
    !!analysis && analysis.source_language !== "ko" && analysis.reply_draft_seller_translation.trim() !== analysis.reply_draft_client.trim();
  const seg = useMemo(() => (analysis ? segments(analyzedText, rows) : null), [analysis, analyzedText, rows]);

  const currency = project.currency_code;
  const priceMinor = parseMoney(form.price, currency);
  const pctSum = plan.reduce((s, m) => s + (bpFromPercent(m.pct) ?? 0), 0);
  const planOk = plan.length > 0 && pctSum === 10000 && plan.every((m) => bpFromPercent(m.pct));
  const missing: string[] = [];
  if (!form.title.trim()) missing.push("a title");
  if (list(form.deliverables, /;/).length === 0) missing.push("deliverables");
  if (!form.deadline) missing.push("a deadline");
  if (form.revisions.trim() === "" || !/^\d+$/.test(form.revisions.trim())) missing.push("revisions");
  if (!form.usage.trim()) missing.push("usage rights");
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim())) missing.push("the client email");
  if (!priceMinor) missing.push("a price");
  if (!planOk) missing.push("a plan that adds up to 100%");
  const blockedText = missing.length ? `Blocked: add ${missing.slice(0, -1).join(", ")}${missing.length > 1 ? " and " : ""}${missing.at(-1)}.` : "";

  const accept = useMutation({
    mutationFn: async () => {
      const intake = analysis && !stored ? { message: analyzedText, analysis } : undefined;
      let current = await api.patchProject(project.id, {
        title: form.title.trim(),
        deliverables: list(form.deliverables, /;/),
        file_formats: list(form.fileFormats, /,/),
        deadline_date: form.deadline,
        revisions_included: Number(form.revisions),
        usage_rights: form.usage.trim(),
        client_email: form.email.trim(),
        client_display_name: form.clientName.trim() || undefined,
        currency_code: currency,
        total_minor_units: priceMinor,
        source_language: analysis?.source_language,
        intake,
      });
      const entries: MilestonePlanEntry[] = plan.map((m) => ({ title: m.title, basis_points: bpFromPercent(m.pct)!, billing_trigger: m.trigger }));
      const same = current.milestones.filter((m) => m.kind === "plan").length === entries.length &&
        current.milestones.filter((m) => m.kind === "plan").every((m, i) => m.percentage_basis_points === entries[i].basis_points && m.title === entries[i].title);
      if (!same) current = await api.putMilestones(project.id, entries);
      return api.sellerAccept(project.id, current.scope_version);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(["project", project.id], updated);
      navigate(`/projects/${project.id}`);
    },
    onError: () => queryClient.invalidateQueries({ queryKey: ["project", project.id] }),
  });

  const set = (key: keyof Form) => (value: string) => setForm((f) => ({ ...f, [key]: value }));
  const analyzeError = analyze.error instanceof ApiError ? analyze.error : null;
  const kindOf = (key: string): ProvKind | undefined => rows.find((r) => r.key === key)?.kind;

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageTitle title="Review the client's request">
          Every field shows where it came from. If the message does not say it, the agent says so.
        </PageTitle>
        <div className="flex flex-wrap gap-2" aria-label="Legend">
          <ProvChip kind="explicit" />
          <ProvChip kind="inferred" />
          <ProvChip kind="needs" />
          <ProvChip kind="unknown" />
        </div>
      </div>

      <div className="grid gap-6 min-[1000px]:grid-cols-2">
        <section aria-labelledby="msg-h" className="rounded-2xl border border-line bg-surface p-6 sm:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="msg-h" className="font-display text-[28px]">Client message 1</h2>
            <Chip icon={<Languages size={15} aria-hidden />}>{analysis ? languageName(analysis.source_language) : "Paste to start"}, pasted by Jiwoo</Chip>
          </div>
          {seg && analysis ? (
            <p className="mt-5 text-[18px] leading-[2.1] whitespace-pre-wrap">
              {seg.parts.map((part, i) =>
                part.row ? (
                  <mark key={i} className={cx("rounded-md px-1.5 py-0.5", provMark(part.row.kind))}>
                    {part.text}
                    <Marker n={part.n!} />
                  </mark>
                ) : (
                  <span key={i}>{part.text}</span>
                ),
              )}
            </p>
          ) : (
            <>
              <label htmlFor="msg" className="sr-only">Client message</label>
              <textarea
                id="msg"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={9}
                placeholder="Paste the client's first message here."
                className="mt-4 w-full rounded-lg border border-line-strong bg-surface p-3 text-[17px] leading-relaxed"
              />
            </>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {analysis ? (
              <Button variant="secondary" disabled={!!stored || locked} onClick={() => { setAnalysis(null); setMessage(analyzedText); }}>
                Edit message
              </Button>
            ) : (
              <>
                <Button pending={analyze.isPending} disabled={!message.trim() || message.length > MAX_MESSAGE} icon={<Sparkles size={18} aria-hidden />} onClick={() => analyze.mutate()}>
                  Analyze
                </Button>
                <Button variant="secondary" onClick={() => setMessage(EXAMPLE_INTAKE)}>Paste example</Button>
              </>
            )}
          </div>
          {!analysis && <div className="mt-2"><CharCount length={message.length} limit={MAX_MESSAGE} /></div>}
          <AiProgress
            active={analyze.isPending}
            task="Analyzing the client's message"
            stages={["Reading the message", "Checking evidence for each term", "Drafting the clarifying reply"]}
          />
          {analyzeError && (
            <div className="mt-3 space-y-2">
              <ErrorNote error={analyzeError} />
              <p className="text-[14px] text-muted">Nothing was saved. You can try again, or fill the scope by hand below.</p>
            </div>
          )}
          <p className="mt-6 flex items-center gap-2 rounded-lg bg-paper-deep px-3 py-2.5 text-[14px] text-muted">
            <Shield size={15} aria-hidden className="shrink-0" /> Do not paste personal data. Demo messages may be read by the AI provider.
          </p>
        </section>

        <section aria-labelledby="found-h" className="rounded-2xl border border-line bg-surface p-6 sm:p-8">
          <h2 id="found-h" className="font-display text-[28px]">What the agent found</h2>
          {analysis?.source === "cached" && (
            <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[14px] text-muted">
              <Chip icon="clock">Cached analysis</Chip> The AI service is unavailable, so this is a saved result for the demo message.
            </p>
          )}
          {!analysis ? (
            <p className="mt-4 text-muted">
              Analyze the message and the agent lists every term it found, with the exact words it relied on.
            </p>
          ) : (
            <ol className="mt-4 border-t border-line">
              {rows.map((row) => (
                <li
                  key={row.key}
                  className={cx("flex items-start gap-3 border-b border-line px-1 py-3", (row.kind === "needs" || row.kind === "unknown") && "bg-warn-soft/70 px-3")}
                >
                  <span aria-hidden className="mt-0.5 flex size-[22px] shrink-0 items-center justify-center rounded-full bg-ink text-[13px] font-semibold text-white">
                    {seg?.numbers.get(row.key) ?? "–"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[16px] font-semibold">{row.text}</p>
                    {row.note && <p className="text-[14px] text-muted">{row.note}</p>}
                  </div>
                  <ProvChip kind={row.kind} className="shrink-0" />
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      {analysis && (
        <section aria-labelledby="reply-h" className="mt-6 rounded-2xl border border-line bg-surface p-6 sm:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="reply-h" className="flex items-center gap-2 font-display text-[28px]">
              <Sparkles size={20} className="text-accent" aria-hidden /> Clarifying reply draft
            </h2>
            <Button variant="secondary" icon={<Copy size={17} aria-hidden />} onClick={async () => setCopied(await copyText(analysis.reply_draft_client))}>
              {copied ? "Copied" : "Copy reply"}
            </Button>
          </div>
          <div className={cx("mt-4 grid gap-6", showTranslation && "min-[1000px]:grid-cols-2 min-[1000px]:divide-x min-[1000px]:divide-line")}>
            <div lang={analysis.source_language}>
              <p className="text-[14px] font-semibold text-muted">
                {languageName(analysis.source_language)}: goes to the client{showTranslation ? "" : " (same language as yours, so no translation is needed)"}
              </p>
              <p className={cx("mt-2 whitespace-pre-wrap text-[16px] leading-relaxed", analysis.source_language === "ko" && "font-ko leading-[1.6]")}>{analysis.reply_draft_client}</p>
            </div>
            {showTranslation && (
              <div lang="ko" className="min-[1000px]:pl-6">
                <p className="font-sans text-[14px] font-semibold text-muted">한국어: Jiwoo's translation, not sent</p>
                <p className="mt-2 whitespace-pre-wrap font-ko text-[16px] leading-[1.6]">{analysis.reply_draft_seller_translation}</p>
              </div>
            )}
          </div>
          {analysis.questions.length > 0 && (
            <ul className="mt-5 list-disc space-y-1 pl-5 text-[15px] text-muted">
              {analysis.questions.map((q) => <li key={q}>{q}</li>)}
            </ul>
          )}
        </section>
      )}

      <div className="mt-6 grid gap-6 min-[1000px]:grid-cols-2">
        <section aria-labelledby="scope-h" className="rounded-2xl border border-line bg-surface p-6 sm:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="scope-h" className="font-display text-[28px]">Scope, ready to edit</h2>
            <Chip icon="file">Scope v{project.scope_version}, draft</Chip>
          </div>
          <div className="mt-5 grid gap-x-4 gap-y-5 sm:grid-cols-2">
            <FormField className="sm:col-span-2" label="Title" kind={kindOf("title")} value={form.title} onChange={set("title")} />
            <FormField label="Deliverables" kind={kindOf("deliverables")} value={form.deliverables} onChange={set("deliverables")} hint="Separate with ;" />
            <FormField label="File formats" kind={kindOf("file_formats")} value={form.fileFormats} onChange={set("fileFormats")} hint="Separate with ," />
            <FormField label="Deadline" type="date" kind={kindOf("deadline")} value={form.deadline} onChange={set("deadline")} />
            <FormField label="Revisions included" kind={kindOf("revisions")} required value={form.revisions} onChange={set("revisions")} placeholder="Choose a number" inputMode="numeric" />
            <FormField label="Usage rights" kind={kindOf("usage")} required value={form.usage} onChange={set("usage")} placeholder="Choose usage" list="usage-options" />
            <datalist id="usage-options">
              <option value="Personal streaming" />
              <option value="Personal use only" />
              <option value="Commercial use" />
            </datalist>
            <FormField label="Client email" kind={kindOf("email")} required value={form.email} onChange={set("email")} placeholder="Required before billing" type="email" />
            <FormField label="Price" kind={kindOf("budget")} value={form.price} onChange={set("price")} inputMode="decimal" mono />
            <FormField label="Currency" value={currency} onChange={() => undefined} readOnly />
            <FormField className="sm:col-span-2" label="Client name (optional)" value={form.clientName} onChange={set("clientName")} />
          </div>
        </section>

        <section aria-labelledby="plan-h" className="self-start rounded-2xl border border-line bg-surface p-6 sm:p-8">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 id="plan-h" className="font-display text-[28px]">
              Milestone plan: {plan.map((m) => m.pct).join(" / ")}
            </h2>
            <p className="font-semibold">Total <Mono>{formatMoney(priceMinor ?? project.total_minor_units, currency)}</Mono></p>
          </div>
          <div aria-hidden className="mt-4 flex h-14 overflow-hidden rounded-lg text-[14px]">
            {plan.map((m, i) => (
              <div key={i} style={{ flexGrow: bpFromPercent(m.pct) ?? 0 }} className={cx("flex items-center justify-center gap-2 border-r-2 border-paper font-mono", ["bg-[#E2DACB]", "bg-[#D5CBB8]", "bg-[#C4B8A0]"][i % 3])}>
                {m.pct}% <span className="hidden sm:inline">{formatMoney(previewAmount(priceMinor, m.pct, m.amount, planUnchanged(project, plan)), currency)}</span>
              </div>
            ))}
          </div>
          <ol className="mt-3">
            {plan.map((m, i) => (
              <li key={i} className="flex items-center justify-between gap-4 border-b border-line py-3">
                <div>
                  <p className="font-semibold"><span className="mr-2 text-muted">{i + 1}</span>{m.title}</p>
                  <p className="text-[14px] text-muted">{m.trigger === "ON_AGREEMENT" ? "Bills when both sides accept" : "Bills when the client approves the delivery"}</p>
                </div>
                <div className="flex items-center gap-4">
                  <label className="sr-only" htmlFor={`pct-${i}`}>{m.title} percent</label>
                  <input
                    id={`pct-${i}`}
                    value={m.pct}
                    inputMode="decimal"
                    onChange={(e) => setPlan(plan.map((x, j) => (j === i ? { ...x, pct: e.target.value.replace(/%/g, "") } : x)))}
                    className="w-16 rounded-lg border border-line-strong bg-surface px-2 py-1.5 text-center font-mono text-[15px]"
                  />
                  <Mono className="w-24 text-right">{formatMoney(previewAmount(priceMinor, m.pct, m.amount, planUnchanged(project, plan)), currency)}</Mono>
                </div>
              </li>
            ))}
          </ol>
          <p className={cx("mt-3 flex items-center gap-2 border-t-2 border-ink pt-3 font-semibold", planOk ? "text-success" : "text-warn")}>
            {planOk ? <Check size={16} aria-hidden /> : <Lock size={16} aria-hidden />}
            {planOk ? `Adds up to 100% and matches the ${formatMoney(priceMinor, currency)} price.` : `The plan adds up to ${pctSum / 100}%. It needs to be 100%.`}
          </p>
          <div className="mt-4">
            <Button
              block
              blocked={missing.length > 0 || locked}
              pending={accept.isPending}
              icon={<Check size={18} aria-hidden />}
              onClick={() => accept.mutate()}
            >
              {missing.length > 0 && <Lock size={17} aria-hidden />}
              Accept scope v{project.scope_version} and share with client
            </Button>
            {missing.length > 0 && <p className="mt-3 text-center text-[15px] font-semibold text-warn">{blockedText}</p>}
            {locked && <p className="mt-3 text-center text-[15px] text-muted">The scope is agreed. Changes now go through a change order.</p>}
            <div className="mt-3"><ErrorNote error={accept.error} /></div>
          </div>
        </section>
      </div>
    </>
  );
}

function planUnchanged(project: Project, plan: { pct: string }[]): boolean {
  const server = project.milestones.filter((m) => m.kind === "plan");
  return server.length === plan.length && server.every((m, i) => bpFromPercent(plan[i].pct) === m.percentage_basis_points);
}

/** Integer preview of a stage amount. The saved plan's amounts come from the server instead. */
function previewAmount(total: number | null, pct: string, serverAmount: number, unchangedPlan: boolean): number {
  const bp = bpFromPercent(pct);
  if (unchangedPlan && (total === null || total === undefined)) return serverAmount;
  if (!total || bp === null) return serverAmount;
  return Math.floor((total * bp) / 10000);
}

function FormField({
  label,
  value,
  onChange,
  kind,
  required,
  className,
  mono,
  ...rest
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  kind?: ProvKind;
  required?: boolean;
  className?: string;
  mono?: boolean;
  hint?: string;
  type?: string;
  placeholder?: string;
  inputMode?: "numeric" | "decimal";
  list?: string;
  readOnly?: boolean;
}) {
  const needs = required && !value.trim();
  const { hint, ...input } = rest;
  return (
    <div className={className}>
      <div className="flex items-center justify-between gap-2">
        <label className="font-semibold" htmlFor={`f-${label}`}>{label}</label>
        {kind && <ProvChip kind={kind} />}
      </div>
      <input
        id={`f-${label}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-required={required}
        {...input}
        className={cx(
          "mt-1.5 w-full rounded-lg border bg-surface px-3 py-3 text-[16px]",
          mono && "font-mono",
          needs ? "border-2 border-warn bg-warn-soft/40" : "border-line-strong",
          input.readOnly && "bg-paper-deep text-muted",
        )}
      />
      {hint && <p className="mt-1 text-[13px] text-muted">{hint}</p>}
    </div>
  );
}
