import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorBox, Field, Json, Stat, StatusBadge } from "../components/ui";

const BATCH_SIZE = 500;

export default function Ingest() {
  const [tenants, setTenants] = useState<any[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [mode, setMode] = useState<"upsert" | "full_replace">("full_replace");
  const [count, setCount] = useState(2000);
  const [seed, setSeed] = useState(42);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [job, setJob] = useState<any>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api("/v1/tenants").then((t) => {
      setTenants(t);
      if (t.length) setTenantId(t[0]._id);
    }).catch((e) => setError(e.message));
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, []);

  const generate = async () => {
    setError(null);
    try {
      const r = await api(`/api/admin/sample-records?tenantId=${encodeURIComponent(tenantId)}&count=${count}&seed=${seed}`);
      setText(JSON.stringify(r.records, null, 2));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const poll = (jobId: string) => {
    const tick = async () => {
      const j = await api(`/v1/jobs/${jobId}`);
      setJob(j);
      if (!["complete", "failed"].includes(j.status)) timer.current = window.setTimeout(tick, 1500);
    };
    tick().catch((e) => setError(e.message));
  };

  const submit = async () => {
    setError(null);
    setJob(null);
    let records: any[];
    try {
      records = JSON.parse(text);
      if (!Array.isArray(records)) throw new Error("Expected a JSON array of records");
    } catch (e: any) {
      setError(e.message);
      return;
    }
    setSubmitting(true);
    try {
      const batchId = `ui-${Date.now()}`;
      const total = Math.ceil(records.length / BATCH_SIZE);
      let jobId = "";
      for (let i = 0; i < total; i++) {
        const r = await api(`/v1/tenants/${tenantId}/records:batch`, {
          body: { batchId, mode, sequence: i + 1, totalBatches: total, records: records.slice(i * BATCH_SIZE, (i + 1) * BATCH_SIZE) },
        });
        jobId = r.jobId;
      }
      poll(jobId);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const c = job?.counts ?? {};
  const ip = job?.indexProgress;

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <div className="space-y-6 lg:col-span-3">
        <Card title="Submit records" actions={<Button onClick={submit} busy={submitting} disabled={!tenantId || !text}>Submit ({mode})</Button>}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Tenant">
              <select className="input" value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
                {tenants.map((t) => <option key={t._id} value={t._id}>{t.name} ({t._id})</option>)}
              </select>
            </Field>
            <Field label="Mode" hint={mode === "full_replace"
              ? "Writes to a new dataset version; flips the tenant pointer atomically once search indexes have caught up."
              : "Writes into the active version; unchanged records (content hash) are skipped."}>
              <select className="input" value={mode} onChange={(e) => setMode(e.target.value as any)}>
                <option value="full_replace">full_replace (versioned atomic swap)</option>
                <option value="upsert">upsert</option>
              </select>
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-end gap-3 rounded-lg bg-slate-50 p-3">
            <Field label="Sample count"><input className="input w-28" type="number" value={count} onChange={(e) => setCount(Number(e.target.value))} /></Field>
            <Field label="Random seed"><input className="input w-28" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></Field>
            <Button variant="secondary" onClick={generate} disabled={!tenantId}>Generate sample records</Button>
            <span className="text-xs text-slate-500">Seed 42 = same as the seeded data ⇒ embeddings reused. Use another seed for new content.</span>
          </div>
          <Field label={`Records JSON (${text ? "array" : "empty"}) — sent in batches of ${BATCH_SIZE}`}>
            <textarea className="input mt-1 h-80 font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
              placeholder='[{"recordId": "...", ...}]' />
          </Field>
          <ErrorBox error={error} />
        </Card>
      </div>

      <div className="space-y-6 lg:col-span-2">
        <Card title="Job progress">
          {!job && <div className="text-sm text-slate-500">Submit a batch to see progress.</div>}
          {job && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <StatusBadge status={job.status} />
                <span className="font-mono text-xs text-slate-500">{job._id}</span>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Batches" value={`${job.batchesCompleted}/${job.totalBatches}`} />
                <Stat label="Received" value={c.received} />
                <Stat label="Processed" value={c.processed} />
                <Stat label="Embedded" value={c.embedded} />
                <Stat label="Emb. reused" value={c.embeddingReused} />
                <Stat label="Skipped" value={c.skipped} />
                <Stat label="Rejected" value={c.rejected} />
                <Stat label="Voyage tokens" value={c.tokens} />
                <Stat label="Target" value={job.targetDatasetVersion ? `v${job.targetDatasetVersion}` : "active"} />
              </div>
              {job.mode === "full_replace" && (
                <div className="rounded-lg border border-slate-200 p-3 text-sm">
                  <div className="mb-1 font-medium text-slate-700">Versioned swap</div>
                  <ol className="list-decimal space-y-1 pl-5 text-xs text-slate-600">
                    <li>Write all batches to v{job.targetDatasetVersion} (invisible to queries) {job.batchesCompleted >= job.totalBatches && <Badge tone="green">done</Badge>}</li>
                    <li>Wait for Atlas Search + Vector Search to index v{job.targetDatasetVersion}{" "}
                      {ip && !ip.error && <span>(text {ip.text}/{ip.expected}, vector {ip.vector}/{Math.min(ip.expected, 10000)})</span>}
                      {ip?.error && <span className="text-red-700"> {ip.error}</span>}
                    </li>
                    <li>Atomic single-document pointer flip on <code>tenants</code> {job.swap && <Badge tone="green">v{job.swap.from} → v{job.swap.to}</Badge>}</li>
                    <li>Old version purged after the grace period (rollback available until then)</li>
                  </ol>
                </div>
              )}
              <ErrorBox error={job.errorDetails} />
              {job.rejections?.length > 0 && <Json value={job.rejections} label={`${job.rejections.length} rejections`} />}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
