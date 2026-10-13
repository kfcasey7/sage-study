import { useEffect, useState } from "react";
import { NavLink, Link } from "react-router-dom";
import { History, Moon, PlusCircle, Settings as SettingsIcon, Sun } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { HistoryRow } from "../lib/types";
import { formatDate } from "./common";
import { SessionMenu } from "./SessionMenu";

export function Sidebar() {
  const { theme, toggleTheme, historyVersion, cli } = useApp();
  const [recent, setRecent] = useState<HistoryRow[]>([]);

  useEffect(() => {
    api.history().then((rows) => setRecent(rows.slice(0, 8))).catch(() => setRecent([]));
  }, [historyVersion]);

  return (
    <aside className="sidebar">
      <div className="brand">
        <img src="/icon.png" alt="" onError={(e) => (e.currentTarget.style.display = "none")} />
        <span>Sage Study</span>
      </div>
      <NavLink to="/" end className="nav-link"><PlusCircle size={18} /> New session</NavLink>
      <NavLink to="/history" className="nav-link"><History size={18} /> History</NavLink>
      <NavLink to="/settings" className="nav-link">
        <SettingsIcon size={18} /> Settings
        {cli && !cli.ready && <span className="badge warn" style={{ marginLeft: "auto" }} title={cli.message ?? ""}>Setup</span>}
      </NavLink>

      {recent.length > 0 && <div className="sidebar-section">Recent</div>}
      {recent.map((r) => (
        <div key={r.id} className="recent-row">
          <Link className="recent-link" to={r.status === "completed" ? `/results/${r.id}` : `/quiz/${r.id}`}>
            <span className="recent-title">{r.title || r.subject || "Untitled session"}</span>
            <span className="recent-meta">
              {formatDate(r.created_at)}
              {r.status === "completed" && r.score != null ? ` · ${Math.round(r.score)}%` : r.status !== "completed" ? " · in progress" : ""}
            </span>
          </Link>
          <SessionMenu sessionId={r.id} label={`Options for ${r.title || "session"}`} />
        </div>
      ))}

      <div className="sidebar-footer">
        <button className="btn ghost" onClick={toggleTheme} aria-label="Toggle dark mode" style={{ justifyContent: "flex-start" }}>
          {theme === "light" ? <Moon size={17} /> : <Sun size={17} />} {theme === "light" ? "Dark mode" : "Light mode"}
        </button>
      </div>
    </aside>
  );
}
