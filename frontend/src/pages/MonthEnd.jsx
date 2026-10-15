import { useState } from "react";
import { Link } from "react-router-dom";
import { MonthPicker, PageHead, Status } from "../components/ui";
import { useFetch } from "../lib/hooks";
import { longDate, pct, prettyCategory, qty, rupees, thisMonth } from "../lib/format";

export default function MonthEnd() {
  const [month, setMonth] = useState(thisMonth());
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const { data, loading, error, reload } = useFetch(`/audits-monthly?month=${month}`);
  const rows = (data?.rows || []).filter((r) => !onlyFlagged || r.flagged);
  let last = null;
  return (
    <>
      <PageHead
        title="Month-end summary"
        intro="The whole month in one view, like the old MonthlyAuditSheet: opening stock at the start of the month, every purchase and issue, against the month-end count. Variance % is against expected stock."
      >
        <MonthPicker value={month} onChange={setMonth} />
      </PageHead>
      <Status loading={loading && !data} error={error} onRetry={reload} />
      {data && !data.month_end_audit && (
        <div className="panel empty">
          No month-end audit for this month yet. <Link to="/audits">Start one</Link> after closing the month's other audits.
        </div>
      )}
      {data?.month_end_audit && (
        <div className="stack">
          {data.month_end_audit.status !== "closed" && <div className="note note-warn">The month-end audit is still open, so these numbers can change.</div>}
          <div className="kpis">
            <div className="kpi"><div className="kpi-label">Opening from</div><div className="kpi-value" style={{ fontSize: "var(--fs-lg)" }}>{data.opening_from ? longDate(data.opening_from) : "No earlier audit"}</div></div>
            <div className="kpi"><div className="kpi-label">Counted on</div><div className="kpi-value" style={{ fontSize: "var(--fs-lg)" }}><Link to={`/audits/${data.month_end_audit.id}`}>{longDate(data.month_end_audit.date)}</Link></div></div>
            <div className="kpi"><div className="kpi-label">Over threshold</div><div className={`kpi-value ${data.summary.items_flagged ? "neg" : ""}`}>{data.summary.items_flagged}</div></div>
            <div className="kpi"><div className="kpi-label">Net variance</div><div className="kpi-value">{rupees(data.summary.net_variance_value)}</div></div>
            <div className="kpi"><div className="kpi-label">Closing stock value</div><div className="kpi-value">{rupees(data.summary.closing_stock_value)}</div></div>
          </div>
          <div className="panel">
            <div className="panel-head">
              <h2>{rows.length} items</h2>
              <label className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} /> Only items over threshold
              </label>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Item</th><th>Unit</th><th className="num">Opening</th><th className="num">Purchased</th><th className="num">Available</th><th className="num">Issued</th><th className="num">Expected</th><th className="num">Counted</th><th className="num">Variance</th><th className="num">%</th><th className="num">Cost / unit</th><th className="num">Value</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const head = r.category !== last;
                    last = r.category;
                    return [
                      head && <tr className="group" key={`g-${r.category}`}><td colSpan={12}>{prettyCategory(r.category)}</td></tr>,
                      <tr key={r.item_id} className={r.flagged ? "flag" : ""}>
                        <td>{r.name}</td><td className="muted">{r.unit}</td>
                        <td className="num">{qty(r.opening)}</td><td className="num">{qty(r.purchased)}</td><td className="num">{qty(r.total_available)}</td>
                        <td className="num">{qty(r.issued)}</td>
                        <td className="num"><b>{qty(r.ideal)}</b></td><td className="num">{qty(r.counted)}</td>
                        <td className={`num ${r.variance > 0 ? "neg" : ""}`}>{r.variance === null ? "" : qty(r.variance)}</td>
                        <td className="num">{pct(r.variance_pct)}</td>
                        <td className="num muted">{rupees(r.unit_cost, true)}</td>
                        <td className={`num ${r.variance_value > 0 ? "neg" : ""}`}>{r.variance_value === null ? "" : rupees(r.variance_value, true)}</td>
                      </tr>,
                    ];
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
