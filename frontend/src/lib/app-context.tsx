import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, asApiError, type ApiError } from "./api";
import type { SettingsPayload } from "./types";

interface Toast { id: number; message: string; tone: "info" | "success" | "error" }

interface AppState {
  settings: SettingsPayload | null;
  settingsError: ApiError | null;
  reloadSettings: () => Promise<void>;
  setSettings: (s: SettingsPayload) => void;
  theme: "light" | "dark";
  toggleTheme: () => void;
  toast: (message: string, tone?: Toast["tone"]) => void;
  historyVersion: number;
  bumpHistory: () => void;
}

const Ctx = createContext<AppState | null>(null);

function applyTheme(theme: "light" | "dark") {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("sage-theme", theme); } catch { /* storage unavailable */ }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [settingsError, setSettingsError] = useState<ApiError | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => (document.documentElement.dataset.theme as "light" | "dark") || "light");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [historyVersion, setHistoryVersion] = useState(0);

  const reloadSettings = useCallback(async () => {
    try {
      const s = await api.settings();
      setSettings(s);
      setSettingsError(null);
      setTheme(s.settings.theme);
      applyTheme(s.settings.theme);
    } catch (e) {
      setSettingsError(asApiError(e));
    }
  }, []);

  useEffect(() => { void reloadSettings(); }, [reloadSettings]);

  const toggleTheme = useCallback(() => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    applyTheme(next);
    api.updateSettings({ theme: next }).then(setSettings).catch(() => { /* theme still applies locally */ });
  }, [theme]);

  const toast = useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);

  const value = useMemo<AppState>(() => ({
    settings, settingsError, reloadSettings, setSettings, theme, toggleTheme, toast,
    historyVersion, bumpHistory: () => setHistoryVersion((v) => v + 1),
  }), [settings, settingsError, reloadSettings, theme, toggleTheme, toast, historyVersion]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toast-wrap" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <span className={`badge ${t.tone === "error" ? "incorrect" : t.tone === "success" ? "correct" : "primary"}`}>
              {t.tone === "error" ? "Error" : t.tone === "success" ? "Done" : "Note"}
            </span>
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp outside AppProvider");
  return ctx;
}
