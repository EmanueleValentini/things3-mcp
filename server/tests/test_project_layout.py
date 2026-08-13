"""How a project's contents are laid out for the Things JSON command.

Things assigns each to-do to the heading that precedes it in the items array and
ignores a `heading` attribute, so the order of this list is load-bearing.
Verified against the live app: a payload with both headings first put every
to-do under the last one.
"""

from things3_mcp.tools_write import build_project_items


def shape(items):
    return [(item["type"], item["attributes"]["title"]) for item in items]


def test_todos_follow_their_heading():
    items = build_project_items(
        ["Fase 1", "Fase 2"],
        [
            {"title": "b", "heading": "Fase 2"},
            {"title": "a", "heading": "Fase 1"},
        ],
    )
    assert shape(items) == [
        ("heading", "Fase 1"),
        ("to-do", "a"),
        ("heading", "Fase 2"),
        ("to-do", "b"),
    ]


def test_unfiled_todos_come_before_the_first_heading():
    # Anything after a heading would be swallowed by it.
    items = build_project_items(["Fase 1"], [{"title": "sciolto"}, {"title": "a", "heading": "Fase 1"}])
    assert shape(items) == [
        ("to-do", "sciolto"),
        ("heading", "Fase 1"),
        ("to-do", "a"),
    ]


def test_unknown_heading_leaves_the_todo_unfiled():
    items = build_project_items(["Fase 1"], [{"title": "orfano", "heading": "Fase 9"}])
    assert shape(items) == [("to-do", "orfano"), ("heading", "Fase 1")]


def test_heading_order_is_preserved_even_when_empty():
    items = build_project_items(["Uno", "Due", "Tre"], [])
    assert shape(items) == [("heading", "Uno"), ("heading", "Due"), ("heading", "Tre")]


def test_checklists_and_tags_ride_along():
    items = build_project_items(
        ["Fase 1"],
        [{"title": "a", "heading": "Fase 1", "checklist": ["x"], "tags": ["urgente"]}],
        extra_tags=["agent"],
    )
    attributes = items[1]["attributes"]
    assert attributes["tags"] == ["agent", "urgente"]
    assert attributes["checklist-items"][0]["attributes"]["title"] == "x"


def test_no_heading_attribute_is_emitted():
    items = build_project_items(["Fase 1"], [{"title": "a", "heading": "Fase 1"}])
    assert "heading" not in items[1]["attributes"]
