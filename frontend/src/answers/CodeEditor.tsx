/** Monaco editor bundled locally (no CDN), so code questions work offline in the desktop window. */
import Editor, { loader, type OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import TsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import { useApp } from "../lib/app-context";

window.MonacoEnvironment = {
  getWorker: (_id: string, label: string) =>
    label === "typescript" || label === "javascript" ? new TsWorker() : label === "json" ? new JsonWorker() : new EditorWorker(),
};
loader.config({ monaco });

const LANGUAGE_IDS: Record<string, string> = {
  Python: "python", "C++": "cpp", Java: "java", C: "c", MATLAB: "matlab", JavaScript: "javascript",
  SQL: "sql", JSON: "json", XML: "xml", Assembly: "asm",
};

let configured = false;
function configure() {
  if (configured) return;
  configured = true;
  monaco.editor.defineTheme("sage-light", {
    base: "vs", inherit: true, rules: [{ token: "comment", foreground: "6B7568", fontStyle: "italic" }, { token: "keyword", foreground: "4F6F55" }],
    colors: { "editor.background": "#FBFCFA", "editorLineNumber.foreground": "#A9B2A5", "editor.lineHighlightBackground": "#EEF2EA" },
  });
  monaco.editor.defineTheme("sage-dark", {
    base: "vs-dark", inherit: true, rules: [{ token: "comment", foreground: "8C9589", fontStyle: "italic" }, { token: "keyword", foreground: "8FB596" }],
    colors: { "editor.background": "#222A24", "editorLineNumber.foreground": "#5E6A5F", "editor.lineHighlightBackground": "#2D372F" },
  });
  // Monaco has no MATLAB grammar; a small Monarch tokenizer covers keywords, comments, strings and numbers.
  monaco.languages.register({ id: "matlab" });
  monaco.languages.setMonarchTokensProvider("matlab", {
    keywords: ["function", "end", "if", "elseif", "else", "for", "while", "switch", "case", "otherwise", "return", "break", "continue", "try", "catch", "global", "persistent", "do", "until"],
    tokenizer: {
      root: [
        [/%\{/, "comment", "@blockComment"],
        [/%.*$/, "comment"],
        [/[a-zA-Z_]\w*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }],
        [/\d+(\.\d+)?([eE][-+]?\d+)?/, "number"],
        [/"([^"]|"")*"/, "string"],
        [/(?<![\w)\]}.'])'([^']|'')*'/, "string"],
      ],
      blockComment: [[/%\}/, "comment", "@pop"], [/./, "comment"]],
    },
  });
  monaco.languages.setLanguageConfiguration("matlab", { comments: { lineComment: "%", blockComment: ["%{", "%}"] } });
  // Nor one for assembly: comments, directives, labels, registers, numbers and strings, for x86/ARM/MIPS alike.
  monaco.languages.register({ id: "asm" });
  monaco.languages.setMonarchTokensProvider("asm", {
    ignoreCase: true,
    tokenizer: {
      root: [
        [/(?:;|@|\/\/|#(?!-?(?:0x)?\d)).*$/, "comment"],  // `#5` is an ARM immediate, not a comment
        [/^\s*[a-z_.$][\w.$]*:/, "type"],
        [/\.[a-z_]\w*/, "keyword"],
        [/\$?\b(?:[re]?[abcd]x|[abcd][hl]|[re]?(?:si|di|sp|bp|ip)|r\d{1,2}[dwb]?|[xw]\d{1,2}|sp|lr|pc|zero|[atsvk]\d|ra|gp|fp|[xyz]mm\d{1,2})\b/, "variable"],
        [/\b0x[0-9a-f]+\b|\b[0-9][0-9a-f]*h\b|\b\d+\b|#-?\d+/, "number"],
        [/"([^"\\]|\\.)*"|'([^'\\]|\\.)*'/, "string"],
        [/^\s*[a-z]\w*/, "keyword"],
      ],
    },
  });
  monaco.languages.setLanguageConfiguration("asm", { comments: { lineComment: ";" } });
}

export default function CodeEditor({ language, value, onChange, readOnly, height = 340, autoFocus = true }: {
  language: string; value: string; onChange: (v: string) => void; readOnly?: boolean; height?: number; autoFocus?: boolean;
}) {
  const { theme } = useApp();
  configure();
  const onMount: OnMount = (editor) => {
    if (!readOnly && autoFocus) editor.focus();
    // Monaco consumes Ctrl+Enter; forward it so the quiz's submit shortcut works inside the editor.
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true }));
    });
  };
  return (
    <div className="editor-shell">
      <div className="editor-bar"><span>{language}</span><span>Tab to indent · Ctrl+Enter to submit</span></div>
      <Editor
        height={height}
        language={LANGUAGE_IDS[language] ?? "plaintext"}
        value={value}
        theme={theme === "dark" ? "sage-dark" : "sage-light"}
        onChange={(v) => onChange(v ?? "")}
        onMount={onMount}
        options={{
          readOnly, minimap: { enabled: false }, fontSize: 14, fontFamily: "Cascadia Code, JetBrains Mono, Consolas, monospace",
          scrollBeyondLastLine: false, tabSize: 4, automaticLayout: true, padding: { top: 10, bottom: 10 }, renderLineHighlight: "line",
        }}
      />
    </div>
  );
}
