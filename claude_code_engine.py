# Review engine that runs the Claude Code CLI's built-in /code-review skill
# against the merge request's commit range in the checked-out repository.
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from common import EFFORT_ORDER, Review, ReviewError

# Each release channel file holds the version it currently points to.
RELEASES_URL = "https://downloads.claude.ai/claude-code-releases"
CHANNELS = ("latest", "stable")

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

# Appended to the Claude Code system prompt for every review.
REVIEW_GUIDANCE = """\
# Merge request review guidance

- Report only problems worth a reviewer's time: bugs, security issues, data
  loss, broken behavior, or clear maintainability hazards. Do not nitpick
  style, formatting, naming, or subjective preferences.
- Do not look for problems just to have something to report. If the change
  is sound, return an empty findings array; that is a good outcome.
- Give every finding a `severity` field, one of:
  - `critical`: security hole, data loss, crash, or breakage in a main flow;
    must be fixed before merging
  - `high`: a real bug with a concrete failure scenario
  - `medium`: an edge-case bug or a risky pattern likely to cause one
  - `low`: a minor issue that is worth fixing but safe to merge as is
"""

# Severity order, most severe first, and the badge shown for each level.
SEVERITY_BADGES = {
    "critical": "🔴 Critical",
    "high": "🟠 High",
    "medium": "🟡 Medium",
    "low": "🔵 Low",
}


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


