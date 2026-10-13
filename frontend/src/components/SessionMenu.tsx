import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { MoreVertical, Settings2, Trash2 } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { SessionView } from "../lib/types";
import { SessionOptionsDialog } from "./SessionOptionsDialog";

const MENU_WIDTH = 220;

/** "⋮" menu for a study session: view/adjust its options, or delete it. */
export function SessionMenu({ sessionId, onOptionsSaved, label = "Session menu" }: {
  sessionId: string;
  onOptionsSaved?: (view: SessionView) => void;
  label?: string;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const { toast, bumpHistory } = useApp();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const r = buttonRef.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(window.innerWidth - MENU_WIDTH - 8, r.right - MENU_WIDTH));
    const top = r.bottom + 4 + 140 > window.innerHeight ? Math.max(8, r.top - 4 - 140) : r.bottom + 4;
    setPos({ top, left });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e.type === "mousedown" && (menuRef.current?.contains(e.target as Node) || buttonRef.current?.contains(e.target as Node))) return;
      setOpen(false);
      setConfirming(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(e); };
    document.addEventListener("mousedown", close);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function stop(e: MouseEvent) {
    // The menu sits inside clickable rows and links; don't trigger them.
    e.preventDefault();
    e.stopPropagation();
  }

  async function remove() {
    setDeleting(true);
    try {
      await api.deleteSession(sessionId);
      setOpen(false);
      bumpHistory();
      toast("Session deleted.");
      if (location.pathname.includes(sessionId)) navigate("/", { replace: true });
    } catch (e) {
      toast(asApiError(e).message, "error");
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  }

  return (
    <>
      <button ref={buttonRef} className="icon-btn session-menu-btn" aria-label={label} aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => { stop(e); setOpen((o) => !o); setConfirming(false); }}>
        <MoreVertical size={17} />
      </button>
      {open && createPortal(
        <div ref={menuRef} className="menu" role="menu" style={{ top: pos.top, left: pos.left, width: MENU_WIDTH }} onClick={stop}>
          {!confirming ? (
            <>
              <button role="menuitem" className="menu-item" onClick={() => { setOpen(false); setDialog(true); }}>
                <Settings2 size={16} /> Session options
              </button>
              <button role="menuitem" className="menu-item danger" onClick={() => setConfirming(true)}>
                <Trash2 size={16} /> Delete session
              </button>
            </>
          ) : (
            <div className="menu-confirm">
              <div style={{ fontWeight: 600 }}>Delete this session?</div>
              <div className="muted small">Its questions, answers, results, and study guide are removed. This can't be undone.</div>
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn sm danger-solid" onClick={remove} disabled={deleting}>{deleting && <span className="spinner" />} Delete</button>
                <button className="btn sm ghost" onClick={() => setConfirming(false)}>Cancel</button>
              </div>
            </div>
          )}
        </div>,
        document.body,
      )}
      {dialog && (
        <SessionOptionsDialog sessionId={sessionId} onClose={() => setDialog(false)}
          onSaved={(view) => { bumpHistory(); onOptionsSaved?.(view); }} />
      )}
    </>
  );
}
