FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --frozen --no-dev

COPY claude_review.py ./

ENTRYPOINT ["uv", "run", "claude_review.py"]