import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { MermaidDiagram } from "./MermaidDiagram";

/** Normalise LaTeX delimiters Claude occasionally uses despite instructions: \( \) and \[ \]. */
function normalizeMath(text: string): string {
  return text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, m) => `$$${m}$$`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, m) => `$${m}$`);
}

export const Markdown = memo(function Markdown({ children, className = "" }: { children: string; className?: string }) {
  return (
    <div className={`md ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: true }]]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore" }]]}
        components={{
          code({ className: cls, children: code, ...rest }) {
            const lang = /language-(\w+)/.exec(cls || "")?.[1];
            if (lang === "mermaid") return <MermaidDiagram code={String(code).trim()} />;
            return <code className={cls} {...rest}>{code}</code>;
          },
          a({ href, children: c }) {
            return <a href={href} target="_blank" rel="noreferrer">{c}</a>;
          },
        }}
      >
        {normalizeMath(children || "")}
      </ReactMarkdown>
    </div>
  );
});
