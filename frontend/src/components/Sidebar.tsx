import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { History, Moon, PlusCircle, Settings as SettingsIcon, Sun } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { StudySetRow } from "../lib/types";
import { formatDate } from "./common";
import { SetMenu } from "./SetMenu";

export function Sidebar() {
  const { theme, toggleTheme, historyVersion, cli } = useApp();
  const [recent, setRecent] = useState<StudySetRow[]>([]);

  useEffect(() => {
    api.sets().then((rows) => setRecent(rows.slice(0, 8))).catch(() => setRecent([]));
  }, [historyVersion]);

  return (
    <aside className="sidebar">
      <div className="brand">
        <img src="/icon.png" alt="" onError={(e) => (e.currentTarget.style.display = "none")} />
        <span>Sage Study</span>
      </div>
      <NavLink to="/" end className="nav-link"><PlusCircle size={18} /> New study set</NavLink>
      <NavLink to="/history" className="nav-link"><History size={18} /> History</NavLink>
      <NavLink to="/settings" className="nav-link">
        <SettingsIcon size={18} /> Settings
        {cli && !cli.ready && <span className="badge warn" style={{ marginLeft: "auto" }} title={cli.message ?? ""}>Setup</span>}
      </NavLink>

      {recent.length > 0 && <div className="sidebar-section">Recent study sets</div>}
      {recent.map((r) => (
        <div key={r.id} className="recent-row">
          <NavLink className="recent-link" to={`/sets/${r.id}`}>
            <span className="recent-title">{r.title || r.subject || "Untitled study set"}</span>
            <span className="recent-meta">
              {formatDate(r.last_activity || r.updated_at)}
              {r.last_score != null ? ` · ${Math.round(r.last_score)}%` : ""}
              {r.breakdown_status === "generating" ? " · building…" : ""}
            </span>
          </NavLink>
          <SetMenu setId={r.id} label={`Options for ${r.title || "study set"}`} />
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
