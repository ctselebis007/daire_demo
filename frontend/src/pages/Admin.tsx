import { useCallback, useEffect, useRef, useState } from "react";
import { api, fmtBytes } from "../api";
import { Badge, Button, Card, ErrorBox, Field, Json, Stat, StatusBadge } from "../components/ui";

const SEED_TENANTS = ["talent-match", "learning-catalog", "vendor-sourcing"];

type IndexAction = "db" | "search" | "vector";
const INDEX_BUTTONS: [IndexAction, string, string][] = [
  ["db", "Create DB Indexes", "Unique, compound and TTL indexes on all collections."],
  ["search", "Create Atlas Search Indexes", "Full-text (BM25) index on keywordText + tenant filter fields."],
  ["vector", "Create Vector Search Indexes", "HNSW index on embedding (dotProduct, scalar quantization) + pre-filter fields."],
];

export default function Admin() {
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, any>>({});
  const [seedOpts, setSeedOpts] = useState({ tenants: SEED_TENANTS, recordsPerTenant: 2000, feedback: true, audits: true, dropExisting: false, randomSeed: 42 });
  const [seedJob, setSeedJob] = useState<any>(null);
  const [targetVectors, setTargetVectors] = useState(10_000_000);
  // Measured in the Atlas UI: Search 1.87 MB and Vector 24.85 MB for 5,000 documents.
  const [atlasBase, setAtlasBase] = useState({ searchMB: 1.87, vectorMB: 24.85, docs: 5000 });
  const pollRef = useRef<number | null>(null);

  const totals = Object.values(stats?.collections ?? {}).reduce(
    (acc: { count: number; storage: number; indexes: number }, c: any) => ({
      count: acc.count + (c.count ?? 0),
      storage: acc.storage + (c.storageSize ?? 0),
      indexes: acc.indexes + (c.totalIndexSize ?? 0),
    }),
    { count: 0, storage: 0, indexes: 0 },
  );
  const vectors: number = stats?.collections?.documents?.count ?? 0;
  const scale = vectors > 0 ? targetVectors / vectors : 0;
  const MB = 1024 * 1024;
  const atlasPerDoc = {
    search: (atlasBase.searchMB * MB) / atlasBase.docs,
    vector: (atlasBase.vectorMB * MB) / atlasBase.docs,
  };
  const atlasNow = { search: atlasPerDoc.search * vectors, vector: atlasPerDoc.vector * vectors };
  const projectedTotal = (totals.storage + totals.indexes) * scale + (atlasPerDoc.search + atlasPerDoc.vector) * targetVectors;

  const refresh = useCallback(async () => {
    try {
      const [s, st] = await Promise.all([api("/api/admin/indexes/status"), api("/api/admin/stats")]);
      setStatus(s);
      setStats(st);
      setError(null);
      return s;
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll index status while any search index is building.
  useEffect(() => {
    const building = status?.search?.some((i: any) => i.exists && !(i.status === "READY" && i.queryable));
    if (!building) return;
    const t = window.setTimeout(refresh, 5000);
    return () => window.clearTimeout(t);
  }, [status, refresh]);

  const runIndex = async (kind: IndexAction) => {
    setBusy(kind);
    setError(null);
    try {
      const r = await api(`/api/admin/indexes/${kind}`, { method: "POST" });
      setResults((s) => ({ ...s, [kind]: r }));
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const pollSeed = (id: string) => {
    const tick = async () => {
      try {
        const j = await api(`/api/admin/seed/${id}`);
        setSeedJob(j);
        if (j.status === "running") {
          pollRef.current = window.setTimeout(tick, 1500);
        } else {
          refresh();
        }
      } catch (e: any) {
        setError(e.message);
      }
    };
    tick();
  };
  useEffect(() => () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
  }, []);

  const startSeed = async () => {
    setError(null);
    try {
      const r = await api("/api/admin/seed", { body: seedOpts });
      pollSeed(r.seedJobId);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const removeSeed = async () => {
    if (!window.confirm("Delete all seed tenants, their documents, jobs, seeded feedback and audits?")) return;
    setBusy("drop");
    try {
      const r = await api("/api/admin/seed", { method: "DELETE" });
      setResults((s) => ({ ...s, drop: r }));
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const purge = async () => {
    setBusy("purge");
    try {
      const r = await api("/api/admin/purge", { method: "POST" });
      setResults((s) => ({ ...s, purge: r }));
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  const toggleTenant = (t: string) =>
    setSeedOpts((o) => ({ ...o, tenants: o.tenants.includes(t) ? o.tenants.filter((x) => x !== t) : [...o.tenants, t] }));

  return (
    <div className="space-y-6">
      <ErrorBox error={error} />
      <div className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
        <b>Recommended order:</b> 1) Create DB Indexes → 2) Seed Synthetic Data → 3) Create Atlas Search Indexes → 4) Create Vector Search Indexes.
        Search and vector index definitions are generated from the union of tenant filter fields, so seed (or create) tenants first.
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Seed synthetic data" actions={<Button onClick={startSeed} busy={seedJob?.status === "running"}>Seed Synthetic Data</Button>}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Tenants">
              <div className="space-y-1">
                {SEED_TENANTS.map((t) => (
                  <label key={t} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={seedOpts.tenants.includes(t)} onChange={() => toggleTenant(t)} /> {t}
                  </label>
                ))}
              </div>
            </Field>
            <div className="space-y-3">
              <Field label="Records per tenant">
                <input className="input" type="number" min={10} max={50000} value={seedOpts.recordsPerTenant}
                  onChange={(e) => setSeedOpts({ ...seedOpts, recordsPerTenant: Number(e.target.value) })} />
              </Field>
              <Field label="Random seed" hint="Same seed ⇒ identical records ⇒ re-seeding skips unchanged records (content hash).">
                <input className="input" type="number" value={seedOpts.randomSeed} onChange={(e) => setSeedOpts({ ...seedOpts, randomSeed: Number(e.target.value) })} />
              </Field>
            </div>
            <div className="space-y-1 text-sm md:col-span-2">
              {([["feedback", "Generate feedback events (2,000 per tenant)"], ["audits", "Generate audit history (2,000 over 120 days — older than TTL will expire)"], ["dropExisting", "Drop existing seed data first"]] as const).map(([k, l]) => (
                <label key={k} className="flex items-center gap-2">
                  <input type="checkbox" checked={(seedOpts as any)[k]} onChange={(e) => setSeedOpts({ ...seedOpts, [k]: e.target.checked })} /> {l}
                </label>
              ))}
            </div>
          </div>
          {seedJob && (
            <div className="mt-4 space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <StatusBadge status={seedJob.status} /> <span className="text-slate-600">{seedJob.step}</span>
              </div>
              {Object.entries(seedJob.progress ?? {}).map(([t, p]: [string, any]) => (
                <div key={t}>
                  <div className="flex justify-between text-xs text-slate-600">
                    <span>{t}</span>
                    <span>{p.done}/{p.total} · embedded {p.embedded} · reused {p.embeddingReused} · skipped {p.skipped} · rejected {p.rejected}</span>
                  </div>
                  <div className="h-2 rounded bg-slate-100">
                    <div className="h-2 rounded bg-emerald-600 transition-all" style={{ width: `${(100 * p.done) / Math.max(1, p.total)}%` }} />
                  </div>
                </div>
              ))}
              <pre className="max-h-40 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-600">{(seedJob.log ?? []).join("\n")}</pre>
              <ErrorBox error={seedJob.error} />
            </div>
          )}
        </Card>

        <Card title="Indexes">
          <div className="space-y-4">
            {INDEX_BUTTONS.map(([kind, label, desc]) => (
              <div key={kind} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-slate-800">{label}</div>
                    <div className="text-xs text-slate-500">{desc}</div>
                  </div>
                  <Button onClick={() => runIndex(kind)} busy={busy === kind}>{label.replace(" Indexes", "")}</Button>
                </div>
                {results[kind] && <IndexResult kind={kind} result={results[kind]} />}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Index status" actions={<Button variant="secondary" onClick={refresh}>Refresh</Button>}>
        {status?.error && <ErrorBox error={status.error} />}
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">Atlas Search / Vector Search</h3>
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr><th className="py-1">Name</th><th>Type</th><th>Status</th><th>Queryable</th><th>Drift</th></tr>
              </thead>
              <tbody>
                {(status?.search ?? []).map((i: any) => (
                  <tr key={i.name} className="border-t border-slate-100">
                    <td className="py-1.5 font-mono text-xs">{i.name}</td>
                    <td>{i.type}</td>
                    <td><StatusBadge status={i.status} /></td>
                    <td>{i.exists ? (i.queryable ? <Badge tone="green">yes</Badge> : <Badge tone="amber">no</Badge>) : "—"}</td>
                    <td>{i.stale ? <Badge tone="amber">out of date</Badge> : i.exists ? <Badge tone="green">in sync</Badge> : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(status?.search ?? []).flatMap((i: any) => i.warnings ?? []).map((w: string) => (
              <div key={w} className="mt-1 text-xs text-amber-700">⚠ {w}</div>
            ))}
            {(status?.search ?? []).map((i: any) => <Json key={i.name} value={i.desiredDefinition} label={`${i.name} definition`} />)}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">Database indexes</h3>
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-xs">
                <thead className="text-left uppercase text-slate-500">
                  <tr><th className="py-1">Collection</th><th>Name</th><th>Keys</th><th>Options</th></tr>
                </thead>
                <tbody>
                  {(status?.db ?? []).map((i: any) => (
                    <tr key={`${i.collection}.${i.name}`} className="border-t border-slate-100">
                      <td className="py-1">{i.collection}</td>
                      <td className="font-mono">{i.name}</td>
                      <td className="font-mono">{i.keys.map((k: any) => `${k[0]}:${k[1]}`).join(", ")}</td>
                      <td>
                        {i.unique && <Badge tone="blue">unique</Badge>}{" "}
                        {i.expireAfterSeconds != null && <Badge tone="amber">TTL {Math.round(i.expireAfterSeconds / 86400)}d</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Data">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="py-1">Tenant</th><th>Dataset version</th><th>Documents</th><th></th></tr>
            </thead>
            <tbody>
              {(stats?.documentsByVersion ?? []).map((r: any) => {
                const t = (stats?.tenants ?? []).find((x: any) => x._id === r.tenantId);
                const tag = t?.activeDatasetVersion === r.datasetVersion ? "active" : t?.previousDatasetVersion === r.datasetVersion ? "previous" : "staged/stale";
                return (
                  <tr key={`${r.tenantId}-${r.datasetVersion}`} className="border-t border-slate-100">
                    <td className="py-1.5">{r.tenantId}</td>
                    <td>v{r.datasetVersion}</td>
                    <td>{r.count.toLocaleString()}</td>
                    <td><Badge tone={tag === "active" ? "green" : tag === "previous" ? "blue" : "amber"}>{tag}</Badge></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <h3 className="mb-2 mt-5 text-sm font-semibold text-slate-700">Collections</h3>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="py-1">Collection</th><th>Docs</th><th>Storage</th><th>Indexes</th><th>Atlas Indexes</th><th>Total</th><th>Avg doc</th></tr>
            </thead>
            <tbody>
              {Object.entries(stats?.collections ?? {}).map(([n, c]: [string, any]) => {
                const atlas = n === "documents" ? atlasNow.search + atlasNow.vector : 0;
                return (
                  <tr key={n} className="border-t border-slate-100">
                    <td className="py-1.5">{n}</td>
                    <td>{(c.count ?? 0).toLocaleString()}</td>
                    <td>{fmtBytes(c.storageSize)}</td>
                    <td>{fmtBytes(c.totalIndexSize)}</td>
                    <td title={atlas ? `Search ${fmtBytes(atlasNow.search)} + Vector ${fmtBytes(atlasNow.vector)}` : undefined}>
                      {atlas ? fmtBytes(atlas) : "—"}
                    </td>
                    <td>{fmtBytes((c.storageSize ?? 0) + (c.totalIndexSize ?? 0) + atlas)}</td>
                    <td>{fmtBytes(c.avgObjSize)}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-slate-300 font-semibold text-slate-800">
                <td className="py-1.5">Total Size</td>
                <td>{totals.count.toLocaleString()}</td>
                <td>{fmtBytes(totals.storage)}</td>
                <td>{fmtBytes(totals.indexes)}</td>
                <td>{fmtBytes(atlasNow.search + atlasNow.vector)}</td>
                <td>{fmtBytes(totals.storage + totals.indexes + atlasNow.search + atlasNow.vector)}</td>
                <td></td>
              </tr>
            </tfoot>
          </table>
          <p className="mt-1 text-xs text-slate-500">
            Atlas Indexes = Atlas Search ({fmtBytes(atlasNow.search)}) + Vector Search ({fmtBytes(atlasNow.vector)}) for the documents collection, estimated from the baseline below.
          </p>

          <h3 className="mb-2 mt-5 text-sm font-semibold text-slate-700">Size projection</h3>
          <div className="mb-3 rounded-lg bg-slate-50 p-3">
            <div className="label">Atlas index baseline (from Atlas UI → Search &amp; Vector Search)</div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span>Search</span>
              <input className="input w-24" type="number" min={0} step={0.01} value={atlasBase.searchMB}
                onChange={(e) => setAtlasBase({ ...atlasBase, searchMB: Math.max(0, Number(e.target.value)) })} />
              <span>MB · Vector</span>
              <input className="input w-24" type="number" min={0} step={0.01} value={atlasBase.vectorMB}
                onChange={(e) => setAtlasBase({ ...atlasBase, vectorMB: Math.max(0, Number(e.target.value)) })} />
              <span>MB for</span>
              <input className="input w-28" type="number" min={1} step={1000} value={atlasBase.docs}
                onChange={(e) => setAtlasBase({ ...atlasBase, docs: Math.max(1, Number(e.target.value)) })} />
              <span>documents</span>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              ≈ {fmtBytes(atlasPerDoc.search)}/doc search · {fmtBytes(atlasPerDoc.vector)}/doc vector
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Number of vectors" hint={`Currently ${vectors.toLocaleString()} vectors (documents collection).`}>
              <input className="input w-44" type="number" min={1} step={1000000} value={targetVectors}
                onChange={(e) => setTargetVectors(Math.max(0, Number(e.target.value)))} />
            </Field>
            <div className="flex gap-1 pb-6">
              {[1_000_000, 10_000_000, 50_000_000].map((n) => (
                <button key={n} onClick={() => setTargetVectors(n)}
                  className={`rounded border px-2 py-1 text-xs ${targetVectors === n ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
                  {n / 1_000_000}M
                </button>
              ))}
            </div>
          </div>
          {vectors > 0 ? (
            <>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                <Stat label="Scale factor" value={`×${scale.toLocaleString(undefined, { maximumFractionDigits: 1 })}`} />
                <Stat label="Projected storage" value={fmtBytes(totals.storage * scale)} />
                <Stat label="Projected DB indexes" value={fmtBytes(totals.indexes * scale)} />
                <Stat label="Projected Atlas Search index" value={fmtBytes(atlasPerDoc.search * targetVectors)} />
                <Stat label="Projected Vector Search index" value={fmtBytes(atlasPerDoc.vector * targetVectors)} />
                <Stat label="Projected total size" value={fmtBytes(projectedTotal)} />
              </div>
              <p className="mt-2 text-xs text-slate-500">
                Storage and DB indexes: linear extrapolation of the current collStats footprint ({fmtBytes((totals.storage + totals.indexes) / vectors)}/vector, all collections).
                Atlas Search / Vector Search: baseline size per document × number of vectors.
              </p>
            </>
          ) : (
            <p className="text-xs text-slate-500">Seed or ingest data to enable the projection.</p>
          )}
        </Card>

        <Card title="Maintenance">
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-slate-600">Purge dataset versions that are neither active, previous (within grace), nor targeted by an open job.</div>
              <Button variant="secondary" onClick={purge} busy={busy === "purge"}>Purge old versions</Button>
            </div>
            {results.purge && <Json value={results.purge} label="purge result" collapsed={false} />}
            <div className="rounded-lg border border-red-200 bg-red-50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm text-red-800">Danger zone: remove all seed tenants and their data.</div>
                <Button variant="danger" onClick={removeSeed} busy={busy === "drop"}>Remove seed data</Button>
              </div>
              {results.drop && <Json value={results.drop} label="deleted" collapsed={false} />}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function IndexResult({ kind, result }: { kind: IndexAction; result: any }) {
  if (kind === "db") {
    const counts = (result.results ?? []).reduce((acc: any, r: any) => ({ ...acc, [r.result]: (acc[r.result] ?? 0) + 1 }), {});
    return (
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {Object.entries(counts).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1"><StatusBadge status={k} /> {v as number}</span>
        ))}
        {(result.results ?? []).filter((r: any) => r.result === "failed").map((r: any) => (
          <div key={r.name} className="w-full text-red-700">{r.collection}.{r.name}: {r.detail}</div>
        ))}
        <Json value={result.results} label="details" />
      </div>
    );
  }
  return (
    <div className="mt-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-mono">{result.name}</span> <StatusBadge status={result.result} />
        {result.result === "recreate-pending" && <span className="text-amber-700">Dimensions changed — old index dropped; click again in ~1 minute to recreate.</span>}
      </div>
      {result.detail && <ErrorBox error={result.detail} />}
      {(result.warnings ?? []).map((w: string) => <div key={w} className="text-amber-700">⚠ {w}</div>)}
      <Json value={result.definition} label="definition" />
    </div>
  );
}
