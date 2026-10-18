FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.302

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# git and the Claude Code CLI back REVIEW_ENGINE=claude-code.
# The CI checkout may be owned by another uid, so trust every directory.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*' \
    && curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_CODE_VERSION}" \
    && install -m 0755 "$(readlink -f /root/.local/bin/claude)" /usr/local/bin/claude \
    && rm -rf /root/.local/bin/claude /root/.local/share/claude

ENV DISABLE_AUTOUPDATER=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY review.py common.py api_engine.py claude_code_engine.py ./

ENTRYPOINT ["uv", "run", "/app/review.py"]
