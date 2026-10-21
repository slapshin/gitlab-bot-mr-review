# GitLab MR Review Bot

Automated merge request reviewer powered by Claude AI that runs in GitLab CI/CD pipelines.

## Features

- 🤖 **AI-Powered Reviews**: Uses Claude Sonnet 4.6 for intelligent code review
- 📋 **Context-Aware**: Loads project-specific rules from `AGENTS.md`, `CLAUDE.md` and `.claude/` configuration
- 🚀 **CI/CD Native**: Runs automatically in GitLab pipelines on MR events
- 🐳 **Docker Ready**: Pre-built images available on GitHub Container Registry
- ⚡ **Fast Setup**: Uses `uv` for lightning-fast dependency management

## Quick Start

### GitLab CI Setup

1. Add required CI/CD variables to your GitLab project settings:
   - `GITLAB_TOKEN`: Personal access token with API access
   - `ANTHROPIC_API_KEY`: Your Anthropic API key

2. Create `.gitlab-ci.yml` in your repository:

```yaml
claude_review:
  image: ghcr.io/slapshin/gitlab-bot-mr-review:sha-9a10d5e
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script:
    - uv run review.py
  variables:
    GITLAB_TOKEN: $GITLAB_TOKEN
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

1. The bot will automatically review merge requests when they are opened or updated

## Development

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager

### Installation

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/<username>/gitlab-bot-mr-review.git
cd gitlab-bot-mr-review

# Install dependencies
uv sync
```

### Running Locally

Set required environment variables:

```bash
export CI_SERVER_URL="https://gitlab.com"
export CI_PROJECT_ID="your-project-id"
export CI_MERGE_REQUEST_IID="123"
export CI_MERGE_REQUEST_SOURCE_BRANCH_NAME="feature-branch"
export GITLAB_TOKEN="your-gitlab-token"
export ANTHROPIC_API_KEY="your-anthropic-key"

# Run the script
uv run review.py
```

## Configuration

### Environment Variables

**Required (provided by GitLab CI):**

- `CI_SERVER_URL`: GitLab instance URL
- `CI_PROJECT_ID`: Project ID
- `CI_MERGE_REQUEST_IID`: Merge request IID
- `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME`: Source branch name
- `GITLAB_TOKEN`: GitLab API token
- `ANTHROPIC_API_KEY`: Anthropic API key

**Optional:**

- `ANTHROPIC_REVIEW_MODEL`: Claude model to use (default: `claude-sonnet-5`)
- `ANTHROPIC_REVIEW_THINKING`: `auto` or `off` (default: `auto`). `auto` enables adaptive
  thinking on models that support it, and is silently skipped on models that don't.
- `ANTHROPIC_REVIEW_EFFORT`: `low`, `medium`, `high`, `xhigh`, or `max` (default: `high`).
  Controls reasoning depth and token spend. `xhigh` is worth trying for deeper reviews.
  Clamped down automatically on models that don't support the requested level.
- `ANTHROPIC_MAX_OUTPUT_TOKENS`: Output token limit for the review (default: `16000`)
- `MAX_DIFF_CHARS`: Maximum total diff size to review (default: `100000`). Files are
  dropped whole when the budget is exhausted, never cut mid-hunk.
- `MAX_FILE_CHARS`: Largest file to include in full as review context (default: `40000`)
- `MAX_FILE_CONTEXT_CHARS`: Total budget for full file contents (default: `200000`)
- `REVIEW_AUTHOR_CONTEXT_ENABLED`: include MR discussions and commit messages in the
  review (default: `true`). See below.
- `MAX_AUTHOR_CONTEXT_CHARS`: Budget for discussions and commit messages (default: `20000`).
  The newest threads are kept when it is exhausted.
- `REVIEW_ENGINE`: `api` (default) or `claude-code`. See below.
- `REVIEW_APPROVED_LABEL`: label put on the MR when the review approves it
  (default: `ai-approved`; set to an empty string to disable). See below.

