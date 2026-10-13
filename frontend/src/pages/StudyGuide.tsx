import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import katex from "katex";
import {
  AlertTriangle, ArrowLeft, BookOpen, FileDown, FileText, FolderOpen, Lightbulb, ListChecks, PenLine, Repeat, Shapes, Sigma, Target,
} from "lucide-react";
import { api, asApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import type { ApiErrorBody, GuideSectionState, StudyGuide as Guide, StudySection } from "../lib/types";
import { ErrorBanner, formatDate, Loading } from "../components/common";
import { Markdown } from "../components/Markdown";
import { MarkdownInline } from "../components/MarkdownInline";
import { MermaidDiagram } from "../components/MermaidDiagram";
import { ChartView } from "../components/ChartView";
import { SessionMenu } from "../components/SessionMenu";

function Formula({ latex }: { latex: string }) {
  const html = katex.renderToString(latex.replace(/^\$+|\$+$/g, ""), { displayMode: true, throwOnError: false, strict: "ignore" });
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}

function Section({ s, state, sessionId, onSectionChange }: {
  s: StudySection; state: GuideSectionState; sessionId: string; onSectionChange: (sec: StudySection) => void;
}) {
  const [repairing, setRepairing] = useState(false);
  const onDiagramError = useCallback((message: string) => {
    if (s.diagram.repaired) return;
    setRepairing(true);
    api.repairDiagram(sessionId, state.subtopic_id, message)
      .then(onSectionChange)
      .catch(() => { /* keep showing the source fallback */ })
      .finally(() => setRepairing(false));
  }, [s.diagram.repaired, sessionId, state.subtopic_id, onSectionChange]);

  const hasDiagram = s.diagram.include && s.diagram.mermaid.trim();
  const hasChart = s.chart.include && s.chart.series.some((x) => x.points.length);
  return (
    <article className="guide-section">
      <div className="card">
        <h2>
          <Target size={20} color="var(--primary)" /> {s.title}
          <span className="spacer" />
          {state.score != null && <span className="badge incorrect">Your score: {Math.round(state.score)}%</span>}
          {state.weak_reasons.includes("confidently_wrong") && <span className="badge warn">Confidently wrong</span>}
        </h2>

        <div className="guide-block">
          <h3><BookOpen size={16} /> The idea</h3>
          <Markdown>{s.explanation}</Markdown>
        </div>

        {s.key_formulas.length > 0 && (
          <div className="guide-block">
            <h3><Sigma size={16} /> Key formulas</h3>
            {s.key_formulas.map((f, i) => (
              <div key={i} className="formula">
                <Formula latex={f.latex} />
                <div className="desc"><Markdown>{f.description}</Markdown></div>
              </div>
            ))}
          </div>
        )}

        {(hasDiagram || hasChart) && (
          <div className="guide-block">
            <h3><Shapes size={16} /> Visual</h3>
            <div className="stack">
              {hasDiagram && (
                <figure className="figure" style={{ margin: 0 }}>
                  {repairing ? <div className="row muted small"><span className="spinner" /> Fixing this diagram…</div>
                    : <MermaidDiagram code={s.diagram.mermaid} onError={onDiagramError} />}
                  {s.diagram.caption && <figcaption className="caption">{s.diagram.caption}</figcaption>}
                </figure>
              )}
              {hasChart && (
                <figure className="figure" style={{ margin: 0 }}>
                  <ChartView spec={s.chart} />
                  {s.chart.caption && <figcaption className="caption">{s.chart.caption}</figcaption>}
                </figure>
              )}
            </div>
          </div>
        )}

        <div className="guide-block">
          <h3><PenLine size={16} /> Worked example</h3>
          <Markdown>{s.worked_example.problem}</Markdown>
          <ol className="steps">
            {s.worked_example.steps.map((step, i) => <li key={i}><Markdown>{step}</Markdown></li>)}
          </ol>
          <div className="formula"><strong>Answer:</strong> <MarkdownInline>{s.worked_example.answer}</MarkdownInline></div>
        </div>

        <div className="guide-block">
          <h3><AlertTriangle size={16} /> Common mistakes</h3>
          {s.common_mistakes.map((mk, i) => (
            <div key={i} className={`mistake ${mk.from_your_answers ? "yours" : ""}`}>
              <div className="m-title">{mk.mistake}{mk.from_your_answers && <span className="badge incorrect">From your answers</span>}</div>
              <div className="small"><strong>Why it happens:</strong> <MarkdownInline>{mk.why}</MarkdownInline></div>
              <div className="small"><strong>How to avoid it:</strong> <MarkdownInline>{mk.fix}</MarkdownInline></div>
            </div>
          ))}
        </div>

        <div className="guide-block">
          <h3><ListChecks size={16} /> Practice</h3>
          {s.practice_questions.map((p, i) => (
            <div key={i} className="practice">
              <div style={{ display: "flex", gap: 8 }}><strong>{i + 1}.</strong><Markdown>{p.question}</Markdown></div>
              <details>
                <summary>Show answer</summary>
                <div className="ans"><Markdown>{p.answer}</Markdown></div>
              </details>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

export default function StudyGuide() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { toast, bumpHistory } = useApp();
  const [guide, setGuide] = useState<Guide | null>(null);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<ApiErrorBody | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const poll = useCallback(async () => {
    if (pollRef.current) window.clearTimeout(pollRef.current);
    try {
      const g = await api.guide(id);
      setGuide(g);
      if (g.status === "generating") pollRef.current = window.setTimeout(poll, 2000);
      else bumpHistory();
    } catch (e) {
      setError(asApiError(e).toBody());
    }
  }, [id, bumpHistory]);

  useEffect(() => {
    api.results(id).then((r) => setTitle(r.session.title)).catch(() => { /* title is cosmetic */ });
    (async () => {
      try {
        const g = await api.guide(id);
        if (g.status === "none") {
          setGuide(await api.startGuide(id));
          pollRef.current = window.setTimeout(poll, 2000);
        } else {
          setGuide(g);
          if (g.status === "generating") pollRef.current = window.setTimeout(poll, 2000);
        }
      } catch (e) {
        setError(asApiError(e).toBody());
      }
    })();
    return () => { if (pollRef.current) window.clearTimeout(pollRef.current); };
  }, [id, poll]);

  const updateSection = useCallback((subtopicId: string, section: StudySection) => {
    setGuide((g) => g && g.content ? {
      ...g, content: { ...g.content, sections: g.content.sections.map((s) => (s.subtopic_id === subtopicId ? { ...s, section } : s)) },
    } : g);
  }, []);

  async function retrySection(subtopicId: string) {
    try {
      setGuide(await api.retryGuideSection(id, subtopicId));
      pollRef.current = window.setTimeout(poll, 2000);
    } catch (e) { setError(asApiError(e).toBody()); }
  }

  async function exportMd() {
    setBusy("md"); setSaved(null);
    try {
      const r = await api.exportMarkdown(id);
      if (r.path) { setSaved(r.path); toast("Study guide saved as Markdown.", "success"); }
    } catch (e) { setError(asApiError(e).toBody()); } finally { setBusy(null); }
  }

  async function exportPdf() {
    if (!contentRef.current) return;
    setBusy("pdf"); setSaved(null);
    try {
      const head = [...document.querySelectorAll('link[rel="stylesheet"], style')].map((n) => n.outerHTML).join("\n");
      const clone = contentRef.current.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("details").forEach((d) => d.setAttribute("open", ""));
      clone.querySelectorAll(".no-print").forEach((n) => n.remove());
      const r = await api.exportPdf(id, `<h1>Study Guide: ${title}</h1>${clone.innerHTML}`, head);
      if (r.fallback === "print") { toast(r.message ?? "Opening the print dialog…"); window.print(); }
      else if (r.path) { setSaved(r.path); toast("Study guide saved as PDF.", "success"); }
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

  if (error && !guide) {
    return (
      <div className="page">
        <Link to={`/results/${id}`} className="btn ghost sm" style={{ marginBottom: 12 }}><ArrowLeft size={14} /> Back to results</Link>
        <ErrorBanner error={error} onRetry={() => { setError(null); void poll(); }} />
      </div>
    );
  }
  if (!guide || !guide.content) return <Loading message="Building your study guide…" sub="Writing explanations, examples, and practice for your weak areas." />;

  const sections = guide.content.sections;
  const ready = sections.filter((s) => s.status === "ready").length;
  const generating = guide.status === "generating";

  return (
    <div className="page">
      <Link to={`/results/${id}`} className="btn ghost sm no-print" style={{ marginBottom: 12 }}><ArrowLeft size={14} /> Back to results</Link>
      <div className="page-header">
        <div>
          <h1>Study guide</h1>
          <p>{title}{guide.content.generated_at ? ` · ${formatDate(guide.content.generated_at)}` : ""} · {sections.length} focus area{sections.length === 1 ? "" : "s"}</p>
        </div>
        <div className="row no-print">
          <button className="btn sm" onClick={exportMd} disabled={generating || !ready || !!busy}>{busy === "md" ? <span className="spinner" /> : <FileText size={15} />} Markdown</button>
          <button className="btn sm" onClick={exportPdf} disabled={generating || !ready || !!busy}>{busy === "pdf" ? <span className="spinner" /> : <FileDown size={15} />} PDF</button>
          <button className="btn sm primary" onClick={retest} disabled={!!busy}>{busy === "retest" ? <span className="spinner" /> : <Repeat size={15} />} Retest weak areas</button>
          <SessionMenu sessionId={id} />
        </div>
      </div>

      <ErrorBanner error={error} compact />
      {saved && (
        <div className="banner info no-print">
          <FileDown size={20} />
          <div className="banner-body">
            <div className="banner-title">Saved</div>
            <div className="small" style={{ wordBreak: "break-all" }}>{saved}</div>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn sm" onClick={() => api.openFile(saved)}>Open</button>
              <button className="btn sm ghost" onClick={() => api.reveal(saved)}><FolderOpen size={14} /> Show in folder</button>
            </div>
          </div>
        </div>
      )}
      {generating && (
        <div className="banner info no-print">
          <span className="spinner" style={{ marginTop: 3 }} />
          <div className="banner-body">Writing your guide: {ready} of {sections.length} sections ready. Each section is tailored to the questions you missed.</div>
        </div>
      )}

      <div className="card no-print" style={{ marginBottom: 22 }}>
        <div className="row"><Lightbulb size={18} color="var(--primary)" /><strong>Focus areas</strong></div>
        <div className="chips" style={{ marginTop: 10 }}>
          {sections.map((s) => (
            <a key={s.subtopic_id} className="badge primary" href={`#sec-${s.subtopic_id}`}
              onClick={(e) => { e.preventDefault(); document.getElementById(`sec-${s.subtopic_id}`)?.scrollIntoView({ behavior: "smooth" }); }}>
              {s.name}{s.score != null ? ` · ${Math.round(s.score)}%` : ""}
            </a>
          ))}
        </div>
      </div>

      <div ref={contentRef}>
        {sections.map((st) => (
          <div key={st.subtopic_id} id={`sec-${st.subtopic_id}`}>
            {st.status === "ready" && st.section && (
              <Section s={st.section} state={st} sessionId={id} onSectionChange={(sec) => updateSection(st.subtopic_id, sec)} />
            )}
            {st.status === "pending" && (
              <div className="card guide-section no-print">
                <h2>{st.name}</h2>
                <div className="stack">
                  <div className="skeleton" style={{ height: 18, width: "70%" }} />
                  <div className="skeleton" style={{ height: 18, width: "90%" }} />
                  <div className="skeleton" style={{ height: 140 }} />
                </div>
              </div>
            )}
            {st.status === "failed" && (
              <div className="card guide-section no-print">
                <h2>{st.name}</h2>
                <ErrorBanner error={st.error} onRetry={() => retrySection(st.subtopic_id)} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
