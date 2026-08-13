"""The rules that protect the user's own data: scope, confirmation, audit."""

import json

import pytest

from things3_mcp import agents, tools_write
from things3_mcp.config import SCOPE_AGENTS_ONLY
from things3_mcp.permissions import PermissionDenied


class FakeServer:
    """Captures the functions each module registers so they can be called
    directly, without going through the MCP transport."""

    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


@pytest.fixture
def write_tools(services):
    server = FakeServer()
    tools_write.register(server, services)
    return server.tools


@pytest.fixture
def agent_tools(services):
    server = FakeServer()
    agents.register(server, services)
    return server.tools


DESTRUCTIVE = [
    ("delete_item", {"uuid": "todo-personal"}),
    ("cancel_item", {"uuid": "todo-personal"}),
    ("set_notes", {"uuid": "todo-personal", "notes": "nuovo"}),
    ("remove_tags", {"uuid": "todo-claimed", "tags": ["wip"]}),
    ("complete_item", {"uuid": "todo-personal"}),
]


@pytest.mark.parametrize("name,kwargs", DESTRUCTIVE)
def test_destructive_tools_preview_instead_of_writing(write_tools, services, name, kwargs):
    result = write_tools[name](**kwargs)
    assert result["confirmation_required"] is True
    assert result["preview"]
    assert services.writer.calls == []  # RefusingWriter recorded no update


def test_set_notes_preview_shows_what_would_be_lost(write_tools):
    result = write_tools["set_notes"](uuid="todo-personal", notes="nuovo")
    assert result["preview"]["current_notes"] == "numero: 123"
    assert result["preview"]["new_notes"] == "nuovo"


def test_remove_tags_preview_shows_the_resulting_list(write_tools):
    result = write_tools["remove_tags"](uuid="todo-claimed", tags=["wip"])
    assert result["preview"]["tags_after"] == ["agent", "agent:claude"]


def test_confirmed_true_lets_the_write_through(write_tools, services):
    write_tools["set_notes"](uuid="todo-personal", notes="nuovo", confirmed=True)
    assert services.writer.calls[0][2]["notes"] == "nuovo"


def test_agent_owned_items_complete_without_confirmation(write_tools, services):
    write_tools["complete_item"](uuid="todo-claimed")
    assert services.writer.calls[0][2] == {"completed": True}


def test_moving_within_the_same_project_needs_no_confirmation(write_tools, services):
    write_tools["move_item"](uuid="todo-loose", project="proj-stream")
    assert services.writer.calls


def test_moving_out_of_a_project_needs_confirmation(write_tools, services):
    result = write_tools["move_item"](uuid="todo-personal", project="proj-stream")
    assert result["confirmation_required"] is True
    assert services.writer.calls == []


def test_empty_trash_is_disabled_by_default(write_tools):
    with pytest.raises(PermissionError, match="cannot be undone"):
        write_tools["empty_trash"](confirmed=True)


def test_empty_trash_still_previews_once_enabled(write_tools, config):
    config.allow_empty_trash = True
    result = write_tools["empty_trash"]()
    assert result["confirmation_required"] is True
    assert result["preview"]["count"] == 1


def test_agents_only_scope_blocks_personal_writes(write_tools, config):
    config.write_scope = SCOPE_AGENTS_ONLY
    with pytest.raises(PermissionDenied, match="agents-only"):
        write_tools["append_note"](uuid="todo-personal", text="ciao")


def test_agents_only_scope_allows_agent_area_writes(write_tools, config, services):
    config.write_scope = SCOPE_AGENTS_ONLY
    write_tools["append_note"](uuid="todo-claimed", text="ciao")
    assert services.writer.calls


def test_agent_tools_refuse_items_outside_their_area(agent_tools):
    with pytest.raises(PermissionDenied, match="agent_. tools only manage"):
        agent_tools["agent_log_progress"](uuid="todo-personal", note="ciao")


def test_claiming_a_task_held_by_another_agent_fails(agent_tools, config):
    config.agent_id = "codex"
    with pytest.raises(PermissionDenied, match="already claimed by claude"):
        agent_tools["agent_claim_task"](uuid="todo-claimed")


def test_reclaiming_your_own_task_is_a_no_op(agent_tools, services):
    result = agent_tools["agent_claim_task"](uuid="todo-claimed")
    assert result["uuid"] == "todo-claimed"
    assert services.writer.calls == []


def test_claiming_a_free_task_tags_and_stamps_it(agent_tools, services):
    agent_tools["agent_claim_task"](uuid="todo-free")
    _, _, attributes = services.writer.calls[0]
    assert attributes["add-tags"] == ["agent", "wip", "agent:claude"]
    assert "claimed by claude" in attributes["append-notes"]


def test_next_task_skips_claimed_work(agent_tools):
    assert agent_tools["agent_next_task"]()["title"] == "Write the tests"


def test_complete_task_clears_wip_and_records_a_summary(agent_tools, services):
    agent_tools["agent_complete_task"](uuid="todo-claimed", summary="fatto")
    _, _, attributes = services.writer.calls[0]
    assert attributes["completed"] is True
    assert "wip" not in attributes["tags"]
    assert "fatto" in attributes["append-notes"]


def test_needs_review_leaves_the_task_open(agent_tools, services):
    agent_tools["agent_complete_task"](
        uuid="todo-claimed", summary="da guardare", needs_review=True
    )
    _, _, attributes = services.writer.calls[0]
    assert "completed" not in attributes
    assert "needs-review" in attributes["tags"]


def test_workspace_init_reports_the_streams(agent_tools):
    status = agent_tools["agent_workspace_init"]()
    assert status["ready"] is True
    assert [s["title"] for s in status["streams"]] == ["Refactor auth"]


def test_workspace_init_explains_a_missing_area(agent_tools, config):
    config.agents_area = "Nonexistent"
    status = agent_tools["agent_workspace_init"]()
    assert status["ready"] is False
    assert "Create an area" in status["action_needed"]


def test_audit_log_records_confirmations(write_tools, guard, tmp_path, monkeypatch):
    from things3_mcp import permissions

    log = tmp_path / "audit.log"
    monkeypatch.setattr(permissions, "AUDIT_LOG", log)
    monkeypatch.setattr(permissions, "CONFIG_DIR", tmp_path)
    write_tools["delete_item"](uuid="todo-personal")
    entry = json.loads(log.read_text().splitlines()[0])
    assert entry["tool"] == "delete_item"
    assert entry["outcome"] == "confirmation_required"
