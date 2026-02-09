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

    # Load standard paths
    for path in CLAUDE_MD_PATHS:
        file_path = Path(path)
        if file_path.exists() and file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8")
                print(f"added file {file_path} content to context")

                context_parts.append(f"--- {path} ---\n{content}")
            except Exception as e:
                print(f"Warning: Could not read {path}: {e}")
                continue

    # Load all other files in .claude/ directory
    claude_dir = Path(".claude")
    if claude_dir.exists() and claude_dir.is_dir():
        for file_path in claude_dir.rglob("*"):
            if file_path.is_file():
                rel_path = str(file_path)
                # Skip already loaded files
                if rel_path in CLAUDE_MD_PATHS:
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")

                    print(f"added file {file_path} content to context")
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
The following are the project's CLAUDE.md and .claude/ configuration files.
These contain project rules, conventions, and instructions you MUST follow when reviewing:

{claude_context}

--- End of project rules ---
"""

    return f"""You are a senior code reviewer.
{context_block}
Review this merge request diff. Follow ALL rules and conventions defined above.
Be concise. Reference specific files and line numbers.
If the code looks good, say so briefly.

MR Title: {mr.title}
MR Description: {mr.description or 'N/A'}

Diff:
{diff_text}"""


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

    prompt = build_prompt(mr, diff_text, claude_context)

    # Initialize Anthropic client with API key from environment
    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = anthropic.Anthropic(api_key=api_key)
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    review = msg.content[0].text
    mr.notes.create({"body": f"🤖 **Claude Code Review**\n\n{review}"})
    print("Review posted successfully.")


if __name__ == "__main__":
    main()
