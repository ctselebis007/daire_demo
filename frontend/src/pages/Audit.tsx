import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorBox, Json, Stat, StatusBadge } from "../components/ui";

export default function Audit() {
  const [tenantId, setTenantId] = useState("");
  const [tenants, setTenants] = useState<any[]>([]);
  const [audits, setAudits] = useState<any>(null);
  const [feedback, setFeedback] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [ttlDays, setTtlDays] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const q = tenantId ? `?tenantId=${encodeURIComponent(tenantId)}` : "";
      const [a, f, s] = await Promise.all([api(`/v1/audits${q}`), api(`/v1/feedback${q}`), api("/api/setup")]);
      setAudits(a);
      setFeedback(f);
      setTtlDays(s.settings.audit_ttl_days);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    api("/v1/tenants").then(setTenants).catch(() => {});
  }, []);
  useEffect(() => {
    load();
  }, [tenantId]);

  const open = async (requestId: string) => {
    try {
      setDetail(await api(`/v1/audits/${encodeURIComponent(requestId)}`));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const oldestDays = audits?.oldest ? (Date.now() - new Date(audits.oldest).getTime()) / 86_400_000 : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <select className="input max-w-xs" value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
          <option value="">All tenants</option>
          {tenants.map((t) => <option key={t._id} value={t._id}>{t.name}</option>)}
        </select>
        <Button variant="secondary" onClick={load}>Refresh</Button>
      </div>
      <ErrorBox error={error} />

      <div className="grid gap-4 md:grid-cols-4">
        <Stat label="Audit records" value={audits?.total?.toLocaleString() ?? "–"} />
        <Stat label="TTL retention" value={ttlDays ? `${ttlDays} days` : "–"} />
        <Stat label="Oldest record age" value={oldestDays != null ? `${oldestDays.toFixed(1)} days` : "–"} />
        <Stat label="TTL status" value={oldestDays == null ? "–" : oldestDays > (ttlDays ?? 0) + 1 ? "pending (create DB indexes)" : "enforced"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="API audit log (newest first)">
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="text-left uppercase text-slate-500">
                <tr><th className="py-1">Time</th><th>Tenant</th><th>Status</th><th>Total ms</th><th>Request</th></tr>
              </thead>
              <tbody>
                {(audits?.items ?? []).map((a: any) => (
                  <tr key={a._id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => open(a.requestId)}>
                    <td className="py-1.5">{new Date(a.createdAt).toLocaleString()}</td>
                    <td>{a.tenantId}</td>
                    <td><StatusBadge status={String(a.httpStatusCode)} /></td>
                    <td>{a.timingsMs?.total}</td>
                    <td className="font-mono">{a.requestId}{a.seed && <Badge>seed</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title={detail ? `Audit ${detail.audit.requestId}` : "Audit detail"}>
          {!detail && <div className="text-sm text-slate-500">Click an audit row. Requests are PII-scrubbed before storage; feedback joins on requestId.</div>}
          {detail && (
            <div className="space-y-2 text-sm">
              <div className="flex flex-wrap gap-1">
                <StatusBadge status={String(detail.audit.httpStatusCode)} />
                {Object.entries(detail.audit.timingsMs ?? {}).map(([k, v]) => <Badge key={k}>{k} {String(v)}ms</Badge>)}
              </div>
              {detail.audit.error && <ErrorBox error={`${detail.audit.error.code}: ${detail.audit.error.message}`} />}
              <Json value={detail.audit.sanitizedRequest} label="sanitized request" collapsed={false} />
              <Json value={detail.audit.semanticSearchResponse} label="semantic search response" />
              <Json value={detail.audit.modelSearchResponse} label="rerank response" />
              <Json value={detail.audit.apiResponse} label="API response" />
              <Json value={detail.feedback} label={`${detail.feedback.length} feedback events`} />
            </div>
          )}
        </Card>
      </div>

      <Card title="Feedback events (newest first)">
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-left uppercase text-slate-500">
              <tr><th className="py-1">Time</th><th>Tenant</th><th>Record</th><th>User</th><th>Type</th><th>Success</th><th>Rating</th><th>Clicked</th><th>Pos</th></tr>
            </thead>
            <tbody>
              {feedback.map((f) => (
                <tr key={f._id} className="border-t border-slate-100">
                  <td className="py-1">{new Date(f.createdAt).toLocaleString()}</td>
                  <td>{f.tenantId}</td>
                  <td className="font-mono">{f.recordId}</td>
                  <td>{f.userId}</td>
                  <td>{f.feedbackType}</td>
                  <td>{f.successScore}</td>
                  <td>{f.userRating ?? "–"}</td>
                  <td>{f.interaction?.clicked ? "yes" : "no"}</td>
                  <td>{f.interaction?.position ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
