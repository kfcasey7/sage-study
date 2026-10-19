import { useRef, useState, type DragEvent } from "react";
import {
  AlertTriangle, CheckCircle2, CirclePlay, FileImage, FileText, Globe, Link2, Presentation, RefreshCw, Sheet, Upload, X,
} from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { SourceView } from "../lib/types";

const TYPE_LABELS: Record<string, string> = {
  pdf: "PDF", docx: "Word document", pptx: "PowerPoint", text: "Text", image: "Image", web: "Web page", web_pdf: "PDF link",
  web_file: "Linked file", youtube: "YouTube video", gdoc: "Google Doc", gslides: "Google Slides", gsheet: "Google Sheet",
};

export function sourceIcon(type: string, size = 18) {
  if (type === "youtube") return <CirclePlay size={size} />;
  if (type === "web") return <Globe size={size} />;
  if (type === "image") return <FileImage size={size} />;
  if (type === "pptx" || type === "gslides") return <Presentation size={size} />;
  if (type === "gsheet") return <Sheet size={size} />;
  return <FileText size={size} />;
}

function hostOf(url: string | null): string {
  if (!url) return "";
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

function readyDetail(s: SourceView): string {
  const type = TYPE_LABELS[s.source_type] ?? "Source";
  const host = s.kind === "link" && s.source_type !== "youtube" ? ` · ${hostOf(s.url)}` : "";
  if (s.content_kind === "text" && s.char_count) {
    return `${type}${host} · ${s.char_count.toLocaleString()} characters${s.source_type === "youtube" ? " of transcript" : ""}`;
  }
  if (s.content_kind === "pdf") return `${type}${host} · scanned, Claude reads the pages`;
  if (s.content_kind === "image") return `${type} · Claude reads it directly`;
  return `${type}${host}`;
}

/** One source: type icon, title, and Processing / Ready / Couldn't read, with remove (and retry for links). */
export function SourceCard({ source, onRemove, onRetry, onUploadInstead, showLabel = false }: {
  source: SourceView;
  onRemove?: () => void;
  onRetry?: () => void;
  onUploadInstead?: () => void;
  showLabel?: boolean;
}) {
  const failed = source.status === "failed";
  const title = source.title && source.title !== source.url ? source.title : hostOf(source.url) || source.title;
  return (
    <div className={`source-card ${failed ? "failed" : ""}`}>
      <div className="source-icon">{sourceIcon(source.source_type)}</div>
      <div className="source-main">
        <div className="source-title" title={source.url ?? source.title}>
          {showLabel && source.label && <span className="source-label">{source.label}</span>}
          {source.kind === "link" && source.url && source.status !== "processing"
            ? <a href={source.url} title="Open in your browser" onClick={(e) => { e.preventDefault(); void api.openUrl(source.url!); }}>{title}</a>
            : title}
        </div>
        <div className="source-status">
          {source.status === "processing" && <><span className="spinner" /> {source.kind === "link" ? `Reading ${hostOf(source.url)}…` : "Processing…"}</>}
          {source.status === "ready" && <><CheckCircle2 size={14} color="var(--correct)" /> <span>{readyDetail(source)}
            {source.in_breakdown === false && <span className="badge warn" style={{ marginLeft: 6 }}>Not in breakdown yet</span>}</span></>}
          {failed && <><AlertTriangle size={14} /> <span><strong>Couldn't read:</strong> {source.error?.message ?? "Unknown error."}</span></>}
        </div>
        {failed && (onRetry || onUploadInstead) && (
          <div className="row" style={{ marginTop: 6 }}>
            {onRetry && source.kind === "link" && <button className="btn sm" onClick={onRetry}><RefreshCw size={13} /> Try again</button>}
            {onUploadInstead && <button className="btn sm ghost" onClick={onUploadInstead}><Upload size={13} /> Upload the file instead</button>}
          </div>
        )}
      </div>
      {onRemove && <button className="icon-btn" onClick={onRemove} aria-label={`Remove ${title}`}><X size={16} /></button>}
    </div>
  );
}

interface Pending { key: string; name: string; error?: string }

/** Add files (drop or browse) and links (paste one or more). New sources are reported through onAdded;
 *  the parent shows them (with SourceCard) and polls links that are still being read. */
export function SourceAdder({ scope, onAdded, compact = false, inputRef: externalRef }: {
  scope: { set_id?: string; draft_id?: string };
  onAdded: (sources: SourceView[]) => void;
  compact?: boolean;
  inputRef?: React.RefObject<HTMLInputElement>;
}) {
  const { settings, toast } = useApp();
  const [drag, setDrag] = useState(false);
  const [links, setLinks] = useState("");
  const [adding, setAdding] = useState(false);
  const [pending, setPending] = useState<Pending[]>([]);
  const ownRef = useRef<HTMLInputElement>(null);
  const inputRef = externalRef ?? ownRef;
  const opts = settings?.options;

  function addFiles(list: FileList | File[]) {
    if (!opts) return;
    const accepted = new Set(opts.extensions);
    for (const file of Array.from(list)) {
      const key = `${file.name}-${file.size}-${Math.random()}`;
      const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
      if (!accepted.has(ext)) {
        setPending((p) => [...p, { key, name: file.name, error: `Unsupported type. Use ${opts.extensions.join(", ")}.` }]);
        continue;
      }
      if (file.size > opts.max_file_mb * 1024 * 1024) {
        setPending((p) => [...p, { key, name: file.name, error: `Larger than ${opts.max_file_mb} MB.` }]);
        continue;
      }
      setPending((p) => [...p, { key, name: file.name }]);
      api.addFileSource(file, scope)
        .then((s) => {
          setPending((p) => p.filter((x) => x.key !== key));
          if (s.duplicate) toast(`"${file.name}" is already in this list.`);
          else onAdded([s]);
        })
        .catch((e) => setPending((p) => p.map((x) => (x.key === key ? { ...x, error: asApiError(e).message } : x))));
    }
  }

  async function addLinks() {
    const urls = links.split(/[\s,]+/).map((u) => u.trim()).filter(Boolean);
    if (!urls.length) return;
    setAdding(true);
    try {
      const out = await api.addLinkSources(urls, scope);
      const bad = out.filter((s) => !s.id);
      const dupes = out.filter((s) => s.duplicate);
      const fresh = out.filter((s) => s.id && !s.duplicate) as SourceView[];
      if (fresh.length) onAdded(fresh);
      if (dupes.length) toast(dupes.length === 1 ? "That link is already in this list." : `${dupes.length} links were already in this list.`);
      if (bad.length) {
        toast(bad.map((b) => `${b.url}: ${b.error?.message}`).join(" "), "error");
        setLinks(bad.map((b) => b.url).join("\n"));
      } else {
        setLinks("");
      }
    } catch (e) {
      toast(asApiError(e).message, "error");
    } finally {
      setAdding(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
    const text = e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain");
    if (!e.dataTransfer.files.length && /^https?:\/\//.test(text)) setLinks((l) => (l ? `${l}\n${text}` : text));
  }

  return (
    <div className={`source-adder ${compact ? "compact" : ""}`}>
      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
      >
        <Upload size={compact ? 20 : 26} />
        <div><strong>Drop files here</strong> or click to browse</div>
        {!compact && <div className="muted small">PDF, Word, PowerPoint, text/Markdown, or photos of notes (PNG/JPG), up to {opts?.max_file_mb ?? 20} MB each</div>}
        <input ref={inputRef} type="file" multiple hidden accept={opts?.extensions.join(",")}
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
      </div>
      <div className="link-box">
        <Link2 size={18} className="link-icon" />
        <textarea className="textarea" rows={links.includes("\n") ? 3 : 1} value={links} onChange={(e) => setLinks(e.target.value)}
          placeholder={compact ? "Paste links (one per line)" : "Paste links: web pages, PDFs, YouTube videos, public Google Docs/Slides (one per line)"}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void addLinks(); } }}
          aria-label="Links to add" />
        <button className="btn" onClick={() => void addLinks()} disabled={!links.trim() || adding}>
          {adding ? <span className="spinner" /> : null} Add {links.trim().split(/\s+/).filter(Boolean).length > 1 ? "links" : "link"}
        </button>
      </div>
      {pending.length > 0 && (
        <div className="source-list">
          {pending.map((p) => (
            <div key={p.key} className={`source-card ${p.error ? "failed" : ""}`}>
              <div className="source-icon">{sourceIcon(p.name.toLowerCase().endsWith(".pptx") ? "pptx" : /\.(png|jpe?g)$/i.test(p.name) ? "image" : "pdf")}</div>
              <div className="source-main">
                <div className="source-title">{p.name}</div>
                <div className="source-status">
                  {p.error ? <><AlertTriangle size={14} /> <span><strong>Couldn't read:</strong> {p.error}</span></> : <><span className="spinner" /> Uploading…</>}
                </div>
              </div>
              {p.error && <button className="icon-btn" onClick={() => setPending((l) => l.filter((x) => x.key !== p.key))} aria-label="Dismiss"><X size={16} /></button>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
