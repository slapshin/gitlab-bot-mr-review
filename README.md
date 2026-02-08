# GitLab MR Review Bot

Automated merge request reviewer powered by Claude AI that runs in GitLab CI/CD pipelines.

## Features

- 🤖 **AI-Powered Reviews**: Uses Claude Sonnet 4.5 for intelligent code review
- 📋 **Context-Aware**: Loads project-specific rules from `.claude/` configuration
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
    - uv run claude_review.py
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
uv run claude_review.py
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

- `CLAUDE_MODEL`: Claude model to use (default: `claude-sonnet-4-5-20250929`)
- `MAX_DIFF_CHARS`: Maximum diff size to review (default: `100000`)

### Project-Specific Rules

Create `.claude/CLAUDE.md` in your repository to define project-specific review guidelines:

```markdown
# Project Review Guidelines

## Code Style
- Use snake_case for Python functions
- Maximum line length: 88 characters

## Testing Requirements
- All new features must include tests
- Maintain 80% code coverage
```

The bot will automatically load and follow these rules when reviewing merge requests.

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

The bot is a single Python script that:

1. **Loads Context**: Reads `.claude/` configuration from the source branch
2. **Fetches Diff**: Retrieves merge request changes via GitLab API
3. **AI Review**: Analyzes code with Claude AI using project-specific rules
4. **Posts Comment**: Adds review as an MR comment with 🤖 branding

### Key Components

- `load_claude_context()`: Loads project rules from `.claude/` directory
- `get_mr_diff()`: Fetches diff data from GitLab API
- `build_prompt()`: Constructs review prompt with context
- `main()`: Orchestrates the review workflow

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
