import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, BookOpen, CircleHelp, Flag, Globe, HelpCircle, MessageCircleQuestion, MessageSquareWarning, Send, SkipForward,
  Undo2, Video,
} from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { AnswerView, ApiErrorBody, Confidence, QuestionView, SessionView } from "../lib/types";
import { ErrorBanner, Loading } from "../components/common";
import { SessionMenu } from "../components/SessionMenu";
import { QuestionChat } from "../components/QuestionChat";
import { VideoPanel } from "../components/Videos";
import { ReportQuestionDialog, type ReportResult } from "../components/ReportQuestionDialog";
import { Markdown } from "../components/Markdown";
import { AnswerInput, isAnswered, PROMPT_INSIDE_INPUT } from "../answers/AnswerInput";
import { FeedbackPanel } from "../answers/FeedbackPanel";

type Phase = "loading" | "pending" | "question" | "error" | "finishing";
const CLAUDE_GRADED = new Set(["short_response", "long_response", "free_response", "math", "code", "error_analysis", "applied_scenario", "fill_blank"]);

export default function Quiz() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { toast, bumpHistory } = useApp();
  const [session, setSession] = useState<SessionView | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [pendingMsg, setPendingMsg] = useState("Getting your session ready…");
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [q, setQ] = useState<QuestionView | null>(null);
  const [response, setResponse] = useState<Record<string, unknown>>({});
  const [confidence, setConfidence] = useState<Confidence | null>(null);
  const [answer, setAnswer] = useState<AnswerView | null>(null);
  const [submitting, setSubmitting] = useState<null | "answer" | "skip" | "defer">(null);
  const [progress, setProgress] = useState({ answered: 0, served: 0, skipped_waiting: 0 });
  const [confirmFinish, setConfirmFinish] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [videosOpen, setVideosOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reported, setReported] = useState<Set<string>>(new Set());
  const pollRef = useRef<number | null>(null);
  const topRef = useRef<HTMLDivElement>(null);

  const finish = useCallback(async () => {
    setPhase("finishing");
    try {
      await api.finish(id);
      bumpHistory();
      navigate(`/results/${id}`, { replace: true });
    } catch (e) {
      setError(asApiError(e).toBody());
      setPhase("error");
    }
  }, [id, navigate, bumpHistory]);

  const loadNext = useCallback(async () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
    try {
      const r = await api.next(id);
      setProgress({ answered: r.progress.answered, served: r.progress.served, skipped_waiting: r.progress.skipped_waiting ?? 0 });
      if (r.state === "question") {
        setQ(r.question);
        setResponse({});
        setConfidence(null);
        setAnswer(null);
        setError(null);
        setPhase("question");
        topRef.current?.scrollIntoView({ block: "start" });
      } else if (r.state === "pending") {
        setPendingMsg(r.message);
        setPhase("pending");
        api.session(id).then(setSession).catch(() => { /* keep polling */ });
        pollRef.current = window.setTimeout(loadNext, 1500);
      } else if (r.state === "done") {
        void finish();
      } else {
        setError(r.error);
        setPhase("error");
      }
    } catch (e) {
      setError(asApiError(e).toBody());
      setPhase("error");
    }
  }, [id, finish]);

  useEffect(() => {
    api.session(id)
      .then((s) => {
        setSession(s);
        if (s.status === "completed") navigate(`/results/${id}`, { replace: true });
        else void loadNext();
      })
      .catch((e) => { setError(asApiError(e).toBody()); setPhase("error"); });
    return () => { if (pollRef.current) window.clearTimeout(pollRef.current); };
  }, [id, loadNext, navigate]);

  async function submit(skipped: boolean) {
    if (!q || submitting) return;
    setSubmitting(skipped ? "skip" : "answer");
    setError(null);
    try {
      const a = await api.answer(q.id, { response: skipped ? {} : response, confidence: skipped ? null : confidence, skipped });
      setProgress((p) => ({ ...p, answered: p.answered + 1 }));
      if (a.revealed) {
        setAnswer(a);
      } else {
        toast(skipped ? "Marked as \"I don't know\". It counts as a miss." : "Answer saved. Feedback comes at the end.");
        await loadNext();
      }
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally {
      setSubmitting(null);
    }
  }

  async function skipForNow() {
    if (!q || submitting) return;
    setSubmitting("defer");
    setError(null);
    try {
      await api.deferQuestion(q.id);
      toast("Skipped. It'll come back after the other questions.");
      await loadNext();
    } catch (e) {
      setError(asApiError(e).toBody());
    } finally {
      setSubmitting(null);
    }
  }

  function onReported(r: ReportResult) {
    if (!q) return;
    if (r.replaced) {
      toast("Thanks for the report. That question was removed, and a new one will be added at the end.", "success");
      void loadNext();
    } else {
      setReported((prev) => new Set(prev).add(q.id));
      toast("Thanks for the report. This question won't count toward your score.", "success");
    }
  }

  function onOptionsSaved(view: SessionView) {
    setSession(view);
    setQ((prev) => (prev ? { ...prev, total: view.config.count } : prev));
    if (phase !== "question") void loadNext();
  }

  async function regrade() {
    if (!q) return;
    setSubmitting("answer");
    try { setAnswer(await api.regrade(q.id)); } catch (e) { setError(asApiError(e).toBody()); } finally { setSubmitting(null); }
  }

  async function retryGeneration() {
    setError(null);
    setPhase("pending");
    try { await api.retrySession(id); } catch { /* the next poll reports the error */ }
    void loadNext();
  }

  const canSubmit = !!q && !answer && !submitting && isAnswered(q.type, response);
  const total = q?.total ?? session?.config.count ?? 0;
  const isLast = total - progress.answered <= 1;
  const locked = !!answer || !!submitting;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.target as HTMLElement | null)?.closest?.(".chat-panel")) return;  // typing in the chat
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (answer && answer.grade_status !== "error") void loadNext();
        else if (canSubmit) void submit(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (phase === "loading") return <Loading message="Opening your session…" rotate={false} />;
  if (phase === "finishing") return <Loading message="Wrapping up and grading your answers…" sub="Hang tight. Written answers take a few seconds each." />;

  const pct = total ? (progress.answered / total) * 100 : 0;
  return (
    <div className={`page${(chatOpen || videosOpen) && phase === "question" ? " has-chat" : ""}`} ref={topRef}>
      {session?.study_set_id && (
        <Link to={`/sets/${session.study_set_id}`} className="btn ghost sm" style={{ marginBottom: 12 }}><ArrowLeft size={14} /> Back to study set</Link>
      )}
      <div className="page-header">
        <div>
          <h1>{session?.title || "Study session"}</h1>
          <p>{session?.subject ? `${session.subject} · ` : ""}{session?.config.adaptive ? "Adaptive difficulty · " : ""}{session?.config.feedback_mode === "end" ? "Feedback at the end" : "Feedback after each answer"}</p>
          {session?.config.docs_truncated && (
            <p className="small" style={{ color: "var(--partial-text)", marginTop: 4 }}>
              Your documents are long ({(session.config.doc_chars ?? 0).toLocaleString()} characters), so each question is written from the most relevant excerpts.
            </p>
          )}
        </div>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          {progress.answered > 0 && (
            confirmFinish ? (
              <div className="row">
                <span className="small muted">End now? Unanswered questions won't count.</span>
                <button className="btn sm primary" onClick={finish}>Finish</button>
                <button className="btn sm ghost" onClick={() => setConfirmFinish(false)}>Keep going</button>
              </div>
            ) : (
              <button className="btn sm ghost" onClick={() => setConfirmFinish(true)}><Flag size={14} /> Finish early</button>
            )
          )}
          <SessionMenu sessionId={id} onOptionsSaved={onOptionsSaved} />
        </div>
      </div>

      <div className="quiz-top">
        <div className="progress" style={{ flex: 1 }} role="progressbar" aria-valuenow={progress.answered} aria-valuemax={total}>
          <div style={{ width: `${pct}%` }} />
        </div>
        <span className="count">{Math.min(progress.answered + (answer ? 0 : 1), total)} of {total}</span>
      </div>
      {progress.skipped_waiting > 0 && (
        <div className="muted small" style={{ marginTop: -10, marginBottom: 14 }}>
          <Undo2 size={13} style={{ verticalAlign: -2 }} /> {progress.skipped_waiting} skipped question{progress.skipped_waiting === 1 ? "" : "s"} will come back at the end.
        </div>
      )}

      {phase === "error" && <ErrorBanner error={error} onRetry={retryGeneration} />}

      {phase === "pending" && (
        <div className="card">
          <Loading message={pendingMsg} />
          {session && session.subtopics.length > 0 && progress.answered === 0 && (
            <div style={{ textAlign: "center", marginTop: -20 }}>
              <div className="muted small" style={{ marginBottom: 8 }}>Subtopics in this session</div>
              <div className="chips" style={{ justifyContent: "center" }}>
                {session.subtopics.map((s) => <span key={s.id} className="badge primary" title={s.description}>{s.name}</span>)}
              </div>
            </div>
          )}
        </div>
      )}

      {phase === "question" && q && (
        <div className="card" key={q.id}>
          <div className="quiz-meta">
            <span className="badge primary"><BookOpen size={12} /> {q.subtopic_name}</span>
            <span className="badge">{q.type_label}</span>
            <span className="badge">Difficulty {q.difficulty} · {q.difficulty_label}</span>
            {q.was_skipped && <span className="badge warn"><Undo2 size={12} /> Skipped earlier</span>}
            {q.uses_outside_knowledge && (
              <span className="badge warn" title="This question relies on general knowledge beyond your uploaded material."><Globe size={12} /> Beyond your material</span>
            )}
            {reported.has(q.id) && <span className="badge"><MessageSquareWarning size={12} /> Reported · won't count</span>}
            <span className="spacer" />
            {!reported.has(q.id) && (
              <button className="btn sm ghost" onClick={() => setReportOpen(true)} disabled={!!submitting || answer?.grade_status === "pending"}
                title="Report a poorly made question (wrong answer key, unclear, off-topic…)">
                <MessageSquareWarning size={15} /> Report
              </button>
            )}
            <button className="btn sm ghost" onClick={() => { setVideosOpen((o) => !o); setChatOpen(false); }} aria-pressed={videosOpen}
              title="Find 1-3 YouTube videos on the concept behind this question">
              <Video size={15} /> Find video
            </button>
            <button className="btn sm ghost" onClick={() => { setChatOpen((o) => !o); setVideosOpen(false); }} aria-pressed={chatOpen}
              title="Chat about this question (uses Claude Code)">
              <MessageCircleQuestion size={15} /> Ask about this
            </button>
          </div>

          {q.scenario && <div className="scenario"><Markdown>{q.scenario}</Markdown></div>}
          {!PROMPT_INSIDE_INPUT.has(q.type) && <div className="question-prompt"><Markdown>{q.prompt}</Markdown></div>}
          {q.source_hint && <div className="muted small" style={{ marginTop: -10, marginBottom: 14 }}>Source: {q.source_hint}</div>}

          <AnswerInput q={q} value={response} onChange={setResponse} locked={locked} answerKey={answer?.answer_key} />

          {!answer && (
            <div className="confidence" style={{ marginTop: 18 }}>
              <span className="small muted"><HelpCircle size={14} style={{ verticalAlign: -2 }} /> How confident are you? (optional)</span>
              <div className="segmented">
                {(["low", "medium", "high"] as Confidence[]).map((c) => (
                  <button key={c} className={confidence === c ? "on" : ""} onClick={() => setConfidence(confidence === c ? null : c)} disabled={!!submitting}>
                    {c[0].toUpperCase() + c.slice(1)}
                  </button>
                ))}
              </div>
            </div>
          )}

          {submitting === "answer" && CLAUDE_GRADED.has(q.type) && (
            <Loading message="Grading your answer…" sub="Claude is checking your reasoning against the rubric." />
          )}

          {answer?.grade_status === "error" && <ErrorBanner error={answer.grade_error} onRetry={regrade} />}
          {answer && answer.grade_status === "done" && <FeedbackPanel a={answer} type={q.type} />}
          {error && phase === "question" && <ErrorBanner error={error} onRetry={() => setError(null)} compact />}

          <div className="quiz-actions">
            {!answer ? (
              <>
                <button className="btn" onClick={() => submit(true)} disabled={!!submitting}
                  title="Counts as a miss and shows you the answer">
                  {submitting === "skip" ? <span className="spinner" /> : <CircleHelp size={16} />} I don't know
                </button>
                <button className="btn ghost" onClick={skipForNow} disabled={!!submitting || isLast}
                  title={isLast ? "This is the last question, so there's nothing to skip ahead to" : "Move this question to the end of the quiz"}>
                  {submitting === "defer" ? <span className="spinner" /> : <SkipForward size={16} />} Skip for now
                </button>
                <span className="spacer" />
                <span className="muted small"><span className="kbd">Ctrl</span> + <span className="kbd">Enter</span></span>
                <button className="btn primary" onClick={() => submit(false)} disabled={!canSubmit}>
                  {submitting === "answer" ? <span className="spinner" /> : <Send size={16} />} Submit answer
                </button>
              </>
            ) : (
              <>
                <span className="spacer" />
                <button className="btn primary" onClick={loadNext} disabled={answer.grade_status === "pending"} autoFocus>
                  {progress.answered >= total ? "See results" : "Next question"} <ArrowRight size={16} />
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {reportOpen && q && (
        <ReportQuestionDialog questionId={q.id} answered={!!answer} onClose={() => setReportOpen(false)} onReported={onReported} />
      )}

      {chatOpen && phase === "question" && q && (
        <QuestionChat questionId={q.id} refreshKey={answer ? `${answer.revealed}-${answer.grade_status}` : "open"}
          onClose={() => setChatOpen(false)} />
      )}
      {videosOpen && phase === "question" && q && (
        <VideoPanel questionId={q.id} answered={!!answer} onClose={() => setVideosOpen(false)} />
      )}
    </div>
  );
}
