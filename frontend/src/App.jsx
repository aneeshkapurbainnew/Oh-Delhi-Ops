import { useCallback, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api, setUnauthorizedHandler } from "./lib/api";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Prices from "./pages/Prices";
import Purchases from "./pages/Purchases";
import Issues from "./pages/Issues";
import Wastage from "./pages/Wastage";
import SalesCosts from "./pages/SalesCosts";
import Expenses from "./pages/Expenses";
import Audits from "./pages/Audits";
import AuditDetail from "./pages/AuditDetail";
import MonthEnd from "./pages/MonthEnd";
import Stock from "./pages/Stock";
import PnL from "./pages/PnL";
import Reviews from "./pages/Reviews";
import Setup from "./pages/Setup";
import Daily from "./pages/Daily";
import Kitchen from "./pages/Kitchen";

const NAV = [
  ["Owner", [["/", "Dashboard"], ["/pnl", "P&L"], ["/reviews", "Reviews"]]],
  ["Every day", [["/daily", "Daily orders"], ["/prices", "Prices"], ["/purchases", "Purchases"], ["/issues", "Station issues"], ["/wastage", "Wastage"], ["/sales", "Sales and channel costs"], ["/expenses", "Expenses"]]],
  ["Stock", [["/audits", "Audits"], ["/month-end", "Month-end summary"], ["/stock", "Stock and ordering"]]],
  ["Setup", [["/setup", "Setup"]]],
];

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = checking, null = signed out
  const [fullApp, setFullApp] = useState(false);
  const [pending, setPending] = useState(0);
  const [stations, setStations] = useState([]);
  const [version, setVersion] = useState("");

  const loadPending = useCallback(() => {
    api.get("/pending/count").then((d) => setPending(d.count)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!user) return undefined;
    loadPending();
    api.get("/stations").then(setStations).catch(() => {});
    api.get("/health").then((h) => setVersion(h.version)).catch(() => {});
    const t = setInterval(loadPending, 60000);
    return () => clearInterval(t);
  }, [user, loadPending]);

  const check = useCallback(() => {
    api.get("/auth/me").then(setUser).catch(() => setUser(null));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    check();
  }, [check]);

  const signOut = async () => {
    await api.post("/auth/logout").catch(() => {});
    setUser(null);
  };

  if (user === undefined) return <div className="empty">Loading…</div>;
  if (!user) return <Login onSignedIn={setUser} />;
  if (user.station_id && !fullApp) {
    const st = stations.find((s) => s.id === user.station_id);
    return <Kitchen user={user} stationName={st?.name || "Your"} onOpenFull={() => setFullApp(true)} onSignOut={signOut} />;
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">OD</div>
          <div>
            <div className="brand-name">Oh Delhi Ops</div>
            <div className="brand-sub">Stock, costs and P&L</div>
          </div>
        </div>
        {NAV.map(([group, links]) => (
          <nav className="nav" key={group} aria-label={group}>
            <div className="nav-group">{group}</div>
            {links.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}>
                {label}
                {to === "/daily" && pending > 0 && <span className="pill pill-chili" title="Items stations didn't get in full">{pending}</span>}
              </NavLink>
            ))}
          </nav>
        ))}
        <div className="sidebar-foot">
          <div>{user.name}</div>
          {user.station_id && <div><button onClick={() => setFullApp(false)}>Back to kitchen screen</button></div>}
          {user.id !== 0 && <button onClick={signOut}>Sign out</button>}
          {version && <div style={{ marginTop: 10, opacity: 0.7 }}>Version {version}</div>}
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/daily" element={<Daily onPendingChange={loadPending} />} />
          <Route path="/prices" element={<Prices />} />
          <Route path="/purchases" element={<Purchases />} />
          <Route path="/issues" element={<Issues />} />
          <Route path="/wastage" element={<Wastage />} />
          <Route path="/sales" element={<SalesCosts />} />
          <Route path="/expenses" element={<Expenses />} />
          <Route path="/audits" element={<Audits />} />
          <Route path="/audits/:id" element={<AuditDetail />} />
          <Route path="/month-end" element={<MonthEnd />} />
          <Route path="/stock" element={<Stock />} />
          <Route path="/pnl" element={<PnL />} />
          <Route path="/reviews" element={<Reviews />} />
          <Route path="/setup" element={<Setup currentUser={user} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
