# Sage Study

A desktop study assistant that uses Claude to quiz you on your own course material, grade your answers, and
write a study guide covering whatever you got wrong. Every AI request goes through the **Claude Code CLI**
installed on your computer, using your **Claude subscription login** (e.g. Pro). There is no API key and no API
billing; requests count toward your plan's normal usage limits.

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

Everything runs locally. The app is a single-user program that only talks to Claude through the `claude`
command on this machine.

## Setup

**Requirements:**

- Python 3.11+
- Node.js 18+ (LTS recommended). Node is only needed to build the interface.
- [Claude Code](https://claude.com/claude-code), installed and logged in with your Claude account (see below).

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
4. checks that Claude Code is on your PATH and logged in, and tells you what to do if it isn't,
5. creates a desktop shortcut:
   - **Windows:** `Sage Study.lnk` on the Desktop (OneDrive-redirected Desktops are handled) and in the Start
     Menu. It runs `pythonw`, so no terminal window opens.
   - **macOS:** `Sage Study.app` on the Desktop.
   - **Linux:** `sage-study.desktop` on the Desktop and in `~/.local/share/applications`.

Options: `--no-shortcut`, `--skip-frontend`.

**Linux note:** pywebview needs a GUI toolkit. On Debian/Ubuntu install
`sudo apt install python3-gi gir1.2-webkit2-4.1`, then
`.venv/bin/pip install pygobject` (or `pip install pywebview[qt]` for Qt).

## Setting up Claude Code

1. Install Claude Code: <https://claude.com/claude-code>. On Windows, the native installer puts `claude` in
   `%USERPROFILE%\.local\bin`.
2. Open a terminal, run `claude`, and log in with your **Claude Pro** account. Type `/login` if it doesn't
   prompt you. Then `/exit`.
3. Check: `claude auth status --text` should show you as logged in with your Claude account.
4. In Sage Study, **Settings → Claude Code status** should show **Ready**. Click **Check again** after
   logging in.

How the app calls it: for every request it runs `claude -p` with JSON output and these restrictions.

- **No API billing.** Every `ANTHROPIC_*` environment variable (including `ANTHROPIC_API_KEY`) and the
  Bedrock/Vertex/Foundry switches are removed from the child process, so the CLI can only use your
  subscription login.
- **No tools.** `--tools ""` turns off all built-in tools. `--restricted` blocks shells and code execution.
  `--strict-mcp-config` and `--setting-sources ""` ignore your MCP servers and your Claude Code settings or
  hooks, so the model can't edit files, run commands, browse, or reach your connected accounts.
- **Images and scanned PDFs** are the one exception. For requests that include them, Claude gets only the
  read-only `Read` tool, confined to a temporary folder holding copies of those files. The folder is
  deleted after each call.
- **Timeouts.** Every call has one: 2 to 7 minutes depending on the task.

## Using it

1. **New session:** describe what to cover, drop in your files, pick question types, difficulty, and count.
2. Sage maps the material into subtopics, then writes questions in small batches while you work.
3. Answer one question at a time. Feedback appears after each answer or at the end (set in **Settings**).
4. **Results** shows your score by subtopic and question type, every missed question, and how many AI calls
   the session made and how long it took.
5. **Generate study guide** covers only your weak areas. **Retest weak areas** starts a new session
   limited to those subtopics.

Only one copy of the app runs at a time. Launching it again brings the existing window to the front.

**If you hit your usage limit,** the app says "Claude usage limit reached — try again after it resets." All
progress is saved after every answer. Reopen the session later from **History** (or **Recent** in the
sidebar) to keep going. Answers that couldn't be graded get a **Grade now** button.

## Models and usage

Sage uses the CLI's model aliases, and you can change them in **Settings**:

| Task | Default |
|---|---|
| Mapping subtopics, writing questions | **Haiku** (fast, light on usage limits) |
| Grading written, math, and code answers; study guides; diagram fixes | **Sonnet** |

Objective questions (multiple choice, true/false, select-all, matching, ordering, and exactly matching
fill-in-the-blanks) are graded on your computer with no AI call. The results screen shows how many AI calls
a session made and how long they took. The app pre-generates upcoming questions in the background while
you answer, so waiting is mostly limited to the start of a session.

**Documents:**

- **Text** from PDF, Word, PowerPoint, and text/Markdown files is extracted locally and sent inline.
- **Images and scanned PDFs** (too little extractable text) are read by Claude Code directly.
- **Long material:** each call sends about 120,000 characters. Longer material is split into chunks, and
  each request gets the chunks most relevant to the subtopic being asked about. The quiz and results screens
  say when this happened.

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
| `system.py` | Shared system prompt + material preamble |
| `topic_map.py` | Splitting the material into subtopics |
| `generate.py` | Question writing, with per-type guidance (`TYPE_GUIDANCE`) and difficulty levels |
| `grade.py` | Rubric grading, with per-type notes for math, code, and error analysis |
| `study_guide.py` | Study guide sections, plus Mermaid diagram repair |

## Development

```bash
# Backend tests (schemas, grading, mastery, ingest, the CLI wrapper with a mocked subprocess, and the
# full app flow against a fake Claude)
.venv/Scripts/python -m pytest

# Run the backend alone at http://127.0.0.1:8765 (serves the built UI)
cd backend && ../.venv/Scripts/python -m sage.dev

# Demo mode: canned responses, no Claude Code calls. Handy for UI work.
SAGE_FAKE_CLAUDE=1 ../.venv/Scripts/python -m sage.dev

# Frontend with hot reload (proxies /api to the backend above)
cd frontend && npm run dev

# Live end-to-end check through the real CLI (3 questions + study guide; uses some of your plan's usage)
.venv/Scripts/python scripts/e2e_live.py --url http://127.0.0.1:<port>   # port: see instance.json in the data folder
```

On macOS/Linux use `.venv/bin/python` instead of `.venv/Scripts/python`.

### Layout

```
backend/sage/
  app.py              FastAPI app, local-only guard, static frontend
  main.py             desktop entry: single instance, server thread, pywebview window
  llm_client.py       the only AI entry point: runs `claude -p`, schema-validated JSON, retries, errors
  ingest.py           uploads: PDF/DOCX/PPTX text extraction, images, chunking long material
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

## How it works

- **One wrapper.** `backend/sage/llm_client.py` is the only module that calls the AI. Each request is
  `claude -p --output-format json --model <alias> --system-prompt … --json-schema …` plus the safety flags
  above, with the prompt sent on stdin. The CLI's `--json-schema` returns schema-checked output. The app
  then validates it again with Pydantic, which also checks things a JSON schema can't (answer indices in
  range, the `{{blank}}` count matching the answers, and so on). It retries up to twice with the
  validator's error message.
- **Turn limits.** The installed CLI has no max-turns flag. Calls have no tools at all, or only `Read` on a
  few files, so there's nothing to loop on, and every call has a hard timeout.
- **Errors** are mapped to clear messages: Claude Code missing, not logged in, usage limit reached,
  timeout, refusal, and unusable output.
- **Security.** The backend listens only on 127.0.0.1. It rejects foreign `Host` headers (DNS rebinding) and
  any write without the app's custom header (cross-site requests).
