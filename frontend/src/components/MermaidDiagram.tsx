import { useEffect, useId, useRef, useState } from "react";
import { useApp } from "../lib/app-context";

type MermaidApi = typeof import("mermaid").default;
let mermaidPromise: Promise<MermaidApi> | null = null;

function loadMermaid(): Promise<MermaidApi> {
  mermaidPromise ??= import("mermaid").then((m) => m.default);
  return mermaidPromise;
}

function themeVars(dark: boolean) {
  return dark
    ? { primaryColor: "#334237", primaryTextColor: "#e3eae1", primaryBorderColor: "#8fb596", lineColor: "#a3ad9f",
        secondaryColor: "#2d372f", tertiaryColor: "#273029", background: "#273029", mainBkg: "#334237", textColor: "#e3eae1",
        fontFamily: "Inter Variable, Inter, sans-serif" }
    : { primaryColor: "#e3ebe0", primaryTextColor: "#2f3a30", primaryBorderColor: "#6b8f71", lineColor: "#6b7568",
        secondaryColor: "#eef2ea", tertiaryColor: "#ffffff", background: "#ffffff", mainBkg: "#e3ebe0", textColor: "#2f3a30",
        fontFamily: "Inter Variable, Inter, sans-serif" };
}

/** Renders Mermaid source to inline SVG. Calls onError once with the parser message on failure. */
export function MermaidDiagram({ code, onError }: { code: string; onError?: (message: string) => void }) {
  const { theme } = useApp();
  const id = "m" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reported = useRef<string | null>(null);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  useEffect(() => {
    let cancelled = false;
    setError(null);
    loadMermaid()
      .then(async (mermaid) => {
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", themeVariables: themeVars(theme === "dark"), flowchart: { htmlLabels: false } });
        await mermaid.parse(code);
        const { svg: out } = await mermaid.render(id, code);
        if (!cancelled) setSvg(out);
      })
      .catch((e: unknown) => {
        document.getElementById("d" + id)?.remove(); // mermaid leaves an error node behind
        const msg = e instanceof Error ? e.message : String(e);
        if (!cancelled) {
          setSvg(null);
          setError(msg);
          if (onErrorRef.current && reported.current !== code) {
            reported.current = code;
            onErrorRef.current(msg);
          }
        }
      });
    return () => { cancelled = true; };
  }, [code, theme, id]);

  if (error) {
    return (
      <div>
        <div className="muted small" style={{ marginBottom: 6 }}>This diagram couldn't be drawn, so here is its source:</div>
        <pre>{code}</pre>
      </div>
    );
  }
  if (!svg) return <div className="skeleton" style={{ height: 180 }} />;
  return <div className="mermaid-box" dangerouslySetInnerHTML={{ __html: svg }} />;
}