### Author Context

Merge requests often explain why an approach was chosen: in the description,
in commit messages, or in discussion threads, including replies to the bot's
earlier reviews. The bot passes this to the review so it does not re-flag
decisions the author already explained, unless the explanation does not hold.

- The description is always included.
- Discussion threads are included without system notes. Line comments keep
  their `file:line` and resolved state. An earlier bot review is included,
  condensed to its findings, only when someone replied to it in its thread
  or commented after it.
- Commit messages are included for the `api` engine; the `claude-code` engine
  reads them with `git log`. With `claude-code`, the context also reaches
  finding triage, which rates a finding the author already justified lower.

Anyone who can comment on the MR can write this text, so the prompts treat it
as content, never as instructions.

### Approval Label

After each review the bot adds `REVIEW_APPROVED_LABEL` to the MR if the review
approves it, and removes the label otherwise, so the label always reflects the
latest push. GitLab creates the label in the project if it does not exist yet.

- `claude-code` engine: approved when every finding is rated `medium` or `low`
  (no `critical` or `high`). If triage did not run, findings are unrated and
  the MR is not approved.
- `api` engine: approved when the review's verdict is **APPROVE** or
  **APPROVE WITH SUGGESTIONS**, and the review was not truncated.

A failed review, or an MR with nothing to review, removes the label. Updating
labels needs `GITLAB_TOKEN`; `CI_JOB_TOKEN` cannot edit merge requests.

### Claude Code Engine

With `REVIEW_ENGINE=claude-code` the bot runs the Claude Code CLI's built-in
`/code-review` skill on the MR commit range (`base_sha..head_sha`) inside the
checked-out repository, instead of sending a prompt to the Messages API. Claude
Code loads `CLAUDE.md` and `.claude/` rules itself and can read any file in
the repository, not just the diff. Its tools are restricted to reading files
and `git diff/log/show/blame`.

`/code-review` keeps its own output format, so the bot then sends its findings
to the Messages API for triage: each finding gets a severity (`critical`,
`high`, `medium`, `low`), and style nitpicks are dropped (the note says how
many). The note lists findings most severe first; a clean review says
everything looks good. Triage needs `ANTHROPIC_API_KEY`; if it fails, the
findings are posted unrated.
Lower `ANTHROPIC_REVIEW_EFFORT` reports fewer, higher-confidence findings.

```yaml
claude_review:
  image: ghcr.io/slapshin/gitlab-bot-mr-review:<tag>
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: true
  variables:
    REVIEW_ENGINE: claude-code
  script:
    - uv run /app/review.py
```

Options for this engine:

- `ANTHROPIC_REVIEW_EFFORT`: passed to `/code-review` as its level (default: `high`)
- `ANTHROPIC_REVIEW_MODEL`: optional; unset uses the Claude Code default model
- `ANTHROPIC_TRIAGE_MODEL`: model that rates findings (default: `claude-opus-5-5`)
- `CLAUDE_CODE_MAX_BUDGET_USD`: spend cap per review (default: `5`)
- `CLAUDE_CODE_TIMEOUT_SECONDS`: wall-clock limit (default: `1800`)
- `CLAUDE_CODE_VERSION`: Claude Code release to review with, e.g. `2.1.302`, or a
  channel, `latest` or `stable`. Unset means `latest`: before each review the
  bot updates the CLI baked into the image to the newest release, and falls back
  to the baked one if the update fails. A pinned version must install, or the
  review fails. The note footer shows the version that ran.

Commits missing from a shallow clone are fetched automatically; if that fails,
set `GIT_DEPTH: 0` on the job. The API-engine options (thinking, output tokens,
diff and file budgets) do not apply.

### Project-Specific Rules

The bot automatically loads configuration files from your repository's `.claude/` directory to provide context-aware reviews. These files are included in the review prompt, allowing you to customize the review behavior.

