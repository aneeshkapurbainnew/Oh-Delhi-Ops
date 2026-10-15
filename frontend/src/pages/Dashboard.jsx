import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { MonthPicker, PageHead, Status } from "../components/ui";
import { useFetch } from "../lib/hooks";
import { dayNum, longDate, pct, qty, rupees, thisMonth } from "../lib/format";

function Kpi({ label, value, sub, tone }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone || ""}`}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export default function Dashboard() {
  const [month, setMonth] = useState(thisMonth());
  const { data, loading, error, reload } = useFetch(`/reports/dashboard?month=${month}`);

  return (
    <>
      <PageHead title="Dashboard" intro="Month-to-date numbers, calculated from prices, issues, purchases, sales and audits.">
        <MonthPicker value={month} onChange={setMonth} />
      </PageHead>
      <Status loading={loading && !data} error={error} onRetry={reload} />
      {data && <Body d={data} />}
    </>
  );
}

function Body({ d }) {
  const k = d.kpis;
  const series = d.series.map((s) => ({ ...s, day: dayNum(s.date) }));
  const hasSales = series.some((s) => s.net_sales > 0);
  const reviewsOpen = (d.reviews.open || 0) + (d.reviews.in_progress || 0);
  return (
    <div className="stack">
      {!k.wage_cost_entered && (
        <div className="note note-warn">
          Wage cost for this month isn't entered yet, so EBITDA excludes wages. <Link to="/pnl">Enter it on the P&L</Link>.
        </div>
      )}
      {d.unpriced_items.length > 0 && (
        <div className="note note-warn">
          {d.unpriced_items.length} items have no price, so their consumption costs ₹0: {d.unpriced_items.slice(0, 6).join(", ")}
          {d.unpriced_items.length > 6 ? "…" : ""}. <Link to="/prices">Set prices</Link>.
        </div>
      )}
      <div className="kpis">
        <Kpi label="Net sales" value={rupees(k.net_sales)} />
        <Kpi label="Food cost" value={pct(k.food_cost_pct)} sub="Kitchen stations ÷ net sales" />
        <Kpi label="Gross cost" value={pct(k.gross_cost_pct)} sub={`Consumption ${rupees(k.consumption)}`} />
        <Kpi label="Wastage" value={rupees(k.wastage)} sub="Cooked food, in ₹" />
        <Kpi
          label="Restaurant EBITDA"
          value={rupees(k.ebitda)}
          sub={k.ebitda_pct === null ? "No sales entered" : `${pct(k.ebitda_pct)} of net sales`}
          tone={k.ebitda < 0 ? "neg" : ""}
        />
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Daily sales and consumption</h2>
          <span className="muted xs">Bars: net sales. Line: food cost %.</span>
        </div>
        <div className="panel-body" style={{ height: 260 }}>
          {hasSales || series.some((s) => s.consumption_cost > 0) ? (
            <ResponsiveContainer>
              <ComposedChart data={series} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#e4e8e3" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} tickLine={false} />
                <YAxis yAxisId="r" tick={{ fontSize: 11 }} tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} width={48} />
                <YAxis yAxisId="p" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} width={40} />
                <Tooltip
                  formatter={(v, n) => (n === "Food cost %" ? pct(v) : rupees(v))}
                  labelFormatter={(l) => `Day ${l}`}
                />
                <Bar yAxisId="r" dataKey="net_sales" name="Net sales" fill="#2e6a57" radius={[2, 2, 0, 0]} />
                <Bar yAxisId="r" dataKey="consumption_cost" name="Consumption" fill="#b9c0ba" radius={[2, 2, 0, 0]} />
                <Line yAxisId="p" dataKey="food_cost_pct" name="Food cost %" stroke="#b47a0c" strokeWidth={2} dot={false} connectNulls />
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty">No sales or station issues this month yet.</div>
          )}
        </div>
      </div>

      <div className="cols-3">
        <div className="panel">
          <div className="panel-head">
            <h2>Latest audit</h2>
            {d.audit && <Link to={`/audits/${d.audit.id}`} className="small">Open</Link>}
          </div>
          <div className="panel-body">
            {!d.audit ? (
              <div className="empty">No audits yet. <Link to="/audits">Start one</Link>.</div>
            ) : (
              <>
                <div className="list-row"><span>Date</span><span>{longDate(d.audit.date)}</span></div>
                <div className="list-row"><span>Items over threshold</span><span className={d.audit.summary.items_flagged ? "neg" : ""}>{d.audit.summary.items_flagged}</span></div>
                <div className="list-row"><span>Shortage value</span><span className="num">{rupees(d.audit.summary.shortage_value)}</span></div>
                <div className="list-row"><span>Excess value</span><span className="num">{rupees(d.audit.summary.excess_value)}</span></div>
                {d.audit.top_flagged.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div className="muted xs" style={{ marginBottom: 4 }}>Biggest flagged variances</div>
                    {d.audit.top_flagged.map((r) => (
                      <div className="list-row" key={r.item_id}>
                        <span>{r.name}</span>
                        <span className={`num ${r.variance > 0 ? "neg" : ""}`}>{r.variance > 0 ? "short" : "excess"} {qty(Math.abs(r.variance))} {r.unit} · {rupees(Math.abs(r.variance_value))}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>To order</h2>
            <Link to="/stock" className="small">Stock and ordering</Link>
          </div>
          <div className="panel-body">
            <div className="list-row"><span>Below minimum</span><span className={d.stock.order_now ? "neg" : ""}>{d.stock.order_now}</span></div>
            <div className="list-row"><span>Below par</span><span>{d.stock.order}</span></div>
            {d.stock.urgent.map((r) => (
              <div className="list-row" key={r.item_id}>
                <span>{r.name}</span>
                <span className="num">{qty(r.estimated_stock)} / min {qty(r.min_stock)} {r.unit}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><h2>Follow-ups</h2></div>
          <div className="panel-body">
            <div className="list-row"><span><Link to="/daily">Not given to stations in full</Link></span><span className={d.pending_count ? "neg" : ""}>{d.pending_count}</span></div>
            {d.pending.slice(0, 4).map((p) => (
              <div className="list-row small" key={p.requisition_id}><span>{p.station}: {p.item}</span><span className="muted">short {qty(p.short)} {p.unit}</span></div>
            ))}
            <div className="list-row"><span><Link to="/reviews">Open reviews</Link></span><span>{reviewsOpen}</span></div>
            <div className="list-row"><span><Link to="/purchases">Unpaid vendor bills</Link></span><span className="num">{rupees(d.credit_outstanding)}</span></div>
            <div style={{ marginTop: 10 }}>
              <div className="muted xs" style={{ marginBottom: 4 }}>Consumption by station</div>
              {d.stations.map((s) => (
                <div className="list-row" key={s.station_id}><span>{s.name}</span><span className="num">{rupees(s.cost)}</span></div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
