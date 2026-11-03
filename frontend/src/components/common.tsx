import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Info, RefreshCw, Terminal, Timer, WifiOff } from "lucide-react";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody } from "../lib/types";

export function LeafMark({ size = 46, className = "" }: { size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <path d="M38 8C22 8 10 18 10 32c0 3 .6 5.6 1.6 8 2-9 9-17 19-21-8 6-13 13-15 22 2 .6 4 1 6.4 1C33 42 40 30 38 8Z" fill="currentColor" opacity="0.92" />
    </svg>
  );
}

const FRIENDLY_SUBTEXT = [
  "Brewing some good questions…",
  "Skimming your notes for the important bits…",
  "Sharpening pencils…",
  "Checking the answer key twice…",
  "Finding the tricky parts…",
  "Almost there…",
];

export function Loading({ message, sub, rotate = true }: { message: string; sub?: string; rotate?: boolean }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!rotate || sub) return;
    const t = window.setInterval(() => setI((x) => (x + 1) % FRIENDLY_SUBTEXT.length), 3200);
    return () => window.clearInterval(t);
  }, [rotate, sub]);
  return (
    <div className="loading" role="status" aria-live="polite">
      <LeafMark className="leaf-spinner" />
      <div className="message">{message}</div>
      <div className="sub">{sub ?? (rotate ? FRIENDLY_SUBTEXT[i] : "")}</div>
    </div>
  );
}

const ERROR_TITLES: Record<string, string> = {
  cli_missing: "Claude Code not found",
  not_logged_in: "Claude Code isn't logged in",
  usage_limit: "Claude usage limit reached",
  cli_error: "Claude Code ran into a problem",
  overloaded: "Claude is busy",
  server_error: "Something went wrong",
  network: "No connection",
  timeout: "Request timed out",
  app_offline: "App backend not responding",
  refusal: "Request declined",
  truncated: "Response was cut off",
  invalid_output: "Couldn't read Claude's response",
  unsupported_file: "Unsupported file",
  file_too_large: "Files too large",
  missing_file: "File missing",
  bad_request: "Couldn't do that",
  conflict: "Not available right now",
  not_found: "Not found",
};

/** What to do about the failures people are most likely to run into. */
function ErrorHelp({ code }: { code: string }) {
  const { settings } = useApp();
  const docs = settings?.app.install_docs_url ?? "https://code.claude.com/docs/en/setup";
  if (code === "cli_missing") {
    return <div className="small" style={{ marginTop: 6 }}>Claude Code is a separate program from Anthropic. <a href={docs} target="_blank" rel="noreferrer">See how to install it</a>, then try again.</div>;
  }
  if (code === "not_logged_in") {
    return <div className="small" style={{ marginTop: 6 }}>Open a terminal (PowerShell on Windows, Terminal on a Mac), type <code>claude</code>, and follow the steps to sign in. Then try again.</div>;
  }
  if (code === "usage_limit") {
    return <div className="small" style={{ marginTop: 6 }}>This is your own Claude plan's limit, not a problem with the app. You haven't lost anything, and you weren't charged.</div>;
  }
  if (code === "network") {
    return <div className="small" style={{ marginTop: 6 }}>Check your Wi-Fi or internet connection. Everything you've done so far is saved.</div>;
  }
  return null;
}

export function ErrorBanner({ error, onRetry, compact }: { error: ApiErrorBody | null | undefined; onRetry?: () => void; compact?: boolean }) {
  const navigate = useNavigate();
  const [countdown, setCountdown] = useState<number | null>(null);
  useEffect(() => {
    if (!error?.retry_after) { setCountdown(null); return; }
    setCountdown(Math.ceil(error.retry_after));
    const t = window.setInterval(() => setCountdown((c) => (c && c > 1 ? c - 1 : 0)), 1000);
    return () => window.clearInterval(t);
  }, [error]);
  if (!error) return null;
  const setupIssue = ["cli_missing", "not_logged_in"].includes(error.code);
  const limit = error.code === "usage_limit";
  const Icon = setupIssue ? Terminal : limit ? Timer : ["network", "app_offline"].includes(error.code) ? WifiOff : AlertTriangle;
  const canRetry = onRetry && (error.retryable || ["refusal", "invalid_output", "truncated"].includes(error.code));
  return (
    <div className={`banner ${limit ? "warn" : "error"}`} role="alert">
      <Icon size={20} />
      <div className="banner-body">
        <div className="banner-title">{ERROR_TITLES[error.code] ?? "Something went wrong"}</div>
        <div>{error.message}</div>
        <ErrorHelp code={error.code} />
        {!compact && error.detail && <div className="banner-detail">Details: {error.detail}</div>}
        {(setupIssue || canRetry) && (
          <div className="row" style={{ marginTop: 10 }}>
            {setupIssue && <button className="btn sm primary" onClick={() => navigate("/settings")}><Terminal size={14} /> Check Claude Code status</button>}
            {canRetry && (
              <button className="btn sm" onClick={onRetry} disabled={!!countdown}>
                <RefreshCw size={14} /> {countdown ? `Retry in ${countdown}s` : "Try again"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function InfoBanner({ children, tone = "info", title }: { children: ReactNode; tone?: "info" | "warn"; title?: string }) {
  return (
    <div className={`banner ${tone}`}>
      {tone === "warn" ? <AlertTriangle size={20} /> : <Info size={20} />}
      <div className="banner-body">
        {title && <div className="banner-title">{title}</div>}
        {children}
      </div>
    </div>
  );
}

export function VerdictBadge({ verdict, skipped }: { verdict: string | null | undefined; skipped?: boolean }) {
  if (skipped) return <span className="badge incorrect">Skipped</span>;
  if (!verdict) return <span className="badge">Not graded</span>;
  const label = verdict === "correct" ? "Correct" : verdict === "partial" ? "Partial" : "Incorrect";
  return <span className={`badge ${verdict}`}>{label}</span>;
}

export function scoreColor(score: number | null | undefined): string {
  if (score == null) return "var(--border-strong)";
  if (score >= 85) return "var(--correct)";
  if (score >= 70) return "var(--primary)";
  if (score >= 40) return "var(--partial)";
  return "var(--incorrect)";
}

export function ScoreRing({ score, size = 132 }: { score: number | null; size?: number }) {
  const r = (size - 14) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score ?? 0));
  return (
    <div className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--surface-3)" strokeWidth="12" fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={scoreColor(score)} strokeWidth="12" fill="none" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} style={{ transition: "stroke-dashoffset 0.8s var(--ease)" }} />
      </svg>
      <div className="value">
        <strong>{score == null ? "–" : `${Math.round(score)}%`}</strong>
        <span className="muted small">overall</span>
      </div>
    </div>
  );
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
