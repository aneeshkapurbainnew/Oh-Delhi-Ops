const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const qtyFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });

export const rupees = (v, decimals = false) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "–"
    : `${v < 0 ? "−" : ""}₹${(decimals ? inr2 : inr).format(Math.abs(v))}`;
export const qty = (v) => (v === null || v === undefined ? "–" : qtyFmt.format(v));
export const pct = (v, d = 1) => (v === null || v === undefined ? "–" : `${Number(v).toFixed(d)}%`);

export const todayISO = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
export const thisMonth = () => todayISO().slice(0, 7);
export const monthLabel = (m) =>
  new Date(`${m}-01T00:00:00`).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
export const dayLabel = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
export const longDate = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
export const dayNum = (iso) => Number(iso.slice(8, 10));
export const isWeekend = (iso) => [0, 6].includes(new Date(`${iso}T00:00:00`).getDay());
export const prettyCategory = (c) =>
  (c || "").toLowerCase().replace(/_/g, " ").replace(/^\w/, (x) => x.toUpperCase());
export const shiftMonth = (m, delta) => {
  const [y, mo] = m.split("-").map(Number);
  const d = new Date(y, mo - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
export const shiftDay = (iso, delta) => {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + delta);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
export const toNum = (s) => (s === "" || s === null || s === undefined ? null : Number(s));
