import { useEffect, useMemo, useState } from "react";
import { DayPicker, ItemPicker, NumCell, PageHead, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch, useUnsavedWarning } from "../lib/hooks";
import { compressImage } from "../lib/image";
import { dayLabel, longDate, prettyCategory, qty, rupees, shiftDay, todayISO, toNum } from "../lib/format";

const STEPS = [
  ["plan", "1. Plan and send"],
  ["receive", "2. Receive from vendors"],
  ["give", "3. Give to stations"],
  ["pending", "Pending"],
];
const ORDER_PILL = { draft: ["Not sent", "pill-grey"], sent: ["Sent", "pill-turmeric"], received: ["Received", "pill-green"] };

export default function Daily({ onPendingChange }) {
  const [step, setStep] = useState("plan");
  const [planDate, setPlanDate] = useState(shiftDay(todayISO(), 1));
  const [dayDate, setDayDate] = useState(todayISO());
  const pending = useFetch("/pending/count");
  const refreshPending = () => {
    pending.reload();
    onPendingChange?.();
  };
  return (
    <>
      <PageHead
        title="Daily orders"
        intro="Vegetables, poultry, dairy, eggs, noodles and rumali. Stations ask for what they need, you send each vendor their order on WhatsApp, record what arrived, and record what each station got."
      />
      <div className="tabs">
        {STEPS.map(([k, l]) => (
          <button key={k} className={step === k ? "on" : ""} onClick={() => setStep(k)}>
            {l}
            {k === "pending" && pending.data?.count > 0 && <span className="pill pill-chili" style={{ marginLeft: 6 }}>{pending.data.count}</span>}
          </button>
        ))}
      </div>
      {step === "plan" && <Plan on={planDate} setOn={setPlanDate} />}
      {step === "receive" && <Receive on={dayDate} setOn={setDayDate} />}
      {step === "give" && <Give on={dayDate} setOn={setDayDate} onSaved={refreshPending} />}
      {step === "pending" && <Pending onChanged={refreshPending} goGive={(d) => { setDayDate(d); setStep("give"); }} />}
    </>
  );
}

/* ------------------------------------------------------------------ 1. plan + send */
const roundQty = (q, ratio) => (ratio > 1 ? Math.ceil(q - 1e-9) : Math.round(q * 10) / 10);

/** Split `total` across vendors by share; the last vendor takes the remainder so nothing is lost. */
function splitQty(total, split, ratio) {
  const out = split.map((s) => ({ vendor_id: s.vendor_id, qty: roundQty(total * s.share, ratio) }));
  const rest = out.slice(0, -1).reduce((a, l) => a + l.qty, 0);
  out[out.length - 1].qty = Math.max(roundQty(total - rest, ratio), 0);
  return out;
}

