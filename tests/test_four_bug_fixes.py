"""Regression tests for the four server.py bug fixes (branch fix/four-server-bugs).

Covers: unclosed/truncated ```json action blocks, move-agent with a non-object
body, move-platform with `[1]`, and load() with a list-shaped state.json.
Uses the shared hq/api fixtures, so the real server and data/ are never touched.
"""
import json

import pytest

import server

GHOST = "deadbeef"


# ---------- bug 1: parse_actions with an unclosed or truncated fence ----------

def test_unclosed_fence_with_complete_json_is_bad():
    acts = {"actions": [{"type": "assign", "agent": "A", "task": "do it"}]}
    text, actions, bad = server.parse_actions("Do this\n```json\n" + json.dumps(acts))
    assert actions == []
    assert bad is True
    assert text == "Do this"


def test_truncated_block_without_closing_fence_is_bad():
    text, actions, bad = server.parse_actions('Start\n```json\n{"actions":[{"type":"assign"')
    assert actions == []
    assert bad is True
    assert text == "Start"


# ---------- bug 2: move-agent with a non-object body ----------

@pytest.mark.parametrize("raw", [b"[1]", b'"str"', b"null"])
def test_move_agent_non_object_body_is_400(api, hq, raw):
    a = hq.agent("Worker")
    code, body, _ = api.post(f"/api/agents/{a['id']}/move", raw=raw)
    assert code == 400
    assert isinstance(body, dict) and "error" in body


# ---------- bug 3: move-platform with `[1]` ----------

def test_move_platform_list_body_is_400(api, hq):
    p = hq.project("Main")
    code, body, _ = api.post(f"/api/projects/{p['id']}/move", raw=b"[1]")
    assert code == 400
    assert isinstance(body, dict) and "error" in body


def test_move_platform_unknown_id_is_404(api, hq):
    hq.project("Main")
    code, body, _ = api.post(f"/api/projects/{GHOST}/move", {"q": 1, "r": 0})
    assert code == 404
    assert "error" in body


def test_move_platform_repositions(api, hq):
    hq.project("Main")
    second = server.create_project({"name": "Second", "description": "", "q": 1, "r": 0})
    code, body, _ = api.post(f"/api/projects/{second['id']}/move", {"q": 0, "r": -1})
    assert code == 200 and body["q"] == 0 and body["r"] == -1
    assert server.projects[second["id"]]["q"] == 0


def test_move_platform_rejects_taken_spot(api, hq):
    hq.project("Main")
    second = server.create_project({"name": "Second", "description": "", "q": 1, "r": 0})
    code, body, _ = api.post(f"/api/projects/{second['id']}/move", {"q": 0, "r": 0})
    assert code == 400 and "error" in body


# ---------- bug 4: load() with a list-shaped state.json ----------

@pytest.mark.parametrize("content", ["[]", "[1, 2, 3]", '"just a string"', "42"])
def test_load_with_non_object_state_does_not_crash(hq, capsys, content):
    server.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    server.STATE_FILE.write_text(content, encoding="utf-8")
    hq.reload_from_disk()                       # must not raise
    assert server.projects == {} and server.agents == {}
    assert "could not read saved state" in capsys.readouterr().err
    assert server.STATE_FILE.read_text(encoding="utf-8") == content   # file preserved
