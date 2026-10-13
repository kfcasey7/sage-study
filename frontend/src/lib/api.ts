import type {
  AnswerView, ApiErrorBody, ChatView, CliStatus, Confidence, HistoryRow, NextResponse, Results, SessionOptions, SessionView,
  SettingsPayload, StudyGuide, StudySection, Trends, UploadInfo,
} from "./types";

export class ApiError extends Error {
  code: string;
  retryAfter: number | null;
  retryable: boolean;
  detail: string | null;
  constructor(body: ApiErrorBody) {
    super(body.message);
    this.code = body.code;
    this.retryAfter = body.retry_after ?? null;
    this.retryable = !!body.retryable;
    this.detail = body.detail ?? null;
  }
  toBody(): ApiErrorBody {
    return { code: this.code, message: this.message, retry_after: this.retryAfter, retryable: this.retryable, detail: this.detail };
  }
}

// Every write carries this header; the backend rejects writes without it (blocks cross-site requests).
const CLIENT_HEADERS = { "x-sage-client": "1" };

async function request<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers: body instanceof FormData ? CLIENT_HEADERS : { ...CLIENT_HEADERS, "content-type": "application/json" },
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
      ...init,
    });
  } catch {
    throw new ApiError({ code: "app_offline", message: "Can't reach the Sage Study backend. Try restarting the app.", retryable: true });
  }
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const err = (data as { error?: ApiErrorBody } | null)?.error;
    throw new ApiError(err ?? { code: "server_error", message: `Request failed (${res.status}).`, detail: text.slice(0, 300) });
  }
  return data as T;
}

const get = <T,>(p: string) => request<T>("GET", p);
const post = <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});
const put = <T,>(p: string, b: unknown) => request<T>("PUT", p, b);
const del = <T,>(p: string) => request<T>("DELETE", p);

export const api = {
  settings: () => get<SettingsPayload>("/api/settings"),
  updateSettings: (s: Partial<SettingsPayload["settings"]>) => put<SettingsPayload>("/api/settings", s),
  cliStatus: (refresh = false) => get<CliStatus>(`/api/settings/cli-status${refresh ? "?refresh=true" : ""}`),

  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<UploadInfo>("POST", "/api/uploads", fd);
  },
  deleteUpload: (id: string) => del<{ ok: boolean }>(`/api/uploads/${id}`),

  createSession: (body: {
    material: string; subject: string; upload_ids: string[]; types: string[]; difficulty: number;
    adaptive: boolean; count: number; language: string;
  }) => post<SessionView>("/api/sessions", body),
  session: (id: string) => get<SessionView>(`/api/sessions/${id}`),
  deleteSession: (id: string) => del<{ ok: boolean }>(`/api/sessions/${id}`),
  retrySession: (id: string) => post<SessionView>(`/api/sessions/${id}/retry`),
  next: (id: string) => get<NextResponse>(`/api/sessions/${id}/next`),
  answer: (qid: string, body: { response: Record<string, unknown>; confidence: Confidence | null; skipped: boolean }) =>
    post<AnswerView>(`/api/questions/${qid}/answer`, body),
  regrade: (qid: string) => post<AnswerView>(`/api/questions/${qid}/regrade`),
  deferQuestion: (qid: string) => post<{ ok: boolean; skipped_waiting: number }>(`/api/questions/${qid}/defer`),
  questionChat: (qid: string) => get<ChatView>(`/api/questions/${qid}/chat`),
  askClaude: (qid: string, message: string) => post<ChatView>(`/api/questions/${qid}/chat`, { message }),
  updateOptions: (id: string, options: SessionOptions) => put<SessionView>(`/api/sessions/${id}/options`, options),
  finish: (id: string) => post<Results>(`/api/sessions/${id}/finish`),
  results: (id: string) => get<Results>(`/api/sessions/${id}/results`),
  retest: (id: string) => post<SessionView>(`/api/sessions/${id}/retest`),

  startGuide: (id: string, force = false) => post<StudyGuide>(`/api/sessions/${id}/study-guide`, { force }),
  guide: (id: string) => get<StudyGuide>(`/api/sessions/${id}/study-guide`),
  retryGuideSection: (id: string, subtopicId: string) => post<StudyGuide>(`/api/sessions/${id}/study-guide/sections/${subtopicId}/retry`),
  repairDiagram: (id: string, subtopic_id: string, error: string) =>
    post<StudySection>(`/api/sessions/${id}/study-guide/repair-diagram`, { subtopic_id, error }),
  exportMarkdown: (id: string) => post<{ path?: string; cancelled?: boolean }>(`/api/sessions/${id}/study-guide/export/markdown`),
  exportPdf: (id: string, body_html: string, head_html: string) =>
    post<{ path?: string; cancelled?: boolean; fallback?: "print"; message?: string }>(`/api/sessions/${id}/study-guide/export/pdf`, { body_html, head_html }),
  reveal: (path: string) => post<{ ok: boolean }>("/api/reveal", { path }),
  openFile: (path: string) => post<{ ok: boolean }>("/api/open-file", { path }),

  history: () => get<HistoryRow[]>("/api/history"),
  subjects: () => get<string[]>("/api/subjects"),
  trends: (subject: string) => get<Trends>(`/api/trends?subject=${encodeURIComponent(subject)}`),
};

export function asApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError({ code: "client_error", message: e instanceof Error ? e.message : String(e) });
}
