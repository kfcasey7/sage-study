import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, ArrowLeft, BookOpenCheck, ChevronDown, Clock, Globe, Layers, MessageSquareWarning, RefreshCw, Repeat, Sparkles, Video } from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, ResultQuestion, Results as ResultsT } from "../lib/types";
import { ErrorBanner, formatDateTime, formatDuration, Loading, ScoreRing, scoreColor, VerdictBadge } from "../components/common";
import { Markdown } from "../components/Markdown";
import { SessionMenu } from "../components/SessionMenu";
import { ReportQuestionDialog } from "../components/ReportQuestionDialog";

const PURPOSE_LABELS: Record<string, string> = {
  topic_map: "Mapping subtopics", generate: "Writing questions", grade: "Grading answers",
  study_guide: "Study guide", diagram_repair: "Fixing diagrams", chat: "Question chats",
};

const tooltipStyle = { background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, color: "var(--text)" };

function QuestionReview({ q, open = false, onReport }: { q: ResultQuestion; open?: boolean; onReport: () => void }) {
  return (
    <details className="miss" open={open}>
      <summary>
        <span className="badge" style={{ flexShrink: 0 }}>Q{q.position + 1}</span>
        <div className="q">
          <Markdown>{q.type === "fill_blank" ? q.prompt.replace(/\{\{\s*blank\s*\}\}/g, "_____") : q.prompt}</Markdown>
          <div className="row small muted" style={{ marginTop: 6, gap: 6 }}>
            <span>{q.subtopic_name}</span>·<span>{q.type_label}</span>·<span>Difficulty {q.difficulty}</span>
            {q.confidence && <>·<span>Confidence: {q.confidence}</span></>}
          </div>
        </div>
        <div className="row" style={{ flexShrink: 0, gap: 6 }}>
          {q.reported && <span className="badge" title={q.report_reason ?? undefined}><MessageSquareWarning size={12} /> Reported · not counted</span>}
          {q.used_video_help && <span className="badge warn" title="You opened Find video before answering. Your grade isn't affected."><Video size={12} /> Used help · video</span>}
          {q.confidently_wrong && <span className="badge incorrect" title="Answered with high confidence but scored below 50"><AlertTriangle size={12} /> Confidently wrong</span>}
          {q.uses_outside_knowledge && <span className="badge warn" title="Relied on knowledge beyond your material"><Globe size={12} /></span>}
          <VerdictBadge verdict={q.grade_status === "done" ? q.verdict : null} skipped={q.skipped} />
          {q.score != null && <span className="small muted">{Math.round(q.score)}%</span>}
          <ChevronDown size={16} className="muted" />
        </div>
      </summary>
      <div className="miss-body">
        {q.display.scenario && <div className="full"><h4>Scenario</h4><div className="answer-box"><Markdown>{q.display.scenario}</Markdown></div></div>}
        {q.display.flawed_work && <div className="full"><h4>Work you checked</h4><pre>{q.display.flawed_work}</pre></div>}
        <div>
          <h4>Your answer</h4>
          <div className="answer-box yours"><Markdown>{q.your_answer}</Markdown></div>
        </div>
        <div>
          <h4>Correct answer</h4>
          <div className="answer-box correct"><Markdown>{q.correct_answer}</Markdown></div>
        </div>
        {q.feedback && <div className="full"><h4>Feedback</h4><Markdown>{q.feedback}</Markdown></div>}
        {q.misconception && <div className="full"><h4>Underlying idea to revisit</h4><p style={{ margin: 0 }}>{q.misconception}</p></div>}
        {q.explanation && <div className="full"><h4>Explanation</h4><Markdown>{q.explanation}</Markdown></div>}
        {q.grade_status === "error" && <div className="full"><ErrorBanner error={q.grade_error} compact /></div>}
        <div className="full row" style={{ justifyContent: "flex-end" }}>
          {q.reported ? (
            <span className="muted small">You reported this question ({q.report_reason?.toLowerCase()}), so it isn't counted in your scores.</span>
          ) : (
            <button className="btn sm ghost" onClick={onReport} title="Report a poorly made question (wrong answer key, unclear, off-topic…)">
              <MessageSquareWarning size={14} /> Report this question
            </button>
          )}
        </div>
      </div>
    </details>
  );
}

