# Pull Request Process

Claude Code creates PRs using the **tars-bot-01** GitHub App, which authenticates as its own identity (not the user's personal `gh` token).

## Prerequisites

1. `.env` contains `GH_APP_ID`, `GH_INSTALLATION_ID`, `GH_APP_PRIVATE_KEY_PATH`
2. `tars-bot.private-key.pem` exists in the project root (gitignored)
3. The GitHub App has **Contents: Read & write** and **Pull requests: Read & write** permissions

## Steps

### 1. Generate a fresh installation token

```bash
TOKEN=$(uv run python3 scripts/gh_app_token.py)
```

Tokens are valid for ~1 hour. Generate a new one for each PR session.

### 2. Create a feature branch

```bash
git checkout main && git pull
git checkout -b <branch-name>
```

Branch naming conventions:
- `feat/<topic>` — new features or workflows
- `fix/<topic>` — bug fixes
- `chore/<topic>` — version bumps, dependency updates, CI tweaks

### 3. Make changes, commit

```bash
git add <files>
git commit -m "<message>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

### 4. Push via the App token

Push using `x-access-token` auth so the push is attributed to the GitHub App, not the user's SSH key:

```bash
REPO=$(git config --get remote.origin.url | sed -E 's#.*github.com[:/](.*)\.git#\1#')
git push "https://x-access-token:${TOKEN}@github.com/${REPO}.git" <branch-name>
```

### 5. Create the PR via the App token

```bash
GH_TOKEN="$TOKEN" gh pr create \
  --base main \
  --head <branch-name> \
  --title "<title>" \
  --body "<body>"
```

Using `GH_TOKEN` env var overrides the user's `gh auth` for that single command.

## One-liner reference

```bash
TOKEN=$(uv run python3 scripts/gh_app_token.py) && \
  REPO=$(git config --get remote.origin.url | sed -E 's#.*github.com[:/](.*)\.git#\1#') && \
  git push "https://x-access-token:${TOKEN}@github.com/${REPO}.git" "$(git branch --show-current)" && \
  GH_TOKEN="$TOKEN" gh pr create --base main --head "$(git branch --show-current)" \
    --title "PR title" --body "PR body"
```

## Notes

- The App token is short-lived (~1 hour) — always generate fresh before pushing
- The `.pem` private key is gitignored (`*.pem` in `.gitignore`)
- `scripts/gh_app_token.py` reads credentials from `.env` via `python-dotenv`
- The PR will show as authored by **tars-bot-01[bot]** in GitHub
