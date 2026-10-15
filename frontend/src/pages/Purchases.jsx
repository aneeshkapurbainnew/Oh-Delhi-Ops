import { useEffect, useMemo, useState } from "react";
import { ItemPicker, Modal, MonthPicker, PageHead, Seg, Status, useToast } from "../components/ui";
import { api, apiBase } from "../lib/api";
import { useFetch } from "../lib/hooks";
import { compressImage } from "../lib/image";
import { dayLabel, rupees, thisMonth, todayISO, toNum } from "../lib/format";

const STATUS_PILL = { paid: "pill-green", credit: "pill-chili", partial: "pill-turmeric" };
const STATUS_LABEL = { paid: "Paid", credit: "Credit", partial: "Part paid" };

function monthRange(m) {
  const [y, mo] = m.split("-").map(Number);
  const last = new Date(y, mo, 0).getDate();
  return [`${m}-01`, `${m}-${String(last).padStart(2, "0")}`];
}

// eslint-disable-next-line no-unused-vars
export function openPhoto(billId, _toast) {
  window.open(`${apiBase}/api/purchases/${billId}/photo`, "_blank", "noopener");
}

export default function Purchases() {
  const toast = useToast();
  const [month, setMonth] = useState(thisMonth());
  const [vendorId, setVendorId] = useState("");
  const [start, end] = monthRange(month);
  const list = useFetch(`/purchases?start=${start}&end=${end}${vendorId ? `&vendor_id=${vendorId}` : ""}`);
  const outstanding = useFetch("/purchases/outstanding");
  const vendors = useFetch("/vendors");
  const items = useFetch("/items");
  const [editing, setEditing] = useState(null); // null | "new" | bill id

  const refresh = () => {
    list.reload();
    outstanding.reload();
  };

  return (
    <>
      <PageHead title="Purchases" intro="Every bill line moves stock in and updates that item's price.">
        <MonthPicker value={month} onChange={setMonth} />
        <select value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
          <option value="">All vendors</option>
          {(vendors.data || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
        </select>
        <button className="btn-primary" onClick={() => setEditing("new")}>Add bill</button>
      </PageHead>

      <div className="stack">
        {outstanding.data?.length > 0 && (
          <div className="panel">
            <div className="panel-head"><h2>Unpaid by vendor</h2></div>
            <div className="panel-body" style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              {outstanding.data.map((v) => (
                <div key={v.vendor_id}>
                  <div className="small">{v.vendor}</div>
                  <div style={{ fontWeight: 650 }} className="num">{rupees(v.outstanding)}</div>
                  <div className="muted xs">{v.bills} bill{v.bills > 1 ? "s" : ""}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="panel">
          <Status loading={list.loading && !list.data} error={list.error} onRetry={list.reload} />
          {list.data && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th><th>Vendor</th><th>Bill no.</th><th className="num">Lines</th>
                    <th className="num">Total</th><th>Payment</th><th className="num">Unpaid</th><th>Photo</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.bills.map((b) => (
                    <tr key={b.id} style={{ cursor: "pointer" }} onClick={() => setEditing(b.id)}>
                      <td>{dayLabel(b.date)}</td>
                      <td>{b.vendor}</td>
                      <td className="muted">{b.bill_no || "–"}</td>
                      <td className="num">{b.line_count}</td>
                      <td className="num">{rupees(b.total, true)}</td>
                      <td><span className={`pill ${STATUS_PILL[b.payment_status]}`}>{STATUS_LABEL[b.payment_status]}</span></td>
                      <td className="num">{b.outstanding > 0 ? rupees(b.outstanding, true) : "–"}</td>
                      <td>
                        {b.has_photo ? (
                          <button className="btn-sm" onClick={(e) => { e.stopPropagation(); openPhoto(b.id, toast); }}>View</button>
                        ) : (
                          <span className="pill pill-turmeric">missing</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {list.data.bills.length > 0 && (
                    <tr className="total">
                      <td colSpan={4}>Month total</td>
                      <td className="num">{rupees(list.data.total, true)}</td>
                      <td />
                      <td className="num">{rupees(list.data.outstanding, true)}</td>
                      <td />
                    </tr>
                  )}
                </tbody>
              </table>
              {list.data.bills.length === 0 && <div className="empty">No bills this month. Add the first bill to start tracking stock and prices.</div>}
            </div>
          )}
        </div>
      </div>

      {editing && items.data && vendors.data && (
        <BillEditor
          billId={editing === "new" ? null : editing}
          items={items.data}
          vendors={vendors.data}
          onVendorAdded={vendors.reload}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            refresh();
          }}
        />
      )}
    </>
  );
}

const blankLine = () => ({ key: Math.random(), item_id: null, qty: null, rate: null });

function BillEditor({ billId, items, vendors, onVendorAdded, onClose, onSaved }) {
  const toast = useToast();
  const [bill, setBill] = useState(
    billId ? null : { vendor_id: "", date: todayISO(), bill_no: "", payment_status: "paid", amount_paid: null, notes: "", lines: [blankLine()] }
  );
  const [photo, setPhoto] = useState(null);
  const [hasPhoto, setHasPhoto] = useState(false);
  const [busy, setBusy] = useState(false);
  const [newVendor, setNewVendor] = useState("");
  const byId = useMemo(() => Object.fromEntries(items.map((i) => [i.id, i])), [items]);

  useEffect(() => {
    if (!billId) return;
    api.get(`/purchases/${billId}`).then((b) => {
      setHasPhoto(b.has_photo);
      setBill({ ...b, bill_no: b.bill_no || "", notes: b.notes || "", lines: b.lines.map((l) => ({ ...l, key: l.id })) });
    }).catch((e) => toast(e.message, "error"));
  }, [billId, toast]);

  if (!bill) return <Modal title="Bill" onClose={onClose}><div className="empty">Loading…</div></Modal>;

  const set = (k, v) => setBill((b) => ({ ...b, [k]: v }));
  const setLine = (key, patch) => setBill((b) => ({ ...b, lines: b.lines.map((l) => (l.key === key ? { ...l, ...patch } : l)) }));
  const total = bill.lines.reduce((s, l) => s + (l.qty || 0) * (l.rate || 0), 0);

  const addVendor = async () => {
    if (!newVendor.trim()) return;
    try {
      const v = await api.post("/vendors", { name: newVendor.trim() });
      await onVendorAdded();
      set("vendor_id", v.id);
      setNewVendor("");
    } catch (e) {
      toast(e.message, "error");
    }
  };

  const save = async () => {
    const lines = bill.lines.filter((l) => l.item_id);
    if (!bill.vendor_id) return toast("Choose a vendor.", "error");
    if (!lines.length) return toast("Add at least one item.", "error");
    if (lines.some((l) => !l.qty || l.rate === null)) return toast("Every line needs a quantity and a rate.", "error");
    setBusy(true);
    try {
      const body = {
        vendor_id: Number(bill.vendor_id),
        date: bill.date,
        bill_no: bill.bill_no || null,
        payment_status: bill.payment_status,
        amount_paid: bill.payment_status === "partial" ? bill.amount_paid : null,
        notes: bill.notes || null,
        lines: lines.map((l) => ({ item_id: l.item_id, qty: l.qty, rate: l.rate })),
      };
      const saved = billId ? await api.put(`/purchases/${billId}`, body) : await api.post("/purchases", body);
      if (photo) await api.upload(`/purchases/${saved.id}/photo`, await compressImage(photo));
      toast(billId ? "Bill updated." : "Bill saved.");
      onSaved();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete this bill? Its stock and prices are removed too.")) return;
    try {
      await api.del(`/purchases/${billId}`);
      toast("Bill deleted.");
      onSaved();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <Modal
      title={billId ? "Edit bill" : "Add bill"}
      onClose={onClose}
      wide
      footer={
        <>
          {billId && <button className="btn-danger" style={{ marginRight: "auto" }} onClick={remove}>Delete bill</button>}
          <button onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : billId ? "Save changes" : "Save bill"}</button>
        </>
      }
    >
      <div className="stack">
        <div className="form-grid">
          <label className="field">Vendor
            <select value={bill.vendor_id} onChange={(e) => set("vendor_id", e.target.value)}>
              <option value="">Choose vendor</option>
              {vendors.filter((v) => v.active || v.id === bill.vendor_id).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </label>
          <label className="field">New vendor
            <div style={{ display: "flex", gap: 4 }}>
              <input value={newVendor} onChange={(e) => setNewVendor(e.target.value)} placeholder="Name" style={{ flex: 1 }} />
              <button className="btn-sm" onClick={addVendor} type="button">Add</button>
            </div>
          </label>
          <label className="field">Bill date<input type="date" value={bill.date} onChange={(e) => set("date", e.target.value)} /></label>
          <label className="field">Bill number (optional)<input value={bill.bill_no} onChange={(e) => set("bill_no", e.target.value)} /></label>
        </div>
        <div className="form-grid">
          <label className="field">Payment
            <Seg options={[["paid", "Paid"], ["credit", "Credit"], ["partial", "Part paid"]]} value={bill.payment_status} onChange={(v) => set("payment_status", v)} />
          </label>
          {bill.payment_status === "partial" && (
            <label className="field">Amount paid (₹)
              <input type="number" min="0" value={bill.amount_paid ?? ""} onChange={(e) => set("amount_paid", toNum(e.target.value))} />
            </label>
          )}
          <label className="field">Bill photo {hasPhoto && !photo && "(uploaded; choose a file to replace)"}
            <input type="file" accept="image/*,application/pdf" capture="environment" onChange={(e) => setPhoto(e.target.files?.[0] || null)} />
          </label>
        </div>

        <table>
          <thead>
            <tr><th style={{ width: "42%" }}>Item</th><th className="num">Quantity</th><th>Unit</th><th className="num">Rate (₹ / unit)</th><th className="num">Amount</th><th /></tr>
          </thead>
          <tbody>
            {bill.lines.map((l) => {
              const it = byId[l.item_id];
              return (
                <tr key={l.key}>
                  <td><ItemPicker items={items} value={l.item_id} onChange={(i) => setLine(l.key, { item_id: i.id })} renderMeta={(i) => i.purchase_unit} /></td>
                  <td><input type="number" min="0" step="any" style={{ width: 100 }} value={l.qty ?? ""} onChange={(e) => setLine(l.key, { qty: toNum(e.target.value) })} /></td>
                  <td className="muted small">
                    {it?.purchase_unit || "–"}
                    {it && it.conversion_ratio !== 1 && <div className="xs">= {it.conversion_ratio} {it.consumption_unit}</div>}
                  </td>
                  <td><input type="number" min="0" step="any" style={{ width: 110 }} value={l.rate ?? ""} onChange={(e) => setLine(l.key, { rate: toNum(e.target.value) })} /></td>
                  <td className="num">{rupees((l.qty || 0) * (l.rate || 0), true)}</td>
                  <td><button className="btn-sm btn-ghost" aria-label="Remove line" onClick={() => setBill((b) => ({ ...b, lines: b.lines.filter((x) => x.key !== l.key) }))}>✕</button></td>
                </tr>
              );
            })}
            <tr className="total">
              <td><button className="btn-sm" onClick={() => setBill((b) => ({ ...b, lines: [...b.lines, blankLine()] }))}>Add line</button></td>
              <td colSpan={3} className="num">Bill total</td>
              <td className="num">{rupees(total, true)}</td>
              <td />
            </tr>
          </tbody>
        </table>
        <label className="field">Notes<textarea value={bill.notes} onChange={(e) => set("notes", e.target.value)} /></label>
      </div>
    </Modal>
  );
}