function Plan({ on, setOn }) {
  const toast = useToast();
  const plan = useFetch(`/daily-orders/plan?on=${on}`);
  const orders = useFetch(`/daily-orders?on=${on}`);
  const vendors = useFetch("/vendors");
  const items = useFetch("/items");
  const [edits, setEdits] = useState({}); // item_id -> [{vendor_id, qty}]
  const [added, setAdded] = useState([]);
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edits).length > 0 || added.length > 0;
  useUnsavedWarning(dirty);

  useEffect(() => {
    setEdits({});
    setAdded([]);
  }, [on]);

  const activeVendors = (vendors.data || []).filter((v) => v.active);
  const receivedVendors = new Set((plan.data?.orders || []).filter((o) => o.status === "received").map((o) => o.vendor_id));
  const statusOf = (vid) => (plan.data?.orders || []).find((o) => o.vendor_id === Number(vid))?.status;

  const rows = useMemo(() => {
    if (!plan.data) return [];
    const have = new Set(plan.data.rows.map((r) => r.item_id));
    const extra = added.filter((i) => !have.has(i.id)).map((i) => ({
      item_id: i.id, name: i.name, category: i.category, consumption_unit: i.consumption_unit, purchase_unit: i.purchase_unit,
      conversion_ratio: i.conversion_ratio, requested: 0, by_station: [], stock_on_hand: null, suggested_qty: 0,
      default_vendor_id: i.default_vendor_id, planned: [], last_split: null, added: true,
    }));
    return [...plan.data.rows, ...extra];
  }, [plan.data, added]);

  const linesOf = (r) => {
    if (edits[r.item_id]) return edits[r.item_id];
    if (r.planned.length) return r.planned.map((p) => ({ vendor_id: p.vendor_id, qty: p.qty }));
    if (r.last_split) return splitQty(r.suggested_qty, r.last_split, r.conversion_ratio);
    return [{ vendor_id: r.default_vendor_id ?? "", qty: r.suggested_qty }];
  };
  const fromSplit = (r) => !edits[r.item_id] && !r.planned.length && r.last_split;
  const setLines = (r, fn) => setEdits((e) => ({ ...e, [r.item_id]: fn(linesOf(r)) }));
  const isLocked = (l) => receivedVendors.has(Number(l.vendor_id));

  const subtractStock = () => {
    const next = {};
    rows.forEach((r) => {
      if (!r.stock_on_hand) return;
      const ls = linesOf(r);
      if (ls.some(isLocked)) return;
      const need = roundQty(Math.max(r.requested - r.stock_on_hand, 0) / (r.conversion_ratio || 1), r.conversion_ratio);
      const total = ls.reduce((a, l) => a + (l.qty || 0), 0);
      const split = total > 0 ? ls.map((l) => ({ vendor_id: l.vendor_id, share: (l.qty || 0) / total })) : [{ vendor_id: ls[0].vendor_id, share: 1 }];
      next[r.item_id] = splitQty(need, split, r.conversion_ratio);
    });
    setEdits((e) => ({ ...e, ...next }));
    toast("Order quantities reduced by what's already in the store. Review before saving.");
  };

  const save = async () => {
    const merged = {};
    let missing = 0;
    rows.forEach((r) =>
      linesOf(r).forEach((l) => {
        if (isLocked(l) || !(l.qty > 0)) return;
        if (!l.vendor_id) { missing += 1; return; }
        const k = `${r.item_id}|${l.vendor_id}`;
        merged[k] = (merged[k] || 0) + l.qty;
      })
    );
    if (missing) return toast(`Choose a vendor for ${missing} line${missing > 1 ? "s" : ""}.`, "error");
    const lines = Object.entries(merged).map(([k, qty]) => {
      const [item_id, vendor_id] = k.split("|").map(Number);
      return { item_id, vendor_id, qty };
    });
    setBusy(true);
    try {
      orders.setData(await api.put("/daily-orders/plan", { date: on, lines }));
      await plan.reload();
      setEdits({});
      setAdded([]);
      toast("Orders saved. Send each vendor their message below.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const send = async (o) => {
    if (dirty) return toast("Save the plan first so the message matches.", "error");
    try {
      await navigator.clipboard?.writeText(o.message);
    } catch {
      /* copying is a convenience; the link carries the text anyway */
    }
    const touch = window.matchMedia?.("(pointer: coarse)").matches;
    if (o.whatsapp_group && touch && navigator.share) {
      try {
        await navigator.share({ text: o.message });
      } catch {
        return; // share sheet closed without sending
      }
    } else {
      window.open(o.whatsapp_url, "_blank", "noopener");
      if (o.whatsapp_group) toast(`WhatsApp is opening with the message ready. Choose the group "${o.whatsapp_group}".`);
    }
    try {
      await api.post(`/daily-orders/${o.id}/sent`);
      orders.reload();
      plan.reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const copy = async (o) => {
    try {
      await navigator.clipboard.writeText(o.message);
      toast("Message copied.");
    } catch {
      toast("Couldn't copy. Select the text and copy it manually.", "error");
    }
  };

  const late = rows.filter((r) => r.needs_resend);
  let last = null;
  return (
    <div className="stack">
      <div className="panel">
        <div className="panel-head">
          <div className="toolbar"><span className="small muted">Delivery date</span><DayPicker value={on} onChange={setOn} /></div>
          <div className="toolbar">
            <button onClick={subtractStock} disabled={!rows.length}>Subtract stock in store</button>
            <button className="btn-primary" onClick={save} disabled={busy || !rows.length}>{busy ? "Saving…" : "Save orders"}</button>
          </div>
        </div>
        {late.length > 0 && (
          <div className="note note-warn small" style={{ margin: 12 }}>
            Stations changed {late.map((r) => r.name).join(", ")} after the order was sent. Check the quantity, save, and send that vendor the order again.
          </div>
        )}
        <Status loading={plan.loading && !plan.data} error={plan.error} onRetry={plan.reload} />
        {plan.data && rows.length === 0 && (
          <div className="empty">No station has asked for anything for {longDate(on)} yet. Chefs enter tomorrow's needs from their kitchen screen, or add items below.</div>
        )}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Item</th><th>Asked for by</th><th className="num">Total asked</th><th className="num">In store</th>
                  <th className="num" style={{ width: 110 }}>Order</th><th>Unit</th><th style={{ width: 250 }}>Vendor</th><th>Status</th><th style={{ width: 80 }} />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const head = r.category !== last;
                  last = r.category;
                  const ls = linesOf(r);
                  const total = ls.reduce((a, l) => a + (l.qty || 0), 0);
                  const out = [];
                  if (head) out.push(<tr className="group" key={`g-${r.category}`}><td colSpan={9}>{prettyCategory(r.category)}</td></tr>);
                  ls.forEach((l, n) => {
                    const locked = isLocked(l);
                    const st = l.vendor_id ? ORDER_PILL[statusOf(l.vendor_id)] : null;
                    const first = n === 0;
                    out.push(
                      <tr key={`${r.item_id}-${n}`} style={first ? undefined : { background: "var(--bg)" }}>
                        <td>
                          {first ? <>{r.name} {r.any_late && <span className="pill pill-turmeric">changed late</span>}</> : <span className="muted small">↳ split</span>}
                          {first && fromSplit(r) && <div className="xs muted">Split like last time</div>}
                        </td>
                        <td className="small muted">{first ? r.by_station.map((b) => `${b.station} ${qty(b.qty)}`).join(" · ") || (r.added ? "Added by you" : "") : ""}</td>
                        <td className="num">
                          {first && <>{qty(r.requested)} <span className="muted xs">{r.consumption_unit}</span></>}
                          {first && ls.length > 1 && <div className="xs muted">ordering {qty(total)} {r.purchase_unit}</div>}
                        </td>
                        <td className="num muted">{first && r.stock_on_hand != null ? qty(r.stock_on_hand) : ""}</td>
                        <td>
                          {locked ? <span className="num" style={{ display: "block", padding: "4px 6px" }}>{qty(l.qty)}</span> : (
                            <NumCell value={l.qty} dirty={Boolean(edits[r.item_id])} onChange={(q) => setLines(r, (xs) => xs.map((x, i) => (i === n ? { ...x, qty: q } : x)))} />
                          )}
                        </td>
                        <td className="muted small">{r.purchase_unit}</td>
                        <td>
                          <select value={l.vendor_id ?? ""} disabled={locked} style={{ width: "100%" }}
                            onChange={(e) => setLines(r, (xs) => xs.map((x, i) => (i === n ? { ...x, vendor_id: e.target.value ? Number(e.target.value) : "" } : x)))}>
                            <option value="">Choose vendor</option>
                            {activeVendors.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                          </select>
                        </td>
                        <td>{st && <span className={`pill ${st[1]}`}>{st[0]}</span>}</td>
                        <td>
                          {first ? (
                            <button className="btn-sm" title="Order part of this from another vendor" onClick={() => setLines(r, (xs) => [...xs, { vendor_id: "", qty: 0 }])}>Split</button>
                          ) : !locked && (
                            <button className="btn-sm btn-ghost" aria-label="Remove split" onClick={() => setLines(r, (xs) => xs.filter((_, i) => i !== n))}>✕</button>
                          )}
                        </td>
                      </tr>
                    );
                  });
                  return out;
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="panel-body toolbar" style={{ borderTop: "1px solid var(--rule)" }}>
          <span className="small muted">Order something no station asked for:</span>
          <div style={{ width: 320 }}>
            {items.data && (
              <ItemPicker items={items.data.filter((i) => i.daily_order)} value={null} onChange={(i) => setAdded((a) => [...a, i])} renderMeta={(i) => i.purchase_unit} />
            )}
          </div>
        </div>
      </div>

      <h2>Vendor orders for {longDate(on)}</h2>
      {orders.data?.length === 0 && <div className="panel empty">Save the plan to create one order per vendor.</div>}
      <div className="cols-3">
        {(orders.data || []).map((o) => {
          const [label, pill] = ORDER_PILL[o.status];
          return (
            <div className="panel" key={o.id}>
              <div className="panel-head">
                <div>
                  <h3>{o.vendor}</h3>
                  <div className="muted xs">
                    {o.whatsapp_group ? <>WhatsApp group: <b>{o.whatsapp_group}</b></> : o.vendor_phone || "No WhatsApp group or number: add one in Setup → Vendors"}
                  </div>
                </div>
                <span className={`pill ${pill}`}>{label}</span>
              </div>
              <div className="panel-body stack">
                {o.changed_after_send && <div className="note note-warn small">Changed after sending. Send it again.</div>}
                <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: "var(--fs-sm)", background: "var(--bg)", padding: 10, borderRadius: 4 }}>{o.message}</pre>
                <div className="toolbar">
                  {o.status !== "received" && (
                    <button className="btn-primary" onClick={() => send(o)}>
                      {o.status === "sent" ? "Send again" : "Send on WhatsApp"}{o.whatsapp_group ? " (pick group)" : ""}
                    </button>
                  )}
                  <button onClick={() => copy(o)}>Copy message</button>
                </div>
                {o.sent_at && <div className="muted xs">Sent {new Date(o.sent_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ 2. receive */
function Receive({ on, setOn }) {
  const orders = useFetch(`/daily-orders?on=${on}`);
  const prices = useFetch(`/prices/daily?on=${on}`);
  const priceMap = useMemo(() => Object.fromEntries((prices.data || []).map((p) => [p.item_id, p.price])), [prices.data]);
  return (
    <div className="stack">
      <div className="panel panel-body toolbar">
        <span className="small muted">Delivery date</span>
        <DayPicker value={on} onChange={setOn} />
      </div>
      <Status loading={orders.loading && !orders.data} error={orders.error} onRetry={orders.reload} />
      {orders.data?.length === 0 && <div className="panel empty">No vendor orders for {longDate(on)}.</div>}
      {(orders.data || []).map((o) => <ReceiveCard key={o.id} order={o} priceMap={priceMap} onSaved={orders.reload} />)}
    </div>
  );
}

function ReceiveCard({ order, priceMap, onSaved }) {
  const toast = useToast();
  const items = useFetch("/items");
  const [lines, setLines] = useState(() =>
    order.lines.map((l) => ({ ...l, qty_received: l.qty_received ?? l.qty_ordered, rate: l.rate ?? priceMap[l.item_id] ?? null }))
  );
  const [billNo, setBillNo] = useState("");
  const [payment, setPayment] = useState("credit");
  const [paid, setPaid] = useState(null);
  const [photo, setPhoto] = useState(null);
  const [busy, setBusy] = useState(false);
  const received = order.status === "received";

  useEffect(() => {
    setLines((ls) => ls.map((l) => (l.rate == null && priceMap[l.item_id] != null ? { ...l, rate: priceMap[l.item_id] } : l)));
  }, [priceMap]);

  const setLine = (id, patch) => setLines((ls) => ls.map((l) => (l.item_id === id ? { ...l, ...patch } : l)));
  const total = lines.reduce((s, l) => s + (l.qty_received || 0) * (l.rate || 0), 0);

  const save = async () => {
    setBusy(true);
    try {
      const res = await api.post(`/daily-orders/${order.id}/receive`, {
        bill_no: billNo || null,
        payment_status: payment,
        amount_paid: payment === "partial" ? paid : null,
        lines: lines.map((l) => ({ item_id: l.item_id, qty_received: l.qty_received || 0, rate: l.rate })),
      });
      const updated = res.find((x) => x.id === order.id);
      if (photo && updated?.purchase_bill_id) await api.upload(`/purchases/${updated.purchase_bill_id}/photo`, await compressImage(photo));
      toast(`${order.vendor}: receipt saved${updated?.purchase_bill_id ? " and added to Purchases" : ""}.`);
      onSaved();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <h3>{order.vendor}</h3>
          <div className="muted xs">{received ? "Received. You can still correct it." : order.status === "sent" ? "Order sent, waiting for delivery" : "Order not sent yet"}</div>
        </div>
        <span className={`pill ${ORDER_PILL[order.status][1]}`}>{ORDER_PILL[order.status][0]}</span>
      </div>
      <table>
        <thead><tr><th>Item</th><th className="num">Ordered</th><th className="num" style={{ width: 120 }}>Arrived</th><th>Unit</th><th className="num" style={{ width: 120 }}>Rate (₹)</th><th className="num">Amount</th><th /></tr></thead>
        <tbody>
          {lines.map((l) => {
            const short = (l.qty_received || 0) < l.qty_ordered - 1e-9;
            return (
              <tr key={l.item_id}>
                <td>{l.name}</td>
                <td className="num">{qty(l.qty_ordered)}</td>
                <td><NumCell value={l.qty_received} onChange={(v) => setLine(l.item_id, { qty_received: v })} /></td>
                <td className="muted small">{l.purchase_unit}</td>
                <td><NumCell value={l.rate} onChange={(v) => setLine(l.item_id, { rate: v })} /></td>
                <td className="num">{rupees((l.qty_received || 0) * (l.rate || 0), true)}</td>
                <td>{short && <span className="pill pill-chili">short {qty(l.qty_ordered - (l.qty_received || 0))}</span>}</td>
              </tr>
            );
          })}
          <tr className="total"><td colSpan={5}>Bill total</td><td className="num">{rupees(total, true)}</td><td /></tr>
        </tbody>
      </table>
      <div className="panel-body stack">
        <div className="toolbar">
          <span className="small muted">Also arrived (not ordered):</span>
          <div style={{ width: 280 }}>
            {items.data && (
              <ItemPicker
                items={items.data.filter((i) => !lines.some((l) => l.item_id === i.id))}
                value={null}
                onChange={(i) => setLines((ls) => [...ls, { item_id: i.id, name: i.name, purchase_unit: i.purchase_unit, qty_ordered: 0, qty_received: null, rate: priceMap[i.id] ?? null }])}
              />
            )}
          </div>
        </div>
        <div className="form-grid">
          <label className="field">Bill number (optional)<input value={billNo} onChange={(e) => setBillNo(e.target.value)} /></label>
          <label className="field">Payment
            <select value={payment} onChange={(e) => setPayment(e.target.value)}>
              <option value="credit">Credit</option><option value="paid">Paid</option><option value="partial">Part paid</option>
            </select>
          </label>
          {payment === "partial" && <label className="field">Amount paid (₹)<input type="number" min="0" value={paid ?? ""} onChange={(e) => setPaid(toNum(e.target.value))} /></label>}
          <label className="field">Bill photo<input type="file" accept="image/*,application/pdf" capture="environment" onChange={(e) => setPhoto(e.target.files?.[0] || null)} /></label>
        </div>
        <div><button className="btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : received ? "Update receipt" : "Confirm what arrived"}</button></div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ 3. give to stations */
function Give({ on, setOn, onSaved }) {
  const stations = useFetch("/stations");
  const summary = useFetch(`/distribution/summary?on=${on}`);
  const [stationId, setStationId] = useState(null);
  const active = (stations.data || []).filter((s) => s.active);
  useEffect(() => {
    if (!stationId && active.length) setStationId(active[0].id);
  }, [active, stationId]);
  const sum = Object.fromEntries((summary.data || []).map((s) => [s.station_id, s]));
  return (
    <div className="stack">
      <div className="panel panel-body toolbar">
        <span className="small muted">Day</span>
        <DayPicker value={on} onChange={setOn} />
      </div>
      <div className="tabs">
        {active.map((s) => {
          const x = sum[s.id];
          return (
            <button key={s.id} className={s.id === stationId ? "on" : ""} onClick={() => setStationId(s.id)}>
              {s.name}
              {x?.requested_items > 0 && (
                <span className={`pill ${x.pending ? "pill-chili" : "pill-green"}`} style={{ marginLeft: 6 }}>
                  {x.pending ? `${x.pending} pending` : "all given"}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {stationId && <GiveStation key={`${stationId}-${on}`} on={on} stationId={stationId} onSaved={() => { summary.reload(); onSaved(); }} />}
    </div>
  );
}

export function GiveStation({ on, stationId, onSaved, readOnly }) {
  const toast = useToast();
  const { data, setData, loading, error, reload } = useFetch(`/distribution?on=${on}&station_id=${stationId}`);
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  useUnsavedWarning(Object.keys(edits).length > 0);
  if (!data) return <Status loading={loading} error={error} onRetry={reload} />;
  if (!data.rows.length) return <div className="panel empty">This station didn't ask for anything for {longDate(on)}.</div>;
  const given = (r) => (r.item_id in edits ? edits[r.item_id] : r.given ?? (readOnly ? null : r.requested));
  const untouched = data.rows.every((r) => r.given === null);
  const save = async () => {
    setBusy(true);
    try {
      const lines = data.rows.map((r) => ({ item_id: r.item_id, qty_given: given(r) }));
      setData(await api.put("/distribution", { date: on, station_id: stationId, lines }));
      setEdits({});
      toast("Saved. Anything short is now on the Pending list.");
      onSaved?.();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel">
      {!readOnly && untouched && <div className="note small" style={{ margin: 12 }}>Quantities are pre-filled with what the station asked for. Change any that were different, then save.</div>}
      <table>
        <thead>
          <tr><th>Item</th><th>From</th><th className="num">Asked for</th>{!readOnly && <th className="num">In store</th>}<th className="num" style={{ width: 130 }}>Given</th><th>Status</th></tr>
        </thead>
        <tbody>
          {data.rows.map((r) => {
            const g = given(r);
            const short = Math.max(r.requested - (g || 0), 0);
            return (
              <tr key={r.item_id} className={r.pending && r.given != null && !(r.item_id in edits) ? "flag" : ""}>
                <td>{r.name}</td>
                <td><span className={`pill ${r.source === "store" ? "pill-grey" : "pill-green"}`}>{r.source === "store" ? "Store" : "Vendor"}</span></td>
                <td className="num">{qty(r.requested)} <span className="muted xs">{r.unit}</span></td>
                {!readOnly && <td className={`num ${r.in_store < r.requested ? "neg" : "muted"}`}>{qty(r.in_store)}</td>}
                <td>
                  {readOnly ? <span className="num" style={{ display: "block", padding: "4px 6px" }}>{r.given == null ? "–" : qty(r.given)}</span> : (
                    <NumCell value={g} dirty={r.item_id in edits || r.given === null} onChange={(v) => setEdits((e) => ({ ...e, [r.item_id]: v }))} />
                  )}
                </td>
                <td className="small">
                  {r.dismissed ? <span className="muted">Closed: {r.dismissed}</span>
                    : short > 1e-9 ? <><span className="pill pill-chili">short {qty(short)}</span> <span className="muted">{r.reason}</span></>
                    : r.given != null || !readOnly ? <span className="pill pill-green">given</span> : <span className="muted">Not handed over yet</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!readOnly && (
        <div className="panel-body"><button className="btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save what was given"}</button></div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ pending */
function Pending({ onChanged, goGive }) {
  const toast = useToast();
  const { data, loading, error, reload } = useFetch("/pending?days=7");
  const [sel, setSel] = useState(new Set());
  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const dismiss = async () => {
    const reason = window.prompt("Why close these? (e.g. not needed any more, substituted, will come tomorrow)");
    if (!reason) return;
    try {
      await api.post("/pending/dismiss", { requisition_ids: [...sel], reason });
      setSel(new Set());
      reload();
      onChanged();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const share = () => {
    const lines = (data || []).map((p) => `• ${p.station}: ${p.item} short ${qty(p.short)} ${p.unit} (${dayLabel(p.date)}) – ${p.reason}`);
    const text = `*Pending at stations*\n\n${lines.join("\n")}`;
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener");
  };
  if (!data) return <Status loading={loading} error={error} onRetry={reload} />;
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{data.length ? `${data.length} item${data.length > 1 ? "s" : ""} not given in full (last 7 days)` : "Nothing pending"}</h2>
        <div className="toolbar">
          <button onClick={share} disabled={!data.length}>Share on WhatsApp</button>
          <button onClick={dismiss} disabled={!sel.size}>Close selected</button>
        </div>
      </div>
      {data.length === 0 ? <div className="empty">Every station got what it asked for.</div> : (
        <table>
          <thead><tr><th style={{ width: 30 }} /><th>Day</th><th>Station</th><th>Item</th><th className="num">Asked</th><th className="num">Given</th><th className="num">Short</th><th>Why</th><th /></tr></thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.requisition_id}>
                <td><input type="checkbox" aria-label="Select" checked={sel.has(p.requisition_id)} onChange={() => toggle(p.requisition_id)} /></td>
                <td>{dayLabel(p.date)}</td>
                <td>{p.station}</td>
                <td>{p.item}</td>
                <td className="num">{qty(p.requested)}</td>
                <td className="num">{qty(p.given)}</td>
                <td className="num neg">{qty(p.short)} <span className="muted xs">{p.unit}</span></td>
                <td className="small">{p.reason}</td>
                <td><button className="btn-sm" onClick={() => goGive(p.date)}>Give now</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
