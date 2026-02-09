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

    return f"""You are a senior software engineer conducting a thorough code review. Analyze this merge request carefully and provide constructive feedback.

{context_block}## Review Guidelines

### 1. Code Quality
- **Readability**: Is the code clear, well-structured, and easy to understand?
- **Naming**: Are variables, functions, and classes named descriptively?
- **Complexity**: Are functions/methods too complex? Should they be broken down?
- **DRY Principle**: Is there unnecessary code duplication?
- **Comments**: Are complex logic sections documented? Are comments helpful and up-to-date?
- **Dead Code**: Are there unused imports, variables, or commented-out code blocks?

### 2. Best Practices & Patterns
- **Design Patterns**: Are appropriate design patterns used correctly?
- **SOLID Principles**: Does the code follow Single Responsibility, Open/Closed, etc.?
- **Error Handling**: Are errors handled gracefully? Are edge cases covered?
- **Resource Management**: Are resources (files, connections, memory) properly managed?
- **Idiomatic Code**: Does the code follow language-specific conventions and idioms?
- **Testing**: Are there adequate tests? Do tests cover edge cases?

### 3. Security
- **Input Validation**: Are all inputs validated and sanitized?
- **Authentication/Authorization**: Are access controls properly implemented?
- **Sensitive Data**: Are secrets, passwords, or API keys hardcoded? Are they logged?
- **SQL Injection**: Are database queries parameterized?
- **XSS/CSRF**: Are web vulnerabilities addressed?
- **Dependencies**: Are dependencies up-to-date and from trusted sources?
- **Data Exposure**: Is sensitive information properly encrypted/protected?

### 4. Performance
- **Efficiency**: Are there obvious performance bottlenecks (N+1 queries, unnecessary loops)?
- **Scalability**: Will this code handle increased load?
- **Resource Usage**: Are memory and CPU usage optimized?
- **Caching**: Should results be cached?

### 5. Maintainability
- **Modularity**: Is the code properly organized into functions/classes/modules?
- **Coupling**: Are components loosely coupled?
- **Documentation**: Is there sufficient documentation for complex features?
- **Backwards Compatibility**: Does this break existing functionality?
- **Configuration**: Are magic numbers/strings extracted to constants/config?

### 6. Additional Checks
- **Logging**: Is appropriate logging in place for debugging and monitoring?
- **Internationalization**: Is hardcoded text externalized if needed?
- **Accessibility**: For UI changes, are accessibility standards met?
- **API Design**: Are APIs consistent, RESTful, and well-documented?
- **Database**: Are migrations needed? Are indexes appropriate?

## Review Instructions

1. **Follow project-specific rules above** - These take precedence over general guidelines
2. **Be specific** - Reference exact file paths and line numbers (e.g., `user_service.py:45`)
3. **Prioritize issues** - Focus on critical security/correctness issues first
4. **Be constructive** - Suggest solutions, not just problems
5. **Acknowledge good practices** - Mention what was done well
6. **Be concise** - Keep feedback clear and actionable

## Output Format

Structure your review as follows:

**Summary**: Brief overall assessment (2-3 sentences)

**Critical Issues** (if any):
- [Issue with file:line reference and explanation]

**Major Issues** (if any):
- [Issue with file:line reference and explanation]

**Minor Issues/Suggestions** (if any):
- [Issue with file:line reference and explanation]

**Positive Observations** (if any):
- [What was done well]

**Recommendation**: APPROVE / REQUEST CHANGES / COMMENT

---

## Merge Request Details

**Title**: {mr.title}
**Description**: {mr.description or 'N/A'}

## Code Changes

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
