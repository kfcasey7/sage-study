import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ClipboardCopy, RefreshCw } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, Diagnostics as DiagnosticsT } from "../lib/types";
import { ErrorBanner, Loading } from "../components/common";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Some embedded windows don't allow the clipboard API.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

export default function Diagnostics() {
  const { toast } = useApp();
  const [data, setData] = useState<DiagnosticsT | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);

  async function load() {
    setError(null);
    try { setData(await api.diagnostics()); }
    catch (e) { setError(asApiError(e).toBody()); }
  }
  useEffect(() => { void load(); }, []);

  async function copy() {
    if (!data) return;
    toast((await copyText(data.report)) ? "Diagnostic report copied." : "Couldn't copy. Select the details below instead.", "success");
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <Link to="/settings" className="muted small"><ArrowLeft size={13} style={{ verticalAlign: -2 }} /> Settings</Link>
          <h1>Diagnostics</h1>
          <p>Details to include when you report a problem.</p>
        </div>
      </div>

      <ErrorBanner error={error} onRetry={() => void load()} />
      {!data && !error && <Loading message="Checking…" rotate={false} />}

      {data && (
        <section className="card">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.label}>
                  <td className="muted small" style={{ padding: "6px 12px 6px 0", whiteSpace: "nowrap", verticalAlign: "top" }}>{item.label}</td>
                  <td style={{ padding: "6px 0", overflowWrap: "anywhere" }}>{item.label === "Data folder" ? data.data_dir : item.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ marginTop: 14 }}>
            <button className="btn primary sm" onClick={copy}><ClipboardCopy size={14} /> Copy diagnostic report</button>
            <button className="btn sm" onClick={() => void load()}><RefreshCw size={14} /> Check again</button>
          </div>
          <p className="muted small" style={{ marginBottom: 0 }}>
            The report contains only what's listed here, with your home folder shortened to <code>~</code>. It never includes passwords,
            keys, your account's email, your documents, or your study content.
          </p>
        </section>
      )}
    </div>
  );
}
