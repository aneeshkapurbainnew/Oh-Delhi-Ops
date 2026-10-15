import { useState } from "react";
import { DayPicker, NumCell, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch, useUnsavedWarning } from "../lib/hooks";
import { longDate, prettyCategory, shiftDay, todayISO } from "../lib/format";
import { GiveStation } from "./Daily";
import { DayEntry } from "./Issues";

/** Simple screen for a station login on the shared kitchen device. */
export default function Kitchen({ user, stationName, onOpenFull, onSignOut }) {
  const [tab, setTab] = useState("order");
  const today = todayISO();
  return (
    <div className="kitchen">
      <header className="kitchen-head">
        <div className="brand" style={{ padding: 0 }}>
          <div className="brand-mark">OD</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: "1.25rem" }}>{stationName} station</div>
            <div className="muted small">{longDate(today)}</div>
          </div>
        </div>
        <div className="toolbar">
          <button className="btn-ghost" onClick={onOpenFull}>Full app</button>
          <button onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      <div className="tabs kitchen-tabs">
        <button className={tab === "order" ? "on" : ""} onClick={() => setTab("order")}>Order for tomorrow</button>
        <button className={tab === "received" ? "on" : ""} onClick={() => setTab("received")}>Received today</button>
        <button className={tab === "issues" ? "on" : ""} onClick={() => setTab("issues")}>Everything used today</button>
      </div>
      {tab === "order" && <Requirement stationId={user.station_id} />}
      {tab === "received" && (
        <>
          <p className="muted">What the store gave your station today, against what you asked for. Anything short is flagged to the store manager and owner.</p>
          <GiveStation on={today} stationId={user.station_id} readOnly />
        </>
      )}
      {tab === "issues" && (
        <>
          <p className="muted">Everything your station took from the store today, including dry store items. Daily-order items appear here once the store records them.</p>
          <DayEntry stationId={user.station_id} />
        </>
      )}
    </div>
  );
}

const SECTIONS = [
  ["vendor", "From vendors", "Vegetables, poultry, dairy, eggs, noodles, rumali: ordered tonight on WhatsApp."],
  ["store", "From the store", "Dry store items: handed over from store stock, never ordered from a vendor."],
];

function Requirement({ stationId }) {
  const toast = useToast();
  const [on, setOn] = useState(shiftDay(todayISO(), 1));
  const { data, setData, loading, error, reload } = useFetch(`/requisitions?on=${on}&station_id=${stationId}`);
  const [edits, setEdits] = useState({});
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edits).length > 0;
  useUnsavedWarning(dirty);

  const save = async () => {
    setBusy(true);
    try {
      const lines = Object.entries(edits).map(([id, v]) => ({ item_id: Number(id), qty: v }));
      setData(await api.put("/requisitions", { date: on, station_id: stationId, lines }));
      setEdits({});
      toast("Saved. Vendor items go into tonight's order; store items are handed over by the store.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const value = (r) => (r.item_id in edits ? edits[r.item_id] : r.qty);
  const match = (r) => !q || r.name.toLowerCase().includes(q.toLowerCase());
  const asked = (data?.rows || []).filter((r) => value(r)).length;

  return (
    <div className="stack">
      <div className="toolbar" style={{ justifyContent: "space-between" }}>
        <div className="toolbar"><span className="muted">Needed on</span><DayPicker value={on} onChange={(d) => { if (!dirty || window.confirm("Discard unsaved changes?")) { setEdits({}); setOn(d); } }} /></div>
        <button className="btn-primary btn-lg" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save order"}</button>
      </div>
      <div className="toolbar">
        <input className="search" style={{ flex: 1, fontSize: "1.0625rem", padding: "10px 12px" }} placeholder="Search items (e.g. jeera, paneer)" value={q} onChange={(e) => setQ(e.target.value)} />
        {asked > 0 && <span className="pill pill-green">{asked} item{asked > 1 ? "s" : ""} asked for</span>}
      </div>
      {data?.orders_sent && <div className="note note-warn">Tonight's vendor orders have already gone out. You can still change vendor items; the manager will be alerted.</div>}
      <Status loading={loading && !data} error={error} onRetry={reload} />
      {data && data.rows.length === 0 && <div className="empty">This station has no items yet. Ask the manager to add them in Setup → Stations.</div>}
      {data && SECTIONS.map(([src, title, help]) => {
        const rows = data.rows.filter((r) => r.source === src && match(r));
        if (!rows.length) return null;
        let last = null;
        return (
          <div className="panel" key={src}>
            <div className="panel-head">
              <div><h2>{title}</h2><div className="muted small">{help}</div></div>
            </div>
            <table className="kitchen-table">
              <tbody>
                {rows.map((r) => {
                  const head = r.category !== last;
                  last = r.category;
                  return [
                    head && <tr className="group" key={`g-${src}-${r.category}`}><td colSpan={3}>{prettyCategory(r.category)}</td></tr>,
                    <tr key={r.item_id}>
                      <td>{r.name} {r.late && <span className="pill pill-turmeric">changed after sending</span>}</td>
                      <td style={{ width: 150 }}>
                        <NumCell value={value(r)} dirty={r.item_id in edits} onChange={(v) => setEdits((e) => ({ ...e, [r.item_id]: v }))} />
                      </td>
                      <td className="muted" style={{ width: 70 }}>{r.unit}</td>
                    </tr>,
                  ];
                })}
              </tbody>
            </table>
          </div>
        );
      })}
      {dirty && <div><button className="btn-primary btn-lg" onClick={save} disabled={busy}>Save order</button></div>}
    </div>
  );
}
