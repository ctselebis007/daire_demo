import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorBox, Field } from "../components/ui";
import PipelineViewer from "../components/PipelineViewer";

type FilterRow = { field: string; op: string; value: string };

function titleOf(m: any) {
  return m?.name ?? m?.title ?? m?.vendorName ?? "—";
}
function subtitleOf(m: any) {
  if (!m) return "";
  if (m.name) return `${m.level} · ${m.practice} · ${m.yearsExperience}y · ${m.location?.city}, ${m.location?.country}`;
  if (m.title) return `${m.topic} · ${m.level} · ${m.format} · ${m.durationHours}h · ★${m.rating}`;
  if (m.vendorName) return `${m.category} · ${(m.regions ?? []).join("/")} · ★${m.rating}${m.diversityOwned ? " · diversity-owned" : ""}`;
  return "";
}
function tagsOf(m: any): string[] {
  return (m?.skills ?? m?.skillsTaught ?? m?.capabilities ?? []).slice(0, 6);
}

export default function Playground() {
  const [tenants, setTenants] = useState<any[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [query, setQuery] = useState<Record<string, any>>({});
  const [filters, setFilters] = useState<FilterRow[]>([]);
  const [vectorMode, setVectorMode] = useState("auto");
  const [rerank, setRerank] = useState(true);
  const [explain, setExplain] = useState(true);
  const [weights, setWeights] = useState({ vector: 0.7, text: 0.3 });
  const [compare, setCompare] = useState<any>(null);
  const [reco, setReco] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fb, setFb] = useState<Record<string, string>>({});

  useEffect(() => {
    api("/v1/tenants").then((t) => {
      setTenants(t);
      if (t.length) selectTenant(t[0]);
    }).catch((e) => setError(e.message));
  }, []);

  const tenant = useMemo(() => tenants.find((t) => t._id === tenantId), [tenants, tenantId]);
  const props: Record<string, any> = tenant?.queryConfig?.schema?.properties ?? {};
  const types: Record<string, string> = Object.fromEntries((tenant?.indexConfig?.filterFields ?? []).map((f: any) => [f.path, f.type]));
  const allowed: { field: string; ops: string[] }[] = tenant?.filterConfig?.allowed ?? [];
  const tenantWeights = (t: any) => {
    const w = t?.recommendationPipeline?.fusion?.weights ?? {};
    return { vector: w.vector ?? 0.7, text: w.text ?? 0.3 };
  };
  const setVectorWeight = (v: number) => setWeights({ vector: v, text: Math.round((1 - v) * 100) / 100 });

  function selectTenant(t: any) {
    setTenantId(t._id);
    setWeights(tenantWeights(t));
    setCompare(null);
    setReco(null);
    const sq = t.sampleQueries?.[0];
    if (sq) applySample(sq);
    else {
      setQuery({});
      setFilters([]);
    }
  }

  function applySample(sq: any) {
    setQuery(sq.query);
    setFilters((sq.filters ?? []).map((f: any) => ({ field: f.field, op: f.op, value: Array.isArray(f.value) ? f.value.join(", ") : String(f.value) })));
  }

  function parseFilters() {
    return filters.filter((f) => f.field && f.op).map((f) => {
      const t = types[f.field] ?? "string";
      const conv = (v: string): any => (t === "number" ? Number(v) : t === "boolean" ? v.trim() === "true" : v.trim());
      let value: any;
      if (f.op === "exists") value = f.value.trim() !== "false";
      else if (f.op === "in" || f.op === "nin") value = f.value.split(",").map((s) => s.trim()).filter(Boolean).map(conv);
      else value = conv(f.value);
      return { field: f.field, op: f.op, value };
    });
  }

  function cleanQuery() {
    const q: Record<string, any> = {};
    for (const [k, v] of Object.entries(query)) {
      if (v === "" || v == null || (Array.isArray(v) && !v.length)) continue;
      q[k] = v;
    }
    return q;
  }

  const runCompare = async () => {
    setBusy("compare");
    setError(null);
    try {
      setCompare(await api(`/v1/tenants/${tenantId}/search`, { body: { query: cleanQuery(), filters: parseFilters(), vectorMode, weights, limit: 10 } }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const runReco = async () => {
    setBusy("reco");
    setError(null);
    setFb({});
    try {
      setReco(await api(`/v1/tenants/${tenantId}/recommendations`, {
        body: { query: cleanQuery(), filters: parseFilters(), vectorMode, weights, rerank, explain, userId: "demo-user" },
      }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const sendFeedback = async (r: any, positive: boolean) => {
    try {
      await api("/v1/feedback", {
        body: {
          tenantId, requestId: reco.requestId, recordId: r.recordId, userId: "demo-user",
          feedbackType: positive ? "selection" : "dismiss", successScore: positive ? 1 : 0,
          requestFeatures: cleanQuery(), candidateFeatures: { rank: r.rank },
          interaction: { clicked: positive, viewed: true, position: r.rank },
          embeddingSimilarity: r.scores?.semanticSimilarity ?? null,
        },
      });
      setFb((s) => ({ ...s, [r.recordId]: positive ? "👍 recorded" : "👎 recorded" }));
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Query" className="lg:col-span-2" actions={
          <>
            <Button variant="secondary" onClick={runCompare} busy={busy === "compare"} disabled={!tenantId}>Compare search modes</Button>
            <Button onClick={runReco} busy={busy === "reco"} disabled={!tenantId}>Get recommendations</Button>
          </>
        }>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Tenant">
              <select className="input" value={tenantId} onChange={(e) => selectTenant(tenants.find((t) => t._id === e.target.value))}>
                {tenants.map((t) => <option key={t._id} value={t._id}>{t.name}</option>)}
              </select>
            </Field>
            <Field label="Sample queries">
              <select className="input" defaultValue="" onChange={(e) => e.target.value !== "" && applySample(tenant.sampleQueries[Number(e.target.value)])}>
                <option value="">Choose…</option>
                {(tenant?.sampleQueries ?? []).map((s: any, i: number) => <option key={i} value={i}>{s.label}</option>)}
              </select>
            </Field>
            {Object.entries(props).map(([k, p]: [string, any]) => (
              <Field key={k} label={`${k}${tenant?.queryConfig?.schema?.required?.includes(k) ? " *" : ""}`} hint={p.type === "array" ? "comma-separated" : undefined}>
                {p.type === "array" ? (
                  <input className="input" value={(query[k] ?? []).join(", ")}
                    onChange={(e) => setQuery({ ...query, [k]: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
                ) : (p.maxLength ?? 0) > 300 ? (
                  <textarea className="input h-20" value={query[k] ?? ""} onChange={(e) => setQuery({ ...query, [k]: e.target.value })} />
                ) : (
                  <input className="input" value={query[k] ?? ""} onChange={(e) => setQuery({ ...query, [k]: e.target.value })} />
                )}
              </Field>
            ))}
          </div>
        </Card>

        <Card title="Filters & options">
          <div className="space-y-2">
            {filters.map((f, i) => {
              const ops = allowed.find((a) => a.field === f.field)?.ops ?? [];
              return (
                <div key={i} className="grid grid-cols-12 gap-1">
                  <select className="input col-span-5 !px-1 text-xs" value={f.field}
                    onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, field: e.target.value, op: allowed.find((a) => a.field === e.target.value)?.ops[0] ?? "eq" } : x)))}>
                    {allowed.map((a) => <option key={a.field} value={a.field}>{a.field.replace("metadata.", "")}</option>)}
                  </select>
                  <select className="input col-span-2 !px-1 text-xs" value={f.op} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))}>
                    {ops.map((o) => <option key={o}>{o}</option>)}
                  </select>
                  <input className="input col-span-4 !px-1 text-xs" value={f.value} placeholder={types[f.field]}
                    onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                  <button className="col-span-1 text-slate-400 hover:text-red-600" onClick={() => setFilters(filters.filter((_, j) => j !== i))}>✕</button>
                </div>
              );
            })}
            <Button variant="secondary" onClick={() => allowed[0] && setFilters([...filters, { field: allowed[0].field, op: allowed[0].ops[0], value: "" }])}>+ Add filter</Button>
            <p className="text-xs text-slate-500">Only allow-listed fields/operators (tenant filterConfig). Applied as a pre-filter inside $vectorSearch and as compound.filter in $search.</p>
          </div>
          <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
            <Field label="Hybrid weights ($rankFusion)" hint="RRF score = Σ weight × 1/(60 + rank) per pipeline. Applies to the Hybrid column and recommendations.">
              <div className="flex items-center gap-2 text-xs">
                <span className="w-16 text-sky-700">vector {weights.vector.toFixed(2)}</span>
                <input type="range" min={0} max={1} step={0.05} value={weights.vector} className="flex-1 accent-emerald-700"
                  onChange={(e) => setVectorWeight(Number(e.target.value))} />
                <span className="w-14 text-right text-amber-700">text {weights.text.toFixed(2)}</span>
              </div>
              <div className="mt-1 flex gap-2">
                {[[1, 0], [0.7, 0.3], [0.5, 0.5], [0.3, 0.7], [0, 1]].map(([v, t]) => (
                  <button key={v} onClick={() => setWeights({ vector: v, text: t })}
                    className={`rounded border px-1.5 py-0.5 text-[11px] ${weights.vector === v ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
                    {v}/{t}
                  </button>
                ))}
                <button className="ml-auto text-[11px] text-emerald-700 hover:underline" onClick={() => setWeights(tenantWeights(tenant))}>tenant default</button>
              </div>
            </Field>
            <Field label="Vector search mode" hint="auto = exact (ENN) when the tenant has fewer docs than indexConfig.vector.exactSearchBelowDocs">
              <select className="input" value={vectorMode} onChange={(e) => setVectorMode(e.target.value)}>
                <option value="auto">auto</option>
                <option value="ann">ANN (HNSW)</option>
                <option value="exact">exact (ENN)</option>
              </select>
            </Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} /> Voyage rerank</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} /> OpenAI explanations</label>
          </div>
        </Card>
      </div>

      <ErrorBox error={error} />

      {reco && (
        <Card title="Recommendations" actions={
          <div className="flex flex-wrap gap-1">
            <Badge tone="blue">{reco.vectorSearch}</Badge>
            <Badge tone="blue">{reco.fusion}</Badge>
            {reco.weights && <Badge tone="blue">weights {reco.weights.vector}/{reco.weights.text}</Badge>}
            {reco.reranked && <Badge tone="green">reranked · {reco.reranker}</Badge>}
            {Object.entries(reco.timingsMs ?? {}).map(([k, v]) => <Badge key={k}>{k} {String(v)}ms</Badge>)}
          </div>
        }>
          <div className="mb-3 rounded-md bg-slate-50 p-2 text-xs text-slate-600">
            <b>Query text:</b> {reco.queryText}<br /><b>Keyword text:</b> {reco.keywordText}<br /><b>requestId:</b> <span className="font-mono">{reco.requestId}</span>
          </div>
          {reco.explanationError && <ErrorBox error={`Explanations unavailable: ${reco.explanationError}`} />}
          <div className="space-y-3">
            {reco.results.map((r: any) => (
              <div key={r.recordId} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-800">#{r.rank} {titleOf(r.metadata)} <span className="font-mono text-xs font-normal text-slate-400">{r.recordId}</span></div>
                    <div className="text-xs text-slate-500">{subtitleOf(r.metadata)}</div>
                    <div className="mt-1 flex flex-wrap gap-1">{tagsOf(r.metadata).map((t) => <Badge key={t}>{t}</Badge>)}</div>
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-1 text-xs">
                    {r.scores.rerank != null && <Badge tone="green">rerank {r.scores.rerank}</Badge>}
                    {r.scores.preRerankRank != null && <Badge>fused #{r.scores.preRerankRank}</Badge>}
                    <Badge tone="blue">vec #{r.scores.vectorRank ?? "–"}</Badge>
                    <Badge tone="amber">text #{r.scores.textRank ?? "–"}</Badge>
                    <Badge>sim {r.scores.semanticSimilarity}</Badge>
                  </div>
                </div>
                {r.explanation && <p className="mt-2 rounded-md bg-emerald-50 p-2 text-sm text-emerald-900">{r.explanation}</p>}
                <div className="mt-2 flex items-center gap-2 text-xs">
                  {fb[r.recordId] ? <span className="text-slate-500">{fb[r.recordId]}</span> : (
                    <>
                      <button className="rounded border border-slate-200 px-2 py-0.5 hover:bg-slate-50" onClick={() => sendFeedback(r, true)}>👍 Relevant</button>
                      <button className="rounded border border-slate-200 px-2 py-0.5 hover:bg-slate-50" onClick={() => sendFeedback(r, false)}>👎 Not relevant</button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
          <PipelineViewer mongosh={reco.mongosh} pipelineText={reco.pipelineText}
            note={`Exact Atlas stage executed for this request (limit = topK × overfetch). Voyage rerank and OpenAI explanations run in the app afterwards.`} />
        </Card>
      )}

      {compare && (
        <Card title="Search mode comparison" actions={<Badge>embed {compare.embedMs}ms</Badge>}>
          <div className="grid gap-4 lg:grid-cols-3">
            {(["vector", "text", "hybrid"] as const).map((m) => {
              const run = compare.runs[m];
              if (!run) return null;
              return (
                <div key={m}>
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold capitalize text-slate-700">
                      {m === "vector" ? `Vector only (${run.exact ? "ENN" : "ANN"})` : m === "text" ? "Text only (BM25)" : `Hybrid ($rankFusion ${run.weights?.vector}/${run.weights?.text})`}
                    </h3>
                    <Badge>{run.timingMs}ms</Badge>
                  </div>
                  <ol className="space-y-1.5">
                    {run.results.map((r: any) => (
                      <li key={r.recordId} className="rounded-md border border-slate-100 p-2 text-xs">
                        <div className="font-medium text-slate-800">{r.rank}. {titleOf(r.metadata)}</div>
                        <div className="text-slate-500">{subtitleOf(r.metadata)}</div>
                        <div className="mt-1 flex gap-1">
                          <Badge>score {typeof r.scores.score === "number" ? r.scores.score.toFixed(4) : "–"}</Badge>
                          {m === "hybrid" && <><Badge tone="blue">vec #{r.scores.vectorRank ?? "–"}</Badge><Badge tone="amber">text #{r.scores.textRank ?? "–"}</Badge></>}
                        </div>
                      </li>
                    ))}
                    {!run.results.length && <li className="text-xs text-slate-500">No results</li>}
                  </ol>
                  <PipelineViewer mongosh={run.mongosh} pipelineText={run.pipelineText} />
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
