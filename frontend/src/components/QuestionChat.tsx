import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MessageCircleQuestion, Send, X } from "lucide-react";
import { api, asApiError } from "../lib/api";
import type { ApiErrorBody, ChatView } from "../lib/types";
import { ErrorBanner } from "./common";
import { Markdown } from "./Markdown";

const MODE_NOTE: Record<ChatView["mode"], string> = {
  unanswered: "Claude can explain and give hints, but won't give away the answer until you've answered.",
  answered_hidden: "You'll find out if you were right at the end, so Claude won't say yet.",
  revealed: "Ask anything about the answer and your feedback.",
};

const SUGGESTIONS: Record<ChatView["mode"], string[]> = {
  unanswered: ["What is this question asking?", "Can you give me a hint?", "Explain the key concept"],
  answered_hidden: ["Explain the key concept", "Where in my notes is this covered?"],
  revealed: ["Why is that the right answer?", "Where did I go wrong?", "Give me a similar practice question"],
};

/** Floating "Ask Claude" chat about the question on screen. Each question keeps its own conversation. */
export function QuestionChat({ questionId, refreshKey, onClose }: { questionId: string; refreshKey: string; onClose: () => void }) {
  const [view, setView] = useState<ChatView | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState<string | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const currentQid = useRef(questionId);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (currentQid.current !== questionId) {
      currentQid.current = questionId;
      setView(null);
      setDraft("");
      setError(null);
      setSending(null);
    }
    let alive = true;
    api.questionChat(questionId)
      .then((v) => { if (alive) setView(v); })
      .catch((e) => { if (alive) setError(asApiError(e).toBody()); });
    return () => { alive = false; };
  }, [questionId, refreshKey]);

  useEffect(() => { inputRef.current?.focus(); }, [questionId]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [view?.messages.length, sending, error]);

  async function send(text = draft) {
    const message = text.trim();
    if (!message || sending) return;
    const qid = questionId;
    setSending(message);
    setDraft("");
    setError(null);
    try {
      const v = await api.askClaude(qid, message);
      if (currentQid.current === qid) setView(v);
    } catch (e) {
      if (currentQid.current === qid) {
        setError(asApiError(e).toBody());
        setDraft(message);  // keep what they typed so they can retry
      }
    } finally {
      if (currentQid.current === qid) setSending(null);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      void send();
    }
  }

  const mode = view?.mode ?? "unanswered";
  const empty = !!view && view.messages.length === 0 && !sending;

  return createPortal(
    <section className="chat-panel" role="dialog" aria-label="Ask Claude about this question"
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <header className="chat-head">
        <div style={{ minWidth: 0 }}>
          <div className="chat-title"><MessageCircleQuestion size={17} /> Ask Claude</div>
          <div className="chat-note">{MODE_NOTE[mode]}</div>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close chat"><X size={18} /></button>
      </header>

      <div className="chat-list" ref={listRef} aria-live="polite">
        {!view && !error && <div className="skeleton" style={{ height: 60 }} />}
        {empty && (
          <div className="chat-empty">
            <p className="muted small">Ask about this question: what it means, the idea behind it, or a hint.</p>
            <div className="chat-suggestions">
              {SUGGESTIONS[mode].map((s) => (
                <button key={s} className="chip" onClick={() => void send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {view?.messages.map((m) => (
          <div key={m.id} className={`chat-msg ${m.role}`}>
            {m.role === "assistant" ? <Markdown>{m.content}</Markdown> : m.content}
          </div>
        ))}
        {sending && (<>
          <div className="chat-msg user">{sending}</div>
          <div className="chat-msg assistant thinking"><span className="spinner" /> Claude is thinking…</div>
        </>)}
        {error && <ErrorBanner error={error} compact onRetry={() => void send()} />}
      </div>

      <footer className="chat-input">
        <textarea ref={inputRef} className="textarea" rows={2} value={draft} maxLength={4000}
          placeholder="Ask a question…  (Enter to send, Shift+Enter for a new line)"
          onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} />
        <button className="btn primary" onClick={() => void send()} disabled={!draft.trim() || !!sending} aria-label="Send">
          {sending ? <span className="spinner" /> : <Send size={16} />}
        </button>
      </footer>
    </section>,
    document.body,
  );
}
