import { useEffect, useMemo, useState } from "react";
import { ItemPicker, Modal, PageHead, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch } from "../lib/hooks";
import { prettyCategory, toNum } from "../lib/format";

const TABS = [
  ["items", "Items"],
  ["stations", "Stations"],
  ["vendors", "Vendors"],
  ["daily", "Daily ordering"],
  ["channels", "Channels"],
  ["expenses", "Expense categories"],
  ["staff", "Staff"],
  ["users", "Users"],
  ["settings", "Settings"],
];

export default function Setup({ currentUser }) {
  const [tab, setTab] = useState("items");
  return (
    <>
      <PageHead title="Setup" intro="Master data used across the app. Deactivate instead of deleting so past records keep their names." />
      <div className="tabs">
        {TABS.map(([k, l]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "items" && <Items />}
      {tab === "stations" && <Stations />}
      {tab === "vendors" && <SimpleList path="/vendors" label="vendor" withPhone />}
      {tab === "daily" && <DailyItems />}
      {tab === "channels" && <Channels />}
      {tab === "expenses" && <SimpleList path="/expense-categories" label="expense category" />}
      {tab === "staff" && <SimpleList path="/staff" label="staff member" />}
      {tab === "users" && <Users currentUser={currentUser} />}
      {tab === "settings" && <Settings />}
    </>
  );
}

/* ---------- items ---------- */
function Items() {
  const { data, loading, error, reload } = useFetch("/items?include_inactive=true");
  const cats = useFetch("/categories");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [editing, setEditing] = useState(null);
  const rows = useMemo(
    () => (data || []).filter((i) => (!q || i.name.toLowerCase().includes(q.toLowerCase())) && (!cat || i.category === cat)),
    [data, q, cat]
  );
  return (
    <div className="panel">
      <div className="panel-head">
        <div className="toolbar">
          <input className="search" placeholder="Search items" value={q} onChange={(e) => setQ(e.target.value)} />
          <select value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All categories</option>
            {(cats.data || []).map((c) => <option key={c} value={c}>{prettyCategory(c)}</option>)}
          </select>
          <span className="muted small">{rows.length} items</span>
        </div>
        <button className="btn-primary" onClick={() => setEditing({})}>Add item</button>
      </div>
      <Status loading={loading && !data} error={error} onRetry={reload} />
      {data && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Item</th><th>Category</th><th>Pricing</th><th>Purchase unit</th><th className="num">Conversion</th><th>Consumption unit</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id} style={{ cursor: "pointer" }} onClick={() => setEditing(i)}>
                  <td>{i.name}</td>
                  <td>{prettyCategory(i.category)}</td>
                  <td>{i.pricing_mode === "daily" ? "Daily" : "Weekly average"}</td>
                  <td>{i.purchase_unit}</td>
                  <td className="num">{i.conversion_ratio === 1 ? "–" : `1 = ${i.conversion_ratio}`}</td>
                  <td>{i.consumption_unit}</td>
                  <td>{i.active ? <span className="pill pill-green">Active</span> : <span className="pill pill-grey">Inactive</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <ItemForm item={editing} categories={cats.data || []} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); cats.reload(); }} />
      )}
    </div>
  );
}

