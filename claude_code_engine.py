# Review engine that runs the Claude Code CLI's built-in /code-review skill
# against the merge request's commit range in the checked-out repository.
import json
import os
import subprocess
from pathlib import Path

from common import EFFORT_ORDER, Review, ReviewError

# Read-only tools: the review may explore the repository, never modify it.
ALLOWED_TOOLS = ",".join(
    [
        "Read",
        "Grep",
        "Glob",
        "Agent",
        "Bash(git diff:*)",
        "Bash(git log:*)",
        "Bash(git show:*)",
        "Bash(git blame:*)",
    ]
)


def ensure_commit(project_dir, sha):
    """Fetch a commit missing from a shallow CI clone so the range can be diffed."""
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=project_dir,
        capture_output=True,
    )
    if present.returncode == 0:
        return

    print(f"Commit {sha} not in clone, fetching it")
    fetched = subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=1", "origin", sha],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if fetched.returncode != 0:
        raise ReviewError(
            f"Could not fetch commit `{sha}`: {fetched.stderr.strip()}. "
            "Set `GIT_DEPTH: 0` on the review job."
        )


def resolve_effort():
    """Read ANTHROPIC_REVIEW_EFFORT, the level passed to /code-review."""
    requested = os.getenv("ANTHROPIC_REVIEW_EFFORT", "high").strip().lower()
    if requested in EFFORT_ORDER:
        return requested
    print(f"Warning: unknown ANTHROPIC_REVIEW_EFFORT={requested!r}, using 'high'")
    return "high"


def run_review(project_dir, base_sha, head_sha, effort, model, budget_usd, timeout):
    """Run /code-review on base..head and return (review text, cost in USD)."""
    ensure_commit(project_dir, base_sha)
    ensure_commit(project_dir, head_sha)

    # diff_refs.base_sha is already the merge base, so a two-dot range is exact
    # and, unlike three-dot, works in a shallow clone.
    target = f"{base_sha}..{head_sha}"
    command = [
        "claude",
        "-p",
        f"/code-review {effort} {target}",
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        ALLOWED_TOOLS,
        "--max-budget-usd",
        str(budget_usd),
    ]
    if model:
        command += ["--model", model]
    # Claude Code loads CLAUDE.md on its own but not the AGENTS.md convention.
    agents_md = Path(project_dir) / "AGENTS.md"
    if agents_md.is_file() and not (Path(project_dir) / "CLAUDE.md").exists():
        print("Appending AGENTS.md to the Claude Code system prompt")
        command += ["--append-system-prompt-file", str(agents_md)]

    print(f"Running Claude Code /code-review {effort} on {target}")
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise ReviewError("The `claude` CLI is not installed in this image.")
    except subprocess.TimeoutExpired:
        raise ReviewError(f"Claude Code review timed out after {timeout}s.")

    if completed.stderr.strip():
        print(completed.stderr.strip())

    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise ReviewError(
            f"Claude Code exited with code {completed.returncode} without a JSON result."
        )

    cost = result.get("total_cost_usd") or 0.0
    if result.get("is_error") or result.get("subtype") != "success":
        reason = result.get("result") or result.get("subtype") or "unknown error"
        raise ReviewError(f"Claude Code review did not finish: {reason}")
    # CLI-level messages such as "Not logged in" come back as a successful
    # result; only a run that actually called a model produced a review.
    if not result.get("modelUsage"):
        reason = result.get("result") or "no model was called"
        raise ReviewError(f"Claude Code did not run a review: {reason}")

    review = (result.get("result") or "").strip()
    if not review:
        raise ReviewError("Claude Code returned an empty review.")
    return review, cost


def run(project, mr, payload):
    """Review the MR with /code-review in the CI checkout.

    Claude Code loads the project's CLAUDE.md and .claude/ rules itself and
    explores the checked-out repository, so no diff or context is built here.
    """
    diff_refs = payload.get("diff_refs") or {}
    base_sha = diff_refs.get("base_sha") or os.getenv("CI_MERGE_REQUEST_DIFF_BASE_SHA")
    head_sha = diff_refs.get("head_sha") or os.getenv("CI_COMMIT_SHA")
    if not base_sha or not head_sha:
        raise ReviewError("Could not resolve the MR base and head commits.")

    effort = resolve_effort()
    # Unset means the Claude Code default model, not the API engine's default.
    model = os.getenv("ANTHROPIC_REVIEW_MODEL", "").strip()
    budget = float(os.getenv("CLAUDE_CODE_MAX_BUDGET_USD", "5"))
    timeout = int(os.getenv("CLAUDE_CODE_TIMEOUT_SECONDS", "1800"))

    review, cost = run_review(
        os.getenv("CI_PROJECT_DIR", "."), base_sha, head_sha, effort, model, budget, timeout
    )
    print(f"Claude Code review cost: ${cost:.2f}")

    config_parts = ["Engine: Claude Code `/code-review`", f"effort: `{effort}`"]
    if model:
        config_parts.append(f"model: `{model}`")
    config_parts.append(f"commit: `{head_sha[:8]}`")
    config_parts.append(f"cost: ${cost:.2f}")
    return Review(review, [" · ".join(config_parts)])
