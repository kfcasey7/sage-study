# Changelog

This project follows [semantic versioning](https://semver.org/).

## [1.0.0] - Unreleased

The first version meant for sharing with friends and classmates.

### Added

- One-step installers for Windows, macOS, and Linux that need no Python, Node, or terminal knowledge, plus matching uninstallers. Running an installer again repairs the app.
- Packaged downloads built by GitHub Actions.
- A first-run setup wizard, a demo Study Set that works without Claude Code, and a Diagnostics page with a copyable report.
- A check for new versions (it can be turned off), with an update button.
- `--data-dir` to keep study data in a folder of your choice.
- If the app's window can't open, it now opens in your default browser instead.
- Clearer messages for a missing Claude Code, not being signed in, usage limits, and no internet.

### Changed

- The app now uses a different free port at each launch, and requires a secret token created at each launch, so other programs and web pages can't call it.
- Link fetching now refuses every non-public address, and connects only to the address it checked.
- Upload paths in the database are relative to the data folder, so the folder can move. Your database is backed up first and migrated automatically.
- Theme and quiz preferences are now saved in the database. Your saved quiz options reset once when you upgrade.
- "Ask Claude" is now "Ask about this question".

### Earlier

Study Sets, the Material Breakdown, link sources, YouTube playlists, the question chat, and quizzes came before this version.
