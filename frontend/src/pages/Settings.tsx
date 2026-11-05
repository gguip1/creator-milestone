import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plug } from "lucide-react";
import { useEffect, useState } from "react";
import { AppShell, Button, Chip, ErrorNote, Loading, PageTitle } from "../components/ui";
import { api, type RateCardItem } from "../lib/api";
import { formatMoney, moneyInput, parseMoney } from "../lib/format";
import { lastProjectId } from "../lib/hooks";

type Draft = { code: string; name: string; price: string; unit: string; active: boolean };

export function SettingsPage() {
  const queryClient = useQueryClient();
  const card = useQuery({ queryKey: ["rate-card"], queryFn: api.rateCard });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, retry: false });
  const [rows, setRows] = useState<Draft[]>([]);
  const [saved, setSaved] = useState(false);
  const [add, setAdd] = useState({ name: "", price: "" });

  useEffect(() => {
    if (card.data) {
      setRows(card.data.items.map((i) => ({ code: i.code, name: i.name, price: moneyInput(i.unit_price_minor_units, card.data.currency_code), unit: i.unit, active: i.active })));
    }
  }, [card.data]);

  const bad = rows.some((r) => !r.name.trim() || !parseMoney(r.price));
  const save = useMutation({
    mutationFn: () =>
      api.putRateCard(
        rows.map<RateCardItem>((r) => ({ code: r.code, name: r.name.trim(), unit_price_minor_units: parseMoney(r.price)!, unit: r.unit, active: r.active })),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(["rate-card"], data);
      setSaved(true);
    },
  });

  const token = health.data?.paypal.token_ok;
  const input = "rounded-md border border-line-strong bg-fill px-3 py-2 text-[16px]";

  return (
    <AppShell projectId={lastProjectId()}>
      <PageTitle eyebrow="Workspace" title="Settings">Your rate card prices extras. PayPal is the only payment rail, and it runs in the sandbox.</PageTitle>
      <div className="grid gap-6 min-[1000px]:grid-cols-[3fr_2fr]">
        <section aria-labelledby="rate-h" className="rounded-lg border border-line p-6 sm:p-8">
          <h2 id="rate-h" className="eyebrow">Rate card</h2>
          <p className="mt-3 text-[15px] text-muted">Scope Guard prices every extra from this list. The AI never sets a price.</p>
          {card.isPending && <Loading />}
          <ul className="mt-4 divide-y divide-line border-y border-line">
            {rows.map((r, i) => (
              <li key={r.code} className="flex flex-wrap items-center gap-3 py-3">
                <label className="sr-only" htmlFor={`name-${r.code}`}>Item name</label>
                <input id={`name-${r.code}`} className={`${input} min-w-[10rem] flex-1`} value={r.name} onChange={(e) => { setSaved(false); setRows(rows.map((x, j) => (j === i ? { ...x, name: e.target.value } : x))); }} />
                <label className="sr-only" htmlFor={`price-${r.code}`}>Price for {r.name}</label>
                <input id={`price-${r.code}`} inputMode="decimal" className={`${input} w-28 text-right font-mono`} value={r.price} onChange={(e) => { setSaved(false); setRows(rows.map((x, j) => (j === i ? { ...x, price: e.target.value } : x))); }} />
                <label className="flex items-center gap-2 text-[15px]">
                  <input type="checkbox" className="size-5 accent-accent" checked={r.active} onChange={(e) => { setSaved(false); setRows(rows.map((x, j) => (j === i ? { ...x, active: e.target.checked } : x))); }} />
                  Active
                </label>
              </li>
            ))}
          </ul>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label className="text-[14px] font-medium">New item
              <input className={`${input} mt-1 block font-normal`} value={add.name} onChange={(e) => setAdd({ ...add, name: e.target.value })} placeholder="Name" />
            </label>
            <label className="text-[14px] font-medium">Price
              <input inputMode="decimal" className={`${input} mt-1 block w-28 text-right font-mono font-normal`} value={add.price} onChange={(e) => setAdd({ ...add, price: e.target.value })} placeholder="0.00" />
            </label>
            <Button
              variant="secondary"
              disabled={!add.name.trim() || !parseMoney(add.price)}
              onClick={() => {
                const code = add.name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || `item_${rows.length + 1}`;
                if (rows.some((r) => r.code === code)) return;
                setRows([...rows, { code, name: add.name.trim(), price: add.price, unit: "each", active: true }]);
                setAdd({ name: "", price: "" });
                setSaved(false);
              }}
            >
              Add item
            </Button>
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button pending={save.isPending} blocked={bad} onClick={() => save.mutate()} icon={<Check size={18} aria-hidden />}>Save rate card</Button>
            {saved && <Chip tone="success" icon="check">Saved</Chip>}
            {bad && <span className="text-[14px] font-medium text-warn">Every item needs a name and a price like 20.00.</span>}
          </div>
          <div className="mt-3"><ErrorNote error={save.error} /></div>
          {card.data && <p className="mt-3 text-[14px] text-muted">Currency: {card.data.currency_code}. Example: {formatMoney(2000, card.data.currency_code)}.</p>}
        </section>

        <section aria-labelledby="pp-h" className="self-start rounded-lg border border-line p-6 sm:p-8">
          <h2 id="pp-h" className="eyebrow">PayPal connection</h2>
          <p className="mt-3 text-[15px] text-muted">A connection check only. No keys or secrets are shown here.</p>
          <dl className="mt-4 divide-y divide-line border-y border-line text-[16px]">
            <div className="flex justify-between py-2.5"><dt className="text-muted">Environment</dt><dd>{health.data?.paypal.environment ?? "—"}</dd></div>
            <div className="flex justify-between py-2.5"><dt className="text-muted">Credentials</dt><dd>{health.data ? (health.data.paypal.configured ? "Configured" : "Not configured") : "—"}</dd></div>
            <div className="flex items-center justify-between py-2.5">
              <dt className="text-muted">Token check</dt>
              <dd>
                {health.isError ? <Chip tone="danger" icon="alert">Backend unreachable</Chip>
                  : token === true ? <Chip tone="success" icon="check">Connected</Chip>
                  : token === false ? <Chip tone="danger" icon="alert">PayPal did not accept the credentials</Chip>
                  : <Chip icon="help">Not checked</Chip>}
              </dd>
            </div>
          </dl>
          <div className="mt-4">
            <Button variant="secondary" pending={health.isFetching} icon={<Plug size={17} aria-hidden />} onClick={() => health.refetch()}>Check connection</Button>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
