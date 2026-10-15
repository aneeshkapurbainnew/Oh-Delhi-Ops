import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { dayNum, isWeekend, longDate, monthLabel, rupees, shiftDay, shiftMonth, toNum } from "../lib/format";

/* ---------- toast ---------- */
const ToastCtx = createContext(() => {});
export function ToastProvider({ children }) {
  const [t, setT] = useState(null);
  const show = useCallback((msg, kind = "ok") => {
    setT({ msg, kind, id: Date.now() });
  }, []);
  useEffect(() => {
    if (!t) return undefined;
    const h = setTimeout(() => setT(null), t.kind === "error" ? 6000 : 2600);
    return () => clearTimeout(h);
  }, [t]);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {t && (
        <div className={`toast ${t.kind === "error" ? "error" : ""}`} role="status">
          {t.msg}
        </div>
      )}
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/* ---------- layout bits ---------- */
export function PageHead({ title, intro, children }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {intro && <p>{intro}</p>}
      </div>
      {children && <div className="toolbar">{children}</div>}
    </div>
  );
}

export function Status({ loading, error, onRetry }) {
  if (error)
    return (
      <div className="note note-error">
        {error} {onRetry && <button className="btn-sm" onClick={onRetry}>Try again</button>}
      </div>
    );
  if (loading) return <div className="empty">Loading…</div>;
  return null;
}

export function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const h = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={wide ? { width: "min(1100px, 100%)" } : undefined} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

/* ---------- pickers ---------- */
export function MonthPicker({ value, onChange }) {
  return (
    <div className="seg" aria-label="Month">
      <button onClick={() => onChange(shiftMonth(value, -1))} aria-label="Previous month">‹</button>
      <button style={{ minWidth: 140 }} onClick={() => {}} tabIndex={-1}>{monthLabel(value)}</button>
      <button onClick={() => onChange(shiftMonth(value, 1))} aria-label="Next month">›</button>
    </div>
  );
}

export function DayPicker({ value, onChange }) {
  return (
    <div className="toolbar">
      <div className="seg">
        <button onClick={() => onChange(shiftDay(value, -1))} aria-label="Previous day">‹</button>
        <button onClick={() => onChange(shiftDay(value, 1))} aria-label="Next day">›</button>
      </div>
      <input type="date" value={value} onChange={(e) => e.target.value && onChange(e.target.value)} />
      <span className="muted small">{longDate(value)}</span>
    </div>
  );
}

export function Seg({ options, value, onChange }) {
  return (
    <div className="seg">
      {options.map(([v, label]) => (
        <button key={v} className={v === value ? "on" : ""} onClick={() => onChange(v)}>
          {label}
        </button>
      ))}
    </div>
  );
}

/** Searchable item select. items: [{id, name, ...}] */
export function ItemPicker({ items, value, onChange, placeholder = "Search items", renderMeta, autoFocus }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hl, setHl] = useState(0);
  const ref = useRef(null);
  const selected = items.find((i) => i.id === value);
  const matches = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (s ? items.filter((i) => i.name.toLowerCase().includes(s)) : items).slice(0, 60);
  }, [q, items]);
  useEffect(() => {
    const h = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const pick = (i) => {
    onChange(i);
    setQ("");
    setOpen(false);
  };
  return (
    <div className="picker" ref={ref}>
      <input
        style={{ width: "100%" }}
        autoFocus={autoFocus}
        value={open ? q : selected?.name || ""}
        placeholder={placeholder}
        onFocus={() => {
          setOpen(true);
          setHl(0);
        }}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setHl(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setHl((h) => Math.min(h + 1, matches.length - 1));
          else if (e.key === "ArrowUp") setHl((h) => Math.max(h - 1, 0));
          else if (e.key === "Enter" && matches[hl]) {
            e.preventDefault();
            pick(matches[hl]);
          } else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && (
        <div className="picker-list">
          {matches.length === 0 && <div className="muted">No item matches “{q}”.</div>}
          {matches.map((i, n) => (
            <div key={i.id} className={n === hl ? "hl" : ""} onMouseDown={() => pick(i)}>
              <span>{i.name}</span>
              <span className="muted xs">{renderMeta ? renderMeta(i) : ""}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- number cell ---------- */
export function NumCell({ value, onChange, dirty, placeholder, step = "any" }) {
  return (
    <input
      className={`cell ${dirty ? "dirty" : ""}`}
      type="number"
      inputMode="decimal"
      min="0"
      step={step}
      value={value ?? ""}
      placeholder={placeholder}
      onChange={(e) => onChange(toNum(e.target.value))}
      onWheel={(e) => e.currentTarget.blur()}
    />
  );
}

/**
 * Month grid editor used for discounts, delivery, ads and expenses: rows x days.
 * grid: {days, rows:[{id,label,group,values:{iso:amount},total}], day_totals, total}
 */
export function MonthGrid({ grid, edits, setEdits, rowLabel = "Row" }) {
  const days = grid.days;
  const val = (rid, d) => {
    const k = `${rid}|${d}`;
    return k in edits ? edits[k] : grid.rows.find((r) => r.id === rid)?.values[d] ?? null;
  };
  const rowTotal = (r) => days.reduce((s, d) => s + (val(r.id, d) || 0), 0);
  const dayTotal = (d) => grid.rows.reduce((s, r) => s + (val(r.id, d) || 0), 0);
  let lastGroup = null;
  return (
    <div className="table-wrap">
      <table className="grid-month">
        <thead>
          <tr>
            <th className="sticky-col">{rowLabel}</th>
            {days.map((d) => (
              <th key={d} className={`day num ${isWeekend(d) ? "weekend" : ""}`}>{dayNum(d)}</th>
            ))}
            <th className="num">Month</th>
          </tr>
        </thead>
        <tbody>
          {grid.rows.map((r) => {
            const header = r.group && r.group !== lastGroup;
            lastGroup = r.group;
            return [
              header && (
                <tr className="group" key={`g-${r.group}`}>
                  <td className="sticky-col" style={{ background: "var(--bg)" }}>{r.group}</td>
                  <td colSpan={days.length + 1} />
                </tr>
              ),
              <tr key={r.id}>
                <td className="sticky-col">
                  {r.label} {!r.active && <span className="pill pill-grey">inactive</span>}
                </td>
                {days.map((d) => (
                  <td key={d} className={isWeekend(d) ? "weekend" : ""}>
                    <NumCell
                      value={val(r.id, d)}
                      dirty={`${r.id}|${d}` in edits}
                      onChange={(v) => setEdits((e) => ({ ...e, [`${r.id}|${d}`]: v }))}
                    />
                  </td>
                ))}
                <td className="num">{rupees(rowTotal(r))}</td>
              </tr>,
            ];
          })}
          <tr className="total">
            <td className="sticky-col">Total</td>
            {days.map((d) => (
              <td key={d} className="num" style={{ padding: "5px 6px" }}>{dayTotal(d) ? rupees(dayTotal(d)) : ""}</td>
            ))}
            <td className="num">{rupees(days.reduce((s, d) => s + dayTotal(d), 0))}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export const editsToCells = (edits) =>
  Object.entries(edits).map(([k, amount]) => {
    const [row_id, date] = k.split("|");
    return { row_id: Number(row_id), date, amount };
  });
