import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorBox, Field, Json } from "../components/ui";

type Settings = Record<string, any>;
type TestResult = { ok: boolean; error?: string; [k: string]: any };

const TESTS: [string, string][] = [
  ["mongodb", "Test MongoDB"],
  ["voyage", "Test Voyage AI"],
  ["openai", "Test OpenAI"],
];

export default function Setup() {
  const [form, setForm] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [tests, setTests] = useState<Record<string, TestResult | "running">>({});

  const load = async () => {
    const r = await api("/api/setup");
    setForm(r.settings);
  };
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  if (!form) return <ErrorBox error={error} />;
  const set = (k: string, v: any) => {
    setSaved(false);
    setForm({ ...form, [k]: v });
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const { configured, ...body } = form;
      const r = await api("/api/setup", { method: "PUT", body });
      setForm(r.settings);
      setSaved(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const runTest = async (t: string) => {
    setTests((s) => ({ ...s, [t]: "running" }));
    try {
      const r = await api<TestResult>(`/api/setup/test/${t}`, { method: "POST" });
      setTests((s) => ({ ...s, [t]: r }));
    } catch (e: any) {
      setTests((s) => ({ ...s, [t]: { ok: false, error: e.message } }));
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <Card title="Connection settings" actions={<Button onClick={save} busy={saving}>Save</Button>}>
          <div className="grid gap-4">
            <Field label="MongoDB URI" hint="mongodb+srv://user:password@cluster.xxxx.mongodb.net — stored server-side only; the password is never returned.">
              <input className="input font-mono" type="password" value={form.mongodb_uri} onChange={(e) => set("mongodb_uri", e.target.value)} placeholder="mongodb+srv://..." autoComplete="off" />
            </Field>
            <Field label="Database name">
              <input className="input" value={form.db_name} onChange={(e) => set("db_name", e.target.value)} />
            </Field>
            <Field label="Voyage AI API key" hint="Atlas Model API key (endpoint ai.mongodb.com). Leave masked value to keep the existing key.">
              <input className="input font-mono" type="password" value={form.voyage_api_key} onChange={(e) => set("voyage_api_key", e.target.value)} autoComplete="off" />
            </Field>
            <Field label="OpenAI API key" hint="Used for natural-language explanations.">
              <input className="input font-mono" type="password" value={form.openai_api_key} onChange={(e) => set("openai_api_key", e.target.value)} autoComplete="off" />
            </Field>

            <button className="text-left text-sm font-medium text-emerald-700 hover:underline" onClick={() => setAdvanced(!advanced)}>
              {advanced ? "▾" : "▸"} Advanced
            </button>
            {advanced && (
              <div className="grid gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4 md:grid-cols-2">
                <Field label="Voyage base URL">
                  <input className="input font-mono" value={form.voyage_base_url} onChange={(e) => set("voyage_base_url", e.target.value)} />
                </Field>
                <Field label="Embedding model">
                  <select className="input" value={form.embedding_model} onChange={(e) => set("embedding_model", e.target.value)}>
                    {["voyage-4", "voyage-4-large", "voyage-4-lite"].map((m) => <option key={m}>{m}</option>)}
                  </select>
                </Field>
                <Field label="Embedding dimensions" hint="Changing after seeding requires re-embedding and recreating the vector index.">
                  <select className="input" value={form.embedding_dimensions} onChange={(e) => set("embedding_dimensions", Number(e.target.value))}>
                    {[256, 512, 1024, 2048].map((d) => <option key={d}>{d}</option>)}
                  </select>
                </Field>
                <Field label="Voyage reranker">
                  <select className="input" value={form.rerank_model} onChange={(e) => set("rerank_model", e.target.value)}>
                    {["rerank-3-lite", "rerank-3", "disabled"].map((m) => <option key={m}>{m}</option>)}
                  </select>
                </Field>
                <Field label="OpenAI model">
                  <input className="input" value={form.openai_model} onChange={(e) => set("openai_model", e.target.value)} />
                </Field>
                <Field label="Audit TTL (days)">
                  <input className="input" type="number" value={form.audit_ttl_days} onChange={(e) => set("audit_ttl_days", Number(e.target.value))} />
                </Field>
                <Field label="Old-version purge grace (seconds)" hint="Rollback window after a full_replace swap.">
                  <input className="input" type="number" value={form.purge_grace_seconds} onChange={(e) => set("purge_grace_seconds", Number(e.target.value))} />
                </Field>
              </div>
            )}
          </div>
          {saved && <div className="mt-3 text-sm text-emerald-700">Saved.</div>}
          <ErrorBox error={error} />
        </Card>
      </div>

      <div className="space-y-6">
        <Card title="Status">
          <div className="space-y-2 text-sm">
            {(["mongodb", "voyage", "openai"] as const).map((k) => (
              <div key={k} className="flex items-center justify-between">
                <span className="capitalize text-slate-600">{k}</span>
                <Badge tone={form.configured?.[k] ? "green" : "amber"}>{form.configured?.[k] ? "configured" : "not set"}</Badge>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Connection tests">
          <div className="space-y-4">
            {TESTS.map(([key, label]) => {
              const r = tests[key];
              return (
                <div key={key}>
                  <div className="flex items-center justify-between">
                    <Button variant="secondary" onClick={() => runTest(key)} busy={r === "running"}>{label}</Button>
                    {r && r !== "running" && <Badge tone={r.ok ? "green" : "red"}>{r.ok ? "PASS" : "FAIL"}</Badge>}
                  </div>
                  {r && r !== "running" && (
                    <>
                      {r.error && <ErrorBox error={r.error} />}
                      {key === "mongodb" && r.capabilities && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          <Badge tone="blue">v{r.capabilities.version}</Badge>
                          <Badge tone={r.capabilities.rankFusion ? "green" : "red"}>$rankFusion</Badge>
                          <Badge tone={r.capabilities.scoreFusion ? "green" : "slate"}>$scoreFusion</Badge>
                          <Badge tone={r.capabilities.searchIndexes ? "green" : "red"}>Search indexes</Badge>
                          <Badge tone={r.capabilities.changeStreams ? "green" : "amber"}>Change streams</Badge>
                        </div>
                      )}
                      <Json value={r} label="details" />
                    </>
                  )}
                </div>
              );
            })}
          </div>
          <p className="mt-4 text-xs text-slate-500">Save settings before testing.</p>
        </Card>
      </div>
    </div>
  );
}
