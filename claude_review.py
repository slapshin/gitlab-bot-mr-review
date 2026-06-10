# scripts/claude_review.py
import os
import gitlab
import anthropic
from pathlib import Path


# Standard .claude paths that Claude Code uses
CLAUDE_MD_PATHS = [
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    ".claude/settings.json",
]


def load_claude_context():
    """Load CLAUDE.md and .claude/ config files from local filesystem."""
    context_parts = []

    # Get the project directory from GitLab CI environment
    project_dir = Path(os.getenv("CI_PROJECT_DIR", "."))
    print(f"Loading context from project directory: {project_dir}")

    # Load standard paths
    for path in CLAUDE_MD_PATHS:
        file_path = project_dir / path
        if file_path.exists() and file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8")
                print(f"Added file {path} content to context")
                context_parts.append(f"--- {path} ---\n{content}")
            except Exception as e:
                print(f"Warning: Could not read {path}: {e}")
                continue

    # Load all other files in .claude/ directory
    claude_dir = project_dir / ".claude"
    if claude_dir.exists() and claude_dir.is_dir():
        for file_path in claude_dir.rglob("*"):
            if file_path.is_file():
                # Get relative path from project directory
                rel_path = str(file_path.relative_to(project_dir))
                # Skip already loaded files
                if rel_path in CLAUDE_MD_PATHS:
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                    print(f"Added file {rel_path} content to context")
                    context_parts.append(f"--- {rel_path} ---\n{content}")
                except Exception as e:
                    print(f"Warning: Could not read {rel_path}: {e}")
                    continue

    return "\n\n".join(context_parts)


def get_mr_diff(project, mr_iid):
    mr = project.mergerequests.get(mr_iid)
    changes = mr.changes()["changes"]

    diff_parts = []
    for c in changes:
        diff_parts.append(f"--- {c['old_path']}\n+++ {c['new_path']}\n{c['diff']}")

    return mr, "\n".join(diff_parts)


def build_prompt(mr, diff_text, claude_context):
    context_block = ""
    if claude_context:
        context_block = f"""
## Project-Specific Rules

The following are the project's CLAUDE.md and .claude/ configuration files.
These contain project rules, conventions, and instructions you MUST follow when reviewing:

{claude_context}

--- End of project rules ---

"""

    system_content = f"""You are a senior software engineer conducting a code review of a merge request. Focus your review on the actual changes in the diff — do not comment on unchanged code or hypothetical issues outside the scope of the MR.

{context_block}## What to Look For

Focus on issues that **actually appear in the diff**. Prioritize by impact:

1. **Correctness** — Bugs, logic errors, off-by-one errors, race conditions, unhandled edge cases
2. **Security** — Injection vulnerabilities, hardcoded secrets, missing input validation, data exposure
3. **Error handling** — Unhandled exceptions, swallowed errors, missing cleanup/resource management
4. **Performance** — Obvious bottlenecks only (N+1 queries, unnecessary allocations in hot paths)
5. **Code quality** — Unclear naming, unnecessary complexity, code duplication, dead code
6. **Idiomatic code** — Language-specific conventions and best practices

**Skip items that don't apply.** Do not force feedback on every category. A clean diff with no issues is a valid outcome.

## Review Principles

- **Be specific** — Reference exact file paths and line numbers (e.g., `user_service.py:45`)
- **Suggest fixes** — Show what the improved code should look like when possible
- **Don't nitpick** — Ignore trivial style preferences, minor formatting, or subjective naming unless it hurts readability
- **Respect intent** — Understand what the author is trying to achieve before criticizing the approach
- **Project rules take precedence** — If project-specific rules above conflict with general guidelines, follow the project rules

## Output Format

Structure your review with these sections. **Omit any section that has no items** — do not include empty sections.

**Summary**: 2-3 sentence overall assessment of the changes.

**Critical Issues**: Bugs, security vulnerabilities, data loss risks — must be fixed before merging.
- `file:line` — Description and suggested fix

**Suggestions**: Improvements worth considering but not blocking.
- `file:line` — Description and suggested fix

**Nits**: Minor observations, take-or-leave.
- `file:line` — Description

**What's Done Well**: Notable good practices in the changes (only if genuinely notable).

**Verdict**: One of the following:
- **APPROVE** — Changes are correct and ready to merge (may have minor nits)
- **APPROVE WITH SUGGESTIONS** — No blocking issues, but suggestions would improve the code
- **REQUEST CHANGES** — Has critical issues or bugs that must be addressed before merging"""

    user_content = f"""## Merge Request Details

**Title**: {mr.title}
**Description**: {mr.description or "N/A"}

## Code Changes

{diff_text}"""

    return system_content, user_content


def main():
    gitlab_url = os.environ["CI_SERVER_URL"]
    project_id = os.environ["CI_PROJECT_ID"]
    mr_iid = os.environ["CI_MERGE_REQUEST_IID"]
    # Try GITLAB_TOKEN first, fallback to CI_JOB_TOKEN
    gitlab_token = os.getenv("GITLAB_TOKEN") or os.environ["CI_JOB_TOKEN"]

    gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_token)
    project = gl.projects.get(project_id)

    # Load .claude/ context from local filesystem
    claude_context = load_claude_context()
    if claude_context:
        print(f"Loaded .claude/ context ({len(claude_context)} chars)")
    else:
        print("No .claude/ config found, reviewing without project rules")

    mr, diff_text = get_mr_diff(project, mr_iid)

    if not diff_text.strip():
        print("No changes to review")
        return

    max_chars = int(os.getenv("MAX_DIFF_CHARS", "100000"))
    if len(diff_text) > max_chars:
        diff_text = diff_text[:max_chars] + "\n\n... (diff truncated)"

    system_content, user_content = build_prompt(mr, diff_text, claude_context)

    # Initialize Anthropic client with API key from environment
    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = anthropic.Anthropic(api_key=api_key)
    model = os.getenv("CLAUDE_REVIEW_MODEL", "claude-sonnet-4-6")

    print(f"Model used for review: {model}")

    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": system_content,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    usage = msg.usage
    print(f"Tokens - input: {usage.input_tokens}, output: {usage.output_tokens}")
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    if cache_write:
        print(f"Cache write tokens: {cache_write}")
    if cache_read:
        print(f"Cache read tokens: {cache_read}")

    token_parts = [
        f"input: {usage.input_tokens}",
        f"output: {usage.output_tokens}",
    ]
    if cache_write:
        token_parts.append(f"cache write: {cache_write}")
    if cache_read:
        token_parts.append(f"cache read: {cache_read}")
    token_summary = ", ".join(token_parts)

    review = msg.content[0].text
    footer = f"\n\n---\n_Model: `{model}` · Tokens — {token_summary}_"
    mr.notes.create({"body": f"🤖 **Claude Code Review**\n\n{review}{footer}"})
    print("Review posted successfully.")


if __name__ == "__main__":
    main()
