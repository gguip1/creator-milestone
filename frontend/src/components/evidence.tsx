import type { Classification } from "../lib/api";
import { formatMoney } from "../lib/format";
import { CLAUSE_LABEL, CLASSIFICATION } from "../lib/status";
import { Chip, cx, Mono } from "./ui";

export type EvidenceRow = {
  key: string;
  quote: string | null;
  classification: Classification | null;
  clauseRef: string | null;
  clauseText: string | null;
  rate: string;
  amount: number | null;
  needsPrice?: boolean;
};

export function verdictLabel(
  classification: Classification | null,
  clauseRef: string | null,
  revisions?: { used: number; included: number | null },
): string {
  if (!classification) return "Billable";
  const base = CLASSIFICATION[classification]?.label ?? classification;
  if (classification === "exceeds_limit" && clauseRef === "revisions" && revisions?.included != null) {
    return `${base}: ${revisions.used}/${revisions.included} revisions used`;
  }
  return base;
}

export function EvidenceTable({
  rows,
  total,
  currency,
  totalLabel = "Change order total",
  revisions,
  footnote,
}: {
  rows: EvidenceRow[];
  total: number;
  currency: string;
  totalLabel?: string;
  revisions?: { used: number; included: number | null };
  footnote?: string;
}) {
  return (
    <div>
      <div
        role="table"
        aria-label="What the client asked, checked against the agreement"
        className="text-[15px]"
      >
        <div
          role="row"
          className="hidden gap-4 border-b border-line pb-2 text-[14px] font-semibold text-ink md:grid md:grid-cols-[220px_1fr_144px_84px]"
        >
          <span role="columnheader">Client asked</span>
          <span role="columnheader">Verdict and agreement clause</span>
          <span role="columnheader">Rate card</span>
          <span role="columnheader" className="text-right">
            Amount
          </span>
        </div>
        {rows.map((row) => {
          const c = row.classification ? CLASSIFICATION[row.classification] : null;
          return (
            <div
              role="row"
              key={row.key}
              className="grid gap-x-4 gap-y-2 border-b border-line py-2.5 md:grid-cols-[220px_1fr_144px_84px]"
            >
              <p role="cell" className="font-display text-[17px] leading-snug text-ink italic">
                {row.quote ? `“${row.quote}”` : "—"}
              </p>
              <div role="cell" className="flex flex-col gap-1.5">
                {c && (
                  <Chip tone={c.tone} icon={c.icon}>
                    {verdictLabel(row.classification, row.clauseRef, revisions)}
                  </Chip>
                )}
                {row.clauseRef && row.clauseText && (
                  <span className="text-muted">
                    {CLAUSE_LABEL[row.clauseRef] ?? row.clauseRef}: {row.clauseText}
                  </span>
                )}
              </div>
              <span role="cell" className="text-ink">
                {row.rate}
              </span>
              <span role="cell" className={cx("md:text-right", row.amount === null && "text-muted")}>
                {row.amount === null ? (
                  row.needsPrice ? (
                    <span className="font-semibold text-warn">Needs a price</span>
                  ) : (
                    "Not billed"
                  )
                ) : (
                  <Mono>{formatMoney(row.amount, currency)}</Mono>
                )}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-0 flex flex-wrap items-baseline justify-between gap-2 border-t-2 border-ink pt-3">
        <p className="text-[14px] text-muted">{footnote}</p>
        <p className="flex items-baseline gap-3 font-semibold">
          {totalLabel} <Mono className="text-[20px]">{formatMoney(total, currency)}</Mono>
        </p>
      </div>
    </div>
  );
}
