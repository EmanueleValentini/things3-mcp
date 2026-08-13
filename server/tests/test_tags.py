"""Tags have to exist before they can be assigned.

Things ignores unknown tags without reporting anything, so a missing tag would
show up as an agent workspace that silently loses its `wip` markers.
"""

import pytest

from things3_mcp import tags
from things3_mcp.writer import Writer


@pytest.fixture
def created(monkeypatch):
    names = []
    monkeypatch.setattr(tags.applescript, "create_tag", lambda name: names.append(name))
    return names


def test_missing_tags_are_created(db, created):
    tags.ensure_exist(db, ["agent", "nuovo", "altro"])
    assert created == ["nuovo", "altro"]


def test_existing_tags_are_left_alone(db, created):
    tags.ensure_exist(db, ["agent", "wip"])
    assert created == []


def test_matching_ignores_case(db, created):
    tags.ensure_exist(db, ["Agent", "WIP"])
    assert created == []


def test_the_same_new_tag_is_only_created_once(db, created):
    tags.ensure_exist(db, ["nuovo", "Nuovo", "nuovo"])
    assert created == ["nuovo"]


def test_empty_input_does_nothing(db, created):
    assert tags.ensure_exist(db, None) == []
    assert created == []


def test_collect_reaches_nested_items():
    payload = [
        {
            "type": "project",
            "attributes": {
                "tags": ["uno"],
                "items": [
                    {"type": "heading", "attributes": {"title": "h"}},
                    {"type": "to-do", "attributes": {"add-tags": ["due", "uno"]}},
                ],
            },
        }
    ]
    assert tags.collect(payload) == ["uno", "due"]


def test_collect_on_a_payload_without_tags():
    assert tags.collect([{"type": "to-do", "attributes": {"title": "x"}}]) == []


def test_writes_create_their_tags_first(config, db, created, monkeypatch):
    """The guarantee that matters: no write goes out before its tags exist."""
    order = []
    monkeypatch.setattr(
        tags.applescript, "create_tag", lambda name: order.append(f"tag:{name}")
    )
    monkeypatch.setattr(
        "things3_mcp.writer.subprocess.run",
        lambda *a, **k: order.append("url") or type("R", (), {"returncode": 0, "stderr": ""})(),
    )
    Writer(config, db).send(
        [{"type": "to-do", "attributes": {"title": "x", "tags": ["nuovo"]}}],
        needs_auth=False,
    )
    assert order == ["tag:nuovo", "url"]
