#!/usr/bin/env python3
"""Agent HQ: a tiny local server that manages agents and streams their status to the browser."""
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "agents.json"
WORKSPACES = ROOT / "workspaces"
OPENCODE_TIMEOUT = 900
SECRET_ENV = ("OPENROUTER_API_KEY", "GEMINI_API_KEY")
HOST, PORT = "127.0.0.1", 8765
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}
MAX_BODY, MAX_OUTPUT, MAX_HISTORY, MAX_AGENTS = 100_000, 20_000, 10, 40
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\-]{1,100}$")
PROVIDER_TIMEOUT = 120


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


lock = threading.RLock()
agents = {}
clients = []


def find_opencode():
    candidates = [os.environ.get("OPENCODE_EXE", "")]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(str(Path(appdata) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"))
    candidates.append(str(Path.home() / ".opencode" / "bin" / "opencode.exe"))
    for c in candidates:
        if c and c.lower().endswith(".exe") and Path(c).is_file():
            return c
    return None


def backend_info():
    oc = find_opencode() is not None
    missing = "OpenCode was not found. Install it, or set OPENCODE_EXE in .env to the full path of opencode.exe."
    return [
        {"id": "mock", "label": "Mock (no API, for testing)", "ready": True, "needsKey": None},
        {"id": "opencode", "label": "OpenCode: builder (edits files, runs commands)", "ready": oc, "needsKey": None,
         "missing": missing, "note": "Works in its own folder under workspaces/, but it is NOT sandboxed: the model can run shell commands as you. Free models only."},
        {"id": "opencode-readonly", "label": "OpenCode: read-only (plans, reviews)", "ready": oc, "needsKey": None,
         "missing": missing, "note": "Read-only planning agent. It cannot edit files or run commands."},
        {"id": "openrouter", "label": "OpenRouter", "ready": bool(os.environ.get("OPENROUTER_API_KEY")),
         "needsKey": "OPENROUTER_API_KEY"},
        {"id": "gemini", "label": "Google Gemini (AI Studio)", "ready": bool(os.environ.get("GEMINI_API_KEY")),
         "needsKey": "GEMINI_API_KEY"},
    ]


def snapshot():
    with lock:
        ordered = sorted(agents.values(), key=lambda a: a["slot"])
        return {"agents": ordered, "backends": backend_info()}


def save():
    DATA_FILE.parent.mkdir(exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(list(agents.values()), indent=2), encoding="utf-8")
    os.replace(tmp, DATA_FILE)


def load():
    if not DATA_FILE.exists():
        return
    try:
        stored = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("Warning: could not read data/agents.json, starting empty", file=sys.stderr)
        return
    for a in stored:
        if a.get("status") == "working":
            a.update(status="failed", error="The server restarted while this task was running.",
                     finishedAt=time.time())
        agents[a["id"]] = a


def broadcast():
    payload = json.dumps(snapshot())
    for q in list(clients):
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


# ---------- worker backends ----------

def http_json(url, headers, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=PROVIDER_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {e.code} from provider: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}") from None
    except (TimeoutError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Provider did not return a usable response ({type(e).__name__})") from None


def require_key(name):
    key = os.environ.get(name)
    if not key:
        raise RuntimeError(f"{name} is not set. Put it in the .env file next to server.py, then restart the server.")
    return key


def run_mock(agent, task):
    time.sleep(random.uniform(3, 6))
    if "fail" in task.lower():
        raise RuntimeError("Mock failure (your task contained the word 'fail').")
    return f"[mock worker for {agent['name']}]\nPretended to work on:\n{task}"


def run_openrouter(agent, task):
    key = require_key("OPENROUTER_API_KEY")
    data = http_json(
        "https://openrouter.ai/api/v1/chat/completions",
        {"Authorization": f"Bearer {key}"},
        {"model": agent["model"], "messages": [
            {"role": "system", "content": agent["role"] or "You are a helpful agent."},
            {"role": "user", "content": task}]})
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected response from OpenRouter: {json.dumps(data)[:300]}") from None
    return text


def run_gemini(agent, task):
    key = require_key("GEMINI_API_KEY")
    model = agent["model"].removeprefix("models/")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{urllib.parse.quote(model, safe='')}:generateContent")
    body = {"contents": [{"role": "user", "parts": [{"text": task}]}]}
    if agent["role"]:
        body["systemInstruction"] = {"parts": [{"text": agent["role"]}]}
    data = http_json(url, {"x-goog-api-key": key}, body)
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected response from Gemini: {json.dumps(data)[:300]}") from None
    return text


def run_opencode(agent, task, readonly=False):
    exe = find_opencode()
    if not exe:
        raise RuntimeError("OpenCode was not found. Install it, or set OPENCODE_EXE in .env.")
    ws = WORKSPACES / agent["id"]
    ws.mkdir(parents=True, exist_ok=True)
    prompt = f"Task: {task}"
    if agent["role"]:
        prompt = f"Your role: {agent['role']}\n\n{prompt}"
    cmd = [exe, "run", "-m", agent["model"], "--dir", str(ws), "--format", "json"]
    if readonly:
        cmd += ["--agent", "plan"]
    cmd.append(prompt)
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=OPENCODE_TIMEOUT, stdin=subprocess.DEVNULL, env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"OpenCode took longer than {OPENCODE_TIMEOUT // 60} minutes and was stopped.") from None
    texts, files, shell_runs, errors = [], [], 0, []
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind, part = ev.get("type"), ev.get("part") or {}
        if kind == "text" and part.get("text"):
            texts.append(part["text"])
        elif kind == "tool_use":
            tool, inp = part.get("tool"), (part.get("state") or {}).get("input") or {}
            if tool == "bash":
                shell_runs += 1
            elif tool in ("write", "edit", "patch") and inp.get("filePath"):
                try:
                    name = str(Path(inp["filePath"]).resolve().relative_to(ws.resolve()))
                except ValueError:
                    name = inp["filePath"]
                if name not in files:
                    files.append(name)
        elif kind == "error":
            data = (ev.get("error") or {}).get("data") or {}
            errors.append(str(data.get("message") or ev.get("error"))[:400])
    if errors and not texts and not files:
        raise RuntimeError("OpenCode error: " + errors[0])
    if proc.returncode != 0 and not texts and not files:
        raise RuntimeError("OpenCode failed: " + (proc.stderr.strip()[-400:] or f"exit code {proc.returncode}"))
    out = "\n\n".join(texts).strip() or "(the model gave no text reply)"
    if files:
        out += "\n\nFiles written in workspaces/" + agent["id"] + ":\n" + "\n".join("- " + f for f in files)
    if shell_runs:
        out += f"\n\n(ran {shell_runs} shell command{'s' if shell_runs > 1 else ''})"
    return out


RUNNERS = {"mock": run_mock, "openrouter": run_openrouter, "gemini": run_gemini,
           "opencode": run_opencode, "opencode-readonly": lambda a, t: run_opencode(a, t, readonly=True)}


def worker(agent_id, snap, task):
    try:
        output = RUNNERS[snap["backend"]](snap, task)
        if not output.strip():
            raise RuntimeError("The model returned an empty response.")
        status, error = "done", ""
    except Exception as e:  # any failure becomes a visible "failed" state
        output, status, error = "", "failed", str(e)
    with lock:
        a = agents.get(agent_id)
        if not a:
            return
        finished = time.time()
        a.update(status=status, output=output[:MAX_OUTPUT], error=error[:2000], finishedAt=finished)
        a["history"].insert(0, {"task": task, "status": status, "output": a["output"],
                                "error": a["error"], "finishedAt": finished})
        del a["history"][MAX_HISTORY:]
        save()
        broadcast()


# ---------- agent operations ----------

def create_agent(d):
    if not isinstance(d, dict):
        raise ApiError(400, "Invalid request")
    name = str(d.get("name", "")).strip()
    role = str(d.get("role", "")).strip()
    backend = d.get("backend")
    model = str(d.get("model", "")).strip()
    if not 1 <= len(name) <= 40:
        raise ApiError(400, "Name must be 1-40 characters")
    if len(role) > 2000:
        raise ApiError(400, "Role is too long (max 2000 characters)")
    if backend not in RUNNERS:
        raise ApiError(400, "Unknown worker type")
    if backend == "mock":
        model = "mock"
    elif not MODEL_RE.match(model) or model.startswith("-"):
        raise ApiError(400, "Enter a model id (letters, digits and . _ : / - only)")
    elif backend.startswith("opencode") and not model.startswith("opencode/"):
        raise ApiError(400, "OpenCode models must start with 'opencode/' (the free models), e.g. opencode/big-pickle")
    with lock:
        if len(agents) >= MAX_AGENTS:
            raise ApiError(400, f"Agent limit ({MAX_AGENTS}) reached")
        used = {a["slot"] for a in agents.values()}
        slot = next(i for i in range(len(used) + 1) if i not in used)
        agent = {"id": uuid.uuid4().hex[:8], "name": name, "role": role, "backend": backend, "model": model,
                 "slot": slot, "status": "idle", "task": "", "output": "", "error": "",
                 "startedAt": None, "finishedAt": None, "history": []}
        agents[agent["id"]] = agent
        save()
        broadcast()
        return dict(agent)


def start_task(agent_id, d):
    task = str(d.get("task", "")).strip() if isinstance(d, dict) else ""
    if not task:
        raise ApiError(400, "Task is empty")
    if len(task) > 10_000:
        raise ApiError(400, "Task is too long (max 10000 characters)")
    with lock:
        a = agents.get(agent_id)
        if not a:
            raise ApiError(404, "Agent not found")
        if a["status"] == "working":
            raise ApiError(409, "This agent is already working")
        a.update(status="working", task=task, output="", error="", startedAt=time.time(), finishedAt=None)
        snap = dict(a)
        save()
        broadcast()
    threading.Thread(target=worker, args=(agent_id, snap, task), daemon=True).start()
    return {"ok": True}


def delete_agent(agent_id):
    with lock:
        if agents.pop(agent_id, None) is None:
            raise ApiError(404, "Agent not found")
        save()
        broadcast()
    return {"ok": True}


# ---------- HTTP ----------

TASK_ROUTE = re.compile(r"^/api/agents/([0-9a-f]{8})/task$")
AGENT_ROUTE = re.compile(r"^/api/agents/([0-9a-f]{8})$")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def _guard(self, mutating):
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            raise ApiError(403, "Bad host header")
        if mutating:
            origin = self.headers.get("Origin")
            if origin and origin not in ALLOWED_ORIGINS:
                raise ApiError(403, "Bad origin")

    def _read_json(self):
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise ApiError(415, "Content-Type must be application/json")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "Request body too large")
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid JSON") from None

    def _dispatch(self, fn, mutating):
        try:
            self._guard(mutating)
            fn()
        except ApiError as e:
            self._json(e.code, {"error": e.message})
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as e:
            print(f"Internal error: {e!r}", file=sys.stderr)
            self._json(500, {"error": "Internal server error"})

    def do_GET(self):
        self._dispatch(self._get, False)

    def do_POST(self):
        self._dispatch(self._post, True)

    def do_DELETE(self):
        self._dispatch(self._delete, True)

    def _get(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._json(200, snapshot())
        elif path == "/api/events":
            self._events()
        else:
            raise ApiError(404, "Not found")

    def _post(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/agents":
            self._json(201, create_agent(self._read_json()))
            return
        m = TASK_ROUTE.match(path)
        if m:
            self._json(202, start_task(m.group(1), self._read_json()))
            return
        raise ApiError(404, "Not found")

    def _delete(self):
        m = AGENT_ROUTE.match(urllib.parse.urlparse(self.path).path)
        if not m:
            raise ApiError(404, "Not found")
        self._json(200, delete_agent(m.group(1)))

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q = queue.Queue(maxsize=50)
        with lock:
            clients.append(q)
            first = json.dumps(snapshot())
        try:
            self.wfile.write(f"data: {first}\n\n".encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            with lock:
                if q in clients:
                    clients.remove(q)


def main():
    load_env()
    load()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"Agent HQ running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
