# GitLab MR review bot entry point: fetches the merge request, runs the
# selected review engine and posts the result as an MR note.
import os
import sys

import gitlab
import gitlab.exceptions

import api_engine
import claude_code_engine
from common import ReviewError

NOTE_HEADER = "🤖 **Claude Code Review**"

# REVIEW_ENGINE value -> engine module exposing run(project, mr, payload).
ENGINES = {
    "api": api_engine,
    "claude-code": claude_code_engine,
}


def post_note(mr, body):
    try:
        mr.notes.create({"body": body})
    except gitlab.exceptions.GitlabError as e:
        print(f"ERROR: could not post note to MR: {e}")
        return False
    return True


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

    engine = select_engine()
    try:
        review = engine.run(project, mr, payload)
    except ReviewError as e:
        print(f"ERROR: {e}")
        post_note(mr, f"{NOTE_HEADER}\n\n⚠️ Review could not be completed: {e}")
        return 1

    if review is None:
        print("No changes to review")
        return 0

    footer = "\n\n---\n" + "\n\n".join(f"_{line}_" for line in review.footer_lines)
    if not post_note(mr, f"{NOTE_HEADER}\n\n{review.text}{footer}"):
        return 1

    print("Review posted successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
