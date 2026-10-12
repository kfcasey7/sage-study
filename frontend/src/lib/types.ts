export type Verdict = "correct" | "partial" | "incorrect";
export type Confidence = "low" | "medium" | "high";

export interface ApiErrorBody {
  code: string;
  message: string;
  retry_after?: number | null;
  retryable?: boolean;
  detail?: string | null;
}

export interface ModelOption { id: string; label: string; description: string }
export interface QuestionTypeOption { id: string; label: string; grading: "local" | "claude" | "hybrid" }

export interface Settings {
  model: string;
  effort: "low" | "medium" | "high";
  feedback_mode: "immediate" | "end";
  theme: "light" | "dark";
  fallback_enabled: boolean;
}

export interface SettingsPayload {
  settings: Settings;
  key: { key_set: boolean; source: "keyring" | "env" | "none"; last4: string | null };
  options: {
    models: ModelOption[];
    efforts: string[];
    difficulty_levels: Record<string, { label: string; description: string }>;
    question_types: QuestionTypeOption[];
    code_languages: string[];
    question_counts: number[];
    max_questions: number;
    max_file_mb: number;
    extensions: string[];
    pricing: Record<string, { input: number; output: number; cache_read: number }>;
  };
  app: { name: string; version: string; data_dir: string };
  warning?: string;
}

export interface UploadInfo {
  id: string;
  filename: string;
  kind: "pdf" | "image" | "text";
  source_type: string;
  size: number;
  char_count: number | null;
  status: "ready";
}

export interface Subtopic { id: string; name: string; description: string; position: number }

export interface SessionConfig {
  types: string[];
  difficulty: number;
  adaptive: boolean;
  count: number;
  language: string;
  feedback_mode: "immediate" | "end";
  model: string;
  effort: string;
  fallback: boolean;
}

export interface SessionView {
  id: string;
  title: string;
  subject: string;
  material: string;
  status: "analyzing" | "generating" | "ready" | "completed";
  error: ApiErrorBody | null;
  created_at: string;
  config: SessionConfig;
  current_difficulty: number;
  subtopics: Subtopic[];
  documents: UploadInfo[];
  progress: { served: number; answered: number; grading: number; generated: number };
  generating: boolean;
}

export interface QuestionView {
  id: string;
  position: number;
  total: number;
  type: string;
  type_label: string;
  subtopic_id: string;
  subtopic_name: string;
  difficulty: number;
  difficulty_label: string;
  prompt: string;
  uses_outside_knowledge: boolean;
  source_hint: string;
  options?: { id: number; text: string }[];
  blank_count?: number;
  left?: string[];
  right?: string[];
  items?: { id: number; text: string }[];
  language?: string;
  starter_code?: string;
  flawed_work?: string;
  scenario?: string;
}

export type NextResponse =
  | { state: "question"; question: QuestionView; progress: SessionView["progress"] }
  | { state: "pending"; message: string; progress: SessionView["progress"] }
  | { state: "done"; progress: SessionView["progress"] }
  | { state: "error"; error: ApiErrorBody; progress: SessionView["progress"] };

export interface AnswerKey {
  correct_ids?: number[];
  correct?: boolean;
  matches?: number[];
  order?: number[];
  blanks?: string[];
}

export interface CriterionResult { criterion: string; awarded: number; max: number; comment: string }

export interface AnswerView {
  question_id: string;
  grade_status: "pending" | "done" | "error";
  grade_error: ApiErrorBody | null;
  revealed: boolean;
  score?: number;
  verdict?: Verdict;
  skipped?: boolean;
  feedback?: string;
  correct_answer?: string;
  explanation?: string;
  your_answer?: string;
  misconception?: string;
  criteria?: CriterionResult[];
  answer_key?: AnswerKey;
}

export interface MasteryBucket {
  n: number; correct: number; partial: number; incorrect: number; skipped: number; confidently_wrong: number; score: number | null;
}
export interface SubtopicMastery extends MasteryBucket {
  id: string; name: string; description: string; weak: boolean; weak_reasons: ("low_score" | "confidently_wrong")[];
}
export interface TypeMastery extends MasteryBucket { type: string; label: string }

export interface ResultQuestion {
  id: string;
  position: number;
  type: string;
  type_label: string;
  subtopic_id: string;
  subtopic_name: string;
  difficulty: number;
  prompt: string;
  display: QuestionView;
  uses_outside_knowledge: boolean;
  confidence: Confidence | null;
  skipped: boolean;
  grade_status: "pending" | "done" | "error";
  grade_error: ApiErrorBody | null;
  score: number | null;
  verdict: Verdict | null;
  feedback: string;
  misconception: string;
  explanation: string;
  your_answer: string;
  correct_answer: string;
  criteria: CriterionResult[];
  confidently_wrong: boolean;
}

export interface CostSummary {
  total: { calls: number; input: number; output: number; cache_write: number; cache_read: number; cost: number };
  by_purpose: { purpose: string; calls: number; input: number; output: number; cache_write: number; cache_read: number; cost: number }[];
}

export interface Results {
  session: {
    id: string; title: string; subject: string; created_at: string; completed_at: string | null; status: string;
    config: SessionConfig; parent_session_id: string | null;
  };
  mastery: { overall: MasteryBucket; subtopics: SubtopicMastery[]; types: TypeMastery[]; weak_subtopic_ids: string[] };
  questions: ResultQuestion[];
  missed: ResultQuestion[];
  ungraded: string[];
  cost: CostSummary;
  study_guide_status: "generating" | "ready" | "failed" | null;
}

export interface ChartSpec {
  include: boolean;
  chart_type: "line" | "bar" | "scatter" | "area";
  title: string;
  x_label: string;
  y_label: string;
  series: { name: string; points: { label: string; x: number; y: number }[] }[];
  caption: string;
}

export interface StudySection {
  title: string;
  explanation: string;
  key_formulas: { latex: string; description: string }[];
  diagram: { include: boolean; kind: string; mermaid: string; caption: string; repaired?: boolean };
  chart: ChartSpec;
  worked_example: { problem: string; steps: string[]; answer: string };
  common_mistakes: { mistake: string; why: string; fix: string; from_your_answers: boolean }[];
  practice_questions: { question: string; answer: string }[];
}

export interface GuideSectionState {
  subtopic_id: string;
  name: string;
  score: number | null;
  weak_reasons: string[];
  status: "pending" | "ready" | "failed";
  section: StudySection | null;
  error: ApiErrorBody | null;
}

export interface StudyGuide {
  status: "generating" | "ready" | "failed" | "none";
  content: { generated_at: string; overall_score: number | null; sections: GuideSectionState[] } | null;
}

export interface HistoryRow {
  id: string;
  created_at: string;
  completed_at: string | null;
  subject: string;
  title: string;
  status: string;
  score: number | null;
  parent_session_id: string | null;
  answered: number;
  count: number;
  adaptive: boolean;
  cost: number;
  guide_status: string | null;
}

export interface Trends {
  subject: string;
  sessions: { session_id: string; created_at: string; score: number | null; title: string }[];
  subtopics: { name: string; latest: number; change: number | null; points: { session_id: string; date: string; score: number }[] }[];
}
