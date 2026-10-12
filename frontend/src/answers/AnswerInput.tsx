import { FillBlank, Matching, MultipleChoice, SelectAll, TrueFalse, type InputProps } from "./objective";
import { Ordering } from "./Ordering";
import { CodeAnswer, ErrorAnalysisAnswer, MathAnswer, TextAnswer } from "./written";

export function AnswerInput(props: InputProps) {
  switch (props.q.type) {
    case "multiple_choice": return <MultipleChoice {...props} />;
    case "select_all": return <SelectAll {...props} />;
    case "true_false": return <TrueFalse {...props} />;
    case "fill_blank": return <FillBlank {...props} />;
    case "matching": return <Matching {...props} />;
    case "ordering": return <Ordering {...props} />;
    case "math": return <MathAnswer {...props} />;
    case "code": return <CodeAnswer {...props} />;
    case "error_analysis": return <ErrorAnalysisAnswer {...props} />;
    default: return <TextAnswer {...props} />;
  }
}

/** Whether the response has enough content to submit. */
export function isAnswered(type: string, r: Record<string, unknown>): boolean {
  const filled = (s: unknown) => typeof s === "string" && s.trim().length > 0;
  switch (type) {
    case "multiple_choice": return typeof r.choice === "number";
    case "select_all": return Array.isArray(r.choices) && r.choices.length > 0;
    case "true_false": return typeof r.value === "boolean";
    case "fill_blank": return Array.isArray(r.blanks) && (r.blanks as string[]).some(filled);
    case "matching": return Array.isArray(r.matches) && (r.matches as unknown[]).some((m) => m !== null && m !== undefined);
    case "ordering": return Array.isArray(r.order);
    case "math": return filled(r.final) || filled(r.work);
    case "code": return filled(r.code);
    case "error_analysis": return filled(r.text) || filled(r.code);
    default: return filled(r.text);
  }
}

/** Question types whose prompt is rendered inside the input (fill-in-the-blank sentence). */
export const PROMPT_INSIDE_INPUT = new Set(["fill_blank"]);
