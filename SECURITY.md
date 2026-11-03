# Security

## Reporting a problem

Please report security problems privately through [GitHub's private vulnerability reporting](https://github.com/kfcasey7/sage-study/security/advisories/new) rather than in a public issue. Include how to reproduce the problem. This is a personal project, so responses are best-effort.

Problems in Claude Code itself should go to Anthropic, not here.

## How the app protects you

- **Claude sign-in.** The app never asks for, reads, stores, copies, or transmits your Claude login or session tokens. You sign in through Anthropic's own flow, inside Claude Code. The app only runs `claude auth status` to see whether you're signed in, and keeps three fields from its answer: signed in or not, sign-in type, and plan type.
- **Claude Code runs locked down.** Each call strips `ANTHROPIC_*` and third-party-provider variables from its environment, turns off shell and file tools, ignores your MCP servers, settings, and hooks, and has a timeout. Images and scanned PDFs get a read-only tool confined to a temporary folder of copies. Video searches without a YouTube key get only web search, and no files.
- **Local server.** The app's backend listens on `127.0.0.1` only, on a free port chosen at each launch. It accepts only its own `Host` and `Origin`, and requires a secret token created at each launch. Other websites can't call it, and neither can other programs that don't have the token.
- **Link fetching.** The backend reads pasted links itself. It refuses addresses on your computer or local network, including through redirects, and connects to the same public address it checked.
- **YouTube key.** Kept in your operating system's credential store (Windows Credential Manager, macOS Keychain, or Secret Service on Linux), and never sent to the frontend.
- **No telemetry.** The app has no analytics or tracking of any kind.

## What it doesn't protect against

A program already running under your own user account can read your files, including the study database and the token file for the current launch. That's true of nearly all desktop software, so the token's job is to stop web pages and other users' programs.

## Secrets in the repo

CI scans the full git history with [gitleaks](https://github.com/gitleaks/gitleaks). The fake keys in the tests are listed in `.gitleaks.toml`.
