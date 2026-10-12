/** Inputs for Claude-graded written answers: text, math (LaTeX), code and error analysis. */
import { lazy, Suspense, useMemo } from "react";
import katex from "katex";
import { Markdown } from "../components/Markdown";
import type { InputProps } from "./objective";

const CodeEditor = lazy(() => import("./CodeEditor"));

const ROWS: Record<string, number> = { short_response: 4, free_response: 8, applied_scenario: 8, long_response: 14 };
const PLACEHOLDER: Record<string, string> = {
  short_response: "Answer in a sentence or two…",
  long_response: "Write your essay. Organise it into paragraphs, explain your reasoning, and support claims with the material…",
  free_response: "Explain your answer in your own words…",
  applied_scenario: "Apply the concept to the scenario. State your assumptions, show your reasoning, and give a conclusion…",
};

export function TextAnswer({ q, value, onChange, locked }: InputProps) {
  const text = (value.text as string) ?? "";
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  return (
    <div>
      <textarea className="textarea" rows={ROWS[q.type] ?? 6} value={text} disabled={locked} placeholder={PLACEHOLDER[q.type] ?? "Your answer…"}
        onChange={(e) => onChange({ ...value, text: e.target.value })} aria-label="Your answer" autoFocus />
      <div className="muted small" style={{ textAlign: "right", marginTop: 4 }}>{words} word{words === 1 ? "" : "s"} · supports Markdown and $LaTeX$</div>
    </div>
  );
}

/** Lines without $ delimiters are treated as display math, so students can type raw LaTeX line by line. */
function workToMarkdown(work: string): string {
  if (work.includes("$")) return work;
  return work.split("\n").filter((l) => l.trim()).map((l) => `$$\n${l}\n$$`).join("\n\n");
}

function renderInline(latex: string): string {
  try {
    return katex.renderToString(latex, { throwOnError: false, displayMode: true, strict: "ignore" });
  } catch {
    return "";
  }
}

export function MathAnswer({ value, onChange, locked }: InputProps) {
  const work = (value.work as string) ?? "";
  const final = (value.final as string) ?? "";
  const finalHtml = useMemo(() => (final.trim() ? renderInline(final) : ""), [final]);
  return (
    <div className="stack">
      <label className="field">
        Your work
        <span className="field-hint">Type LaTeX one step per line (e.g. <code>{"F = ma \\Rightarrow a = \\frac{F}{m}"}</code>), or mix prose with <code>$...$</code>.</span>
        <textarea className="textarea mono" rows={7} value={work} disabled={locked} spellCheck={false}
          onChange={(e) => onChange({ ...value, work: e.target.value })} placeholder={"\\sum F_y = 0\nN - mg\\cos\\theta = 0"} autoFocus />
      </label>
      <div>
        <div className="muted small" style={{ marginBottom: 4 }}>Preview</div>
        <div className="math-preview">{work.trim() ? <Markdown>{workToMarkdown(work)}</Markdown> : <span className="muted small">Your rendered work appears here.</span>}</div>
      </div>
      <label className="field">
        Final answer
        <span className="field-hint">LaTeX, including units if needed, e.g. <code>{"v = 12.4\\,\\text{m/s}"}</code></span>
        <input className="input mono" value={final} disabled={locked} spellCheck={false} onChange={(e) => onChange({ ...value, final: e.target.value })} placeholder="x = 2" />
      </label>
      {finalHtml && <div className="math-preview" dangerouslySetInnerHTML={{ __html: finalHtml }} />}
    </div>
  );
}

export function CodeAnswer({ q, value, onChange, locked }: InputProps) {
  const code = (value.code as string) ?? q.starter_code ?? "";
  return (
    <Suspense fallback={<div className="skeleton" style={{ height: 320 }} />}>
      <CodeEditor language={q.language || "Python"} value={code} readOnly={locked} onChange={(c) => onChange({ ...value, code: c })} />
    </Suspense>
  );
}

export function ErrorAnalysisAnswer({ q, value, onChange, locked }: InputProps) {
  const isCode = !!q.language;
  const explanation = (value.text as string) ?? "";
  return (
    <div className="stack">
      <div>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Work to check</div>
        {isCode ? (
          <pre>{q.flawed_work}</pre>
        ) : (
          <div className="scenario"><Markdown>{q.flawed_work ?? ""}</Markdown></div>
        )}
      </div>
      <label className="field">
        What's wrong, and why?
        <textarea className="textarea" rows={5} value={explanation} disabled={locked} onChange={(e) => onChange({ ...value, text: e.target.value })}
          placeholder="Identify each mistake and explain why it's wrong…" autoFocus />
      </label>
      {isCode ? (
        <div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Corrected code</div>
          <Suspense fallback={<div className="skeleton" style={{ height: 260 }} />}>
            <CodeEditor language={q.language!} value={(value.code as string) ?? q.flawed_work ?? ""} readOnly={locked} height={260} autoFocus={false}
              onChange={(c) => onChange({ ...value, code: c })} />
          </Suspense>
        </div>
      ) : (
        <label className="field">
          Corrected work
          <textarea className="textarea mono" rows={6} value={(value.code as string) ?? ""} disabled={locked}
            onChange={(e) => onChange({ ...value, code: e.target.value })} placeholder="Show the corrected steps (LaTeX with $...$ is fine)…" />
        </label>
      )}
    </div>
  );
}
