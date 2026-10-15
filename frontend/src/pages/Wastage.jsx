import { useState } from "react";
import { MonthPicker, PageHead, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch } from "../lib/hooks";
import { dayLabel, qty, rupees, thisMonth, todayISO, toNum } from "../lib/format";

const blank = () => ({ date: todayISO(), dish: "", station_id: "", qty: null, unit: "", value: null, reason: "", notes: "" });

export default function Wastage() {
  const toast = useToast();
  const [month, setMonth] = useState(thisMonth());
  const list = useFetch(`/wastage?month=${month}`);
  const stations = useFetch("/stations");
  const reasons = useFetch("/wastage/reasons");
  const [f, setF] = useState(blank());
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const dishes = [...new Set((list.data?.rows || []).map((r) => r.dish))];

  const add = async (e) => {
    e.preventDefault();
    if (!f.dish.trim() || !f.value || !f.reason) return toast("Enter the dish, its value in ₹ and a reason.", "error");
    setBusy(true);
    try {
      await api.post("/wastage", {
        date: f.date,
        dish: f.dish.trim(),
        station_id: f.station_id ? Number(f.station_id) : null,
        qty: f.qty || null,
        unit: f.unit || null,
        value: f.value,
        reason: f.reason,
        notes: f.notes || null,
      });
      toast("Wastage recorded.");
      setF({ ...blank(), date: f.date, station_id: f.station_id });
      list.reload();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id) => {
    if (!window.confirm("Delete this wastage entry?")) return;
    try {
      await api.del(`/wastage/${id}`);
      list.reload();
    } catch (err) {
      toast(err.message, "error");
    }
  };

  return (
    <>
      <PageHead
        title="Wastage"
        intro="Cooked food that was thrown away, valued in rupees. It doesn't change raw-material stock, and the full amount is added to COGS on the P&L."
      >
        <MonthPicker value={month} onChange={setMonth} />
      </PageHead>
      <div className="stack">
        <form className="panel panel-body" onSubmit={add}>
          <datalist id="dishes">{dishes.map((d) => <option key={d} value={d} />)}</datalist>
          <div className="form-grid" style={{ gridTemplateColumns: "140px 2fr 1fr 90px 100px 120px 1.4fr", alignItems: "end" }}>
            <label className="field">Date<input type="date" value={f.date} onChange={(e) => set("date", e.target.value)} /></label>
            <label className="field">Dish or item<input list="dishes" value={f.dish} onChange={(e) => set("dish", e.target.value)} placeholder="e.g. Dal Makhani" /></label>
            <label className="field">Station
              <select value={f.station_id} onChange={(e) => set("station_id", e.target.value)}>
                <option value="">–</option>
                {(stations.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            <label className="field">Qty (optional)<input type="number" min="0" step="any" value={f.qty ?? ""} onChange={(e) => set("qty", toNum(e.target.value))} /></label>
            <label className="field">Unit<input value={f.unit} onChange={(e) => set("unit", e.target.value)} placeholder="plates" /></label>
            <label className="field">Value (₹)<input type="number" min="0" step="any" value={f.value ?? ""} onChange={(e) => set("value", toNum(e.target.value))} /></label>
            <label className="field">Reason
              <select value={f.reason} onChange={(e) => set("reason", e.target.value)}>
                <option value="">Choose</option>
                {(reasons.data || []).map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
          </div>
          <div className="toolbar" style={{ marginTop: 12 }}>
            <input style={{ flex: 1 }} placeholder="Notes (optional)" value={f.notes} onChange={(e) => set("notes", e.target.value)} />
            <button className="btn-primary" disabled={busy}>Record wastage</button>
          </div>
        </form>

        <div className="panel">
          <Status loading={list.loading && !list.data} error={list.error} onRetry={list.reload} />
          {list.data && (
            <>
              <div className="panel-head">
                <h2>{rupees(list.data.total)} this month</h2>
                <div className="toolbar small">
                  {list.data.by_station.map((s) => <span key={s.name}>{s.name}: <b className="num">{rupees(s.value)}</b></span>)}
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Date</th><th>Dish</th><th>Station</th><th className="num">Qty</th><th>Reason</th><th>Notes</th><th className="num">Value</th><th /></tr></thead>
                  <tbody>
                    {list.data.rows.map((r) => (
                      <tr key={r.id}>
                        <td>{dayLabel(r.date)}</td>
                        <td>{r.dish}</td>
                        <td>{r.station || "–"}</td>
                        <td className="num">{r.qty ? <>{qty(r.qty)} <span className="muted xs">{r.unit}</span></> : "–"}</td>
                        <td>{r.reason}</td>
                        <td className="muted small">{r.notes}</td>
                        <td className="num">{rupees(r.value, true)}</td>
                        <td><button className="btn-sm btn-ghost btn-danger" onClick={() => remove(r.id)}>Delete</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {list.data.rows.length === 0 && <div className="empty">No wastage recorded this month.</div>}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
