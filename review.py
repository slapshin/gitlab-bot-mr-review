# GitLab MR review bot entry point: fetches the merge request, runs the
# selected review engine and posts the result as an MR note.
import os
import sys

import gitlab
import gitlab.exceptions

import api_engine
import claude_code_engine
from common import NOTE_HEADER, ReviewError

DEFAULT_APPROVED_LABEL = "ai-approved"

# REVIEW_ENGINE value -> engine module exposing run(project, mr, payload).
ENGINES = {
    "api": api_engine,
    "claude-code": claude_code_engine,
}


def bot_version():
    """Describe the running bot build, e.g. "main (16264cb)", from the image's build args."""
    version = os.getenv("BOT_VERSION", "").strip() or "dev"
    commit = os.getenv("BOT_COMMIT", "").strip()
    if commit and commit != "unknown":
        return f"{version} (`{commit[:7]}`)"
    return version


def post_note(mr, body):
    try:
        mr.notes.create({"body": body})
    except gitlab.exceptions.GitlabError as e:
        print(f"ERROR: could not post note to MR: {e}")
        return False
    return True


def sync_approved_label(project, mr, approved):
    """Add the approval label after an approving review and remove it otherwise,
    so it always reflects the latest review run."""
    label = os.getenv("REVIEW_APPROVED_LABEL", DEFAULT_APPROVED_LABEL).strip()
    if not label:
        return
    has_label = label in mr.labels
    if approved == has_label:
        return

    action = "add_labels" if approved else "remove_labels"
    try:
        project.mergerequests.update(mr.iid, {action: label})
    except gitlab.exceptions.GitlabError as e:
        print(f"Warning: could not update label {label!r} on MR: {e}")
        return
    print(f"{'Added' if approved else 'Removed'} label {label!r}")


def select_engine():
    name = os.getenv("REVIEW_ENGINE", "api").strip().lower()
    if name not in ENGINES:
        print(f"Warning: unknown REVIEW_ENGINE={name!r}, using 'api'")
        name = "api"
    print(f"Review engine: {name}")
    return ENGINES[name]


def main():
    try:
        gitlab_url = os.environ["CI_SERVER_URL"]
        project_id = os.environ["CI_PROJECT_ID"]
        mr_iid = os.environ["CI_MERGE_REQUEST_IID"]
    except KeyError as e:
        print(f"ERROR: required environment variable {e.args[0]} is not set")
        return 1

    # Try GITLAB_TOKEN first, fallback to CI_JOB_TOKEN
    gitlab_token = os.getenv("GITLAB_TOKEN") or os.environ["CI_JOB_TOKEN"]

    gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_token)

    try:
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_iid)
        payload = mr.changes()
    except gitlab.exceptions.GitlabError as e:
        print(f"ERROR: could not fetch merge request from GitLab: {e}")
        return 1

    version_line = f"Review bot: {bot_version()}"
    print(version_line)
    engine = select_engine()
    try:
        review = engine.run(project, mr, payload)
    except ReviewError as e:
        print(f"ERROR: {e}")
        sync_approved_label(project, mr, approved=False)
        post_note(
            mr, f"{NOTE_HEADER}\n\n⚠️ Review could not be completed: {e}\n\n---\n_{version_line}_"
        )
        return 1

    if review is None:
        print("No changes to review")
        sync_approved_label(project, mr, approved=False)
        return 0

    sync_approved_label(project, mr, review.approved)

    footer_lines = review.footer_lines + [version_line]
    footer = "\n\n---\n" + "\n\n".join(f"_{line}_" for line in footer_lines)
    if not post_note(mr, f"{NOTE_HEADER}\n\n{review.text}{footer}"):
        return 1

    print("Review posted successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
