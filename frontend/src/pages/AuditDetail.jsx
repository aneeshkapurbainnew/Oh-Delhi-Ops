import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { NumCell, PageHead, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch, useUnsavedWarning } from "../lib/hooks";
import { longDate, pct, prettyCategory, qty, rupees } from "../lib/format";

const FILTERS = [
  ["all", "All items"],
  ["moved", "With stock or movement"],
  ["uncounted", "Not counted yet"],
  ["flagged", "Over threshold"],
];

export default function AuditDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data, setData, loading, error, reload } = useFetch(`/audits/${id}`);
  const [edits, setEdits] = useState({});
  const [filterChoice, setFilter] = useState(null);
  const filter = filterChoice ?? (data?.kind === "opening" ? "all" : "moved");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edits).length > 0;
  useUnsavedWarning(dirty);

  const rows = useMemo(() => {
    if (!data) return [];
    const s = q.toLowerCase();
    return data.rows.filter((r) => {
      if (s && !r.name.toLowerCase().includes(s)) return false;
      if (filter === "moved") return r.total_available !== 0 || r.issued !== 0 || r.counted !== null || r.item_id in edits;
      if (filter === "uncounted") return r.counted === null;
      if (filter === "flagged") return r.flagged;
      return true;
    });
  }, [data, filter, q, edits]);

  if (!data) return <Status loading={loading} error={error} onRetry={reload} />;
  const closed = data.status === "closed";
  const isOpening = data.kind === "opening";
  const maxVar = Math.max(1, ...data.rows.map((r) => Math.abs(r.variance_pct || 0)));

  const saveCounts = async () => {
    setBusy(true);
    try {
      const counts = Object.entries(edits).map(([item_id, counted_qty]) => ({ item_id: Number(item_id), counted_qty }));
      setData(await api.put(`/audits/${id}/counts`, { counts }));
      setEdits({});
      toast(`Saved ${counts.length} counts.`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const act = async (action) => {
    if (dirty) return toast("Save your counts first.", "error");
    try {
      if (action === "delete") {
        if (!window.confirm("Delete this audit and its counts?")) return;
        await api.del(`/audits/${id}`);
        nav("/audits");
        return;
      }
      await api.post(`/audits/${id}/${action}`);
      toast(action === "close" ? "Audit closed." : "Audit reopened.");
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  const s = data.summary;
  let last = null;
  return (
    <>
      <PageHead
        title={`${data.kind_label}: ${longDate(data.date)}`}
        intro={
          isOpening
            ? "Sets starting stock. Leave items you don't stock blank."
            : `Movements since ${data.previous_date ? longDate(data.previous_date) : "the start"}. Expected = opening + purchased − issued. Variance = expected − counted (positive = shortage); variance % is against expected, and rows over ${data.threshold_pct}% are flagged. Blank = not counted; its expected stock carries forward.`
        }
      >
        <Link to="/audits" className="btn btn-ghost">All audits</Link>
        {closed ? (
          <button onClick={() => act("reopen")}>Reopen</button>
        ) : (
          <>
            <button className="btn-danger" onClick={() => act("delete")}>Delete</button>
            <button className="btn-primary" disabled={!dirty || busy} onClick={saveCounts}>{busy ? "Saving…" : `Save counts${dirty ? ` (${Object.keys(edits).length})` : ""}`}</button>
            <button onClick={() => act("close")}>Close audit</button>
          </>
        )}
      </PageHead>

      {s && !isOpening && (
        <div className="kpis" style={{ marginBottom: 16 }}>
          <div className="kpi"><div className="kpi-label">Items counted</div><div className="kpi-value">{s.items_counted}</div></div>
          <div className="kpi"><div className="kpi-label">Over {data.threshold_pct}%</div><div className={`kpi-value ${s.items_flagged ? "neg" : ""}`}>{s.items_flagged}</div></div>
          <div className="kpi"><div className="kpi-label">Shortage</div><div className="kpi-value">{rupees(s.shortage_value)}</div></div>
          <div className="kpi"><div className="kpi-label">Excess</div><div className="kpi-value">{rupees(s.excess_value)}</div></div>
          <div className="kpi"><div className="kpi-label">Closing stock value</div><div className="kpi-value">{rupees(s.closing_stock_value)}</div></div>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <div className="seg">
            {FILTERS.map(([k, l]) => <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>)}
          </div>
          <input className="search" placeholder="Search items" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th><th>Unit</th>
                {!isOpening && <><th className="num">Opening</th><th className="num">Purchased</th><th className="num">Issued</th><th className="num">Expected</th></>}
                <th className="num" style={{ width: 120 }}>Counted</th>
                {!isOpening && <><th className="num">Variance</th><th className="num">Variance %</th><th className="num">Value</th></>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const head = r.category !== last;
                last = r.category;
                const counted = r.item_id in edits ? edits[r.item_id] : r.counted;
                return [
                  head && <tr className="group" key={`g-${r.category}`}><td colSpan={12}>{prettyCategory(r.category)}</td></tr>,
                  <tr key={r.item_id} className={r.flagged ? "flag" : ""}>
                    <td>{r.name}</td>
                    <td className="muted">{r.unit}</td>
                    {!isOpening && (
                      <>
                        <td className="num">{qty(r.opening)}</td>
                        <td className="num">{qty(r.purchased)}</td>
                        <td className="num">{qty(r.issued)}</td>
                        <td className="num" title={r.ideal < 0 ? "More was issued than was in stock: check purchases and issues for this item" : undefined}>{r.ideal < 0 && <span className="pill pill-turmeric" style={{ marginRight: 6 }}>check entries</span>}<b>{qty(r.ideal)}</b></td>
                      </>
                    )}
                    <td>
                      {closed ? (
                        <span className="num" style={{ display: "block", padding: "4px 6px" }}>{qty(r.counted)}</span>
                      ) : (
                        <NumCell value={counted} placeholder={isOpening ? "" : "not counted"} dirty={r.item_id in edits} onChange={(v) => setEdits((e) => ({ ...e, [r.item_id]: v }))} />
                      )}
                    </td>
                    {!isOpening && (
                      <>
                        <td className={`num ${r.variance > 0 ? "neg" : ""}`}>{r.variance === null ? "" : qty(r.variance)}</td>
                        <td className="num">
                          {r.variance_pct === null ? "" : (
                            <>
                              {pct(r.variance_pct)}
                              <span className="var-bar" style={{ width: `${Math.max(2, (Math.abs(r.variance_pct) / maxVar) * 40)}px`, background: r.flagged ? "var(--chili)" : "var(--rule-strong)" }} />
                            </>
                          )}
                        </td>
                        <td className={`num ${r.variance_value > 0 ? "neg" : ""}`}>{r.variance_value === null ? "" : rupees(r.variance_value, true)}</td>
                      </>
                    )}
                  </tr>,
                ];
              })}
            </tbody>
          </table>
          {rows.length === 0 && <div className="empty">No items in this view. Try "All items".</div>}
        </div>
      </div>
      {dirty && <div className="note note-warn small" style={{ marginTop: 10 }}>Variance updates after you save counts.</div>}
    </>
  );
}
