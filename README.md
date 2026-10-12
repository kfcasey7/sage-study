# Sage Study

A desktop study assistant that uses the Claude API to quiz you on your own course material, grade your
answers, and write a study guide covering whatever you got wrong.

- Upload notes, slides, and textbook chapters (PDF, Word, PowerPoint, text/Markdown, or photos of notes).
- 13 question types: multiple choice, select-all, true/false, fill-in-the-blank, matching, ordering, short and
  long response, free response, math with step-by-step LaTeX work, code (Monaco editor), error analysis, and
  applied engineering scenarios.
- Difficulty 1–5 with optional adaptive mode, confidence ratings, and a "Skip / I don't know" button.
- Objective questions are graded instantly on your machine. Written answers are graded by Claude against a
  rubric written alongside each question.
- Results dashboard with per-subtopic and per-type scores. Weak areas are subtopics under 70%, or ones where
  you were wrong with high confidence.
- A personalized study guide for weak areas, with explanations, KaTeX formulas, Mermaid diagrams or charts,
  worked examples, your specific mistakes, and practice questions. Export it to PDF or Markdown.
- History with mastery trends per subject, and one-click retests of your weak areas.

Everything runs locally. The API key stays in your operating system's credential store and is only ever read
by the local backend.

## Setup

**Requirements:** Python 3.11+ and Node.js 18+ (LTS recommended). Node is only needed to build the interface.

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

### macOS / Linux

```bash
./setup.sh
```

The setup script:

1. creates a virtual environment in `.venv` and installs the Python dependencies,
2. generates the app icon (`assets/icon/`),
3. builds the React interface (`frontend/dist`),
4. creates a desktop shortcut:
   - **Windows:** `Sage Study.lnk` on the Desktop (OneDrive-redirected Desktops are handled) and in the Start
     Menu. It runs `pythonw`, so no terminal window opens.
   - **macOS:** `Sage Study.app` on the Desktop.
   - **Linux:** `sage-study.desktop` on the Desktop and in `~/.local/share/applications`.

Options: `--no-shortcut`, `--skip-frontend`.

**Linux note:** pywebview needs a GUI toolkit. On Debian/Ubuntu install
`sudo apt install python3-gi gir1.2-webkit2-4.1`, then
`.venv/bin/pip install pygobject` (or `pip install pywebview[qt]` for Qt).

## Getting an API key

1. Sign in at <https://console.anthropic.com> and add a payment method or credits under **Billing**.
2. Go to **Settings → API Keys → Create Key** and copy the key (it starts with `sk-ant-`).
3. Open Sage Study → **Settings**, paste the key, and click **Save & verify**.

The key is stored with [`keyring`](https://pypi.org/project/keyring/) (Windows Credential Manager, macOS
Keychain, or Secret Service on Linux). If no key is saved, the app falls back to the `ANTHROPIC_API_KEY`
environment variable.

## Using it

1. **New session:** describe what to cover, drop in your files, pick question types, difficulty, and count.
2. Sage maps the material into subtopics, then writes questions in small batches while you work.
3. Answer one question at a time. Feedback appears after each answer or at the end (set in **Settings**).
4. **Results** shows your score by subtopic and question type, every missed question, and the estimated API
   cost of the session.
5. **Generate study guide** covers only your weak areas. **Retest weak areas** starts a new session
   limited to those subtopics.

Only one copy of the app runs at a time. Launching it again brings the existing window to the front.

## Models and cost

The default model is **Claude Sonnet 5.5** (`claude-sonnet-5-5`). You can switch to Opus 5.5 (most thorough)
or Haiku 5.5 (cheapest) in Settings, along with the thinking effort (low/medium/high).

Each session caches your documents, so after the first call they are re-read at roughly a tenth of the
normal price. A typical 10-question session on Sonnet costs a few cents to about $0.30, depending on document
size and how many written answers need grading. The exact estimate is shown on the results screen.

Prices are in `backend/sage/config.py` (`PRICING`). Update them there if Anthropic's prices change.

## Rebuilding the shortcut

