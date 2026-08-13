"""Making sure tags exist before they are assigned.

The URL scheme silently drops any tag that does not already exist — the
documentation is explicit: "Does not apply a tag if the specified tag doesn't
exist." No error comes back, the tag is simply missing afterwards, which would
quietly break the whole agent workspace since it runs on `agent`, `wip` and
`blocked`.

AppleScript can create tags even though the app's tag element is read-only in
the dictionary, so missing tags are created there first. Verified live.
"""

from __future__ import annotations

from . import applescript
from .db import ThingsDB


def ensure_exist(db: ThingsDB, names: list[str] | None) -> list[str]:
    """Create any tag that does not exist yet. Returns the names unchanged.

    Matching is case-insensitive, the way Things treats tag titles, so asking
    for "Agent" when "agent" exists does not produce a duplicate.
    """
    if not names:
        return []
    existing = {tag["title"].casefold() for tag in db.tags()}
    for name in names:
        if name.casefold() not in existing:
            applescript.create_tag(name)
            existing.add(name.casefold())
    return names


def collect(payload: list[dict]) -> list[str]:
    """Every tag named anywhere in a JSON command payload, nesting included."""
    found: list[str] = []
    for entry in payload:
        attributes = entry.get("attributes") or {}
        for key in ("tags", "add-tags"):
            value = attributes.get(key)
            if isinstance(value, list):
                found.extend(value)
        nested = attributes.get("items")
        if isinstance(nested, list):
            found.extend(collect(nested))
    return list(dict.fromkeys(found))
