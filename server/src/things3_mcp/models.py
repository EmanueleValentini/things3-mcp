"""Row shapes returned to the model.

Kept deliberately small: a task list dumped into an agent's context is mostly
noise, so only fields an agent can act on are included, and empty values are
dropped before serialisation.
"""

from __future__ import annotations

# TMTask.type
TYPE_TODO = 0
TYPE_PROJECT = 1
TYPE_HEADING = 2

# TMTask.status
STATUS_OPEN = 0
STATUS_CANCELED = 2
STATUS_COMPLETED = 3

STATUS_NAMES = {
    STATUS_OPEN: "open",
    STATUS_CANCELED: "canceled",
    STATUS_COMPLETED: "completed",
}

# TMTask.start
START_INBOX = 0
START_ANYTIME = 1
START_SOMEDAY = 2

START_NAMES = {
    START_INBOX: "inbox",
    START_ANYTIME: "anytime",
    START_SOMEDAY: "someday",
}

TYPE_NAMES = {
    TYPE_TODO: "todo",
    TYPE_PROJECT: "project",
    TYPE_HEADING: "heading",
}


def compact(row: dict) -> dict:
    """Drop null/empty values so serialised rows stay small."""
    return {k: v for k, v in row.items() if v not in (None, "", [], {})}
