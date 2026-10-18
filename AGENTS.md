
# Agents.md

## Project Overview

This is a GitLab CI/CD script that automatically reviews merge requests using Claude AI. The script runs in GitLab CI pipelines, fetches MR changes, analyzes them with Claude, and posts review comments back to the MR.

## Architecture

Runs in a GitLab CI/CD pipeline triggered by merge request events.
Workflow: Fetch MR → run the review engine selected by `REVIEW_ENGINE` → Post review note.

**Modules**:

- `review.py`: Entry point (`uv run review.py`) — CI variables, GitLab API (python-gitlab), engine selection via the `ENGINES` map, note posting
- `api_engine.py`: `REVIEW_ENGINE=api` (default) — `load_claude_context()` loads AGENTS.md, CLAUDE.md and .claude/ files, `select_changes()` budgets the diff, `build_prompt()` builds the prompt, `request_review()` calls the Messages API (anthropic SDK)
- `claude_code_engine.py`: `REVIEW_ENGINE=claude-code` — runs `claude -p "/code-review <effort> base..head"` in the CI checkout with read-only tools
- `common.py`: `Review` (note text + footer lines), `ReviewError`, `EFFORT_ORDER`

Engines expose `run(project, mr, payload)` and never talk to GitLab notes; they return a `Review`, `None` (nothing to review), or raise `ReviewError`, which `review.py` posts to the MR. A new engine is a new module plus an `ENGINES` entry.

**Claude integration**: Uses `claude-sonnet-4-6` (Sonnet 4.6) model by default (configurable via `CLAUDE_MODEL` env var) with a structured prompt that incorporates project-specific rules from .claude/ configuration.

## Environment Configuration

Required environment variables (provided by GitLab CI):

- `CI_SERVER_URL`: GitLab instance URL
- `CI_PROJECT_ID`: Project ID
- `CI_MERGE_REQUEST_IID`: Merge request IID
- `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME`: Source branch name
- `GITLAB_TOKEN`: GitLab personal access token with API access (set in CI/CD settings)
- `ANTHROPIC_API_KEY`: Anthropic API key (set in CI/CD settings)

Optional environment variables:

- `CLAUDE_MODEL`: Claude model to use (default: `claude-sonnet-4-6`)
- `MAX_DIFF_CHARS`: Maximum diff size to review (default: `100000`)

## Context Loading

The `load_claude_context()` function reads configuration files from the local filesystem to provide context-aware reviews:

**Files loaded (in order):**

1. `CLAUDE.md` (root level)
2. `.claude/CLAUDE.md`
3. `.claude/settings.json`
4. All other files in `.claude/` directory (recursively)

All loaded files are concatenated and included in the review prompt, allowing Claude to follow project-specific rules, conventions, and guidelines defined in your repository.

**Implementation details:**

- Uses Python's `pathlib` for filesystem operations
- Gracefully handles missing files with warnings
- Reads files with UTF-8 encoding
- Skips binary files automatically (will fail to decode and continue)

## Package Management

This project uses **uv** as the package manager for fast, reliable Python dependency management.

### Development Setup

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run the script locally (requires CI env vars)
uv run review.py
```

### Dependencies

Managed in `pyproject.toml`:

- `anthropic`: Claude API client
- `python-gitlab`: GitLab API client
- `pyyaml`: YAML parsing (for potential config files)

## GitLab CI Setup

Add to your `.gitlab-ci.yml`:

```yaml
claude_review:
  image: ghcr.io/astral-sh/uv:python3.12-bookworm-slim
  script:
    - uv run review.py
  only:
    - merge_requests
  variables:
    GITLAB_TOKEN: $GITLAB_TOKEN
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

## Docker Deployment

The Dockerfile uses the official uv image for efficient builds:

```bash
# Build locally
docker build -t gitlab-mr-reviewer .

# Run (requires CI env vars)
docker run --env-file .env gitlab-mr-reviewer

# Use pre-built image from GitHub Container Registry
docker pull ghcr.io/<username>/gitlab-bot-mr-review:main
```

### GitHub Actions CI/CD

The project includes a GitHub Actions workflow (`.github/workflows/docker-build.yml`) that automatically:

- Builds the Docker image on push to `main` branch
- Publishes to GitHub Container Registry (ghcr.io)
- Creates tagged versions for semantic version tags (e.g., `v1.0.0`)
- Uses Docker layer caching for faster builds
- Runs build validation on pull requests (without publishing)

The workflow is triggered by:

- Pushes to `main` branch
- Git tags matching `v*` pattern (e.g., `v1.0.0`)
- Pull requests to `main` (build only, no push)

Built images are published to: `ghcr.io/<username>/gitlab-bot-mr-review:<tag>`

## Notable Implementation Details

- Loads .claude/ configuration from local filesystem (checked out by GitLab runner)
- Truncates diffs larger than MAX_DIFF_CHARS to prevent token limit issues
- Review comments are branded with 🤖 emoji as "Claude Code Review"
- Gracefully handles missing .claude/ configuration
- Uses CI_JOB_TOKEN as fallback if GITLAB_TOKEN is not provided
