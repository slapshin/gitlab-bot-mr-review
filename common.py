# Types shared by the review entry point and the review engines.
from dataclasses import dataclass, field

# Effort levels, ordered from cheapest to most thorough.
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")


class ReviewError(Exception):
    """A failure worth reporting back to the merge request."""


@dataclass
class Review:
    """A finished review: the note text and the footer lines describing the run."""

    text: str
    footer_lines: list[str] = field(default_factory=list)
