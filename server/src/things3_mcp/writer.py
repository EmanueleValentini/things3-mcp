"""Writes to Things via the `things:///json` URL scheme.

The JSON command is the only write channel that can create headings and
checklist items, build a whole project in one shot, and append to notes without
reading them first. Update operations require the auth token from
Things > Settings > General > Enable Things URL scheme > Manage.

Things drops anything past 250 items per 10 seconds, so every call goes through
a serialised queue with a rolling-window rate limit.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.parse
from typing import Any

from . import tags
from .config import Config
from .db import ThingsDB

RATE_LIMIT_ITEMS = 200  # headroom under the documented 250
RATE_LIMIT_WINDOW = 10.0
CONFIRM_TIMEOUT = 3.0
CONFIRM_INTERVAL = 0.1


class WriteError(RuntimeError):
    pass


class AuthTokenMissing(WriteError):
    def __init__(self) -> None:
        super().__init__(
            "This operation updates an existing item, which needs the Things auth "
            "token. Run /things3:setup, or set THINGS_AUTH_TOKEN. The token is in "
            "Things > Settings > General > Enable Things URL scheme > Manage."
        )


def count_items(payload: list[dict[str, Any]]) -> int:
    """Number of records Things will process, for rate-limiting purposes."""
    total = 0
    for entry in payload:
        total += 1
        attributes = entry.get("attributes") or {}
        for key in ("items", "checklist-items"):
            nested = attributes.get(key)
            if isinstance(nested, list):
                total += count_items(nested)
    return total


class Writer:
    def __init__(self, config: Config, db: ThingsDB):
        self.config = config
        self.db = db
        self._lock = threading.Lock()
        self._recent: list[tuple[float, int]] = []

    # -- rate limiting --------------------------------------------------

    def _throttle(self, items: int) -> None:
        while True:
            now = time.monotonic()
            self._recent = [
                entry for entry in self._recent if now - entry[0] < RATE_LIMIT_WINDOW
            ]
            used = sum(count for _, count in self._recent)
            if used + items <= RATE_LIMIT_ITEMS or not self._recent:
                self._recent.append((now, items))
                return
            time.sleep(RATE_LIMIT_WINDOW - (now - self._recent[0][0]) + 0.05)

    # -- the URL scheme -------------------------------------------------

    def send(self, payload: list[dict[str, Any]], *, needs_auth: bool) -> None:
        if needs_auth and not self.config.auth_token:
            raise AuthTokenMissing()
        # Things drops tags that do not exist yet, without saying so, so they
        # are created first. One choke point covers every write path.
        tags.ensure_exist(self.db, tags.collect(payload))
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        params = {"data": data, "reveal": "false"}
        if self.config.auth_token:
            params["auth-token"] = self.config.auth_token
        url = "things:///json?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        with self._lock:
            self._throttle(count_items(payload))
            result = subprocess.run(
                ["open", "-g", url], capture_output=True, text=True, timeout=30
            )
        if result.returncode != 0:
            raise WriteError(
                f"Things rejected the URL command: {result.stderr.strip() or result.returncode}"
            )

    # -- create / confirm ----------------------------------------------

    def create(self, payload: list[dict[str, Any]], title: str) -> dict[str, Any]:
        """Run a create command and resolve the uuid of the new item.

        The URL scheme returns nothing, so the new record is found by polling
        the database for the expected title created after the call started.
        """
        started = time.time() - 2  # clock skew headroom
        self.send(payload, needs_auth=False)
        item = self._await_creation(title, started)
        if item is None:
            raise WriteError(
                f"Things accepted the command but no item titled {title!r} appeared. "
                "Check that Things 3 is running and the URL scheme is enabled."
            )
        return item

    def _await_creation(self, title: str, since: float) -> dict[str, Any] | None:
        deadline = time.monotonic() + CONFIRM_TIMEOUT
        while time.monotonic() < deadline:
            rows = self.db.query(
                "SELECT uuid FROM TMTask WHERE title = ? AND creationDate >= ?"
                " ORDER BY creationDate DESC LIMIT 1",
                (title, since),
            )
            if rows:
                return self.db.get(rows[0]["uuid"])
            time.sleep(CONFIRM_INTERVAL)
        return None

    def update(self, uuid: str, kind: str, attributes: dict[str, Any]) -> dict[str, Any]:
        """Apply an update operation and return the item as stored afterwards."""
        payload = [
            {
                "type": "to-do" if kind == "todo" else "project",
                "operation": "update",
                "id": uuid,
                "attributes": attributes,
            }
        ]
        before = self.db.get(uuid)
        if before is None:
            raise LookupError(f"No item with uuid {uuid}")
        self.send(payload, needs_auth=True)
        deadline = time.monotonic() + CONFIRM_TIMEOUT
        after = before
        while time.monotonic() < deadline:
            after = self.db.get(uuid) or before
            if after != before:
                return after
            time.sleep(CONFIRM_INTERVAL)
        return after
