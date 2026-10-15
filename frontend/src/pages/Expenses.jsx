import { useState } from "react";
import { MonthGrid, MonthPicker, PageHead, Status, editsToCells, useToast } from "../components/ui";
import { api } from "../lib/api";
import { useFetch, useUnsavedWarning } from "../lib/hooks";
import { thisMonth } from "../lib/format";

export default function Expenses() {
  const toast = useToast();
  const [month, setMonth] = useState(thisMonth());
  const { data, loading, error, reload } = useFetch(`/expenses?month=${month}`);
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const dirty = Object.keys(edits).length > 0;
  useUnsavedWarning(dirty);

  const changeMonth = (m) => {
    if (dirty && !window.confirm("Discard unsaved expenses?")) return;
    setEdits({});
    setMonth(m);
  };
  const save = async () => {
    setBusy(true);
    try {
      await api.put("/expenses", { cells: editsToCells(edits) });
      setEdits({});
      await reload();
      toast("Expenses saved.");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead title="Expenses" intro="Day-wise running costs. Categories are edited in Setup → Expense categories.">
        <MonthPicker value={month} onChange={changeMonth} />
        <button className="btn-primary" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save expenses"}</button>
      </PageHead>
      <div className="note note-warn small" style={{ marginBottom: 12 }}>
        "Delivery Cost" and "Ads Cost (Reelo)" overlap with the Delivery and Ads tabs on Sales and channel costs. Enter each cost in one place only.
      </div>
      <div className="panel">
        {!data ? <Status loading={loading} error={error} onRetry={reload} /> : <MonthGrid grid={data} edits={edits} setEdits={setEdits} rowLabel="Expense" />}
      </div>
    </>
  );
}
