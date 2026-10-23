import { useState, type ReactNode } from "react";

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>
      {(title || actions) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="text-base font-semibold text-slate-800">{title}</h2>}
          {actions && <div className="flex gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

type BtnProps = { onClick?: () => void | Promise<void>; children: ReactNode; variant?: "primary" | "secondary" | "danger"; disabled?: boolean; busy?: boolean; type?: "button" | "submit" };

export function Button({ onClick, children, variant = "primary", disabled, busy, type = "button" }: BtnProps) {
  const styles = {
    primary: "bg-emerald-700 text-white hover:bg-emerald-800",
    secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50",
    danger: "bg-red-600 text-white hover:bg-red-700",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || busy}
      className={`inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium shadow-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${styles}`}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner() {
  return <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />;
}

export function Badge({ tone = "slate", children }: { tone?: "green" | "red" | "amber" | "slate" | "blue"; children: ReactNode }) {
  const t = {
    green: "bg-emerald-100 text-emerald-800",
    red: "bg-red-100 text-red-800",
    amber: "bg-amber-100 text-amber-800",
    slate: "bg-slate-100 text-slate-700",
    blue: "bg-sky-100 text-sky-800",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${t}`}>{children}</span>;
}

export function StatusBadge({ status }: { status?: string }) {
  const s = (status ?? "").toUpperCase();
  const tone = ["READY", "COMPLETE", "CREATED", "UNCHANGED", "UPDATED", "OK", "PASS"].includes(s)
    ? "green"
    : ["FAILED", "MISSING", "ERROR", "FAIL"].includes(s)
      ? "red"
      : ["BUILDING", "PENDING", "PROCESSING", "QUEUED", "AWAITING_INDEX", "RUNNING", "STALE", "RECREATE-PENDING"].includes(s)
        ? "amber"
        : "slate";
  return <Badge tone={tone}>{status ?? "—"}</Badge>;
}

export function ErrorBox({ error }: { error?: string | null }) {
  if (!error) return null;
  return <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>;
}

export function Json({ value, collapsed = true, label = "JSON" }: { value: unknown; collapsed?: boolean; label?: string }) {
  const [open, setOpen] = useState(!collapsed);
  return (
    <div className="mt-2">
      <button className="text-xs font-medium text-emerald-700 hover:underline" onClick={() => setOpen(!open)}>
        {open ? "Hide" : "Show"} {label}
      </button>
      {open && <pre className="mt-1 max-h-96 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(value, null, 2)}</pre>}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold text-slate-800">{value}</div>
    </div>
  );
}
