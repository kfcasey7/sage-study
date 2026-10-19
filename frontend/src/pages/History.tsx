import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDownRight, ArrowUpRight, BookOpenCheck, ClipboardList, History as HistoryIcon, Layers, ListVideo, Minus, TrendingUp } from "lucide-react";
import { SetMenu } from "../components/SetMenu";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, StudySetRow, Trends } from "../lib/types";
import { ErrorBanner, formatDate, Loading, scoreColor } from "../components/common";

function Change({ value }: { value: number | null }) {
  if (value == null) return <span className="muted small">first attempt</span>;
  if (Math.abs(value) < 0.5) return <span className="muted small"><Minus size={13} style={{ verticalAlign: -2 }} /> no change</span>;
  const up = value > 0;
  return (
    <span className="small" style={{ color: up ? "var(--correct)" : "var(--incorrect)", fontWeight: 600 }}>
      {up ? <ArrowUpRight size={14} style={{ verticalAlign: -2 }} /> : <ArrowDownRight size={14} style={{ verticalAlign: -2 }} />}
      {up ? "+" : ""}{Math.round(value)} pts
    </span>
  );
}

export default function History() {
  const navigate = useNavigate();
  const { theme, historyVersion } = useApp();
  const [rows, setRows] = useState<StudySetRow[] | null>(null);
  const [subject, setSubject] = useState<string>("");
  const [trends, setTrends] = useState<Trends | null>(null);
  const [error, setError] = useState<ApiErrorBody | null>(null);

  useEffect(() => {
    api.sets().then(setRows).catch((e) => setError(asApiError(e).toBody()));
  }, [historyVersion]);

  const subjects = useMemo(() => Array.from(new Set((rows ?? []).filter((r) => r.subject).map((r) => r.subject))), [rows]);
  useEffect(() => { if (!subject && subjects.length) setSubject(subjects[0]); }, [subjects, subject]);
  useEffect(() => {
    if (!subject) { setTrends(null); return; }
    api.trends(subject).then(setTrends).catch(() => setTrends(null));
  }, [subject, historyVersion]);


  if (!rows) return error ? <div className="page"><ErrorBanner error={error} /></div> : <Loading message="Loading your history…" rotate={false} />;

  const visible = subject ? rows.filter((r) => r.subject === subject) : rows;
  const chartData = (trends?.sessions ?? []).filter((s) => s.score != null).map((s, i) => ({ name: `${i + 1}. ${formatDate(s.created_at)}`, score: Math.round(s.score!) }));
  const stroke = theme === "dark" ? "#8fb596" : "#5a7f60";

  return (
    <div className="page wide">
      <div className="page-header">
        <div>
          <h1>History</h1>
          <p>Your study sets, and how your mastery is trending.</p>
        </div>
        {subjects.length > 0 && (
          <select className="select" style={{ width: 240 }} value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Filter by subject">
            <option value="">All subjects</option>
            {subjects.map((s) => <option key={s}>{s}</option>)}
          </select>
        )}
      </div>
      <ErrorBanner error={error} compact />

      {rows.length === 0 ? (
        <div className="card empty">
          <HistoryIcon size={40} />
          <p>No study sets yet. Your study sets, with their quizzes, study guides, and playlists, will show up here.</p>
          <button className="btn primary" onClick={() => navigate("/")}>Create a study set</button>
        </div>
      ) : (
        <>
          {subject && trends && trends.sessions.length > 0 && (
            <div className="grid-2">
              <section className="card" style={{ marginTop: 0 }}>
                <h2><TrendingUp size={18} style={{ verticalAlign: -3 }} /> {subject}: overall score</h2>
                {chartData.length > 1 ? (
                  <div className="chart-box" style={{ height: 240 }}>
                    <ResponsiveContainer>
                      <LineChart data={chartData} margin={{ top: 10, right: 16, bottom: 0, left: -12 }}>
                        <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />
                        <XAxis dataKey="name" stroke="var(--muted)" fontSize={11} tickLine={false} />
                        <YAxis domain={[0, 100]} stroke="var(--muted)" fontSize={11} tickLine={false} />
                        <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10 }} formatter={(v) => [`${v}%`, "Score"]} />
                        <Line type="monotone" dataKey="score" stroke={stroke} strokeWidth={2.5} dot={{ r: 4, fill: stroke }} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="muted">Complete another {subject} quiz to see a trend line.</p>
                )}
              </section>
              <section className="card" style={{ marginTop: 0 }}>
                <h2>Subtopic mastery</h2>
                {trends.subtopics.length === 0 && <p className="muted">No graded subtopics yet.</p>}
                {trends.subtopics.map((t) => (
                  <div key={t.name} className="subtopic-row">
                    <span className="name">{t.name}</span>
                    <div className="bar" style={{ width: 110 }}><div style={{ width: `${t.latest}%`, background: scoreColor(t.latest) }} /></div>
                    <span className="small" style={{ width: 40, textAlign: "right" }}>{Math.round(t.latest)}%</span>
                    <span style={{ width: 96, textAlign: "right" }}><Change value={t.change} /></span>
                  </div>
                ))}
              </section>
            </div>
          )}

          <section className="card" style={{ marginTop: 18 }}>
            <table className="data">
              <thead>
                <tr><th>Last activity</th><th>Study set</th><th>Subject</th><th>Last score</th><th>Made from it</th><th /></tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => navigate(`/sets/${r.id}`)}>
                    <td className="small">{formatDate(r.last_activity || r.updated_at)}</td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{r.title || "Untitled study set"}</div>
                      <div className="row small muted" style={{ gap: 6 }}>
                        <span><Layers size={11} style={{ verticalAlign: -1 }} /> {r.subtopics} subtopic{r.subtopics === 1 ? "" : "s"} · {r.sources} source{r.sources === 1 ? "" : "s"}</span>
                        {r.breakdown_status === "generating" && <span className="badge primary">Building breakdown…</span>}
                        {r.breakdown_status === "legacy" && <span className="badge">From an earlier session</span>}
                        {r.breakdown_status === "failed" && <span className="badge warn">Breakdown failed</span>}
                        {r.in_progress > 0 && <span className="badge warn">{r.in_progress} quiz{r.in_progress === 1 ? "" : "zes"} in progress</span>}
                      </div>
                    </td>
                    <td className="small">{r.subject || <span className="muted">–</span>}</td>
                    <td>{r.last_score != null ? <strong style={{ color: scoreColor(r.last_score) }}>{Math.round(r.last_score)}%</strong> : <span className="muted">–</span>}</td>
                    <td className="small">
                      <div className="row" style={{ gap: 10 }}>
                        <span title="Quizzes"><ClipboardList size={13} style={{ verticalAlign: -2 }} /> {r.quizzes}</span>
                        <span title="Study guides"><BookOpenCheck size={13} style={{ verticalAlign: -2 }} /> {r.guides}</span>
                        <span title="Video playlists"><ListVideo size={13} style={{ verticalAlign: -2 }} /> {r.playlists}</span>
                      </div>
                    </td>
                    <td onClick={(e) => e.stopPropagation()} style={{ width: 56, textAlign: "right" }}>
                      <SetMenu setId={r.id} label={`Options for ${r.title || "study set"}`} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
