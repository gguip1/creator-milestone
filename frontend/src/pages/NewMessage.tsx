import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Copy } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { EvidenceTable, type EvidenceRow } from "../components/evidence";
import { AiProgress, AppShell, Button, CharCount, Chip, ErrorNote, ExampleRow, Loading, NextCallout, PageTitle } from "../components/ui";
import { api, type FollowUp } from "../lib/api";
import { EXAMPLE_FOLLOW_UP } from "../lib/examples";
import { isOutfit } from "../lib/art";
import { copyText, useProject } from "../lib/hooks";

export function NewMessagePage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const project = useProject(id);
  const rateCard = useQuery({ queryKey: ["rate-card"], queryFn: api.rateCard });
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<FollowUp | null>(null);
  const [copied, setCopied] = useState(false);
  const check = useMutation({
    mutationFn: () => api.postMessage(id, message),
    onSuccess: (data) => {
      setResult(data);
      queryClient.setQueryData(["project", id], data.project);
    },
    onError: () => queryClient.invalidateQueries({ queryKey: ["project", id] }),
  });

  const clientLang = project.data?.source_language || "en";
  const langName = (() => {
    try {
      return new Intl.DisplayNames(["en"], { type: "language" }).of(clientLang) ?? clientLang;
    } catch {
      return clientLang;
    }
  })();
  const showTranslation =
    clientLang !== "ko" && result?.scope_guard.reply_draft_seller_translation.trim() !== result?.scope_guard.reply_draft_client.trim();
  const names = new Map(rateCard.data?.items.map((i) => [i.code, i.name]));
  const p = project.data;
  const rows: EvidenceRow[] =
    result?.scope_guard.items.map((item, i) => ({
      key: String(i),
      quote: item.quote,
      classification: item.classification,
      clauseRef: item.clause_ref,
      clauseText: item.clause_text,
      rate: item.rate_card_code ? `${names.get(item.rate_card_code) ?? item.rate_card_code}${item.billable ? ` × ${item.quantity}` : ": asked in the reply"}` : "No rate-card match",
      amount: item.billable ? item.amount_minor_units : null,
      needsPrice: item.billable && item.needs_price,
      outfitArt: item.billable && isOutfit(item.rate_card_code, item.quote),
    })) ?? [];

  return (
    <AppShell projectId={id}>
      <PageTitle eyebrow="Step 3 · Guard" title="Check a new client message">
        Paste what the client wrote. The agent compares it with the agreed scope and prices extras from your rate card.
      </PageTitle>
      {project.isPending && <Loading />}
      {result ? (
        result.change_order ? (
          <NextCallout title={`Review change order #${result.change_order.number}`} why="The agent's card is waiting on the project page. Approve it, then the client decides on their page.">
            <Link to={`/projects/${id}`} className="inline-flex items-center gap-2 rounded-md border border-accent bg-accent px-5 py-2.5 font-medium text-on-accent hover:bg-accent-deep">Go to the card</Link>
          </NextCallout>
        ) : (
          <NextCallout title="Nothing to bill" why="Every request was in scope or only a question, so no change order was created. You can copy the reply draft below." />
        )
      ) : (
        <NextCallout title="Paste the client's new message" why="Scope Guard compares each request with the agreed scope, cites the clause, and prices extras from your rate card. The example is message 2 from the demo." />
      )}
      {p && !["AGREED", "IN_PROGRESS"].includes(p.status) && (
        <p role="status" className="mb-6 rounded-lg border border-line p-4 text-muted">
          Scope Guard needs an agreed scope, and this one is <strong>{p.status.replace("_", " ").toLowerCase()}</strong>.{" "}
          <Link className="font-medium text-link underline" to={`/projects/${id}`}>Back to the project</Link>
        </p>
      )}
      <section aria-labelledby="new-msg-h" className="rounded-lg border border-line p-6 sm:p-8">
        <h2 id="new-msg-h" className="eyebrow">Client message</h2>
        <label htmlFor="follow-up" className="sr-only">Client message</label>
        <textarea
          id="follow-up"
          rows={5}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Paste the client's new message here."
          className="quote mt-3 w-full rounded-md border border-line-strong bg-fill p-3 text-[15px]"
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button pending={check.isPending} disabled={!message.trim() || message.length > 5000} onClick={() => check.mutate()}>
            Check against scope
          </Button>
        </div>
        <ExampleRow className="mt-4" button="Use example message 2" onUse={() => setMessage(EXAMPLE_FOLLOW_UP)}>
          The demo client's follow-up after the sketch: a second outfit, one more pass on the face, and a merch question. It only fills the box; nothing is checked until you press the button.
        </ExampleRow>
        <div className="mt-2"><CharCount length={message.length} limit={5000} /></div>
        <AiProgress
          active={check.isPending}
          task="Checking the message against the agreed scope"
          stages={["Reading the message", "Comparing each request with the agreed scope", "Pricing extras from your rate card and drafting the reply"]}
        />
        <div className="mt-3"><ErrorNote error={check.error} /></div>
        <p className="mt-5 rounded-md bg-fill px-3 py-2.5 text-[14px] leading-5 text-muted">
          Do not paste personal data. Demo messages may be read by the AI provider.
        </p>
      </section>

      {result && (
        <>
          <section aria-labelledby="guard-h" className="mt-6 rounded-lg border border-line p-6 sm:p-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="guard-h" className="eyebrow">Scope Guard result</h2>
              {result.scope_guard.source === "cached" && <Chip icon="clock">Cached analysis</Chip>}
            </div>
            {result.scope_guard.source === "cached" && (
              <p className="mt-2 text-[14px] text-muted">The AI service is unavailable, so this is a saved result for the demo message.</p>
            )}
            <div className="mt-4">
              <EvidenceTable
                rows={rows}
                total={result.scope_guard.total_minor_units}
                currency={p?.currency_code ?? "USD"}
                totalLabel={result.change_order ? "Change order total" : "Billable total"}
                revisions={p ? { used: p.revisions_used, included: p.revisions_included } : undefined}
                footnote="Priced from your rate card. AI never sets a price."
              />
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              {result.change_order ? (
                <>
                  <Link to={`/projects/${id}`} className="inline-flex items-center gap-2 rounded-md bg-accent px-5 py-3 font-medium text-on-accent hover:bg-accent-deep">
                    Review change order #{result.change_order.number} <ArrowRight size={17} aria-hidden />
                  </Link>
                  <span className="text-muted">The agent's card is waiting on the project page.</span>
                </>
              ) : (
                <p className="text-muted">Nothing here is billable, so no change order was created.</p>
              )}
            </div>
          </section>

          <section aria-labelledby="draft-h" className="mt-6 rounded-lg border border-line p-6 sm:p-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="draft-h" className="eyebrow">Reply draft</h2>
              <Button variant="secondary" icon={<Copy size={17} aria-hidden />} onClick={async () => setCopied(await copyText(result.scope_guard.reply_draft_client))}>
                {copied ? "Copied" : "Copy reply"}
              </Button>
            </div>
            <div className={`mt-4 grid gap-6 ${showTranslation ? "min-[1000px]:grid-cols-2 min-[1000px]:divide-x min-[1000px]:divide-line" : ""}`}>
              <div lang={clientLang}>
                <p className="text-[14px] text-muted">{langName}: goes to the client{showTranslation ? "" : " (same language as yours, so no translation is needed)"}</p>
                <p className="mt-2 whitespace-pre-wrap leading-relaxed">{result.scope_guard.reply_draft_client}</p>
              </div>
              {showTranslation && (
                <div lang="ko" className="min-[1000px]:pl-6">
                  <p className="text-[14px] text-muted">한국어: Jiwoo's translation, not sent</p>
                  <p className="mt-2 whitespace-pre-wrap font-ko leading-[1.6]">{result.scope_guard.reply_draft_seller_translation}</p>
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </AppShell>
  );
}
