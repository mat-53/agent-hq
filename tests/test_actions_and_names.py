"""Items: Director action rules (assign / unknown actions) and duplicate names (agents + platforms)."""
import pytest

import server
from server import ApiError


# ---------------- Director: assign ----------------

@pytest.mark.parametrize("status", ["idle", "done", "failed"])
def test_assign_accepted_for_idle_done_failed(hq, status):
    hq.agent("Worker", status=status)
    msg = hq.act({"type": "assign", "agent": "Worker", "task": "build it"})
    assert msg.startswith("Assigned to Worker")
    hq.wait_idle()
    calls = hq.stub.worker_calls("Worker")
    assert len(calls) == 1 and calls[0][1].startswith("build it")
    assert hq.by_name("Worker")["by"] == "director"


def test_assign_rejected_for_working_agent(hq):
    hq.stub.worker_gate.clear()          # hold the first task so the agent stays "working"
    hq.agent("Worker")
    assert hq.act({"type": "assign", "agent": "Worker", "task": "first"}).startswith("Assigned")
    hq.wait_until(lambda: len(hq.stub.worker_calls("Worker")) == 1, what="first worker call")
    msg = hq.act({"type": "assign", "agent": "Worker", "task": "second"})
    assert msg.startswith("Could not assign to Worker")
    assert "already working" in msg
    a = hq.by_name("Worker")
    assert a["status"] == "working" and a["task"] == "first"   # the running task was not replaced
    hq.stub.worker_gate.set()
    hq.wait_idle()
    assert [c[1].startswith("first") for c in hq.stub.worker_calls("Worker")] == [True]


def test_assign_working_status_set_directly_is_rejected_and_unchanged(hq):
    a = hq.agent("Busy", status="working")
    a["task"] = "original"
    msg = hq.act({"type": "assign", "agent": "Busy", "task": "new"})
    assert msg.startswith("Could not assign")
    assert a["task"] == "original" and hq.stub.worker_calls() == []
    a["status"] = "idle"    # no worker thread owns this fake "working" state; reset so teardown doesn't wait


def test_assign_agent_name_is_case_and_space_insensitive(hq):
    hq.agent("Alice")
    assert hq.act({"type": "assign", "agent": "  aLiCe ", "task": "x"}).startswith("Assigned to Alice")
    hq.wait_idle()


def test_assign_unknown_agent_skipped(hq):
    hq.agent("Alice")
    msg = hq.act({"type": "assign", "agent": "Nobody", "task": "x"})
    assert msg.startswith("Skipped: no agent named 'Nobody'")
    assert hq.stub.calls == []


def test_assign_missing_agent_field_skipped(hq):
    assert hq.act({"type": "assign", "task": "x"}).startswith("Skipped")
    assert hq.stub.calls == []


def test_assign_to_director_skipped(hq):
    hq.agent("Boss", director=True)
    assert hq.act({"type": "assign", "agent": "Boss", "task": "x"}).startswith("Skipped")
    assert hq.stub.calls == []


@pytest.mark.parametrize("task", [None, "", "   \n", 123, ["a"]])
def test_assign_empty_or_non_string_task_skipped(hq, task):
    a = hq.agent("Alice")
    msg = hq.act({"type": "assign", "agent": "Alice", "task": task})
    assert msg.startswith("Skipped: empty task")
    assert a["status"] == "idle" and hq.stub.calls == []


def test_assign_task_capped_at_max_message_chars(hq):
    n = hq.server.MAX_MESSAGE_CHARS
    assert n == 32_000
    hq.agent("Alice")
    hq.act({"type": "assign", "agent": "Alice", "task": "y" * (n + 1000)})
    hq.wait_idle()
    assert hq.by_name("Alice")["task"] == "y" * n


# ---------------- Director: unknown / malformed actions ----------------

@pytest.mark.parametrize("act", [
    {"type": "explode"},
    {"type": "ASSIGN", "agent": "A", "task": "x"},       # types are case-sensitive
    {"type": ""},
    {"type": None},
    {"type": 5},
    {"type": ["assign"]},
    {},
    {"agent": "A", "task": "x"},                          # no type at all
])
def test_unknown_action_types_skipped(hq, act):
    hq.agent("A")
    assert hq.act(act) == "Skipped an unknown action."
    assert hq.stub.calls == []
    assert hq.by_name("A")["status"] == "idle"


@pytest.mark.parametrize("act", [None, "assign", 42, ["assign"], 1.5, True])
def test_non_dict_action_skipped(hq, act):
    assert hq.act(act) == "Skipped an unknown action."


