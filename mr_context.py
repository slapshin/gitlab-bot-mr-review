# Collects what the MR author and reviewers wrote about the change — the
# description, commit messages and discussion threads — so the review can
# respect decisions that were already explained instead of re-flagging them.
import os

import gitlab.exceptions

from common import NOTE_HEADER

# Wraps the collected text in prompts; occurrences inside the text are defused
# so a comment cannot close the block early.
CONTEXT_TAG = "author_context"

MAX_NOTE_CHARS = 2000
MAX_COMMIT_MESSAGE_CHARS = 2000
MAX_BOT_NOTE_CHARS = 1500

# Lines of an earlier bot review worth keeping: claude-code finding headings,
# api engine findings and verdicts.
BOT_NOTE_KEPT_PREFIXES = ("### ", "- `", "**Verdict")


def is_enabled():
    value = os.getenv("REVIEW_AUTHOR_CONTEXT_ENABLED", "true").strip().lower()
    return value not in ("0", "false", "no", "off")


def build(mr, include_commits):
    """Return the author context as Markdown, or "" when there is none.

    The description is always included. Commit messages and discussions are
    added when REVIEW_AUTHOR_CONTEXT_ENABLED is on; commits only when the
    engine cannot read git history itself.
    """
    sections = []
    if mr.description and mr.description.strip():
        sections.append(f"### Description\n\n{mr.description.strip()}")

    if is_enabled():
        budget = int(os.getenv("MAX_AUTHOR_CONTEXT_CHARS", "20000"))
        if include_commits:
            commits = format_commits(fetch_commits(mr), budget)
            if commits:
                sections.append(f"### Commit Messages\n\n{commits}")
                budget -= len(commits)
        discussions = format_discussions(fetch_discussions(mr), budget)
        if discussions:
            sections.append(f"### Discussions\n\n{discussions}")

    return defuse("\n\n".join(sections))


def wrap(context):
    """Enclose author context in its tag for a prompt."""
    return f"<{CONTEXT_TAG}>\n{context}\n</{CONTEXT_TAG}>"


def defuse(text):
    return text.replace(f"<{CONTEXT_TAG}", f"<\u200b{CONTEXT_TAG}").replace(
        f"</{CONTEXT_TAG}", f"</\u200b{CONTEXT_TAG}"
    )


def fetch_commits(mr):
    try:
        return list(mr.commits())
    except gitlab.exceptions.GitlabError as e:
        print(f"Warning: could not fetch MR commits: {e}")
        return []


def fetch_discussions(mr):
    try:
        return [d.attributes for d in mr.discussions.list(get_all=True)]
    except gitlab.exceptions.GitlabError as e:
        print(f"Warning: could not fetch MR discussions: {e}")
        return []


def format_commits(commits, budget):
    """List commit messages oldest first, keeping the newest within budget."""
    entries = []
    used = 0
    # GitLab returns MR commits newest first.
    for commit in commits:
        message = (commit.message or "").strip()
        if not message or message.startswith("Merge branch"):
            continue
        entry = f"- `{commit.short_id}` {truncate(message, MAX_COMMIT_MESSAGE_CHARS)}"
        entry = entry.replace("\n", "\n  ")
        if used + len(entry) > budget:
            break
        entries.append(entry)
        used += len(entry) + 1
    entries.reverse()
    return "\n".join(entries)


def format_discussions(discussions, budget):
    """Render discussion threads oldest first, keeping the newest within budget."""
    threads = select_threads(discussions)
    rendered = []
    used = 0
    for _, text in sorted(threads, key=lambda t: t[0], reverse=True):
        if used + len(text) > budget:
            break
        rendered.append(text)
        used += len(text) + 2
    omitted = len(threads) - len(rendered)

    rendered.reverse()
    if omitted:
        rendered.insert(0, f"_{omitted} older thread(s) omitted._")
    return "\n\n".join(rendered)


def select_threads(discussions):
    """Return (last activity, rendered text) for each thread worth showing."""
    all_notes = [n for d in discussions for n in d.get("notes") or []]
    last_human_at = max((n["created_at"] for n in all_notes if is_human_note(n)), default="")
    # The review a later human comment most likely answers.
    answered_bot_notes = [
        n for n in all_notes if is_bot_note(n) and n["created_at"] < last_human_at
    ]
    answered_review = max(answered_bot_notes, key=lambda n: n["created_at"], default=None)

    threads = []
    for discussion in discussions:
        notes = [n for n in discussion.get("notes") or [] if not n.get("system")]
        if not notes:
            continue
        # A bot review alone tells the model nothing new, unless someone
        # answered it, in its thread or in a later comment of their own.
        if notes[0] is answered_review or any(is_human_note(n) for n in notes):
            threads.append((notes[-1]["created_at"], format_thread(notes)))
    return threads


def is_bot_note(note):
    return (note.get("body") or "").startswith(NOTE_HEADER)


def is_human_note(note):
    return not note.get("system") and not is_bot_note(note)


def format_thread(notes):
    heading = "#### Thread"
    position = notes[0].get("position") or {}
    path = position.get("new_path") or position.get("old_path")
    if path:
        line = position.get("new_line") or position.get("old_line")
        heading += f" on `{path}:{line}`" if line else f" on `{path}`"
    if notes[0].get("resolvable"):
        heading += " · resolved" if all(n.get("resolved") for n in notes) else " · open"

    lines = [heading]
    for note in notes:
        body = note.get("body") or ""
        if is_bot_note(note):
            lines.append(f"**review bot (earlier review, condensed)**:\n{condense_bot_note(body)}")
        else:
            author = (note.get("author") or {}).get("username", "unknown")
            lines.append(f"**@{author}**: {truncate(body.strip(), MAX_NOTE_CHARS)}")
    return "\n\n".join(lines)


def condense_bot_note(body):
    """Keep the findings and verdict of an earlier bot review, drop the rest."""
    body = body.removeprefix(NOTE_HEADER).split("\n---\n")[0]
    kept = [
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith(BOT_NOTE_KEPT_PREFIXES)
    ]
    condensed = truncate("\n".join(kept) if kept else body.strip(), MAX_BOT_NOTE_CHARS)
    # Quoted, so its headings do not nest above the thread heading.
    return "\n".join(f"> {line}" for line in condensed.splitlines())


def truncate(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " … (truncated)"