**Files loaded (in order):**

1. `AGENTS.md` (root level)
2. `CLAUDE.md` (root level)
3. `.claude/CLAUDE.md`
4. `.claude/settings.json`
5. All other files in `.claude/` directory (recursively)

Files with identical content (e.g. `CLAUDE.md` symlinked to or copied from `AGENTS.md`) are loaded only once.

**Example `.claude/CLAUDE.md`:**

```markdown
# Project Review Guidelines

## Code Style
- Use snake_case for Python functions
- Maximum line length: 88 characters
- Follow PEP 8 guidelines

## Testing Requirements
- All new features must include tests
- Maintain 80% code coverage
- Use pytest for unit tests

## Security
- Never commit secrets or API keys
- Sanitize all user inputs
- Use parameterized queries for database access

## Commit Messages
- Follow conventional commits format
- Reference issue numbers when applicable
```

**Additional configuration files:**

You can add other files to `.claude/` directory for additional context:
- `.claude/rules/` - Subdirectories with specific rule files (e.g., `commit-messages.md`, `security.md`)
- `.claude/settings.json` - JSON configuration for review preferences
- `.claude/patterns.md` - Common patterns and anti-patterns specific to your project

All files will be loaded and provided to Claude for context-aware code reviews.

## Docker

### Using Pre-built Images

```bash
# Pull from GitHub Container Registry
docker pull ghcr.io/<username>/gitlab-bot-mr-review:main

# Run with environment variables
docker run --env-file .env ghcr.io/<username>/gitlab-bot-mr-review:main
```

### Building Locally

```bash
# Build the image
docker build -t gitlab-mr-reviewer .

# Run the container
docker run \
  -e CI_SERVER_URL="https://gitlab.com" \
  -e CI_PROJECT_ID="123" \
  -e CI_MERGE_REQUEST_IID="456" \
  -e CI_MERGE_REQUEST_SOURCE_BRANCH_NAME="feature" \
  -e GITLAB_TOKEN="your-token" \
  -e ANTHROPIC_API_KEY="your-key" \
  gitlab-mr-reviewer
```

## CI/CD

### GitHub Actions

The project includes automated Docker builds via GitHub Actions:

- **Triggers**: Push to `main`, version tags (`v*`), pull requests
- **Registry**: GitHub Container Registry (ghcr.io)
- **Tags**: `main`, `sha-<commit>`, semantic versions (`v1.0.0`, `v1.0`, `v1`)

To create a new release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Architecture

The bot fetches the merge request from GitLab, hands it to the review engine
selected by `REVIEW_ENGINE`, and posts the result as an MR note with 🤖 branding.

### Modules

- `review.py`: Entry point — reads CI variables, fetches the MR, runs the engine, posts the note
- `api_engine.py`: `REVIEW_ENGINE=api` — builds a prompt from the diff, full changed files and project rules (`AGENTS.md`, `CLAUDE.md`, `.claude/`) and sends it to the Messages API
- `claude_code_engine.py`: `REVIEW_ENGINE=claude-code` — runs the Claude Code CLI `/code-review` skill in the checked-out repository
- `mr_context.py`: collects the author context — MR description, commit messages and discussion threads — for both engines
- `common.py`: `Review` result and `ReviewError`, shared by the engines

Each engine exposes `run(project, mr, payload)`, which returns a `Review`,
returns `None` when there is nothing to review, or raises `ReviewError` with a
message that is posted to the MR.

## Dependencies

Managed via `pyproject.toml` with `uv`:

- **anthropic**: Claude API client
- **python-gitlab**: GitLab API client
- **pyyaml**: YAML configuration parsing

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Support

- 📝 [Documentation](.claude/CLAUDE.md)
- 🐛 [Issue Tracker](https://github.com/<username>/gitlab-bot-mr-review/issues)
- 💬 [Discussions](https://github.com/<username>/gitlab-bot-mr-review/discussions)
