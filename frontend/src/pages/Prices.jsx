import { useMemo, useState } from "react";
import { DayPicker, MonthPicker, NumCell, PageHead, Seg, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch, useUnsavedWarning } from "../lib/hooks";
import { dayLabel, prettyCategory, rupees, thisMonth, todayISO } from "../lib/format";

export default function Prices() {
  const [tab, setTab] = useState("daily");
  return (
    <>
      <PageHead
        title="Prices"
        intro="Purchases update these automatically. A price typed here overrides purchase rates for that day or period."
      >
        <Seg options={[["daily", "Daily items"], ["weekly", "Weekly-average items"]]} value={tab} onChange={setTab} />
      </PageHead>
      {tab === "daily" ? <Daily /> : <Weekly />}
    </>
  );
}

function useFilter(rows) {
  const [q, setQ] = useState("");
  const [onlyUnpriced, setOnlyUnpriced] = useState(false);
  const filtered = useMemo(
    () =>
      (rows || []).filter(
        (r) => (!q || r.name.toLowerCase().includes(q.toLowerCase())) && (!onlyUnpriced || r.never_priced)
      ),
    [rows, q, onlyUnpriced]
  );
  const controls = (
    <>
      <input className="search" placeholder="Search items" value={q} onChange={(e) => setQ(e.target.value)} />
      <label className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input type="checkbox" checked={onlyUnpriced} onChange={(e) => setOnlyUnpriced(e.target.checked)} /> Only items without a price
      </label>
    </>
  );
  return [filtered, controls];
}

function grouped(rows, render) {
  let last = null;
  const out = [];
  rows.forEach((r) => {
    if (r.category !== last) {
      last = r.category;
      out.push(
        <tr className="group" key={`g-${r.category}`}>
          <td colSpan={20}>{prettyCategory(r.category)}</td>
        </tr>
      );
    }
    out.push(render(r));
  });
  return out;
}

function Daily() {
  const toast = useToast();
  const [on, setOn] = useState(todayISO());
  const { data, setData, loading, error, reload } = useFetch(`/prices/daily?on=${on}`);
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const [rows, controls] = useFilter(data);
  const dirty = Object.keys(edits).length > 0;
  useUnsavedWarning(dirty);

  const changeDay = (d) => {
    if (dirty && !window.confirm("Discard unsaved prices?")) return;
    setEdits({});
    setOn(d);
  };
  const save = async () => {
    setBusy(true);
    try {
      const prices = Object.entries(edits).map(([id, price]) => ({ item_id: Number(id), price }));
      setData(await api.put("/prices/daily", { date: on, prices }));
      setEdits({});
      toast(`Saved ${prices.length} prices for ${dayLabel(on)}.`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <DayPicker value={on} onChange={changeDay} />
        <div className="toolbar">
          {controls}
          <button className="btn-primary" disabled={!dirty || busy} onClick={save}>
            {busy ? "Saving…" : dirty ? `Save ${Object.keys(edits).length} prices` : "Save prices"}
          </button>
        </div>
      </div>
      <Status loading={loading && !data} error={error} onRetry={reload} />
      {data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Purchase unit</th>
                <th className="num" style={{ width: 130 }}>Price today</th>
                <th>Comes from</th>
                <th className="num">Per consumption unit</th>
              </tr>
            </thead>
            <tbody>
              {grouped(rows, (r) => {
                const editing = r.item_id in edits;
                const shown = editing ? edits[r.item_id] : r.manual_price;
                return (
                  <tr key={r.item_id}>
                    <td>{r.name} {r.never_priced && <span className="pill pill-turmeric">no price</span>}</td>
                    <td className="muted">{r.purchase_unit}</td>
                    <td>
                      <NumCell
                        value={shown}
                        placeholder={r.price ? String(r.price) : ""}
                        dirty={editing}
                        onChange={(v) => setEdits((e) => ({ ...e, [r.item_id]: v }))}
                      />
                    </td>
                    <td className="small muted">
                      {r.manual_price != null
                        ? "Typed for this day"
                        : r.purchase_price != null
                        ? `Purchase today at ${rupees(r.purchase_price, true)}`
                        : r.price_from
                        ? `Carried from ${dayLabel(r.price_from)}`
                        : "Never priced"}
                    </td>
                    <td className="num">
                      {rupees(r.consumption_price, true)} <span className="muted xs">/ {r.consumption_unit}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <div className="empty">No items match.</div>}
        </div>
      )}
    </div>
  );
}

function Weekly() {
  const toast = useToast();
  const [month, setMonth] = useState(thisMonth());
  const { data, setData, loading, error, reload } = useFetch(`/prices/weekly?month=${month}`);
  const [edits, setEdits] = useState({}); // key `${item}|${period}`
  const [busy, setBusy] = useState(false);
  const [rows, controls] = useFilter(data);
  const dirty = Object.keys(edits).length > 0;
  useUnsavedWarning(dirty);

  const changeMonth = (m) => {
    if (dirty && !window.confirm("Discard unsaved prices?")) return;
    setEdits({});
    setMonth(m);
  };
  const save = async () => {
    setBusy(true);
    try {
      const byPeriod = { 1: [], 2: [], 3: [] };
      Object.entries(edits).forEach(([k, price]) => {
        const [id, p] = k.split("|").map(Number);
        byPeriod[p].push({ item_id: id, price });
      });
      let last = null;
      for (const p of [1, 2, 3]) {
        if (byPeriod[p].length) last = await api.put("/prices/weekly", { month, period: p, prices: byPeriod[p] });
      }
      if (last) setData(last);
      setEdits({});
      toast("Prices saved.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <MonthPicker value={month} onChange={changeMonth} />
        <div className="toolbar">
          {controls}
          <button className="btn-primary" disabled={!dirty || busy} onClick={save}>
            {busy ? "Saving…" : "Save prices"}
          </button>
        </div>
      </div>
      <div className="panel-body note small" style={{ borderRadius: 0 }}>
        Each period's price is what you type, otherwise the average purchase rate in that period, otherwise the
        previous period's price (shown in grey). Consumption is costed at the month average.
      </div>
      <Status loading={loading && !data} error={error} onRetry={reload} />
      {data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Purchase unit</th>
                <th className="num" style={{ width: 120 }}>1st–10th</th>
                <th className="num" style={{ width: 120 }}>11th–20th</th>
                <th className="num" style={{ width: 120 }}>21st–end</th>
                <th className="num">Month average</th>
                <th className="num">Per consumption unit</th>
              </tr>
            </thead>
            <tbody>
              {grouped(rows, (r) => (
                <tr key={r.item_id}>
                  <td>{r.name} {r.never_priced && <span className="pill pill-turmeric">no price</span>}</td>
                  <td className="muted">{r.purchase_unit}</td>
                  {r.periods.map((p, n) => {
                    const k = `${r.item_id}|${n + 1}`;
                    return (
                      <td key={n} title={p.carried ? "Carried forward" : p.manual != null ? "Typed" : "From purchases"}>
                        <NumCell
                          value={k in edits ? edits[k] : p.manual}
                          placeholder={p.price ? String(p.price) : ""}
                          dirty={k in edits}
                          onChange={(v) => setEdits((e) => ({ ...e, [k]: v }))}
                        />
                      </td>
                    );
                  })}
                  <td className="num">{rupees(r.average, true)}</td>
                  <td className="num">
                    {rupees(r.consumption_price, true)} <span className="muted xs">/ {r.consumption_unit}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="empty">No items match.</div>}
        </div>
      )}
    </div>
  );
}
