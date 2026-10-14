import { CheckCircle2 } from "lucide-react";

/** Multi-select chips for code languages. Code questions are spread evenly across the picked languages. */
export function LanguagePicker({ options, value, onChange }: { options: string[]; value: string[]; onChange: (v: string[]) => void }) {
  const toggle = (lang: string) =>
    onChange(value.includes(lang) ? value.filter((l) => l !== lang) : options.filter((l) => l === lang || value.includes(l)));
  return (
    <div>
      <div className="field" style={{ marginBottom: 2 }}>Code languages</div>
      <div className="muted small" style={{ marginBottom: 8 }}>Pick one or more. Code questions are spread across them.</div>
      <div className="chips" role="group" aria-label="Code languages">
        {options.map((l) => (
          <button key={l} type="button" className={`chip ${value.includes(l) ? "on" : ""}`} onClick={() => toggle(l)} aria-pressed={value.includes(l)}>
            {value.includes(l) && <CheckCircle2 size={14} />} {l}
          </button>
        ))}
      </div>
      {value.length === 0 && <div className="small" style={{ color: "var(--incorrect)", marginTop: 6 }}>Pick at least one language.</div>}
    </div>
  );
}
