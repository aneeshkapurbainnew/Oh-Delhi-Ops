import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { DayPicker, ItemPicker, MonthPicker, NumCell, PageHead, Seg, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch, useUnsavedWarning } from "../lib/hooks";
import { dayLabel, dayNum, isWeekend, prettyCategory, qty, rupees, thisMonth, todayISO } from "../lib/format";

export default function Issues() {
  const stations = useFetch("/stations");
  const [stationId, setStationId] = useState(null);
  const [mode, setMode] = useState("day");
  const active = (stations.data || []).filter((s) => s.active);

  useEffect(() => {
    if (!stationId && active.length) setStationId(active[0].id);
  }, [active, stationId]);

  return (
    <>
      <PageHead
        title="Station issues"
        intro="What each station took from the store, in consumption units. This replaces the Indian, Tandoor, Chinese, Conti, Staff, Packaging, Daily Items and vegetable/poultry ordering sheets."
      >
        <Seg options={[["day", "Enter a day"], ["month", "Month view"]]} value={mode} onChange={setMode} />
      </PageHead>
      <Status loading={stations.loading} error={stations.error} />
      {active.length > 0 && (
        <div className="tabs" role="tablist">
          {active.map((s) => (
            <button key={s.id} className={s.id === stationId ? "on" : ""} onClick={() => setStationId(s.id)}>
              {s.name}
            </button>
          ))}
        </div>
      )}
      {stationId && (mode === "day" ? <DayEntry key={stationId} stationId={stationId} /> : <MonthView stationId={stationId} />)}
    </>
  );
}

export function DayEntry({ stationId }) {
  const toast = useToast();
  const [on, setOn] = useState(todayISO());
  const { data, setData, loading, error, reload } = useFetch(`/issues/day?on=${on}&station_id=${stationId}`);
  const allItems = useFetch("/items");
  const [edits, setEdits] = useState({});
  const [extra, setExtra] = useState([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edits).length > 0;
  useUnsavedWarning(dirty);

  const rows = useMemo(() => {
    if (!data) return [];
    const have = new Set(data.rows.map((r) => r.item_id));
    const added = extra.filter((i) => !have.has(i.id)).map((i) => ({
      item_id: i.id, name: i.name, category: i.category, unit: i.consumption_unit, unit_cost: null, qty: null, cost: 0, added: true,
    }));
    const s = q.toLowerCase();
    return [...data.rows, ...added].filter((r) => !s || r.name.toLowerCase().includes(s));
  }, [data, extra, q]);

  const value = (r) => (r.item_id in edits ? edits[r.item_id] : r.qty);
  const total = rows.reduce((sum, r) => sum + (value(r) || 0) * (r.unit_cost || 0), 0);

  const changeDay = (d) => {
    if (dirty && !window.confirm("Discard unsaved quantities?")) return;
    setEdits({});
    setExtra([]);
    setOn(d);
  };

  const save = async () => {
    setBusy(true);
    try {
      const lines = Object.entries(edits).map(([id, v]) => ({ item_id: Number(id), qty: v }));
      setData(await api.put("/issues/day", { date: on, station_id: stationId, lines }));
      setEdits({});
      setExtra([]);
      toast(`Saved ${lines.length} lines for ${dayLabel(on)}.`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  let last = null;
  return (
    <div className="panel">
      <div className="panel-head">
        <DayPicker value={on} onChange={changeDay} />
        <div className="toolbar">
          <input className="search" placeholder="Filter this list" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn-primary" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save day"}</button>
        </div>
      </div>
      <Status loading={loading && !data} error={error} onRetry={reload} />
      {data && (
        <>
          {data.rows.length === 0 && (
            <div className="note" style={{ margin: 12 }}>
              This station has no items yet. Add them in <Link to="/setup">Setup → Stations</Link>, or issue a single item below.
            </div>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Item</th><th>Unit</th><th className="num">Cost / unit</th><th className="num" style={{ width: 130 }}>Issued</th><th className="num">Cost</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const head = r.category !== last;
                  last = r.category;
                  const v = value(r);
                  return [
                    head && <tr className="group" key={`g-${r.category}`}><td colSpan={5}>{prettyCategory(r.category)}</td></tr>,
                    <tr key={r.item_id}>
                      <td>{r.name} {r.added && <span className="pill pill-grey">added</span>}</td>
                      <td className="muted">{r.unit}</td>
                      <td className="num muted">{r.unit_cost != null ? rupees(r.unit_cost, true) : "after save"}</td>
                      <td><NumCell value={v} dirty={r.item_id in edits} onChange={(x) => setEdits((e) => ({ ...e, [r.item_id]: x }))} /></td>
                      <td className="num">{v && r.unit_cost != null ? rupees(v * r.unit_cost, true) : ""}</td>
                    </tr>,
                  ];
                })}
                <tr className="total"><td colSpan={4}>Station cost for the day</td><td className="num">{rupees(total, true)}</td></tr>
              </tbody>
            </table>
          </div>
          <div className="panel-body" style={{ display: "flex", gap: 8, alignItems: "center", borderTop: "1px solid var(--rule)" }}>
            <span className="small muted">Issue an item that isn't on this station's list:</span>
            <div style={{ width: 320 }}>
              {allItems.data && (
                <ItemPicker items={allItems.data} value={null} onChange={(i) => setExtra((x) => [...x, i])} renderMeta={(i) => i.consumption_unit} />
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function MonthView({ stationId }) {
  const [month, setMonth] = useState(thisMonth());
  const { data, loading, error, reload } = useFetch(`/issues/month?month=${month}&station_id=${stationId}`);
  const [onlyUsed, setOnlyUsed] = useState(true);
  const rows = (data?.rows || []).filter((r) => !onlyUsed || r.total_qty > 0);
  return (
    <div className="panel">
      <div className="panel-head">
        <MonthPicker value={month} onChange={setMonth} />
        <label className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={onlyUsed} onChange={(e) => setOnlyUsed(e.target.checked)} /> Only items issued this month
        </label>
      </div>
      <Status loading={loading && !data} error={error} onRetry={reload} />
      {data && (
        <div className="table-wrap">
          <table className="grid-month">
            <thead>
              <tr>
                <th className="sticky-col">Item</th>
                {data.days.map((d) => <th key={d} className={`day num ${isWeekend(d) ? "weekend" : ""}`}>{dayNum(d)}</th>)}
                <th className="num">Month qty</th>
                <th className="num">Month cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.item_id}>
                  <td className="sticky-col">{r.name} <span className="muted xs">{r.unit}</span></td>
                  {data.days.map((d) => (
                    <td key={d} className={`num ${isWeekend(d) ? "weekend" : ""}`} style={{ padding: "5px 6px" }}>{r.qty[d] ? qty(r.qty[d]) : ""}</td>
                  ))}
                  <td className="num">{qty(r.total_qty)}</td>
                  <td className="num">{rupees(r.total_cost)}</td>
                </tr>
              ))}
              <tr className="total">
                <td className="sticky-col">Cost</td>
                {data.days.map((d) => <td key={d} className="num" style={{ padding: "5px 6px" }}>{data.day_cost[d] ? rupees(data.day_cost[d]) : ""}</td>)}
                <td />
                <td className="num">{rupees(data.total_cost)}</td>
              </tr>
            </tbody>
          </table>
          {rows.length === 0 && <div className="empty">Nothing issued from this station this month.</div>}
        </div>
      )}
    </div>
  );
}
