import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, ApiError, setToken } from "./api";
import { Button, Card } from "./components/ui";
import Setup from "./pages/Setup";
import Admin from "./pages/Admin";
import Tenants from "./pages/Tenants";
import Ingest from "./pages/Ingest";
import Playground from "./pages/Playground";
import Audit from "./pages/Audit";
import Requirements from "./pages/Requirements";

const NAV = [
  ["/setup", "Setup"],
  ["/admin", "Admin"],
  ["/tenants", "Tenants"],
  ["/ingest", "Ingest"],
  ["/playground", "Playground"],
  ["/audit", "Feedback & Audit"],
  ["/requirements", "Requirements"],
] as const;

export default function App() {
  const [auth, setAuth] = useState<"checking" | "ok" | "needed">("checking");
  const [token, setTok] = useState("");

  const check = async () => {
    try {
      await api("/api/setup");
      setAuth("ok");
    } catch (e) {
      setAuth(e instanceof ApiError && e.status === 401 ? "needed" : "ok");
    }
  };
  useEffect(() => {
    check();
  }, []);

  if (auth === "checking") return null;
  if (auth === "needed")
    return (
      <div className="mx-auto mt-24 max-w-md">
        <Card title="Admin token required">
          <p className="mb-3 text-sm text-slate-600">
            Open the URL printed by the backend at startup, or paste the token from <code>.dare/admin_token</code>.
          </p>
          <input className="input mb-3" type="password" value={token} onChange={(e) => setTok(e.target.value)} placeholder="Admin token" />
          <Button
            onClick={async () => {
              setToken(token);
              await check();
            }}
          >
            Continue
          </Button>
        </Card>
      </div>
    );

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-8 px-6 py-3">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-md bg-emerald-700" />
            <div>
              <div className="text-sm font-bold text-slate-900">DARE</div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500">on MongoDB Atlas</div>
            </div>
          </div>
          <nav className="flex flex-wrap gap-1">
            {NAV.map(([to, label]) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-emerald-50 text-emerald-800" : "text-slate-600 hover:bg-slate-100"}`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-6">
        <Routes>
          <Route path="/" element={<Navigate to="/setup" replace />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/tenants" element={<Tenants />} />
          <Route path="/ingest" element={<Ingest />} />
          <Route path="/playground" element={<Playground />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/requirements" element={<Requirements />} />
          <Route path="/evaluation" element={<Navigate to="/requirements" replace />} />
          <Route path="*" element={<Navigate to="/setup" replace />} />
        </Routes>
      </main>
    </div>
  );
}
