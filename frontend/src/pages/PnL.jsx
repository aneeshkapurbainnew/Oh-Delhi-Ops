import { useEffect, useState } from "react";
import { MonthPicker, PageHead, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch } from "../lib/hooks";
import { pct, rupees, thisMonth, toNum } from "../lib/format";

const SUBTOTALS = new Set(["net_sales", "cogs", "gross_profit", "restaurant_margin"]);
const OF_GROSS = new Set(["gross_sale", "complimentary", "discount"]);

export default function PnL() {
  const toast = useToast();
  const [month, setMonth] = useState(thisMonth());
  const { data, loading, error, reload } = useFetch(`/reports/pnl?month=${month}`);
  const inputs = useFetch(`/monthly-inputs/${month}`);
  const [wage, setWage] = useState(null);
  const [days, setDays] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (inputs.data) {
      setWage(inputs.data.wage_cost || null);
      setDays(inputs.data.days_of_operation);
    }
  }, [inputs.data]);

  const saveInputs = async () => {
    setBusy(true);
    try {
      await api.put(`/monthly-inputs/${month}`, { wage_cost: wage || 0, days_of_operation: days || null });
      toast("Saved.");
      reload();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const download = async () => {
    try {
      await api.download(`/reports/pnl.pdf?month=${month}`, `PnL-${month}.pdf`);
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <>
      <PageHead title="Profit and loss" intro="Built from sales, channel costs, expenses, station issues at the price rules, cooked-food wastage and the wage total from Attendio.">
        <MonthPicker value={month} onChange={setMonth} />
        <button className="btn-primary" onClick={download}>Download PDF</button>
      </PageHead>
      <div className="cols-2" style={{ gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr)", alignItems: "start" }}>
        <div className="panel">
          <Status loading={loading && !data} error={error} onRetry={reload} />
          {data && (
            <table className="pnl">
              <thead><tr><th /><th className="num">Amount</th><th className="num">%</th></tr></thead>
              <tbody>
                {data.lines.map((l) => (
                  <tr key={l.key} className={l.key === "ebitda" ? "ebitda" : SUBTOTALS.has(l.key) ? "sub" : ""}>
                    <td>{l.label}</td>
                    <td className={`num ${l.value < 0 ? "neg" : ""}`}>{rupees(l.value)}</td>
                    <td className="num muted">{l.pct === null ? "–" : `${pct(l.pct)}${OF_GROSS.has(l.key) ? " of gross" : ""}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="stack">
          <div className="panel">
            <div className="panel-head"><h2>Monthly inputs</h2></div>
            <div className="panel-body stack">
              <label className="field">Total wage cost from Attendio (₹)
                <input type="number" min="0" value={wage ?? ""} onChange={(e) => setWage(toNum(e.target.value))} />
              </label>
              <label className="field">Days of operation (blank = days with sales)
                <input type="number" min="0" max="31" value={days ?? ""} onChange={(e) => setDays(toNum(e.target.value))} />
              </label>
              <button className="btn-primary" onClick={saveInputs} disabled={busy}>{busy ? "Saving…" : "Save inputs"}</button>
            </div>
          </div>
          {data && (
            <div className="panel">
              <div className="panel-head"><h2>Cost ratios</h2></div>
              <div className="panel-body">
                <div className="list-row"><span>Food cost (kitchen ÷ net sales)</span><span className="num">{pct(data.ratios.food_cost_pct)}</span></div>
                <div className="list-row"><span>Packaging ÷ net sales</span><span className="num">{pct(data.ratios.packaging_cost_pct)}</span></div>
                <div className="list-row"><span>Gross cost (all stations ÷ total gross)</span><span className="num">{pct(data.ratios.gross_cost_pct)}</span></div>
                <div className="muted xs" style={{ margin: "12px 0 4px" }}>Consumption by station</div>
                {data.stations.map((s) => <div className="list-row" key={s.station_id}><span>{s.name}</span><span className="num">{rupees(s.cost)}</span></div>)}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
