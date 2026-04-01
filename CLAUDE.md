# Project Configuration

## Notion
- **Project name**: Polymarket Bot
- **Project page**: a55d248f-c6ac-4e11-a7b4-d40efd2be958
- **Tasks database**: 3187e505-e99b-817c-adad-d61e81be1261
- **Tasks data source**: collection://6497e505-e99b-8248-9718-07551fec2fa9
- **Projects data source**: collection://56e7e505-e99b-8321-a1f4-878d833d9136

## Skills
- `notion-tasks` — Task management from Notion board. Always check Notion before starting work.
- `tars` — All GitHub operations via tars-bot-01 GitHub App (push, PRs, comments, reviews)
- `codex` — Code review gate. Run `/codex:rescue` after implementation to review changes.

## Code Review
- After writing or modifying code, run a Codex review (`/codex:rescue`) on changed files before marking work as complete
- Fix any issues found by the review before presenting results

## Conventions
- Package manager: `uv`
- Python version: 3.11
- Linter: `ruff`
- Tests: `pytest` (run with `uv run pytest tests/ -v`)
- Coverage: `uv run pytest --cov --cov-report=term-missing`
- Branch naming: `feat/`, `fix/`, `chore/`
- Commits end with `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
- CHANGELOG.md: Keep a Changelog format, update `[Unreleased]` per PR
- PR template: `.github/PULL_REQUEST_TEMPLATE.md`
