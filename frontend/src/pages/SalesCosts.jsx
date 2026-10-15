import { useState } from "react";
import { MonthGrid, MonthPicker, NumCell, PageHead, Status, editsToCells, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch, useUnsavedWarning } from "../lib/hooks";
import { dayLabel, isWeekend, pct, rupees, thisMonth } from "../lib/format";

const TABS = [
  ["sales", "Sales"],
  ["discount", "Discounts"],
  ["delivery", "Delivery"],
  ["ads", "Ads"],
];

export default function SalesCosts() {
  const [month, setMonth] = useState(thisMonth());
  const [tab, setTab] = useState("sales");
  return (
    <>
      <PageHead title="Sales and channel costs" intro="Daily sales, and discount, delivery and ads spend per brand and platform. Brands and platforms are edited in Setup → Channels.">
        <MonthPicker value={month} onChange={setMonth} />
      </PageHead>
      <div className="tabs">
        {TABS.map(([k, l]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "sales" ? <Sales key={month} month={month} /> : <ChannelGrid key={`${tab}-${month}`} month={month} kind={tab} />}
    </>
  );
}

function Sales({ month }) {
  const toast = useToast();
  const { data, setData, loading, error, reload } = useFetch(`/sales?month=${month}`);
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edits).length > 0;
  useUnsavedWarning(dirty);
  const row = (r) => ({ ...r, ...(edits[r.date] || {}) });
  const set = (date, k, v) => setEdits((e) => ({ ...e, [date]: { ...(e[date] || {}), [k]: v } }));

  const save = async () => {
    setBusy(true);
    try {
      const rows = Object.keys(edits).map((d) => {
        const r = row(data.rows.find((x) => x.date === d));
        return { date: d, gross_sale: r.gross_sale || 0, complimentary: r.complimentary || 0, net_sales: r.net_sales || 0 };
      });
      setData(await api.put("/sales", { rows }));
      setEdits({});
      toast(`Saved sales for ${rows.length} days.`);
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <Status loading={loading} error={error} onRetry={reload} />;
  const rows = data.rows.map(row);
  const sum = (k) => rows.reduce((s, r) => s + (r[k] || 0), 0);
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="small muted">Total gross = gross sale + complimentary. Net sales include tax, as in the old sheet.</span>
        <button className="btn-primary" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save sales"}</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Day</th><th className="num">Gross sale</th><th className="num">Complimentary</th><th className="num">Total gross</th><th className="num">Net sales (with tax)</th><th className="num">Net ÷ gross</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const tg = (r.gross_sale || 0) + (r.complimentary || 0);
              return (
                <tr key={r.date} className={isWeekend(r.date) ? "weekend" : ""}>
                  <td>{dayLabel(r.date)}</td>
                  {["gross_sale", "complimentary"].map((k) => (
                    <td key={k} style={{ width: 150 }}><NumCell value={r[k]} dirty={edits[r.date]?.[k] !== undefined} onChange={(v) => set(r.date, k, v)} /></td>
                  ))}
                  <td className="num">{tg ? rupees(tg) : ""}</td>
                  <td style={{ width: 170 }}><NumCell value={r.net_sales} dirty={edits[r.date]?.net_sales !== undefined} onChange={(v) => set(r.date, "net_sales", v)} /></td>
                  <td className="num muted">{r.gross_sale ? pct(((r.net_sales || 0) / r.gross_sale) * 100) : ""}</td>
                </tr>
              );
            })}
            <tr className="total">
              <td>Month</td>
              <td className="num">{rupees(sum("gross_sale"))}</td>
              <td className="num">{rupees(sum("complimentary"))}</td>
              <td className="num">{rupees(sum("gross_sale") + sum("complimentary"))}</td>
              <td className="num">{rupees(sum("net_sales"))}</td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ChannelGrid({ month, kind }) {
  const toast = useToast();
  const { data, loading, error, reload } = useFetch(`/channel-costs?month=${month}&kind=${kind}`);
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edits).length > 0;
  useUnsavedWarning(dirty);
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/channel-costs?kind=${kind}`, { cells: editsToCells(edits) });
      setEdits({});
      await reload();
      toast("Saved.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  if (!data) return <Status loading={loading} error={error} onRetry={reload} />;
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="small muted">Amounts in ₹. Scroll sideways for later days.</span>
        <button className="btn-primary" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
      </div>
      {data.rows.length ? <MonthGrid grid={data} edits={edits} setEdits={setEdits} rowLabel="Brand" /> : <div className="empty">No channels track this cost. Add one in Setup → Channels.</div>}
    </div>
  );
}
