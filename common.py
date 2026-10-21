# Types shared by the review entry point and the review engines.
from dataclasses import dataclass, field

# Effort levels, ordered from cheapest to most thorough.
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")

# Starts every note the bot posts; also how earlier bot notes are recognized.
NOTE_HEADER = "🤖 **Claude Code Review**"


class ReviewError(Exception):
    """A failure worth reporting back to the merge request."""


@dataclass
class Review:
    """A finished review: the note text, the footer lines describing the run,
    and whether the review found nothing that should block merging."""

    text: str
    footer_lines: list[str] = field(default_factory=list)
    approved: bool = False
