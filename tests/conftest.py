"""Shared fixtures for the agent-hq test suite.

Isolation guarantees (the live server on port 8765 and the real data/ folder are never touched):
  * AGENT_HQ_DATA_DIR points to a fresh temp dir, AGENT_HQ_PORT to a free port (never 8765);
    both are set BEFORE server.py is imported because server.py reads them at import time.
  * Every worker backend in server.RUNNERS is replaced by a stub, so no AI agent / CLI / network is used.
  * server.WORKSPACES is redirected to the temp dir.
  * Run with `py -B` so no __pycache__ is written into the repo.
"""
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
TMP_ROOT = Path(tempfile.mkdtemp(prefix="agent-hq-tests-"))


def _free_port():
    for _ in range(50):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        if port != 8765:
            return port
    raise RuntimeError("no free port")


TEST_PORT = _free_port()
os.environ["AGENT_HQ_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["AGENT_HQ_PORT"] = str(TEST_PORT)
# never let real credentials / tool paths leak into the tests
for _k in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
           "CLAUDE_EXE", "OPENCODE_EXE"):
    os.environ.pop(_k, None)

sys.path.insert(0, str(REPO))
import server  # noqa: E402

# ---- hard safety checks: abort the whole run if isolation failed ----
assert server.PORT == TEST_PORT and server.PORT != 8765, "tests must not use port 8765"
assert not str(server.DATA_DIR.resolve()).lower().startswith(str((REPO / "data").resolve()).lower()), \
    "tests must not use the real data/ folder"
assert str(server.DATA_DIR.resolve()).lower().startswith(str(TMP_ROOT.resolve()).lower())

REAL_RUNNER_KEYS = tuple(server.RUNNERS)
REAL_RUNNERS = dict(server.RUNNERS)  # only used by tests that call a real runner on purpose (it fails before any I/O)
DEFAULT_MODEL = {"mock": "mock", "claude": "sonnet", "opencode": "opencode/big-pickle",
                 "opencode-readonly": "opencode/big-pickle", "openrouter": "vendor/model:free",
                 "gemini": "gemini-test"}


class Stub:
    """Fake worker backend. Records calls; can hold workers / the Director until released."""

    def __init__(self):
        self.calls = []                    # (agent name, prompt)
        self.worker_gate = threading.Event()
        self.worker_gate.set()
        self.director_gate = threading.Event()
        self.director_gate.set()
        self.director_reply = "Nothing to do."   # str or callable(prompt) -> str
        self.worker_reply = "worked\nSUMMARY:\nstub summary"   # str or callable(agent, prompt) -> str
        self.worker_error = None            # callable(agent, prompt) -> Exception | None

    def __call__(self, agent, prompt):
        self.calls.append((agent["name"], prompt))
        if server.DIRECTOR_MARK in prompt:
            if not self.director_gate.wait(15):
                raise RuntimeError("stub director gate timeout")
            r = self.director_reply
            return r(prompt) if callable(r) else r
        if not self.worker_gate.wait(15):
            raise RuntimeError("stub worker gate timeout")
        if self.worker_error:
            err = self.worker_error(agent, prompt)
            if err:
                raise err
        r = self.worker_reply
        return r(agent, prompt) if callable(r) else r

    def worker_calls(self, name=None):
        return [c for c in self.calls if server.DIRECTOR_MARK not in c[1] and (name is None or c[0] == name)]

    def director_calls(self):
        return [c for c in self.calls if server.DIRECTOR_MARK in c[1]]


def wait_until(pred, timeout=8.0, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def reset_server_state():
    with server.lock:
        server.projects.clear()
        server.agents.clear()
        server.clients.clear()
        server.chat.clear()
        server.settings.clear()
        server.settings["autoReview"] = True
        server.director_busy = False
        server.review_pending = False
        server.auto_rounds = 0
    server.MODEL_CACHE.clear()
    shutil.rmtree(server.DATA_DIR, ignore_errors=True)


class HQ:
    """Convenience helpers around the in-process server module."""
    server = server
    wait_until = staticmethod(wait_until)

    def __init__(self, stub):
        self.stub = stub

    # -- building state --
    def project(self, name="Main"):
        with server.lock:
            slot = server.auto_slot() or (0, 0)
        return server.create_project({"name": name, "description": "", "q": slot[0], "r": slot[1]})

    def agent(self, name, project=None, backend="mock", status="idle", director=False, role="", model=None):
        pid = project or (next(iter(server.projects)) if server.projects else self.project()["id"])
        a = server.create_agent({"name": name, "role": role, "backend": backend,
                                 "model": model or DEFAULT_MODEL[backend], "project": pid,
                                 "isDirector": director})
        live = server.agents[a["id"]]
        if status != "idle":
            live["status"] = status
        return live

    def by_name(self, name):
        return server.find_agent(name)

    def act(self, action):
        """Run one Director action the way director_run does (lock held)."""
        with server.lock:
            return server.run_action(action)

    def wait_idle(self, timeout=8.0):
        wait_until(lambda: not server.director_busy and
                   not any(a["status"] == "working" for a in list(server.agents.values())),
                   timeout, "all agents idle")

    def wait_status(self, agent, status, timeout=8.0):
        wait_until(lambda: agent["status"] == status, timeout, f"{agent['name']} -> {status}")

    def chat_text(self, role=None):
        return [m["text"] for m in list(server.chat) if role is None or m["role"] == role]

    def state_file(self):
        return json.loads(server.STATE_FILE.read_text(encoding="utf-8"))

    def reload_from_disk(self):
        """Simulate a server restart: drop in-memory state (keep files) and call load()."""
        with server.lock:
            server.projects.clear()
            server.agents.clear()
            server.chat.clear()
            server.settings.clear()
            server.settings["autoReview"] = True
        server.load()


@pytest.fixture(autouse=True)
def hq(monkeypatch):
    reset_server_state()
    stub = Stub()
    monkeypatch.setattr(server, "RUNNERS", {k: stub for k in REAL_RUNNER_KEYS})
    monkeypatch.setattr(server, "WORKSPACES", TMP_ROOT / "workspaces")
    yield HQ(stub)
    # let every background thread finish before the next test resets the shared state
    stub.worker_gate.set()
    stub.director_gate.set()
    try:
        wait_until(lambda: not server.director_busy and
                   not any(a["status"] == "working" for a in list(server.agents.values())), 8, "threads to finish")
        time.sleep(0.05)
    finally:
        reset_server_state()


# ---------- real HTTP server (in-process, on the temp port) ----------

class Client:
    def __init__(self, port):
        self.port = port

    def request(self, method, path, body=None, headers=None, raw=None):
        """body: python object sent as JSON; raw: bytes sent as-is. Returns (status, parsed json or text, headers)."""
        h = {}
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        if data is not None or method == "POST":
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=data, headers=h)
            resp = conn.getresponse()
            payload = resp.read()
            text = payload.decode("utf-8", "replace")
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = text
            return resp.status, parsed, dict(resp.getheaders())
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


@pytest.fixture(scope="session")
def _http_server():
    httpd = server.ThreadingHTTPServer((server.HOST, server.PORT), server.Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def api(_http_server, hq):
    return Client(server.PORT)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