If you move the project folder, or the shortcut is deleted:

```bash
.venv/Scripts/python scripts/create_shortcut.py      # Windows
.venv/bin/python scripts/create_shortcut.py          # macOS / Linux
```

`--remove` deletes it. To regenerate the icon, run `scripts/make_icons.py`.

## Customizing the prompts

Every prompt sent to Claude lives in `backend/sage/prompts/`:

| File | Used for |
|---|---|
| `system.py` | Shared system prompt + material preamble (cached across every call in a session) |
| `topic_map.py` | Splitting the material into subtopics |
| `generate.py` | Question writing, with per-type guidance (`TYPE_GUIDANCE`) and difficulty levels |
| `grade.py` | Rubric grading, with per-type notes for math, code, and error analysis |
| `study_guide.py` | Study guide sections, plus Mermaid diagram repair |

Keep `system.py` free of anything that changes per call (dates, counts), or the prompt cache stops working.

## Development

```bash
# Backend tests (schemas, local grading, mastery, ingest, and the full API flow against a fake Claude)
.venv/Scripts/python -m pytest

# Run the backend alone at http://127.0.0.1:8765 (serves the built UI)
cd backend && ../.venv/Scripts/python -m sage.dev

# Demo mode: canned responses, no API key or cost. Handy for UI work.
SAGE_FAKE_CLAUDE=1 ../.venv/Scripts/python -m sage.dev

# Frontend with hot reload (proxies /api to the backend above)
cd frontend && npm run dev

# Live end-to-end check against the real API (spends ~$0.25–0.60)
.venv/Scripts/python scripts/e2e_live.py --url http://127.0.0.1:8765
```

On macOS/Linux use `.venv/bin/python` instead of `.venv/Scripts/python`.

### Layout

```
backend/sage/
  app.py              FastAPI app, local-only guard, static frontend
  main.py             desktop entry: single instance, server thread, pywebview window
  claude_client.py    Anthropic SDK wrapper: structured outputs, caching, retries, error mapping, cost
  ingest.py           uploads: PDF/image blocks, DOCX/PPTX text extraction
  prompts/            every prompt (see above)
  schemas/            JSON schemas + Pydantic validation for questions, grades, topic map, study guide
  services/           generation, grading (local + Claude), mastery, results, study guide, export
frontend/src/
  pages/              New session, Quiz, Results, Study guide, History, Settings
  answers/            one input component per question type (+ Monaco code editor)
  components/         Markdown/KaTeX, Mermaid, charts, shared UI
scripts/              setup, icons, shortcut, sample PDF, live E2E
```

App data (database, uploads, log) lives in `%LOCALAPPDATA%\SageStudy` on Windows,
`~/Library/Application Support/SageStudy` on macOS, and `~/.local/share/SageStudy` on Linux.
Set `SAGE_DATA_DIR` to use a different folder. If the app won't start, check `sage.log` there.

## How it works (API details)

- **Structured outputs.** Every call uses `output_config.format` with a strict JSON schema, and the result is
  validated again with Pydantic. Constraints JSON Schema can't express (answer indices in range, the
  `{{blank}}` count matching the answers, and so on) trigger one retry with the validator's error message.
  Forced tool use is rejected by the 5.5 models, so structured outputs are used instead.
- **Prompt caching.** All calls share `system prompt → documents → material preamble`, with a 1-hour cache
  breakpoint at the end. A session's model and effort are pinned at creation, because changing either one
  invalidates the cache.
- **PDFs and images** are sent as native `document` and `image` blocks. DOCX and PPTX files are converted to
  text on the backend. Phone photos are auto-rotated and downscaled.
- **Refusal fallback.** Sonnet and Opus requests opt into `fallbacks: "default"` (beta
  `server-side-fallback-2026-07-01`). If a request is declined, the API retries it on another model within
  the same call. You can turn this off in Settings.
- **Security.** The backend listens only on 127.0.0.1. It rejects foreign `Host` headers (DNS rebinding) and
  any write without the app's custom header (cross-site requests).