def installed_version(cli):
    """Return the version of a claude binary, or None when it cannot run."""
    try:
        completed = subprocess.run([cli, "--version"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    # Prints e.g. "2.1.302 (Claude Code)".
    return completed.stdout.split()[0]


def channel_version(channel):
    with urllib.request.urlopen(f"{RELEASES_URL}/{channel}", timeout=10) as response:
        return response.read().decode().strip()


def resolve_cli():
    """Return the claude binary to run, updating it to CLAUDE_CODE_VERSION first.

    An unset CLAUDE_CODE_VERSION follows the latest channel, so every review
    runs the newest release even on an old image. A channel that cannot be
    updated falls back to the image's binary; a pinned version must install.
    """
    target = os.getenv("CLAUDE_CODE_VERSION", "").strip() or "latest"
    current = installed_version("claude")

    wanted = target
    if target in CHANNELS:
        try:
            wanted = channel_version(target)
        except (urllib.error.URLError, OSError) as e:
            print(f"Warning: could not resolve the {target} Claude Code release ({e}); "
                  f"using the image's {current}")
            return "claude"

    if wanted == current:
        print(f"Claude Code {current} is up to date ({target})")
        return "claude"

    print(f"Installing Claude Code {wanted} ({target}), image has {current or 'none'}")
    installed = Path.home() / ".local" / "bin" / "claude"
    try:
        completed = subprocess.run(
            ["claude", "install", wanted], capture_output=True, text=True, timeout=300
        )
        error = completed.stderr.strip() if completed.returncode != 0 else None
    except FileNotFoundError:
        raise ReviewError("The `claude` CLI is not installed in this image.")
    except subprocess.TimeoutExpired:
        error = "install timed out"

    if error is None and installed_version(str(installed)) == wanted:
        return str(installed)

    reason = error or f"{installed} does not report version {wanted}"
    if target in CHANNELS:
        print(f"Warning: could not update Claude Code ({reason}); using the image's {current}")
        return "claude"
    raise ReviewError(f"Could not install pinned Claude Code {target}: {reason}")


def run_review(cli, project_dir, base_sha, head_sha, effort, model, budget_usd, timeout):
    """Run /code-review on base..head and return (review text, cost in USD)."""
    ensure_commit(project_dir, base_sha)
    ensure_commit(project_dir, head_sha)

    # diff_refs.base_sha is already the merge base, so a two-dot range is exact
    # and, unlike three-dot, works in a shallow clone.
    target = f"{base_sha}..{head_sha}"
    command = [
        cli,
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
    appended = [REVIEW_GUIDANCE]
    agents_md = Path(project_dir) / "AGENTS.md"
    if agents_md.is_file() and not (Path(project_dir) / "CLAUDE.md").exists():
        print("Appending AGENTS.md to the Claude Code system prompt")
        appended.append(agents_md.read_text(encoding="utf-8", errors="replace"))

    print(f"Running Claude Code /code-review {effort} on {target}")
    # A file, not an argument: AGENTS.md can exceed the per-argument size limit.
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as prompt_file:
        prompt_file.write("\n\n".join(appended))
        prompt_file.flush()
        command += ["--append-system-prompt-file", prompt_file.name]
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


def parse_findings(review):
    """Return the findings list from /code-review output, or None if it is not JSON.

    In print mode /code-review answers with a JSON array of findings, possibly
    wrapped in a code fence or surrounded by prose.
    """
    start, end = review.find("["), review.rfind("]")
    if start == -1 or end < start:
        return None
    try:
        findings = json.loads(review[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
        return None
    return findings


def severity_of(finding):
    return str(finding.get("severity") or "").strip().lower()


def severity_rank(finding, severities):
    """Sort key: known severities most severe first, unknown ones last."""
    severity = severity_of(finding)
    return severities.index(severity) if severity in severities else len(severities)


def format_findings(findings, web_url, head_sha):
    """Render /code-review findings as Markdown with links to the reviewed commit."""
    if not findings:
        return "✅ Everything looks good, no issues found."

    severities = list(SEVERITY_BADGES)
    findings = sorted(findings, key=lambda f: severity_rank(f, severities))
    counts = [
        f"{sum(severity_of(f) == level for f in findings)} {level}"
        for level in severities
        if any(severity_of(f) == level for f in findings)
    ]
    summary_line = f"Found **{len(findings)}** issue{'s' if len(findings) != 1 else ''}"
    if counts:
        summary_line += f" ({', '.join(counts)})"
    lines = [summary_line + ":"]
    for number, finding in enumerate(findings, 1):
        title = finding.get("short_summary") or finding.get("summary") or "Issue"
        tags = [f"`{tag}`" for tag in (finding.get("category"), finding.get("verdict")) if tag]
        badge = SEVERITY_BADGES.get(severity_of(finding))
        heading = f"### {number}. {badge + ': ' if badge else ''}{title}"
        if tags:
            heading += " · " + " ".join(tags)
        lines += ["", heading]

        path = finding.get("file")
        if path:
            line = finding.get("line")
            location = f"{path}:{line}" if line else path
            anchor = f"#L{line}" if line else ""
            lines.append(f"📄 [`{location}`]({web_url}/-/blob/{head_sha}/{path}{anchor})")

        summary = finding.get("summary")
        if summary and summary != title:
            lines += ["", summary]
        scenario = finding.get("failure_scenario")
        if scenario:
            lines += ["", f"**Failure scenario:** {scenario}"]
    return "\n".join(lines)


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

    cli = resolve_cli()
    version = installed_version(cli)
    review, cost = run_review(
        cli, os.getenv("CI_PROJECT_DIR", "."), base_sha, head_sha, effort, model, budget, timeout
    )
    print(f"Claude Code review cost: ${cost:.2f}")

    findings = parse_findings(review)
    if findings is not None:
        unrated = sum(severity_of(f) not in SEVERITY_BADGES for f in findings)
        if unrated:
            print(f"Warning: {unrated} of {len(findings)} findings have no known severity")
        review = format_findings(findings, project.web_url, head_sha)

    config_parts = [f"Engine: Claude Code {version} `/code-review`", f"effort: `{effort}`"]
    if model:
        config_parts.append(f"model: `{model}`")
    config_parts.append(f"commit: `{head_sha[:8]}`")
    config_parts.append(f"cost: ${cost:.2f}")
    return Review(review, [" · ".join(config_parts)])
