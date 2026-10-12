import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

/** Markdown + math rendered inline (paragraphs unwrapped), for text that sits beside inputs. */
export function MarkdownInline({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore" }]]}
      components={{ p: ({ children: c }) => <span>{c}</span> }}
    >
      {children}
    </ReactMarkdown>
  );
}
