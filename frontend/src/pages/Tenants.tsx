import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorBox, StatusBadge } from "../components/ui";

export default function Tenants() {
  const [tenants, setTenants] = useState<any[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [doc, setDoc] = useState<any>(null);
  const [text, setText] = useState("");
  const [jobs, setJobs] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const loadList = async () => {
    try {
      const t = await api("/v1/tenants");
      setTenants(t);
      if (!selected && t.length) setSelected(t[0]._id);
    } catch (e: any) {
      setError(e.message);
    }
  };
  const loadOne = async (id: string) => {
    const [d, j] = await Promise.all([api(`/v1/tenants/${id}`), api(`/v1/tenants/${id}/jobs`)]);
    setDoc(d);
    setJobs(j);
    const { _id, activeDatasetVersion, previousDatasetVersion, nextDatasetVersion, swappedAt, createdAt, updatedAt, configVersion, seed, ...cfg } = d;
    setText(JSON.stringify(cfg, null, 2));
  };

  useEffect(() => {
    loadList();
  }, []);
  useEffect(() => {
    if (selected) loadOne(selected).catch((e) => setError(e.message));
  }, [selected]);

  const save = async () => {
    setBusy("save");
    setError(null);
    setMsg(null);
    try {
      const body = JSON.parse(text);
      await api(`/v1/tenants/${selected}`, { method: "PUT", body });
      setMsg("Saved. Config cache invalidated via change stream. If filter fields changed, re-run the Search/Vector index buttons on Admin.");
      await loadOne(selected!);
    } catch (e: any) {
      setError(e instanceof SyntaxError ? `Invalid JSON: ${e.message}` : e.message);
    } finally {
      setBusy(null);
    }
  };

  const rollback = async () => {
    if (!window.confirm("Swap active and previous dataset versions?")) return;
    setBusy("rollback");
    setError(null);
    try {
      const r = await api(`/v1/tenants/${selected}/rollback`, { method: "POST" });
      setMsg(`Rolled back: active v${r.activeDatasetVersion}, previous v${r.previousDatasetVersion}`);
      await loadOne(selected!);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-4">
      <Card title="Tenants" className="lg:col-span-1">
        <div className="space-y-1">
          {tenants.map((t) => (
            <button key={t._id} onClick={() => setSelected(t._id)}
              className={`w-full rounded-md px-3 py-2 text-left text-sm ${selected === t._id ? "bg-emerald-50 text-emerald-800" : "hover:bg-slate-50"}`}>
              <div className="font-medium">{t.name}</div>
              <div className="font-mono text-xs text-slate-500">{t._id} · v{t.activeDatasetVersion}</div>
            </button>
          ))}
          {!tenants.length && <div className="text-sm text-slate-500">No tenants yet — seed from the Admin page.</div>}
        </div>
      </Card>

      <div className="space-y-6 lg:col-span-3">
        <ErrorBox error={error} />
        {msg && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{msg}</div>}
        {doc && (
          <>
            <Card title={`${doc.name} (${doc._id})`} actions={
              <>
                <Button variant="secondary" onClick={rollback} busy={busy === "rollback"} disabled={doc.previousDatasetVersion == null}>Rollback</Button>
                <Button onClick={save} busy={busy === "save"}>Save config</Button>
              </>
            }>
              <div className="mb-3 flex flex-wrap gap-2 text-xs">
                <Badge tone="green">active v{doc.activeDatasetVersion}</Badge>
                {doc.previousDatasetVersion != null && <Badge tone="blue">previous v{doc.previousDatasetVersion} (rollback available)</Badge>}
                <Badge>config v{doc.configVersion}</Badge>
                {doc.swappedAt && <Badge>swapped {new Date(doc.swappedAt).toLocaleString()}</Badge>}
              </div>
              <p className="mb-2 text-xs text-slate-500">
                Tenant configuration is a single native MongoDB document (schema, templates, index/filter config, pipeline). Edit and save — no migrations.
              </p>
              <textarea className="input h-[520px] font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
            </Card>
            <Card title="Recent ingestion jobs">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr><th className="py-1">Created</th><th>Mode</th><th>Status</th><th>Batches</th><th>Processed</th><th>Embedded / reused</th><th>Rejected</th><th>Target</th></tr>
                </thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr key={j._id} className="border-t border-slate-100">
                      <td className="py-1.5 text-xs">{new Date(j.createdAt).toLocaleString()}</td>
                      <td>{j.mode}</td>
                      <td><StatusBadge status={j.status} /></td>
                      <td>{j.batchesCompleted}/{j.totalBatches}</td>
                      <td>{j.counts?.processed}</td>
                      <td>{j.counts?.embedded} / {j.counts?.embeddingReused}</td>
                      <td>{j.counts?.rejected}</td>
                      <td>{j.targetDatasetVersion ? `v${j.targetDatasetVersion}` : "active"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
