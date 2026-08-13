"""Where consent for a destructive operation comes from.

A `confirmed=true` argument only shows that the model chose to send it. It
cannot tell the user's decision apart from the model's own conviction — an
instruction like "delete X" is the request, not the confirmation of the
irreversible step. So the server asks the client to put the question to the
user, and treats the flag as the fallback for clients that cannot.
"""

import pytest

from things3_mcp import tools_write
from things3_mcp.permissions import ACCEPTED, DECLINED, UNAVAILABLE, ask_user

from conftest import FakeContext, FakeServer


@pytest.fixture
def write_tools(services, monkeypatch):
    monkeypatch.setattr(tools_write.applescript, "trash", lambda uuid: None)
    monkeypatch.setattr(tools_write.applescript, "delete_area", lambda uuid: None)
    server = FakeServer()
    tools_write.register(server, services)
    return server.tools


# -- the channel itself -------------------------------------------------


def test_ask_user_reports_each_outcome():
    import asyncio

    assert asyncio.run(ask_user(FakeContext(True), "x", {}, "why")) == ACCEPTED
    assert asyncio.run(ask_user(FakeContext(False), "x", {}, "why")) == DECLINED
    assert asyncio.run(ask_user(FakeContext(None), "x", {}, "why")) == UNAVAILABLE
    assert asyncio.run(ask_user(None, "x", {}, "why")) == UNAVAILABLE


def test_the_question_carries_the_details():
    import asyncio

    ctx = FakeContext(True)
    asyncio.run(
        ask_user(ctx, "delete_area", {"area": "Prova", "projects": ["a", "b"]}, "gone for good")
    )
    message = ctx.messages[0]
    assert "gone for good" in message
    assert "Prova" in message
    assert "a, b" in message


# -- how tools use it ---------------------------------------------------


def test_the_user_is_asked_even_when_the_model_says_confirmed(write_tools):
    """The flag does not skip the question; the person still decides."""
    ctx = FakeContext(False)
    result = write_tools["delete_item"](uuid="todo-personal", confirmed=True, ctx=ctx)
    assert ctx.messages, "the client was never asked"
    assert result["declined_by_user"] is True
    assert result["performed"] is False


def test_a_yes_from_the_user_is_enough_without_the_flag(write_tools):
    ctx = FakeContext(True)
    result = write_tools["delete_item"](uuid="todo-personal", ctx=ctx)
    assert result["trashed"] == "todo-personal"


def test_a_no_stops_the_operation(write_tools, services):
    ctx = FakeContext(False)
    result = write_tools["set_notes"](uuid="todo-personal", notes="nuovo", ctx=ctx)
    assert result["declined_by_user"] is True
    assert services.writer.calls == []
    assert "Do not retry" in result["next_step"]


def test_a_client_that_cannot_ask_falls_back_to_the_preview(write_tools):
    ctx = FakeContext(None)  # elicitation unsupported
    result = write_tools["delete_item"](uuid="todo-personal", ctx=ctx)
    assert result["confirmation_required"] is True
    assert "is the request, not the confirmation" in result["next_step"]


def test_the_fallback_still_honours_the_flag(write_tools):
    result = write_tools["delete_item"](uuid="todo-personal", confirmed=True, ctx=FakeContext(None))
    assert result["trashed"] == "todo-personal"


def test_deleting_an_area_asks_the_user(write_tools):
    ctx = FakeContext(False)
    result = write_tools["delete_area"](area="Casa", confirmed=True, ctx=ctx)
    assert "Trasloco" in ctx.messages[0]
    assert result["declined_by_user"] is True


def test_agent_owned_items_are_never_put_to_the_user(write_tools, services):
    """The agent's own work does not interrupt anyone."""
    ctx = FakeContext(False)
    write_tools["complete_item"](uuid="todo-claimed", ctx=ctx)
    assert ctx.messages == []
    assert services.writer.calls[0][2] == {"completed": True}


def test_the_audit_log_records_which_channel_granted_consent(
    write_tools, tmp_path, monkeypatch
):
    import json

    from things3_mcp import permissions

    log = tmp_path / "audit.log"
    monkeypatch.setattr(permissions, "AUDIT_LOG", log)
    monkeypatch.setattr(permissions, "CONFIG_DIR", tmp_path)

    write_tools["delete_item"](uuid="todo-personal", ctx=FakeContext(True))
    write_tools["delete_item"](uuid="todo-inbox", confirmed=True, ctx=FakeContext(None))

    entries = [json.loads(line) for line in log.read_text().splitlines()]
    granted = [e for e in entries if e["outcome"] == "consent_granted"]
    assert [e["channel"] for e in granted] == ["elicitation", "confirmed_flag"]


# -- the agent workspace ------------------------------------------------


@pytest.fixture
def agent_tools(services, monkeypatch):
    from things3_mcp import agents
    from things3_mcp.config import Config

    monkeypatch.setattr(agents.applescript, "create_area", lambda name: None)
    monkeypatch.setattr(
        Config, "save", lambda self, **u: [setattr(self, k, v) for k, v in u.items()]
    )
    server = FakeServer()
    agents.register(server, services)
    return server.tools


def test_adopting_a_users_area_asks_the_user(agent_tools, config):
    ctx = FakeContext(False)
    result = agent_tools["agent_workspace_init"](area="Casa", confirmed=True, ctx=ctx)
    assert "Trasloco" in ctx.messages[0]
    assert result["declined_by_user"] is True
    assert config.agents_areas == ["Agents"]


def test_adopting_it_proceeds_when_the_user_agrees(agent_tools, config):
    agent_tools["agent_workspace_init"](area="Casa", ctx=FakeContext(True))
    assert config.agents_areas == ["Agents", "Casa"]


def test_a_brand_new_area_never_interrupts(agent_tools, config):
    ctx = FakeContext(False)
    agent_tools["agent_workspace_init"](area="Nuova", ctx=ctx)
    assert ctx.messages == []  # nothing of the user's is at stake
    assert config.agents_areas == ["Agents", "Nuova"]
