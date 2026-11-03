import type {
  AnswerView, ApiErrorBody, ChatView, CliStatus, Confidence, Diagnostics, HistoryRow, NextResponse, PlaylistView, QuestionVideos, Results,
  SessionOptions, SessionView, SettingsPayload, SourceView, StudyGuide, StudySection, StudySetRow, StudySetView, Trends,
  UpdateState, UploadInfo, YoutubeKeyStatus,
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
const patch = <T,>(p: string, b: unknown) => request<T>("PATCH", p, b);

/** Study guide endpoints: a quiz's weak-areas guide lives under its session, any guide under its id. */
export const guideBase = (ref: { sessionId: string } | { guideId: string }) =>
  "sessionId" in ref ? `/api/sessions/${ref.sessionId}/study-guide` : `/api/guides/${ref.guideId}`;

export interface QuizOptionsBody { types: string[]; difficulty: number; adaptive: boolean; count: number; languages: string[] }

export const api = {
  settings: () => get<SettingsPayload>("/api/settings"),
  updateSettings: (s: Partial<SettingsPayload["settings"]>) => put<SettingsPayload>("/api/settings", s),
  cliStatus: (refresh = false) => get<CliStatus>(`/api/settings/cli-status${refresh ? "?refresh=true" : ""}`),
  diagnostics: () => get<Diagnostics>("/api/diagnostics"),
  updates: (force = false) => get<UpdateState>(`/api/updates${force ? "?force=true" : ""}`),
  applyUpdate: () => post<{ action: "updating" | "opened_download_page" | "manual"; command?: string; url?: string }>("/api/updates/apply"),
  loadDemo: () => post<{ id: string }>("/api/demo"),
  heartbeat: () => post<{ ok: boolean }>("/api/_heartbeat"),
  quit: () => post<{ ok: boolean }>("/api/_quit"),

  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<UploadInfo>("POST", "/api/uploads", fd);
  },
  deleteUpload: (id: string) => del<{ ok: boolean }>(`/api/uploads/${id}`),

  createSession: (body: {
    material: string; subject: string; upload_ids: string[]; types: string[]; difficulty: number;
    adaptive: boolean; count: number; languages: string[];
  }) => post<SessionView>("/api/sessions", body),
  session: (id: string) => get<SessionView>(`/api/sessions/${id}`),
  deleteSession: (id: string) => del<{ ok: boolean }>(`/api/sessions/${id}`),
  retrySession: (id: string) => post<SessionView>(`/api/sessions/${id}/retry`),
  next: (id: string) => get<NextResponse>(`/api/sessions/${id}/next`),
  answer: (qid: string, body: { response: Record<string, unknown>; confidence: Confidence | null; skipped: boolean }) =>
    post<AnswerView>(`/api/questions/${qid}/answer`, body),
  regrade: (qid: string) => post<AnswerView>(`/api/questions/${qid}/regrade`),
  deferQuestion: (qid: string) => post<{ ok: boolean; skipped_waiting: number }>(`/api/questions/${qid}/defer`),
  reportQuestion: (qid: string, reason: string, note: string) =>
    post<{ ok: boolean; replaced: boolean; excluded: boolean }>(`/api/questions/${qid}/report`, { reason, note }),
  questionChat: (qid: string) => get<ChatView>(`/api/questions/${qid}/chat`),
  askClaude: (qid: string, message: string) => post<ChatView>(`/api/questions/${qid}/chat`, { message }),
  updateOptions: (id: string, options: SessionOptions) => put<SessionView>(`/api/sessions/${id}/options`, options),
  finish: (id: string) => post<Results>(`/api/sessions/${id}/finish`),
  results: (id: string) => get<Results>(`/api/sessions/${id}/results`),
  retest: (id: string) => post<SessionView>(`/api/sessions/${id}/retest`),

  startGuide: (id: string, force = false) => post<StudyGuide>(`/api/sessions/${id}/study-guide`, { force }),
  guide: (base: string) => get<StudyGuide>(base),
  retryGuideSection: (base: string, subtopicId: string) => post<StudyGuide>(`${base}/sections/${subtopicId}/retry`),
  repairDiagram: (base: string, subtopic_id: string, error: string) => post<StudySection>(`${base}/repair-diagram`, { subtopic_id, error }),
  exportMarkdown: (base: string) => post<{ path?: string; cancelled?: boolean }>(`${base}/export/markdown`),
  exportPdf: (base: string, body_html: string, head_html: string) =>
    post<{ path?: string; cancelled?: boolean; fallback?: "print"; message?: string }>(`${base}/export/pdf`, { body_html, head_html }),
  deleteGuide: (guideId: string) => del<{ ok: boolean }>(`/api/guides/${guideId}`),
  reveal: (path: string) => post<{ ok: boolean }>("/api/reveal", { path }),
  openFile: (path: string) => post<{ ok: boolean }>("/api/open-file", { path }),

  // Sources (setup-screen drafts, or a set's Append panel)
  addFileSource: (file: File, scope: { set_id?: string; draft_id?: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    if (scope.set_id) fd.append("set_id", scope.set_id);
    if (scope.draft_id) fd.append("draft_id", scope.draft_id);
    return request<SourceView>("POST", "/api/sources/files", fd);
  },
  addLinkSources: (urls: string[], scope: { set_id?: string; draft_id?: string }) =>
    post<(SourceView & { id: string | null })[]>("/api/sources/links", { urls, ...scope }),
  sources: (ids: string[]) => get<SourceView[]>(`/api/sources?ids=${ids.join(",")}`),
  retrySource: (id: string) => post<SourceView>(`/api/sources/${id}/retry`),
  deleteSource: (id: string) => del<{ ok: boolean }>(`/api/sources/${id}`),

  // Study Sets
  createSet: (body: { title: string; subject: string; prompt: string; source_ids: string[] }) => post<StudySetView>("/api/sets", body),
  sets: () => get<StudySetRow[]>("/api/sets"),
  set: (id: string) => get<StudySetView>(`/api/sets/${id}`),
  updateSet: (id: string, body: { title?: string; subject?: string }) => patch<StudySetView>(`/api/sets/${id}`, body),
  deleteSet: (id: string) => del<{ ok: boolean }>(`/api/sets/${id}`),
  buildBreakdown: (id: string) => post<StudySetView>(`/api/sets/${id}/breakdown`),
  appendToSet: (id: string, prompt: string) => post<StudySetView>(`/api/sets/${id}/append`, { prompt }),
  repairMap: (id: string, error: string) => post<StudySetView["breakdown"]>(`/api/sets/${id}/breakdown/repair-map`, { error }),
  startSetQuiz: (id: string, subtopic_ids: string[], options: QuizOptionsBody) =>
    post<SessionView>(`/api/sets/${id}/quiz`, { subtopic_ids, ...options }),
  startSetGuide: (id: string, subtopic_ids: string[]) => post<StudyGuide>(`/api/sets/${id}/guides`, { subtopic_ids }),
  startPlaylist: (id: string, subtopic_ids: string[]) => post<PlaylistView>(`/api/sets/${id}/playlists`, { subtopic_ids }),

  // Videos
  playlist: (id: string) => get<PlaylistView>(`/api/playlists/${id}`),
  deletePlaylist: (id: string) => del<{ ok: boolean }>(`/api/playlists/${id}`),
  setWatched: (itemId: string, watched: boolean) => put<{ ok: boolean; watched: boolean }>(`/api/playlist-items/${itemId}`, { watched }),
  replaceVideo: (itemId: string) => post<PlaylistView>(`/api/playlist-items/${itemId}/replace`),
  moreVideos: (playlistId: string, subtopic_id: string) => post<PlaylistView>(`/api/playlists/${playlistId}/more`, { subtopic_id }),
  questionVideos: (qid: string) => get<QuestionVideos>(`/api/questions/${qid}/videos`),
  findQuestionVideos: (qid: string) => post<QuestionVideos>(`/api/questions/${qid}/videos`),
  openUrl: (url: string) => post<{ ok: boolean }>("/api/open-url", { url }),
  youtubeKey: () => get<YoutubeKeyStatus>("/api/settings/youtube-key"),
  saveYoutubeKey: (key: string) => put<YoutubeKeyStatus>("/api/settings/youtube-key", { key }),
  deleteYoutubeKey: () => del<YoutubeKeyStatus>("/api/settings/youtube-key"),

  history: () => get<HistoryRow[]>("/api/history"),
  subjects: () => get<string[]>("/api/subjects"),
  trends: (subject: string) => get<Trends>(`/api/trends?subject=${encodeURIComponent(subject)}`),
};

export function asApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError({ code: "client_error", message: e instanceof Error ? e.message : String(e) });
}
