import { useState } from "react";

type Props = { mongosh?: string; pipelineText?: string; note?: string };

// Abbreviate inline query vectors for display only; copies keep the full vector.
function abbreviate(text: string) {
  return text.replace(/("queryVector":\s*)\[([^\]]*)\]/g, (_m, key: string, body: string) => {
    const n = body ? body.split(",").length : 0;
    return `${key}[ /* ${n} floats — included when copied */ ]`;
  });
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
}

export default function PipelineViewer({ mongosh, pipelineText, note }: Props) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<"mongosh" | "compass">("mongosh");
  const [copied, setCopied] = useState(false);
  if (!mongosh && !pipelineText) return null;
  const text = (format === "mongosh" ? mongosh : pipelineText) ?? "";

  const copy = async () => {
    await copyText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium ${open ? "border-emerald-600 bg-emerald-50 text-emerald-800" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`}
      >
        <span className={`relative inline-block h-4 w-7 rounded-full transition ${open ? "bg-emerald-600" : "bg-slate-300"}`}>
          <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${open ? "left-3.5" : "left-0.5"}`} />
        </span>
        Show MongoDB aggregation pipeline
      </button>
      {open && (
        <div className="mt-2 rounded-lg border border-slate-200">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2">
            <div className="flex gap-1 text-xs">
              {(["mongosh", "compass"] as const).map((f) => (
                <button key={f} onClick={() => setFormat(f)}
                  className={`rounded px-2 py-1 font-medium ${format === f ? "bg-white text-emerald-800 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>
                  {f === "mongosh" ? "mongosh command" : "Compass pipeline (array)"}
                </button>
              ))}
            </div>
            <button onClick={copy} className="rounded-md bg-emerald-700 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-800">
              {copied ? "Copied ✓" : "Copy"}
            </button>
          </div>
          {note && <div className="border-b border-slate-200 px-3 py-1.5 text-xs text-slate-500">{note}</div>}
          <pre className="max-h-[480px] overflow-auto bg-slate-900 p-3 text-xs text-slate-100">{abbreviate(text)}</pre>
        </div>
      )}
    </div>
  );
}
