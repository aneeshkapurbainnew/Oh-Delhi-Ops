import { useState } from "react";
import { Modal, MonthPicker, PageHead, Seg, Status, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch } from "../lib/hooks";
import { dayLabel, thisMonth, todayISO, toNum } from "../lib/format";

const STATUS = { open: ["Open", "pill-chili"], in_progress: ["In progress", "pill-turmeric"], resolved: ["Resolved", "pill-green"] };

export default function Reviews() {
  const toast = useToast();
  const [month, setMonth] = useState(thisMonth());
  const [status, setStatus] = useState("");
  const [brand, setBrand] = useState("");
  const [stationId, setStationId] = useState("");
  const qs = new URLSearchParams({ month, ...(status && { status }), ...(brand && { brand }), ...(stationId && { station_id: stationId }) });
  const list = useFetch(`/reviews?${qs}`);
  const trends = useFetch(`/reviews/trends?month=${month}`);
  const brands = useFetch("/brands");
  const stations = useFetch("/stations");
  const staff = useFetch("/staff");
  const options = useFetch("/reviews/options");
  const [editing, setEditing] = useState(null);

  const refresh = () => {
    list.reload();
    trends.reload();
  };
  const quickStatus = async (r, s) => {
    try {
      await api.patch(`/reviews/${r.id}`, { status: s });
      refresh();
    } catch (e) {
      toast(e.message, "error");
    }
  };

  const t = trends.data;
  return (
    <>
      <PageHead title="Reviews" intro="Log customer feedback, assign it, and track it to resolution. Trends show which stations and brands get the most complaints.">
        <MonthPicker value={month} onChange={setMonth} />
        <button className="btn-primary" onClick={() => setEditing({})}>Log review</button>
      </PageHead>

      <div className="stack">
        {t && (
          <div className="cols-3">
            <div className="panel panel-body">
              <h3 style={{ marginBottom: 8 }}>This month</h3>
              <div className="list-row"><span>Logged</span><span>{t.total}</span></div>
              <div className="list-row"><span>Open</span><span className={t.open ? "neg" : ""}>{t.open}</span></div>
              <div className="list-row"><span>In progress</span><span>{t.in_progress}</span></div>
              <div className="list-row"><span>Resolved</span><span>{t.resolved}</span></div>
              <div className="list-row"><span>Average time to resolve</span><span>{t.avg_resolution_hours === null ? "–" : `${t.avg_resolution_hours} h`}</span></div>
            </div>
            {[["By station", t.by_station], ["By brand", t.by_brand]].map(([title, rows]) => (
              <div className="panel panel-body" key={title}>
                <h3 style={{ marginBottom: 8 }}>{title}</h3>
                {rows.length === 0 && <div className="muted small">No reviews yet.</div>}
                {rows.slice(0, 7).map((g) => (
                  <div className="list-row" key={g.name}>
                    <span>{g.name}</span>
                    <span className="small">
                      {g.count} · avg {g.avg_rating ?? "–"} {g.low_ratings > 0 && <span className="pill pill-chili">{g.low_ratings} ≤ 2★</span>}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        <div className="panel">
          <div className="panel-head">
            <div className="toolbar">
              <Seg options={[["", "All"], ["open", "Open"], ["in_progress", "In progress"], ["resolved", "Resolved"]]} value={status} onChange={setStatus} />
              <select value={brand} onChange={(e) => setBrand(e.target.value)}>
                <option value="">All brands</option>
                {(brands.data || []).map((b) => <option key={b}>{b}</option>)}
              </select>
              <select value={stationId} onChange={(e) => setStationId(e.target.value)}>
                <option value="">All stations</option>
                {(stations.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          </div>
          <Status loading={list.loading && !list.data} error={list.error} onRetry={list.reload} />
          {list.data && (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Date</th><th>Brand</th><th>Source</th><th>Item</th><th>Review</th><th>Station</th><th className="num">Rating</th><th>Assigned to</th><th>Status</th></tr></thead>
                <tbody>
                  {list.data.map((r) => (
                    <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => setEditing(r)}>
                      <td>{dayLabel(r.date)}{r.shift && <div className="muted xs">{r.shift}</div>}</td>
                      <td>{r.brand}</td>
                      <td className="muted">{r.source}</td>
                      <td>{r.review_item}</td>
                      <td className="small" style={{ maxWidth: 320 }}>{r.review_text}</td>
                      <td>{r.station || "–"}{r.concerned_person && <div className="muted xs">{r.concerned_person}</div>}</td>
                      <td className={`num ${r.rating !== null && r.rating <= 2 ? "neg" : ""}`}>{r.rating ?? "–"}</td>
                      <td>{r.assigned_to || "–"}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <select value={r.status} onChange={(e) => quickStatus(r, e.target.value)} aria-label="Status">
                          {Object.entries(STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {list.data.length === 0 && <div className="empty">No reviews match. Log one when feedback comes in from Zomato, Swiggy or the floor.</div>}
            </div>
          )}
        </div>
      </div>

      {editing && (
        <ReviewForm
          review={editing}
          brands={brands.data || []}
          stations={stations.data || []}
          staff={(staff.data || []).filter((s) => s.active)}
          options={options.data || { sources: [], shifts: [] }}
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

function ReviewForm({ review, brands, stations, staff, options, onClose, onSaved }) {
  const toast = useToast();
  const [f, setF] = useState({
    brand: "", source: "", date: todayISO(), shift: "", review_item: "", review_text: "", station_id: "",
    concerned_person: "", rating: null, assigned_to: "", status: "open", resolution: "", ...review,
  });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const save = async () => {
    if (!f.brand || !f.source) return toast("Choose a brand and a source.", "error");
    const body = {
      brand: f.brand, source: f.source, date: f.date, shift: f.shift || null, review_item: f.review_item || null,
      review_text: f.review_text || null, station_id: f.station_id ? Number(f.station_id) : null,
      concerned_person: f.concerned_person || null, rating: f.rating, assigned_to: f.assigned_to || null,
      status: f.status, resolution: f.resolution || null,
    };
    try {
      if (review.id) await api.patch(`/reviews/${review.id}`, body);
      else await api.post("/reviews", body);
      toast(review.id ? "Review updated." : "Review logged.");
      onSaved();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  const remove = async () => {
    if (!window.confirm("Delete this review?")) return;
    await api.del(`/reviews/${review.id}`);
    onSaved();
  };
  const people = (
    <datalist id="staff-names">{staff.map((s) => <option key={s.id} value={s.name} />)}</datalist>
  );
  return (
    <Modal
      title={review.id ? "Review" : "Log review"}
      onClose={onClose}
      footer={
        <>
          {review.id && <button className="btn-danger" style={{ marginRight: "auto" }} onClick={remove}>Delete</button>}
          <button onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={save}>{review.id ? "Save changes" : "Log review"}</button>
        </>
      }
    >
      {people}
      <div className="stack">
        <div className="form-grid">
          <label className="field">Brand
            <select value={f.brand} onChange={(e) => set("brand", e.target.value)}>
              <option value="">Choose</option>
              {brands.map((b) => <option key={b}>{b}</option>)}
            </select>
          </label>
          <label className="field">Source
            <select value={f.source} onChange={(e) => set("source", e.target.value)}>
              <option value="">Choose</option>
              {options.sources.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label className="field">Date<input type="date" value={f.date} onChange={(e) => set("date", e.target.value)} /></label>
          <label className="field">Shift
            <select value={f.shift || ""} onChange={(e) => set("shift", e.target.value)}>
              <option value="">–</option>
              {options.shifts.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label className="field">Rating (0–5)<input type="number" min="0" max="5" step="0.5" value={f.rating ?? ""} onChange={(e) => set("rating", toNum(e.target.value))} /></label>
        </div>
        <div className="form-grid">
          <label className="field">Dish / item<input value={f.review_item || ""} onChange={(e) => set("review_item", e.target.value)} /></label>
          <label className="field">Station
            <select value={f.station_id || ""} onChange={(e) => set("station_id", e.target.value)}>
              <option value="">–</option>
              {stations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label className="field">Concerned person<input list="staff-names" value={f.concerned_person || ""} onChange={(e) => set("concerned_person", e.target.value)} /></label>
          <label className="field">Assigned to<input list="staff-names" value={f.assigned_to || ""} onChange={(e) => set("assigned_to", e.target.value)} /></label>
        </div>
        <label className="field">What the customer said<textarea value={f.review_text || ""} onChange={(e) => set("review_text", e.target.value)} /></label>
        <label className="field">Status
          <Seg options={[["open", "Open"], ["in_progress", "In progress"], ["resolved", "Resolved"]]} value={f.status} onChange={(v) => set("status", v)} />
        </label>
        <label className="field">What was done<textarea value={f.resolution || ""} onChange={(e) => set("resolution", e.target.value)} placeholder="e.g. Refund issued, recipe re-briefed with the chef" /></label>
      </div>
    </Modal>
  );
}
