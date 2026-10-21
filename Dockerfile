FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Claude Code baked into the image: a release (e.g. 2.1.302) or a channel.
# The claude-code engine still updates it before each review unless the job
# pins CLAUDE_CODE_VERSION, so this only sets the starting point.
ARG CLAUDE_CODE_VERSION=latest

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# git and the Claude Code CLI back REVIEW_ENGINE=claude-code.
# The CI checkout may be owned by another uid, so trust every directory.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_CODE_VERSION}" \
    && install -m 0755 "$(readlink -f /root/.local/bin/claude)" /usr/local/bin/claude \
    && rm -rf /root/.local/bin/claude /root/.local/share/claude

ENV DISABLE_AUTOUPDATER=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY review.py common.py api_engine.py claude_code_engine.py ./

# Bot build identity shown in every MR note, set by the image build workflow.
ARG BOT_VERSION=dev
ARG BOT_COMMIT=unknown
ENV BOT_VERSION=${BOT_VERSION} BOT_COMMIT=${BOT_COMMIT}

ENTRYPOINT ["uv", "run", "/app/review.py"]