def test_unknown_action_does_not_change_state(hq):
    hq.agent("A")
    before = (dict(server.projects), {k: dict(v) for k, v in server.agents.items()})
    hq.act({"type": "nuke_everything"})
    assert (dict(server.projects), {k: dict(v) for k, v in server.agents.items()}) == before


# ---------------- Duplicate names: agents ----------------

@pytest.mark.parametrize("dup", ["Alice", "alice", "ALICE", "  Alice", "Alice  ", "  aLiCe  "])
def test_create_agent_duplicate_name_rejected(hq, dup):
    p = hq.project()["id"]
    hq.agent("Alice", project=p)
    with pytest.raises(ApiError) as e:
        server.create_agent({"name": dup, "backend": "mock", "project": p})
    assert e.value.code == 400 and "already exists" in e.value.message
    assert len(server.agents) == 1


def test_create_agent_duplicate_across_platforms_rejected(hq):
    p1 = hq.project("One")["id"]
    p2 = hq.project("Two")["id"]
    hq.agent("Alice", project=p1)
    with pytest.raises(ApiError) as e:
        server.create_agent({"name": "alice", "backend": "mock", "project": p2})
    assert e.value.code == 400


def test_create_agent_unique_names_allowed(hq):
    p = hq.project()["id"]
    hq.agent("Alice", project=p)
    hq.agent("Alice 2", project=p)
    hq.agent("Bob", project=p)
    assert len(server.agents) == 3


def test_stored_agent_name_is_stripped(hq):
    p = hq.project()["id"]
    a = server.create_agent({"name": "  Zed  ", "backend": "mock", "project": p})
    assert a["name"] == "Zed"


def test_agent_name_can_be_reused_after_delete(hq):
    a = hq.agent("Alice")
    server.delete_agent(a["id"])
    hq.agent("alice")
    assert len(server.agents) == 1


def test_director_create_agent_duplicate_rejected(hq):
    hq.project("Main")
    hq.agent("Alice")
    msg = hq.act({"type": "create_agent", "name": " ALICE ", "platform": "main", "backend": "mock"})
    assert msg.startswith("Could not create agent") and "already exists" in msg
    assert len(server.agents) == 1


def test_api_create_agent_duplicate_returns_400(api, hq):
    p = hq.project()["id"]
    body = {"name": "Alice", "role": "", "backend": "mock", "project": p}
    assert api.post("/api/agents", body)[0] == 201
    status, data, _ = api.post("/api/agents", dict(body, name="  alice "))
    assert status == 400
    assert len(server.agents) == 1


# ---------------- Duplicate names: platforms ----------------

def _slot():
    with server.lock:
        return server.auto_slot()


@pytest.mark.parametrize("dup", ["Main", "main", "MAIN", "  Main", "Main  ", "  mAiN  "])
def test_create_platform_duplicate_name_rejected(hq, dup):
    hq.project("Main")
    q, r = _slot()
    with pytest.raises(ApiError) as e:
        server.create_project({"name": dup, "description": "", "q": q, "r": r})
    assert e.value.code == 400 and "already exists" in e.value.message
    assert len(server.projects) == 1


def test_create_platform_unique_names_allowed(hq):
    hq.project("Main")
    hq.project("Main 2")
    hq.project("Other")
    assert len(server.projects) == 3


def test_stored_platform_name_is_stripped(hq):
    p = server.create_project({"name": "  Lab  ", "description": "", "q": 0, "r": 0})
    assert p["name"] == "Lab"


def test_platform_name_can_be_reused_after_delete(hq):
    p = hq.project("Main")
    server.delete_project(p["id"])
    hq.project("main")
    assert len(server.projects) == 1


def test_director_create_platform_duplicate_rejected(hq):
    hq.project("Main")
    msg = hq.act({"type": "create_platform", "name": "  MAIN "})
    assert msg.startswith("Could not create platform") and "already exists" in msg
    assert len(server.projects) == 1


def test_agent_and_platform_names_are_separate_namespaces(hq):
    p = hq.project("Alice")["id"]
    hq.agent("Alice", project=p)          # same text as the platform name must be fine
    assert len(server.projects) == 1 and len(server.agents) == 1


def test_api_create_platform_duplicate_returns_400(api, hq):
    assert api.post("/api/projects", {"name": "Main", "description": "", "q": 0, "r": 0})[0] == 201
    q, r = _slot()
    status, _, _ = api.post("/api/projects", {"name": " main ", "description": "", "q": q, "r": r})
    assert status == 400
    assert len(server.projects) == 1