export default function Results() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { theme, bumpHistory } = useApp();
  const [data, setData] = useState<ResultsT | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [reporting, setReporting] = useState<string | null>(null);

  useEffect(() => {
    api.results(id).then((r) => {
      if (r.session.status !== "completed") navigate(`/quiz/${id}`, { replace: true });
      else setData(r);
    }).catch((e) => setError(asApiError(e).toBody()));
  }, [id, navigate]);

  async function regradeAll() {
    if (!data) return;
    setBusy("regrade");
    try {
      for (const qid of data.ungraded) await api.regrade(qid);
      setData(await api.results(id));
    } catch (e) { setError(asApiError(e).toBody()); } finally { setBusy(null); }
  }

  async function retest() {
    setBusy("retest");
    try {
      const s = await api.retest(id);
      bumpHistory();
      navigate(`/quiz/${s.id}`);
    } catch (e) { setError(asApiError(e).toBody()); setBusy(null); }
  }

  if (error && !data) return <div className="page"><ErrorBanner error={error} /></div>;
  if (!data) return <Loading message="Tallying your results…" rotate={false} />;

  const m = data.mastery;
  const weak = m.subtopics.filter((s) => s.weak);
  const scored = m.subtopics.filter((s) => s.score != null);
  const subData = scored.map((s) => ({ name: s.name, score: Math.round(s.score!), weak: s.weak }));
  const typeData = m.types.map((t) => ({ name: t.label, score: Math.round(t.score ?? 0), n: t.n }));
  const axis = { stroke: "var(--muted)", fontSize: 12 };
  const confWrong = m.overall.confidently_wrong;

  return (
    <div className="page wide">
      {data.session.study_set_id && (
        <Link to={`/sets/${data.session.study_set_id}`} className="btn ghost sm" style={{ marginBottom: 12 }}><ArrowLeft size={14} /> Back to study set</Link>
      )}
      <div className="page-header">
        <div>
          <h1>{data.session.title || "Results"}</h1>
          <p>{data.session.subject ? `${data.session.subject} · ` : ""}{formatDateTime(data.session.created_at)}{data.session.parent_session_id ? " · Retest" : ""}</p>
        </div>
        <div className="row">
          {data.session.study_set_id && <Link className="btn" to={`/sets/${data.session.study_set_id}`}><Layers size={16} /> Material Breakdown</Link>}
          <SessionMenu sessionId={id} />
        </div>
      </div>

      <ErrorBanner error={error} compact />
      {data.session.docs_truncated && (
        <div className="banner info"><AlertTriangle size={20} /><div className="banner-body">Your documents were too long to send in full, so questions and feedback used the most relevant excerpts.</div></div>
      )}
      {data.ungraded.length > 0 && (
        <div className="banner warn">
          <AlertTriangle size={20} />
          <div className="banner-body">
            <div className="banner-title">{data.ungraded.length} answer{data.ungraded.length > 1 ? "s" : ""} couldn't be graded</div>
            <div>They're left out of your score until they're graded.</div>
            <button className="btn sm" style={{ marginTop: 8 }} onClick={regradeAll} disabled={!!busy}>{busy === "regrade" ? <span className="spinner" /> : <RefreshCw size={14} />} Grade them now</button>
          </div>
        </div>
      )}

      <section className="card">
        <div className="score-hero">
          <ScoreRing score={m.overall.score} />
          <div style={{ flex: 1 }}>
            <div className="grid-3">
              <div className="stat"><div className="label">Correct</div><div className="value" style={{ color: "var(--correct)" }}>{m.overall.correct}</div></div>
              <div className="stat"><div className="label">Partial</div><div className="value" style={{ color: "var(--partial-text)" }}>{m.overall.partial}</div></div>
              <div className="stat"><div className="label">Missed</div><div className="value" style={{ color: "var(--incorrect)" }}>{m.overall.incorrect}</div>{m.overall.skipped > 0 && <div className="small muted">incl. {m.overall.skipped} skipped</div>}</div>
            </div>
            <div className="row small muted" style={{ marginTop: 12 }}>
              <span>{m.overall.n} questions graded</span>
              {confWrong > 0 && <span className="badge incorrect"><AlertTriangle size={12} /> {confWrong} confidently wrong</span>}
              <span className="spacer" />
              <span title="Requests sent to Claude Code during this session"><Sparkles size={13} style={{ verticalAlign: -2 }} /> {data.ai.total.calls} AI call{data.ai.total.calls === 1 ? "" : "s"}</span>
              <span title="Time spent waiting on Claude, and total session length"><Clock size={13} style={{ verticalAlign: -2 }} /> {formatDuration(data.ai.total.seconds)} AI time · {formatDuration(data.session_seconds)} total</span>
            </div>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-title">
          <h2>Where to focus</h2>
        </div>
        {weak.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>No weak areas. Every subtopic is at 70% or above with no confidently wrong answers. Nice work!</p>
        ) : (
          <>
            <p className="muted">These subtopics scored below 70% or had an answer that was confidently wrong.</p>
            <div className="chips" style={{ marginBottom: 14 }}>
              {weak.map((s) => (
                <span key={s.id} className="badge incorrect" style={{ fontSize: "0.85rem", padding: "5px 11px" }}>
                  {s.name} · {s.score == null ? "–" : `${Math.round(s.score)}%`}{s.weak_reasons.includes("confidently_wrong") ? " · confidently wrong" : ""}
                </span>
              ))}
            </div>
            <div className="row">
              <Link className="btn primary" to={`/guide/${id}`}><BookOpenCheck size={16} /> {data.study_guide_status ? "Open study guide" : "Generate study guide"}</Link>
              <button className="btn" onClick={retest} disabled={!!busy}>{busy === "retest" ? <span className="spinner" /> : <Repeat size={16} />} Retest weak areas</button>
            </div>
          </>
        )}
      </section>

      <div className="grid-2" style={{ marginTop: 18 }}>
        <section className="card" style={{ marginTop: 0 }}>
          <h2>By subtopic</h2>
          {subData.length >= 3 ? (
            <div className="chart-box">
              <ResponsiveContainer>
                <RadarChart data={subData} outerRadius="70%">
                  <PolarGrid stroke="var(--chart-grid)" />
                  <PolarAngleAxis dataKey="name" tick={{ fill: "var(--muted)", fontSize: 11 }} />
                  <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                  <Radar dataKey="score" stroke={theme === "dark" ? "#8fb596" : "#5a7f60"} fill={theme === "dark" ? "#8fb596" : "#6b8f71"} fillOpacity={0.35} isAnimationActive={false} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, "Score"]} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="chart-box" style={{ height: 220 }}>
              <ResponsiveContainer>
                <BarChart data={subData} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="name" {...axis} tickLine={false} />
                  <YAxis domain={[0, 100]} {...axis} tickLine={false} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, "Score"]} cursor={{ fill: "var(--surface-2)" }} />
                  <Bar dataKey="score" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                    {subData.map((d) => <Cell key={d.name} fill={scoreColor(d.score)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div style={{ marginTop: 8 }}>
            {m.subtopics.map((s) => (
              <div key={s.id} className="subtopic-row">
                <span className="name" title={s.description}>{s.name}</span>
                {s.weak && <span className="badge incorrect">Weak</span>}
                <div className="bar"><div style={{ width: `${s.score ?? 0}%`, background: scoreColor(s.score) }} /></div>
                <span className="small" style={{ width: 70, textAlign: "right" }}>{s.score == null ? "no data" : `${Math.round(s.score)}%`} <span className="muted">({s.n})</span></span>
              </div>
            ))}
          </div>
        </section>

        <section className="card" style={{ marginTop: 0 }}>
          <h2>By question type</h2>
          <div className="chart-box" style={{ height: Math.max(160, typeData.length * 38 + 30) }}>
            <ResponsiveContainer>
              <BarChart data={typeData} layout="vertical" margin={{ top: 4, right: 20, bottom: 4, left: 10 }}>
                <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
                <XAxis type="number" domain={[0, 100]} {...axis} tickLine={false} />
                <YAxis type="category" dataKey="name" width={150} {...axis} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v, _n, p) => [`${v}% (${(p.payload as { n: number }).n} question${(p.payload as { n: number }).n > 1 ? "s" : ""})`, "Score"]} cursor={{ fill: "var(--surface-2)" }} />
                <Bar dataKey="score" radius={[0, 6, 6, 0]} barSize={18} isAnimationActive={false}>
                  {typeData.map((d) => <Cell key={d.name} fill={scoreColor(d.score)} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      <section className="card" style={{ marginTop: 18 }}>
        <div className="card-title">
          <h2>{showAll ? "All questions" : `Missed questions (${data.missed.length})`}</h2>
          <button className="btn sm ghost" onClick={() => setShowAll(!showAll)}>{showAll ? "Show missed only" : "Show all questions"}</button>
        </div>
        {(showAll ? data.questions : data.missed).length === 0 && <p className="muted">Nothing missed. 🎉</p>}
        {(showAll ? data.questions : data.missed).map((q, i) => (
          <QuestionReview key={q.id} q={q} open={!showAll && i === 0} onReport={() => setReporting(q.id)} />
        ))}
        {data.reported.length > 0 && !showAll && (
          <p className="muted small" style={{ marginBottom: 0 }}>
            {data.reported.length} reported question{data.reported.length === 1 ? " isn't" : "s aren't"} counted. Choose "Show all questions" to see {data.reported.length === 1 ? "it" : "them"}.
          </p>
        )}
        {reporting && (
          <ReportQuestionDialog questionId={reporting} answered onClose={() => setReporting(null)}
            onReported={() => { api.results(id).then(setData).catch((e) => setError(asApiError(e).toBody())); bumpHistory(); }} />
        )}
      </section>

      <details className="card" style={{ marginTop: 18 }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}><Sparkles size={15} style={{ verticalAlign: -2 }} /> AI calls &amp; time</summary>
        <table className="data" style={{ marginTop: 12 }}>
          <thead><tr><th>Step</th><th>Calls</th><th>Retried / failed</th><th>Time</th></tr></thead>
          <tbody>
            {data.ai.by_purpose.map((p) => (
              <tr key={p.purpose}>
                <td>{PURPOSE_LABELS[p.purpose] ?? p.purpose}</td><td>{p.calls}</td><td>{p.failed}</td><td>{formatDuration(p.seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small" style={{ marginTop: 10, marginBottom: 0 }}>
          Questions written with {data.session.config.model_fast ?? "haiku"}; grading and study guide with {data.session.config.model_smart ?? "sonnet"}.
          Calls run through Claude Code and count toward your own Claude plan's usage limits.
        </p>
      </details>
    </div>
  );
}
