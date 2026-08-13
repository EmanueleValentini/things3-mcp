"""AppleScript bridge for the few operations the URL scheme cannot do.

Only trashing, emptying the trash, and reading the current selection live here.
Everything else goes through the URL scheme, which is a public, stable API.
"""

from __future__ import annotations

import subprocess

from .config import THINGS_APP

APP = "Things3"

# List *names* are localised (the trash is "Cestino" in Italian), so every
# reference goes through the stable internal ids instead.
TRASH_LIST_ID = "TMTrashListSource"


class AppleScriptError(RuntimeError):
    pass


def run(script: str, *args: str, timeout: float = 30) -> str:
    """Run an AppleScript. Any `args` reach it as `argv` in an `on run` handler.

    Names for new tags and areas come from the model, so they are passed as
    arguments rather than pasted into the source — a title is data, and data
    should never be able to become another statement.
    """
    command = ["osascript", "-e", script]
    if args:
        command += ["--", *args]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        message = result.stderr.strip()
        if "-1743" in message or "not allowed" in message.lower():
            raise AppleScriptError(
                "macOS denied automation access to Things 3. Grant it in System "
                "Settings > Privacy & Security > Automation, then retry. "
                "Run /things3:setup to trigger the prompt."
            )
        raise AppleScriptError(message or f"osascript exited {result.returncode}")
    return result.stdout.strip()


def is_installed() -> bool:
    return THINGS_APP.exists()


def is_running() -> bool:
    script = (
        'tell application "System Events" to return (exists (processes where name is '
        f'"{APP}"))'
    )
    return run(script) == "true"


def version() -> str:
    return run(f'tell application "{APP}" to return version')


def create_tag(name: str) -> str:
    """Create a tag and return its id.

    The URL scheme cannot do this — it ignores tags that do not exist — and the
    dictionary marks the application's tag element read-only, but `make new tag`
    works anyway. Verified against Things 3.22.
    """
    result = run(
        "on run argv\n"
        f'  tell application "{APP}" to make new tag with properties {{name:(item 1 of argv)}}\n'
        "end run",
        name,
    )
    return result.replace("tag id ", "").strip()


def create_area(name: str) -> str:
    """Create an area of responsibility and return its id.

    Like tags, this works despite the dictionary marking the application's area
    element read-only. Verified against Things 3.22.
    """
    result = run(
        "on run argv\n"
        f'  tell application "{APP}" to make new area with properties {{name:(item 1 of argv)}}\n'
        "end run",
        name,
    )
    return result.replace("area id ", "").strip()


def delete_area(uuid: str) -> None:
    """Delete an area, by id.

    Always by id, never by name: an id either resolves to one object or fails,
    while a name depends on what else is in the file. Things does not put a
    deleted area in the trash — this cannot be undone from the app.
    """
    run(
        "on run argv\n"
        f'  tell application "{APP}" to delete area id (item 1 of argv)\n'
        "end run",
        uuid,
    )


def trash(uuid: str) -> None:
    """Move a to-do or project to the Things trash. Recoverable in-app."""
    run(
        "on run argv\n"
        "  set theId to item 1 of argv\n"
        f'  tell application "{APP}"\n'
        "    if exists to do id theId then\n"
        f'      move to do id theId to list id "{TRASH_LIST_ID}"\n'
        "    else if exists project id theId then\n"
        f'      move project id theId to list id "{TRASH_LIST_ID}"\n'
        "    else\n"
        '      error "no item with that id"\n'
        "    end if\n"
        "  end tell\n"
        "end run",
        uuid,
    )


def empty_trash() -> None:
    """Permanently delete everything in the trash. Irreversible."""
    run(f'tell application "{APP}" to empty trash')


def selected_todos() -> list[dict[str, str]]:
    """Titles and ids of what the user currently has selected in Things."""
    raw = run(
        f'tell application "{APP}"\n'
        f"  set output to {{}}\n"
        f"  repeat with t in selected to dos\n"
        f'    set end of output to (id of t) & "\t" & (name of t)\n'
        f"  end repeat\n"
        f"  set AppleScript's text item delimiters to linefeed\n"
        f"  return output as text\n"
        f"end tell"
    )
    items = []
    for line in raw.splitlines():
        if "\t" in line:
            uuid, title = line.split("\t", 1)
            items.append({"uuid": uuid, "title": title})
    return items
