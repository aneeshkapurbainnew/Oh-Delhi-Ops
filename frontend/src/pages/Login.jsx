import { useState } from "react";
import { api } from "../lib/api";

export default function Login({ onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await api.post("/auth/login", { email, password }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="panel panel-body" onSubmit={submit}>
        <div className="brand" style={{ padding: 0 }}>
          <div className="brand-mark">OD</div>
          <div>
            <div style={{ fontWeight: 650 }}>Oh Delhi Ops</div>
            <div className="muted xs">Sign in with your team account</div>
          </div>
        </div>
        <label className="field">Email<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></label>
        <label className="field">Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {error && <div className="note note-error">{error}</div>}
        <button className="btn-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="muted xs" style={{ margin: 0 }}>No account? Ask a colleague to add you in Setup → Users.</p>
      </form>
    </div>
  );
}
