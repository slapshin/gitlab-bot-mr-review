# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a GitLab CI/CD script that automatically reviews merge requests using Claude AI. The script runs in GitLab CI pipelines, fetches MR changes, analyzes them with Claude, and posts review comments back to the MR.

## Architecture

**Single Python script** (`claude_review.py`):

- Runs in GitLab CI/CD pipeline triggered by merge request events
- Direct integration with GitLab API (via python-gitlab) and Anthropic API (via anthropic SDK)
- Workflow: Load .claude/ context → Fetch MR diff → Analyze with Claude → Post review comment

**Key functions**:

- `load_claude_context()`: Loads CLAUDE.md and .claude/ configuration files from the local filesystem for context-aware reviews
- `get_mr_diff(project, mr_iid)`: Fetches diff data from GitLab API
- `build_prompt(mr, diff_text, claude_context)`: Constructs the review prompt with project rules
- `main()`: Orchestrates the review process using CI environment variables

**Claude integration**: Uses `claude-sonnet-4-5-20250929` (Sonnet 4.5) model by default (configurable via `CLAUDE_MODEL` env var) with a structured prompt that incorporates project-specific rules from .claude/ configuration.

## Environment Configuration

Required environment variables (provided by GitLab CI):

- `CI_SERVER_URL`: GitLab instance URL
- `CI_PROJECT_ID`: Project ID
- `CI_MERGE_REQUEST_IID`: Merge request IID
- `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME`: Source branch name
- `GITLAB_TOKEN`: GitLab personal access token with API access (set in CI/CD settings)
- `ANTHROPIC_API_KEY`: Anthropic API key (set in CI/CD settings)

Optional environment variables:

- `CLAUDE_MODEL`: Claude model to use (default: `claude-sonnet-4-5-20250929`)
- `MAX_DIFF_CHARS`: Maximum diff size to review (default: `100000`)

## Package Management

This project uses **uv** as the package manager for fast, reliable Python dependency management.

### Development Setup

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run the script locally (requires CI env vars)
uv run claude_review.py
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
    - uv run claude_review.py
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
