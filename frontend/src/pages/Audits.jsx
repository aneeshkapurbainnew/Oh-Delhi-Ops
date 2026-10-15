import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHead, Seg, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch } from "../lib/hooks";
import { longDate, rupees, todayISO } from "../lib/format";

export default function Audits() {
  const toast = useToast();
  const nav = useNavigate();
  const { data, loading, error, reload } = useFetch("/audits");
  const [date, setDate] = useState(todayISO());
  const [kind, setKind] = useState("spot");
  const [busy, setBusy] = useState(false);
  const first = data && data.length === 0;

  const create = async () => {
    setBusy(true);
    try {
      const a = await api.post("/audits", { date, kind: first ? "opening" : kind });
      nav(`/audits/${a.id}`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead
        title="Audits"
        intro="Count stock on any day. Each audit compares the count with opening + purchases − issues − store wastage since the previous audit. Close every audit in a month before closing its month-end audit."
      />
      <div className="stack">
        <div className="panel panel-body">
          <div className="toolbar">
            <label className="field">Count date<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
            {first ? (
              <div className="note small" style={{ alignSelf: "end" }}>Your first audit is an opening count: it sets starting stock and has no variance.</div>
            ) : (
              <label className="field">Type
                <Seg options={[["spot", "Audit"], ["month_end", "Month-end"], ["opening", "Opening count"]]} value={kind} onChange={setKind} />
              </label>
            )}
            <button className="btn-primary" style={{ alignSelf: "end" }} onClick={create} disabled={busy}>
              {first ? "Start opening count" : "Start audit"}
            </button>
          </div>
          {kind === "opening" && !first && (
            <div className="note note-warn small" style={{ marginTop: 10 }}>
              An opening count resets the chain: earlier audits no longer feed opening stock. Use it only when restarting stock tracking.
            </div>
          )}
        </div>

        <div className="panel">
          <Status loading={loading && !data} error={error} onRetry={reload} />
          {data && data.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Date</th><th>Type</th><th>Status</th><th className="num">Items counted</th><th className="num">Over threshold</th><th className="num">Shortage</th><th className="num">Excess</th><th className="num">Closing stock value</th></tr>
                </thead>
                <tbody>
                  {data.map((a) => (
                    <tr key={a.id}>
                      <td><Link to={`/audits/${a.id}`}>{longDate(a.date)}</Link></td>
                      <td>{a.kind_label}</td>
                      <td><span className={`pill ${a.status === "closed" ? "pill-green" : "pill-turmeric"}`}>{a.status === "closed" ? "Closed" : "Counting"}</span></td>
                      <td className="num">{a.summary?.items_counted ?? "–"}</td>
                      <td className={`num ${a.summary?.items_flagged ? "neg" : ""}`}>{a.summary?.items_flagged ?? "–"}</td>
                      <td className="num">{a.summary ? rupees(a.summary.shortage_value) : "–"}</td>
                      <td className="num">{a.summary ? rupees(a.summary.excess_value) : "–"}</td>
                      <td className="num">{a.summary ? rupees(a.summary.closing_stock_value) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data && data.length === 0 && <div className="empty">No audits yet. Start with an opening count of everything in the store.</div>}
        </div>
      </div>
    </>
  );
}
