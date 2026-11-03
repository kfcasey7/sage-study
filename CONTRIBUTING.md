# Contributing

Thanks for helping. Bug reports are most useful with the diagnostic report from **Settings > Help > Diagnostics**.

## Setting up

You need [uv](https://docs.astral.sh/uv/) and, if you change the UI, Node.js 22 or newer.

```bash
uv sync --group dev
uv run pytest
uv run ruff check backend scripts
```

Run the app from your checkout with `uv run sage-study`. For UI work, see the Development section of the README.

## Rules that keep the app shareable

- All AI goes through `backend/sage/llm_client.py`, and through the user's own Claude Code. Don't bundle or modify Claude Code, and don't add code that reads Claude credentials.
- Don't weaken the safety flags in `build_args`, or the environment stripping in `child_env`.
- Don't add telemetry.
- Keep user data in the data folder (`config.DATA_DIR`), never next to the code.
- If you change `frontend/`, run `python scripts/build_frontend.py` and commit the updated `backend/sage/web`. CI fails if it's stale.
- If you change dependencies, regenerate `constraints.txt` (`uv pip compile pyproject.toml --universal --python-version 3.13 --no-header --no-annotate -o constraints.txt`) and `THIRD_PARTY_NOTICES.md` (`python scripts/gen_notices.py`).
- Database changes need a new version in `backend/sage/migrations.py` and a test. Migrations must never lose data.

## Releasing

1. Update `__version__` in `backend/sage/__init__.py` and add a section to `CHANGELOG.md`.
2. Rebuild the UI if the frontend changed, and commit.
3. Tag and push: `git tag v1.2.3 && git push origin main v1.2.3`. GitHub Actions builds the downloads and publishes the release.