function ItemForm({ item, categories, onClose, onSaved }) {
  const toast = useToast();
  const [f, setF] = useState({ name: "", category: "", pricing_mode: "weekly_avg", purchase_unit: "Kg", consumption_unit: "Kg", conversion_ratio: 1, active: true, daily_order: false, default_vendor_id: null, ...item });
  const vendors = useFetch("/vendors");
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const save = async () => {
    try {
      const body = { name: f.name, category: f.category, pricing_mode: f.pricing_mode, purchase_unit: f.purchase_unit, consumption_unit: f.consumption_unit, conversion_ratio: f.conversion_ratio || 1, active: f.active, daily_order: f.daily_order, default_vendor_id: f.default_vendor_id ? Number(f.default_vendor_id) : null };
      if (item.id) await api.patch(`/items/${item.id}`, body);
      else await api.post("/items", body);
      toast(item.id ? "Item updated." : "Item added.");
      onSaved();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  return (
    <Modal title={item.id ? `Edit ${item.name}` : "Add item"} onClose={onClose} footer={<><button onClick={onClose}>Cancel</button><button className="btn-primary" onClick={save}>{item.id ? "Save item" : "Add item"}</button></>}>
      <datalist id="cats">{categories.map((c) => <option key={c} value={c} />)}</datalist>
      <div className="stack">
        <div className="form-grid">
          <label className="field">Name<input value={f.name} onChange={(e) => set("name", e.target.value)} /></label>
          <label className="field">Category<input list="cats" value={f.category} onChange={(e) => set("category", e.target.value)} /></label>
          <label className="field">Pricing
            <select value={f.pricing_mode} onChange={(e) => set("pricing_mode", e.target.value)}>
              <option value="weekly_avg">Weekly average (dry goods, packaging)</option>
              <option value="daily">Daily (vegetables, meat, dairy)</option>
            </select>
          </label>
        </div>
        <div className="form-grid">
          <label className="field">Bought in<input value={f.purchase_unit} onChange={(e) => set("purchase_unit", e.target.value)} /></label>
          <label className="field">Used in<input value={f.consumption_unit} onChange={(e) => set("consumption_unit", e.target.value)} /></label>
          <label className="field">How many {f.consumption_unit || "units"} in 1 {f.purchase_unit || "unit"}
            <input type="number" min="0" step="any" value={f.conversion_ratio ?? ""} onChange={(e) => set("conversion_ratio", toNum(e.target.value))} />
          </label>
        </div>
        <label className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} /> Active (shown in entry screens and audits)
        </label>
        <div className="form-grid">
          <label className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={f.daily_order} onChange={(e) => set("daily_order", e.target.checked)} /> Ordered daily from a vendor
          </label>
          {f.daily_order && (
            <label className="field">First-choice vendor
              <select value={f.default_vendor_id || ""} onChange={(e) => set("default_vendor_id", e.target.value || null)}>
                <option value="">None</option>
                {(vendors.data || []).filter((v) => v.active).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
            </label>
          )}
        </div>
        {item.id && <div className="note small">Changing the conversion changes how past purchases convert into stock. Change it only to fix a mistake.</div>}
      </div>
    </Modal>
  );
}

/* ---------- stations ---------- */
const KINDS = [["kitchen", "Kitchen (counts in food cost %)"], ["staff", "Staff meals / utilities"], ["packaging", "Packaging"], ["daily_items", "Daily items (drinks, breads…)"]];

function Stations() {
  const toast = useToast();
  const { data, loading, error, reload } = useFetch("/stations");
  const items = useFetch("/items");
  const [sel, setSel] = useState(null);
  const [assigned, setAssigned] = useState(null);
  const [newName, setNewName] = useState("");

  useEffect(() => {
    if (!sel) return;
    setAssigned(null);
    api.get(`/stations/${sel}/items`).then(setAssigned).catch((e) => toast(e.message, "error"));
  }, [sel, toast]);

  const patch = async (s, body) => {
    try {
      await api.patch(`/stations/${s.id}`, body);
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const add = async () => {
    if (!newName.trim()) return;
    await api.post("/stations", { name: newName.trim(), kind: "kitchen", sort: (data || []).length });
    setNewName("");
    reload();
  };
  const saveItems = async () => {
    try {
      await api.put(`/stations/${sel}/items`, { item_ids: assigned.map((i) => i.id) });
      toast("Station items saved.");
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="cols-2" style={{ alignItems: "start" }}>
      <div className="panel">
        <div className="panel-head"><h2>Stations</h2></div>
        <Status loading={loading && !data} error={error} />
        {data && (
          <table>
            <thead><tr><th>Name</th><th>Counts as</th><th className="num">Items</th><th>Active</th><th /></tr></thead>
            <tbody>
              {data.map((s) => (
                <tr key={s.id} style={sel === s.id ? { background: "var(--green-wash)" } : undefined}>
                  <td><input className="cell" defaultValue={s.name} onBlur={(e) => e.target.value !== s.name && patch(s, { name: e.target.value })} /></td>
                  <td>
                    <select value={s.kind} onChange={(e) => patch(s, { kind: e.target.value })}>
                      {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                  </td>
                  <td className="num">{s.item_count}</td>
                  <td><input type="checkbox" checked={s.active} onChange={(e) => patch(s, { active: e.target.checked })} aria-label="Active" /></td>
                  <td><button className="btn-sm" onClick={() => setSel(s.id)}>Items</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="panel-body toolbar">
          <input placeholder="New station name" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <button onClick={add}>Add station</button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>{sel ? `${data?.find((s) => s.id === sel)?.name} items` : "Station items"}</h2>
          {sel && assigned && <button className="btn-primary" onClick={saveItems}>Save list</button>}
        </div>
        {!sel && <div className="empty">Choose a station to edit the items shown on its entry screen.</div>}
        {sel && !assigned && <div className="empty">Loading…</div>}
        {sel && assigned && (
          <div className="panel-body stack">
            {items.data && (
              <ItemPicker
                items={items.data.filter((i) => !assigned.some((a) => a.id === i.id))}
                value={null}
                placeholder="Add an item to this station"
                onChange={(i) => setAssigned((a) => [...a, i])}
                renderMeta={(i) => prettyCategory(i.category)}
              />
            )}
            <div className="table-wrap" style={{ maxHeight: 520 }}>
              <table>
                <tbody>
                  {assigned.map((i) => (
                    <tr key={i.id}>
                      <td>{i.name}</td>
                      <td className="muted small">{prettyCategory(i.category)}</td>
                      <td style={{ width: 40 }}><button className="btn-sm btn-ghost" aria-label={`Remove ${i.name}`} onClick={() => setAssigned((a) => a.filter((x) => x.id !== i.id))}>✕</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- vendors / expense categories / staff ---------- */
function SimpleList({ path, label, withPhone }) {
  const toast = useToast();
  const { data, loading, error, reload } = useFetch(path);
  const [name, setName] = useState("");
  const save = async (row, patch) => {
    try {
      const body = withPhone
        ? { name: row.name, phone: row.phone, whatsapp_group: row.whatsapp_group, active: row.active, ...patch }
        : { name: row.name, active: row.active, ...patch };
      await api.patch(`${path}/${row.id}`, body);
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const add = async () => {
    if (!name.trim()) return;
    try {
      await api.post(path, { name: name.trim() });
      setName("");
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  return (
    <div className="panel" style={{ maxWidth: 720 }}>
      <div className="panel-body toolbar">
        <input placeholder={`New ${label}`} value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn-primary" onClick={add}>Add {label}</button>
      </div>
      <Status loading={loading && !data} error={error} />
      {data && (
        <table>
          <thead><tr><th>Name</th>{withPhone && <><th>WhatsApp group (orders go here)</th><th>Phone (optional)</th></>}<th>Active</th></tr></thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.id}>
                <td><input className="cell" defaultValue={r.name} onBlur={(e) => e.target.value !== r.name && save(r, { name: e.target.value })} /></td>
                {withPhone && <td><input className="cell" placeholder="e.g. Raju Veg Orders" defaultValue={r.whatsapp_group || ""} onBlur={(e) => e.target.value !== (r.whatsapp_group || "") && save(r, { whatsapp_group: e.target.value || null })} /></td>}
                {withPhone && <td><input className="cell" defaultValue={r.phone || ""} onBlur={(e) => e.target.value !== (r.phone || "") && save(r, { phone: e.target.value || null })} /></td>}
                <td><input type="checkbox" checked={r.active} onChange={(e) => save(r, { active: e.target.checked })} aria-label="Active" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data?.length === 0 && <div className="empty">None yet.</div>}
    </div>
  );
}

/* ---------- channels ---------- */
const CH_KINDS = [["discount", "Discounts"], ["delivery", "Delivery"], ["ads", "Ads"]];

function Channels() {
  const toast = useToast();
  const { data, loading, error, reload } = useFetch("/channels");
  const [f, setF] = useState({ platform: "", brand: "" });
  const save = async (c, patch) => {
    try {
      await api.patch(`/channels/${c.id}`, { platform: c.platform, brand: c.brand, kinds: c.kinds, sort: c.sort, active: c.active, ...patch });
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const add = async () => {
    if (!f.platform.trim() || !f.brand.trim()) return toast("Enter a platform and a brand.", "error");
    await api.post("/channels", { ...f, sort: (data || []).length });
    setF({ platform: f.platform, brand: "" });
    reload();
  };
  const platforms = [...new Set((data || []).map((c) => c.platform))];
  return (
    <div className="panel" style={{ maxWidth: 900 }}>
      <div className="panel-body toolbar">
        <datalist id="platforms">{platforms.map((p) => <option key={p} value={p} />)}</datalist>
        <input list="platforms" placeholder="Platform (e.g. Swiggy)" value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value })} />
        <input placeholder="Brand (e.g. Oh Delhi)" value={f.brand} onChange={(e) => setF({ ...f, brand: e.target.value })} />
        <button className="btn-primary" onClick={add}>Add channel</button>
      </div>
      <Status loading={loading && !data} error={error} />
      {data && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Platform</th><th>Brand</th>{CH_KINDS.map(([k, l]) => <th key={k}>{l}</th>)}<th>Active</th></tr></thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id}>
                  <td>{c.platform}</td>
                  <td><input className="cell" defaultValue={c.brand} onBlur={(e) => e.target.value !== c.brand && save(c, { brand: e.target.value })} /></td>
                  {CH_KINDS.map(([k]) => (
                    <td key={k}>
                      <input
                        type="checkbox"
                        aria-label={k}
                        checked={c.kinds.includes(k)}
                        onChange={(e) => save(c, { kinds: e.target.checked ? [...c.kinds, k] : c.kinds.filter((x) => x !== k) })}
                      />
                    </td>
                  ))}
                  <td><input type="checkbox" aria-label="Active" checked={c.active} onChange={(e) => save(c, { active: e.target.checked })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------- settings ---------- */
function Settings() {
  const toast = useToast();
  const { data, setData } = useFetch("/settings");
  if (!data) return <div className="empty">Loading…</div>;
  const save = async () => {
    try {
      setData(await api.put("/settings", data));
      toast("Settings saved.");
    } catch (e) {
      toast(e.message, "error");
    }
  };
  return (
    <div className="panel panel-body stack" style={{ maxWidth: 520 }}>
      <label className="field">Outlet name (used on the P&L PDF)
        <input value={data.outlet_name} onChange={(e) => setData({ ...data, outlet_name: e.target.value })} />
      </label>
      <label className="field">Flag audit variance above (%)
        <input type="number" min="0.1" step="0.1" value={data.variance_threshold_pct} onChange={(e) => setData({ ...data, variance_threshold_pct: e.target.value })} />
      </label>
      <div className="muted xs">Variance % = (expected − counted) ÷ expected, where expected = opening + purchases − issued.</div>
      <div><button className="btn-primary" onClick={save}>Save settings</button></div>
    </div>
  );
}

/* ---------- users (built-in login) ---------- */
function Users({ currentUser }) {
  const toast = useToast();
  const { data, loading, error, reload } = useFetch("/users");
  const [f, setF] = useState({ name: "", email: "", password: "", station_id: "" });
  const stations = useFetch("/stations");
  const [pw, setPw] = useState({ current_password: "", new_password: "", repeat: "" });

  const add = async (e) => {
    e.preventDefault();
    try {
      await api.post("/users", { ...f, station_id: f.station_id ? Number(f.station_id) : null });
      toast(`Added ${f.email}. Share the password with them; they can change it in Setup → Users.`);
      setF({ name: "", email: "", password: "", station_id: "" });
      reload();
    } catch (err) {
      toast(err.message, "error");
    }
  };
  const patch = async (u, body, msg) => {
    try {
      await api.patch(`/users/${u.id}`, body);
      if (msg) toast(msg);
      reload();
    } catch (err) {
      toast(err.message, "error");
    }
  };
  const resetPassword = (u) => {
    const p = window.prompt(`New password for ${u.email} (at least 8 characters):`);
    if (p) patch(u, { password: p }, `Password reset for ${u.email}. They have been signed out.`);
  };
  const changeOwn = async (e) => {
    e.preventDefault();
    if (pw.new_password !== pw.repeat) return toast("The new passwords don't match.", "error");
    try {
      await api.post("/auth/password", { current_password: pw.current_password, new_password: pw.new_password });
      toast("Password changed. Other devices have been signed out.");
      setPw({ current_password: "", new_password: "", repeat: "" });
    } catch (err) {
      toast(err.message, "error");
    }
  };

  return (
    <div className="cols-2" style={{ alignItems: "start" }}>
      <div className="panel">
        <div className="panel-head"><h2>People who can sign in</h2></div>
        <Status loading={loading && !data} error={error} />
        {data && (
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Opens</th><th>Last sign-in</th><th>Active</th><th /></tr></thead>
            <tbody>
              {data.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td className="small">{u.email}</td>
                  <td>
                    <select value={u.station_id || ""} onChange={(e) => patch(u, { station_id: e.target.value ? Number(e.target.value) : null })} aria-label="Opens">
                      <option value="">Full app</option>
                      {(stations.data || []).map((s) => <option key={s.id} value={s.id}>{s.name} kitchen screen</option>)}
                    </select>
                  </td>
                  <td className="muted small">{u.last_login_at ? new Date(u.last_login_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "Never"}</td>
                  <td>
                    <input type="checkbox" aria-label="Active" checked={u.active} disabled={u.id === currentUser?.id}
                      onChange={(e) => patch(u, { active: e.target.checked }, e.target.checked ? `${u.email} can sign in again.` : `${u.email} has been signed out and can't sign in.`)} />
                  </td>
                  <td><button className="btn-sm" onClick={() => resetPassword(u)}>Reset password</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form className="panel-body stack" onSubmit={add} style={{ borderTop: "1px solid var(--rule)" }}>
          <h3>Add a person</h3>
          <div className="form-grid">
            <label className="field">Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></label>
            <label className="field">Email<input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required /></label>
            <label className="field">Starting password<input value={f.password} minLength={8} onChange={(e) => setF({ ...f, password: e.target.value })} required /></label>
            <label className="field">Opens
              <select value={f.station_id} onChange={(e) => setF({ ...f, station_id: e.target.value })}>
                <option value="">Full app (owner, manager, store)</option>
                {(stations.data || []).map((s) => <option key={s.id} value={s.id}>{s.name} kitchen screen</option>)}
              </select>
            </label>
          </div>
          <div className="muted xs">For a shared kitchen device, create one login per station (e.g. indian@ohdelhi.in). It opens a simple screen for that station. This is a convenience, not a permission: there are no roles yet.</div>
          <div><button className="btn-primary">Add person</button></div>
        </form>
      </div>

      {currentUser?.id !== 0 && (
        <form className="panel panel-body stack" onSubmit={changeOwn} style={{ maxWidth: 420 }}>
          <h3>Change your password</h3>
          <label className="field">Current password<input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required /></label>
          <label className="field">New password (8+ characters)<input type="password" autoComplete="new-password" minLength={8} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required /></label>
          <label className="field">Repeat new password<input type="password" autoComplete="new-password" value={pw.repeat} onChange={(e) => setPw({ ...pw, repeat: e.target.value })} required /></label>
          <div><button className="btn-primary">Change password</button></div>
        </form>
      )}
    </div>
  );
}

/* ---------- daily ordering: which items, which vendor ---------- */
function DailyItems() {
  const toast = useToast();
  const { data, loading, error, reload } = useFetch("/items");
  const vendors = useFetch("/vendors");
  const [q, setQ] = useState("");
  const daily = (data || []).filter((i) => i.daily_order && (!q || i.name.toLowerCase().includes(q.toLowerCase())));
  const patch = async (i, body) => {
    try {
      await api.patch(`/items/${i.id}`, body);
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const bulk = async (category, vendorId) => {
    const targets = daily.filter((i) => i.category === category);
    if (!vendorId || !window.confirm(`Set the first-choice vendor for all ${targets.length} ${prettyCategory(category).toLowerCase()} items?`)) return;
    try {
      await Promise.all(targets.map((i) => api.patch(`/items/${i.id}`, { default_vendor_id: Number(vendorId) })));
      reload();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const activeVendors = (vendors.data || []).filter((v) => v.active);
  const cats = [...new Set(daily.map((i) => i.category))];
  return (
    <div className="stack" style={{ maxWidth: 900 }}>
      <div className="note small">
        These items appear on the chefs' "Order for tomorrow" screen and in Daily orders. The first-choice vendor is pre-selected when you plan, and you can switch any line to another vendor before sending (e.g. your second vegetable vendor). Vendor WhatsApp numbers are set in Setup → Vendors.
      </div>
      <div className="panel">
        <div className="panel-head">
          <input className="search" placeholder="Search daily items" value={q} onChange={(e) => setQ(e.target.value)} />
          <div style={{ width: 320 }}>
            {data && (
              <ItemPicker items={data.filter((i) => !i.daily_order)} value={null} placeholder="Add an item to daily ordering" onChange={(i) => patch(i, { daily_order: true })} />
            )}
          </div>
        </div>
        <Status loading={loading && !data} error={error} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>Item</th><th>Unit ordered</th><th style={{ width: 240 }}>First-choice vendor</th><th /></tr></thead>
            <tbody>
              {cats.map((c) => [
                <tr className="group" key={`g-${c}`}>
                  <td colSpan={2}>{prettyCategory(c)}</td>
                  <td>
                    <select value="" onChange={(e) => bulk(c, e.target.value)} aria-label={`Set vendor for all ${c}`}>
                      <option value="">Set for all in this group…</option>
                      {activeVendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                    </select>
                  </td>
                  <td />
                </tr>,
                ...daily.filter((i) => i.category === c).map((i) => (
                  <tr key={i.id}>
                    <td>{i.name}</td>
                    <td className="muted">{i.purchase_unit}</td>
                    <td>
                      <select value={i.default_vendor_id || ""} onChange={(e) => patch(i, { default_vendor_id: e.target.value ? Number(e.target.value) : null })} style={{ width: "100%" }}>
                        <option value="">Not set</option>
                        {activeVendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                      </select>
                    </td>
                    <td><button className="btn-sm btn-ghost" onClick={() => patch(i, { daily_order: false })}>Remove</button></td>
                  </tr>
                )),
              ])}
            </tbody>
          </table>
          {data && daily.length === 0 && <div className="empty">No daily-order items.</div>}
        </div>
      </div>
    </div>
  );
}
