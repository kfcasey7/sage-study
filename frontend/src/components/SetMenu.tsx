import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { MoreVertical, Pencil, Trash2 } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";

const MENU_WIDTH = 230;

/** "⋮" menu for a Study Set: rename it, or delete it with everything made from it. */
export function SetMenu({ setId, onRename, label = "Study set menu" }: { setId: string; onRename?: () => void; label?: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { toast, bumpHistory } = useApp();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const r = buttonRef.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(window.innerWidth - MENU_WIDTH - 8, r.right - MENU_WIDTH));
    const top = r.bottom + 4 + 160 > window.innerHeight ? Math.max(8, r.top - 4 - 160) : r.bottom + 4;
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
    e.preventDefault();
    e.stopPropagation();
  }

  async function remove() {
    setDeleting(true);
    try {
      await api.deleteSet(setId);
      setOpen(false);
      bumpHistory();
      toast("Study set deleted.");
      if (location.pathname.includes(setId)) navigate("/history", { replace: true });
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
              {onRename && (
                <button role="menuitem" className="menu-item" onClick={() => { setOpen(false); onRename(); }}>
                  <Pencil size={16} /> Rename
                </button>
              )}
              <button role="menuitem" className="menu-item danger" onClick={() => setConfirming(true)}>
                <Trash2 size={16} /> Delete study set
              </button>
            </>
          ) : (
            <div className="menu-confirm">
              <div style={{ fontWeight: 600 }}>Delete this study set?</div>
              <div className="muted small">Its sources, quizzes, results, study guides, and playlists are removed. This can't be undone.</div>
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn sm danger-solid" onClick={remove} disabled={deleting}>{deleting && <span className="spinner" />} Delete</button>
                <button className="btn sm ghost" onClick={() => setConfirming(false)}>Cancel</button>
              </div>
            </div>
          )}
        </div>,
        document.body,
      )}
    </>
  );
}
