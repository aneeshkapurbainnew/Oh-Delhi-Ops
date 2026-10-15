import { useMemo, useState } from "react";
import { PageHead, Seg, Status } from "../components/ui";
import { useFetch } from "../lib/hooks";
import { dayLabel, prettyCategory, qty } from "../lib/format";

const STATUS = {
  order_now: ["Below minimum", "pill-chili"],
  order: ["Below par", "pill-turmeric"],
  ok: ["OK", "pill-green"],
  no_usage: ["No usage last month", "pill-grey"],
};

export default function Stock() {
  const { data, loading, error, reload } = useFetch("/stock/levels");
  const [view, setView] = useState("order");
  const [q, setQ] = useState("");
  const rows = useMemo(
    () =>
      (data || []).filter((r) => {
        if (q && !r.name.toLowerCase().includes(q.toLowerCase())) return false;
        if (view === "order") return r.status === "order_now" || r.status === "order";
        if (view === "used") return r.status !== "no_usage";
        return true;
      }),
    [data, view, q]
  );
  const lastAudit = data?.find((r) => r.last_audit_date)?.last_audit_date;
  let last = null;
  return (
    <>
      <PageHead
        title="Stock and ordering"
        intro="Current stock = last audit + purchases − issues since then. Minimum = last month's usage ÷ 4 × 1.25; par = ÷ 4 × 1.5. Suggested order tops up to par."
      >
        <Seg options={[["order", "Needs ordering"], ["used", "Items in use"], ["all", "All items"]]} value={view} onChange={setView} />
        <input className="search" placeholder="Search items" value={q} onChange={(e) => setQ(e.target.value)} />
      </PageHead>
      {data && !lastAudit && <div className="note note-warn" style={{ marginBottom: 12 }}>No audit yet, so stock is estimated from zero. Do an opening count first.</div>}
      <div className="panel">
        <Status loading={loading && !data} error={error} onRetry={reload} />
        {data && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Item</th><th>Status</th><th className="num">Stock now</th><th className="num">Minimum</th><th className="num">Par</th><th className="num">Last month used</th><th className="num">Suggested order</th><th className="num">In purchase units</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const head = r.category !== last;
                  last = r.category;
                  const [label, pill] = STATUS[r.status];
                  return [
                    head && <tr className="group" key={`g-${r.category}`}><td colSpan={8}>{prettyCategory(r.category)}</td></tr>,
                    <tr key={r.item_id}>
                      <td>{r.name}</td>
                      <td><span className={`pill ${pill}`}>{label}</span></td>
                      <td className={`num ${r.estimated_stock < 0 ? "neg" : ""}`}>{qty(r.estimated_stock)} <span className="muted xs">{r.unit}</span></td>
                      <td className="num">{qty(r.min_stock)}</td>
                      <td className="num">{qty(r.par_stock)}</td>
                      <td className="num">{qty(r.last_month_usage)}</td>
                      <td className="num"><b>{r.suggested_qty ? `${qty(r.suggested_qty)} ${r.unit}` : ""}</b></td>
                      <td className="num">{r.suggested_purchase_qty ? `${r.suggested_purchase_qty} ${r.purchase_unit}` : ""}</td>
                    </tr>,
                  ];
                })}
              </tbody>
            </table>
            {rows.length === 0 && <div className="empty">{view === "order" ? "Nothing needs ordering right now." : "No items match."}</div>}
          </div>
        )}
      </div>
      {lastAudit && <p className="muted xs">Based on the audit of {dayLabel(lastAudit)}. Negative stock means issues were recorded without a matching purchase.</p>}
    </>
  );
}
