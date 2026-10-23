import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Button, Card, ErrorBox, Stat } from "../components/ui";

const QUESTIONS: { q: string; a: string; demo: [string, string] }[] = [
  {
    q: "Multi-tenant vector isolation",
    a: "tenantId + datasetVersion are filter fields in the vector index, so $vectorSearch pre-filters during HNSW traversal (not after). Small tenants switch automatically to exact ENN; numCandidates is tuned per tenant. Large tenants can move to their own collection and Search Nodes isolate search workload.",
    demo: ["/playground", "Playground (vector mode ANN/ENN) + benchmark below"],
  },
  {
    q: "Native hybrid search",
    a: "$rankFusion runs $vectorSearch and $search (BM25) inside one aggregation with per-tenant weights (default 0.7/0.3) and returns per-pipeline ranks via scoreDetails — no thread pool or application-side RRF.",
    demo: ["/playground", "Compare search modes"],
  },
  {
    q: "Document model fit",
    a: "Tenant config (schemas, templates, index/filter/pipeline config), record metadata and feedback feature snapshots are native nested documents. Index definitions are generated from tenant config — new tenant schemas need no migrations.",
    demo: ["/tenants", "Tenants editor"],
  },
  {
    q: "Operational simplicity",
    a: "Atlas manages vector/search index builds in the background (no VACUUM or GIN maintenance). Audit retention is a TTL index instead of monthly partitions. Index buttons are idempotent with drift detection.",
    demo: ["/admin", "Admin index status + Audit TTL"],
  },
  {
    q: "Atomic bulk operations (full_replace)",
    a: "New data is written to a new datasetVersion (invisible to queries). After Atlas Search and Vector Search have indexed it, a single-document update flips tenants.activeDatasetVersion — atomic by definition. Old version is purged after a grace period; rollback is a pointer flip.",
    demo: ["/ingest", "Ingest with full_replace"],
  },
  {
    q: "Scalability model",
    a: "10M × 1024-d float32 ≈ 41 GB raw; scalar quantization ≈ 4× smaller in RAM. Scale query throughput with dedicated Search Nodes, then shard documents on { tenantId, recordId } for write/storage growth. Validate with the benchmark below at larger seed volumes.",
    demo: ["/admin", "Collection sizes on Admin"],
  },
];

export default function Requirements() {
  const [tenants, setTenants] = useState<any[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [samples, setSamples] = useState(20);
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api("/v1/tenants").then((t) => {
      setTenants(t);
      if (t.length) setTenantId(t[0]._id);
    }).catch((e) => setError(e.message));
  }, []);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api(`/api/admin/bench/${tenantId}?samples=${samples}`, { method: "POST" }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {QUESTIONS.map((x) => (
          <Card key={x.q} title={x.q}>
            <p className="text-sm text-slate-600">{x.a}</p>
            <Link to={x.demo[0]} className="mt-3 inline-block text-sm font-medium text-emerald-700 hover:underline">→ {x.demo[1]}</Link>
          </Card>
        ))}
      </div>

      <Card title="Benchmark: ANN recall vs exact, and latency by mode" actions={<Button onClick={run} busy={busy} disabled={!tenantId}>Run benchmark</Button>}>
        <div className="mb-4 flex flex-wrap gap-3">
          <select className="input max-w-xs" value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
            {tenants.map((t) => <option key={t._id} value={t._id}>{t.name}</option>)}
          </select>
          <input className="input w-32" type="number" min={1} max={100} value={samples} onChange={(e) => setSamples(Number(e.target.value))} />
          <span className="self-center text-xs text-slate-500">sample queries (stored vectors, no model calls)</span>
        </div>
        <ErrorBox error={error} />
        {result && (
          <>
            <div className="grid gap-3 md:grid-cols-4">
              <Stat label="Documents (active version)" value={result.documents.toLocaleString()} />
              <Stat label="Samples" value={result.samples} />
              <Stat label={`Recall@${result.k} (ANN vs ENN)`} value={result.recallAtK != null ? `${(result.recallAtK * 100).toFixed(1)}%` : "–"} />
              <Stat label="Hybrid p95" value={`${result.latencyMs.hybrid.p95} ms`} />
            </div>
            <table className="mt-4 w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr><th className="py-1">Mode</th><th>p50 ms</th><th>p95 ms</th><th>mean ms</th></tr>
              </thead>
              <tbody>
                {Object.entries(result.latencyMs).map(([m, v]: [string, any]) => (
                  <tr key={m} className="border-t border-slate-100">
                    <td className="py-1.5">{{ ann: "Vector ANN (HNSW)", enn: "Vector exact (ENN)", text: "Text (BM25)", hybrid: "Hybrid $rankFusion" }[m] ?? m}</td>
                    <td>{v.p50}</td><td>{v.p95}</td><td>{v.mean}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-slate-500">{result.note}</p>
          </>
        )}
      </Card>
    </div>
  );
}
