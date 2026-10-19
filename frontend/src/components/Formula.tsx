import katex from "katex";

/** A display-mode KaTeX formula (LaTeX without $ delimiters; stray ones are stripped). */
export function Formula({ latex, inline = false }: { latex: string; inline?: boolean }) {
  const html = katex.renderToString(latex.replace(/^\$+|\$+$/g, ""), { displayMode: !inline, throwOnError: false, strict: "ignore" });
  return inline ? <span dangerouslySetInnerHTML={{ __html: html }} /> : <div dangerouslySetInnerHTML={{ __html: html }} />;
}
