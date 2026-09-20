#!/usr/bin/env python3
"""Agent HQ: local server for a small company of AI agents grouped into project platforms."""
import argparse
import json
import os
import queue
import random
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("AGENT_HQ_DATA_DIR") or ROOT / "data")
STATE_FILE = DATA_DIR / "state.json"
LEGACY_FILE = DATA_DIR / "agents.json"
NOTES_DIR = DATA_DIR / "notes"
WORKSPACES = ROOT / "workspaces"
HOST, PORT = "127.0.0.1", int(os.environ.get("AGENT_HQ_PORT") or 8765)
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{h}" for h in ALLOWED_HOSTS}
MAX_OUTPUT, MAX_HISTORY = 20_000, 10
MAX_AGENTS, MAX_PROJECTS, MAX_CHAT, MAX_AUTO_ROUNDS = 40, 12, 200, 4
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\-]{1,100}$")


def _get_int(name, default, minimum=1):
    """Read a positive integer env var; unset / invalid / below `minimum` -> default."""
    try:
        v = int(float(str(os.environ.get(name, "")).strip()))
    except (TypeError, ValueError):
        return default
    return v if v >= minimum else default


# Max characters of one user message (chat box and direct agent tasks). Env: MAX_MESSAGE_CHARS (default 32000).
MAX_MESSAGE_CHARS = _get_int("MAX_MESSAGE_CHARS", 32_000)
# Max HTTP request body in bytes. Derived from MAX_MESSAGE_CHARS so a full-size message can never hit it
# (worst case JSON-escaped: 6 bytes/char); never below the old 100_000.
MAX_BODY = max(100_000, MAX_MESSAGE_CHARS * 8)
# CreateProcess limit on Windows is 32767 chars; OpenCode gets its prompt as an argument (see run_opencode).
WIN_CMDLINE_LIMIT = 32_000


def _parse_timeout(raw, default):
    """Parse a timeout env value. None/unset -> default; '' or 0 -> None (no timeout)."""
    if raw is None:
        return default
    s = str(raw).strip()
    if s == "":
        return None
    try:
        v = int(float(s))
    except (TypeError, ValueError):
        return default
    if v <= 0:
        return None
    return v


def _get_timeout(name, default):
    return _parse_timeout(os.environ.get(name), default)


def _fmt_timeout(timeout):
    if timeout is None:
        return "ohne Zeitlimit"
    if timeout >= 60 and timeout % 60 == 0:
        return f"{timeout} s ({timeout // 60} Minuten)"
    return f"{timeout} s"


class TimeoutPartial(RuntimeError):
    """A timeout that still carries usable partial output (saved by worker())."""
    def __init__(self, message, partial=""):
        super().__init__(message)
        self.partial = partial


PROVIDER_TIMEOUT = _get_timeout("PROVIDER_TIMEOUT", 600)
OPENCODE_TIMEOUT = _get_timeout("OPENCODE_TIMEOUT", 3600)
CLAUDE_TIMEOUT = _get_timeout("CLAUDE_TIMEOUT", 3600)


def refresh_timeouts():
    """Re-read timeouts from the environment (called after load_env() in main())."""
    global PROVIDER_TIMEOUT, OPENCODE_TIMEOUT, CLAUDE_TIMEOUT
    PROVIDER_TIMEOUT = _get_timeout("PROVIDER_TIMEOUT", 600)
    OPENCODE_TIMEOUT = _get_timeout("OPENCODE_TIMEOUT", 3600)
    CLAUDE_TIMEOUT = _get_timeout("CLAUDE_TIMEOUT", 3600)


def refresh_limits():
    """Re-read MAX_MESSAGE_CHARS after load_env() (the .env file is read after import) and re-derive MAX_BODY."""
    global MAX_MESSAGE_CHARS, MAX_BODY
    MAX_MESSAGE_CHARS = _get_int("MAX_MESSAGE_CHARS", 32_000)
    MAX_BODY = max(100_000, MAX_MESSAGE_CHARS * 8)


SECRET_ENV = ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
CLAUDE_MODELS = ("opus", "sonnet", "haiku")
NEIGHBORS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
SUMMARY_RULE = ("\n\nWhen you are finished, end your reply with a line 'SUMMARY:' followed by at most 6 short "
                "lines that your teammates can read. Put nothing after the summary.")
DIRECTOR_MARK = "You are the Director of a small company of AI agents."
DIRECTOR_RULES = DIRECTOR_MARK + """ The human owner talks only to you. You never do the work yourself: you delegate to agents, and create and delete agents and platforms, and pass information between them.
The owner's projects are called PLATFORMS (for example Main or Research). Agents always belong to a platform.
To act, end your reply with ONE json block listing actions, exactly like this:
```json
{"actions":[{"type":"assign","agent":"<agent name>","task":"<complete, self-contained instructions>","include_notes_from":["<other agent name>"]}]}
```
Available action types (each entry is a dict with a "type"):
- {"type":"assign","agent":"<agent name>","task":"<complete, self-contained instructions>","include_notes_from":["<other agent name>"]} -- give a task to a worker. "include_notes_from" is optional: it gives the agent the latest summary of teammates whose findings help with the task.
- {"type":"create_platform","name":"<platform name>"} -- create a new empty platform (e.g. "Research") when the work needs a new area.
- {"type":"create_agent","name":"<agent name>","role":"<role>","platform":"<platform name or id>","backend":"<optional, default claude>","model":"<optional>"} -- create a new worker agent on an existing platform. "backend" is optional (default "claude"); "model" is optional (a sensible default is picked).
- {"type":"delete_platform","name":"<platform name or id>"} -- delete a platform. It is rejected if the platform still has agents or does not exist. If two platforms share a name, give the id instead.
- {"type":"delete_agent","name":"<agent name>"} -- delete an agent. It is rejected while the agent is working.
- {"type":"move_agent","agent":"<agent name>","platform":"<platform name or id>"} -- move an agent onto another platform (e.g. regroup workers). It is rejected while the agent is working, if the platform does not exist, or if several platforms share the name (then give the id).
Rules:
- Only assign to agents whose status is idle, done or failed. Never assign to an agent that is working.
- Give each task clear success criteria. Agents end their work with a short SUMMARY.
- Agent names and platform names are unique (ignoring case and surrounding spaces). Before create_agent or assign, check the AGENTS list. Before create_platform or delete_platform, check the PLATFORMS list (it shows every platform, its id and agent count); empty platforms are listed too. If two platforms share a name, use the id.
- If nothing needs to be done, write only a short plain reply without a json block.
- Keep replies short. Answer in the owner's language."""


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
projects, agents, clients = {}, {}, []
chat = []
settings = {"autoReview": True}
director_busy = False
review_pending = False
auto_rounds = 0


# ---------- tool discovery ----------

def find_exe(env_name, candidates):
    for c in [os.environ.get(env_name, "")] + candidates:
        if c and c.lower().endswith(".exe") and Path(c).is_file():
            return c
    return None


def find_opencode():
    appdata = os.environ.get("APPDATA")
    cands = [str(Path(appdata) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe")] if appdata else []
    return find_exe("OPENCODE_EXE", cands + [str(Path.home() / ".opencode" / "bin" / "opencode.exe")])


def find_claude():
    return find_exe("CLAUDE_EXE", [str(Path.home() / ".local" / "bin" / "claude.exe")])


def backend_info():
    oc, cl = find_opencode() is not None, find_claude() is not None
    oc_missing = "OpenCode was not found. Install it, or set OPENCODE_EXE in .env to the full path of opencode.exe."
    return [
        {"id": "mock", "label": "Mock (no API, for testing)", "ready": True, "needsKey": None},
        {"id": "claude", "label": "Claude (your subscription, via claude CLI)", "ready": cl, "needsKey": None,
         "missing": "The claude CLI was not found. Install Claude Code, or set CLAUDE_EXE in .env.",
         "note": "Uses your Claude subscription limits (the same pool as Claude Code). Opus is smartest but drains the limit fastest. Text only."},
        {"id": "opencode", "label": "OpenCode: builder (edits files, runs commands)", "ready": oc, "needsKey": None,
         "missing": oc_missing, "note": "Works in its own folder under workspaces/, but it is NOT sandboxed: the model can run shell commands as you. Free models only."},
        {"id": "opencode-readonly", "label": "OpenCode: read-only (plans, reviews, browses)", "ready": oc, "needsKey": None,
         "missing": oc_missing, "note": "Read-only agent. It can browse web pages but cannot edit files or run commands."},
        {"id": "openrouter", "label": "OpenRouter (text only)", "ready": bool(os.environ.get("OPENROUTER_API_KEY")),
         "needsKey": "OPENROUTER_API_KEY"},
        {"id": "gemini", "label": "Google Gemini (text only)", "ready": bool(os.environ.get("GEMINI_API_KEY")),
         "needsKey": "GEMINI_API_KEY"},
    ]


# ---------- state ----------

def current_director():
    return next((a for a in agents.values() if a.get("isDirector")), None)


def snapshot():
    with lock:
        return {"projects": sorted(projects.values(), key=lambda p: p["created"]),
                "agents": sorted(agents.values(), key=lambda a: a["created"]),
                "backends": backend_info(), "chat": chat[-80:], "busy": director_busy, "maxMessageChars": MAX_MESSAGE_CHARS,
                "autoReview": settings["autoReview"], "director": (current_director() or {}).get("id")}


def save():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"projects": list(projects.values()), "agents": list(agents.values()),
                               "chat": chat, "settings": settings}, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:30] or "agent"


def load():
    stored = {}
    try:
        if STATE_FILE.exists():
            stored = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        elif LEGACY_FILE.exists():
            stored = {"agents": json.loads(LEGACY_FILE.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        print("Warning: could not read saved state, starting empty", file=sys.stderr)
        return
    if not isinstance(stored, dict):
        print("Warning: could not read saved state, starting empty", file=sys.stderr)
        return
    now = time.time()
    for i, p in enumerate(stored.get("projects", [])):
        p.setdefault("created", now + i)
        projects[p["id"]] = p
    legacy = [a for a in stored.get("agents", []) if a.get("project") not in projects]
    if legacy and not projects:
        pid = uuid.uuid4().hex[:8]
        projects[pid] = {"id": pid, "name": "Main", "description": "", "q": 0, "r": 0, "created": now}
    for i, a in enumerate(stored.get("agents", [])):
        a.setdefault("created", now + i)
        a.setdefault("isDirector", False)
        a.setdefault("summary", "")
        a.setdefault("by", "user")
        a.setdefault("notesFile", f"{slug(a.get('name', ''))}-{a['id']}.md")
        if a.get("project") not in projects:
            a["project"] = next(iter(projects))
        if a.get("status") == "working":
            a.update(status="failed", error="The server restarted while this task was running.", finishedAt=now)
        agents[a["id"]] = a
    chat.extend(stored.get("chat", [])[-MAX_CHAT:])
    settings.update(stored.get("settings", {}))


def broadcast():
    payload = json.dumps(snapshot())
    for q in list(clients):
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


def add_chat(role, text):
    # user text is already length-checked in send_chat (never cut here); Director/system text keeps the 4000 cap
    chat.append({"role": role, "text": text if role == "user" else text[:4000], "ts": time.time()})
    del chat[:-MAX_CHAT]


def write_notes(a):
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    proj = projects.get(a["project"], {}).get("name", "?")
    parts = [f"# {a['name']}", f"Platform: {proj}", f"Role: {a['role'] or '-'}",
             f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}", "", "## Latest summary", a["summary"] or "(no work yet)",
             "", "## Earlier work"]
    for h in a["history"][1:]:
        if h["status"] == "done":
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(h["finishedAt"]))
            parts += [f"### {when} - {h['task'][:80]}", h.get("summary", "")[:800], ""]
    (NOTES_DIR / a["notesFile"]).write_text("\n".join(parts), encoding="utf-8")


def _smart_truncate(text, limit):
    """Cut text to at most `limit` chars, preferring a sentence/line boundary over mid-word."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("\n", ". ", "! ", "? ", "; ", " "):
        idx = cut.rfind(sep)
        if idx >= limit * 0.5:
            # keep sentence-ending punctuation, never cut mid-word
            return cut[:idx + 1].rstrip() if sep != "\n" else cut[:idx].rstrip()
    return cut.rstrip()


def extract_summary(text):
    idx = text.upper().rfind("SUMMARY:")
    body = text[idx + 8:] if idx != -1 else text
    return _smart_truncate(body, 6000) if idx != -1 else _smart_truncate(body, 3000)


# ---------- worker backends ----------

def http_json(url, headers, body=None):
    req = urllib.request.Request(
        url, data=None if body is None else json.dumps(body).encode("utf-8"),
        method="GET" if body is None else "POST", headers={"Content-Type": "application/json", **headers})
    try:
        timeout = _get_timeout("PROVIDER_TIMEOUT", PROVIDER_TIMEOUT)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from provider: {e.read().decode('utf-8', 'replace')[:500]}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}") from None
    except (TimeoutError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Provider did not return a usable response ({type(e).__name__})") from None


def require_key(name):
    key = os.environ.get(name)
    if not key:
        raise RuntimeError(f"{name} is not set. Put it in the .env file next to server.py, then restart the server.")
    return key


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in SECRET_ENV}


def run_mock(agent, task):
    time.sleep(random.uniform(2, 4))
    if DIRECTOR_MARK in task:
        lines = [ln for ln in task.split("CONVERSATION (oldest first):", 1)[-1].strip().splitlines() if ln.strip()]
        if len(lines) >= 2 and lines[-2].startswith("System:"):
            return "Reviewed the results. Nothing more to do right now."
        m = re.search(r"^- (.+?) \| platform", task, re.M)
        if not m:
            return "You have no agents yet. Add one first."
        act = {"actions": [{"type": "assign", "agent": m.group(1), "task": "Introduce yourself in one sentence."}]}
        return f"I'll ask {m.group(1)} to get started.\n```json\n{json.dumps(act)}\n```"
    if "fail" in task.split("\n\nInformation from teammates")[0].lower():
        raise RuntimeError("Mock failure (your task contained the word 'fail').")
    return f"[mock worker for {agent['name']}] Pretended to work.\nSUMMARY:\nDid the task (mock)."


def run_openrouter(agent, task):
    key = require_key("OPENROUTER_API_KEY")
    data = http_json("https://openrouter.ai/api/v1/chat/completions", {"Authorization": f"Bearer {key}"},
                     {"model": agent["model"], "messages": [
                         {"role": "system", "content": agent["role"] or "You are a helpful agent."},
                         {"role": "user", "content": task}]})
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected response from OpenRouter: {json.dumps(data)[:300]}") from None


def run_gemini(agent, task):
    key = require_key("GEMINI_API_KEY")
    model = agent["model"].removeprefix("models/")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent"
    body = {"contents": [{"role": "user", "parts": [{"text": task}]}]}
    if agent["role"]:
        body["systemInstruction"] = {"parts": [{"text": agent["role"]}]}
    data = http_json(url, {"x-goog-api-key": key}, body)
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected response from Gemini: {json.dumps(data)[:300]}") from None


def run_claude(agent, task):
    exe = find_claude()
    if not exe:
        raise RuntimeError("The claude CLI was not found. Install Claude Code, or set CLAUDE_EXE in .env.")
    # Each agent gets its own folder so concurrent claude runs never share a working directory:
    # two claude CLI processes in the same cwd can collide on Claude Code's per-directory state
    # and one silently exits (return code 0, no output) - the cause of the "Claude CLI failed:
    # exit code 0" failure seen for Sonnet Coder while the Director ran at the same time.
    cwd = Path(tempfile.gettempdir()) / "agent-hq-claude" / slug(agent.get("name") or agent["id"])
    cwd.mkdir(parents=True, exist_ok=True)
    system = "You are one AI agent in a small company. Follow the instructions directly and concisely."
    if agent["role"]:
        system += " Your role: " + agent["role"]
    cmd = [exe, "-p", "--model", agent["model"], "--tools", "default", "--strict-mcp-config", "--no-session-persistence",
           "--setting-sources", "project", "--disable-slash-commands", "--dangerously-skip-permissions",
           "--system-prompt", system]
    timeout = _get_timeout("CLAUDE_TIMEOUT", CLAUDE_TIMEOUT)
    try:
        proc = subprocess.run(cmd, input=task, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=str(cwd), env=clean_env(),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        partial = str(e.stdout or "").strip()
        if not partial and e.stderr:
            partial = str(e.stderr or "").strip()[-2000:]
        raise TimeoutPartial(
            f"Der claude CLI wurde abgebrochen nach {_fmt_timeout(timeout)}, Teilergebnis erhalten.",
            partial) from None
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError("Claude CLI failed: " + ((out or proc.stderr).strip()[-400:] or f"exit code {proc.returncode}"))
    return out


def _partial_opencode_output(stdout_text, ws, agent_id):
    """Best-effort parse of (possibly truncated) OpenCode JSON-lines into readable text."""
    texts, files, shell_runs = [], [], 0
    for line in stdout_text.splitlines():
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
    out = "\n\n".join(texts).strip()
    if files:
        out += ("\n\n" if out else "") + "Files written in workspaces/" + agent_id + ":\n" + "\n".join("- " + f for f in files)
    if shell_runs:
        out += f"\n\n(ran {shell_runs} shell command{'s' if shell_runs > 1 else ''})"
    return out.strip()


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
    if os.name == "nt" and len(subprocess.list2cmdline(cmd)) > WIN_CMDLINE_LIMIT:
        # OpenCode takes the prompt as a command-line argument; Windows cuts / rejects >32767 chars.
        # Fail loudly instead of silently dropping part of the message.
        raise RuntimeError(
            f"The prompt is too long for OpenCode on Windows ({len(prompt)} characters; the command line allows about "
            f"{WIN_CMDLINE_LIMIT}). Shorten the message, or use a Claude, Gemini or OpenRouter agent for long input.")
    timeout = _get_timeout("OPENCODE_TIMEOUT", OPENCODE_TIMEOUT)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL, env=clean_env(),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        partial_out = _partial_opencode_output(str(e.stdout or ""), ws, agent["id"])
        if not partial_out and e.stderr:
            partial_out = str(e.stderr or "").strip()[-2000:]
        raise TimeoutPartial(
            f"OpenCode wurde abgebrochen nach {_fmt_timeout(timeout)}, Teilergebnis erhalten.",
            partial_out or "(abgebrochen, kein Teilergebnis vorhanden)") from None
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


# ---------- model lists ----------

MODEL_CACHE = {}


def models_gemini():
    key = require_key("GEMINI_API_KEY")
    data = http_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": key})
    skip = ("image", "tts", "transcribe", "customtools", "embedding")
    names = [m["name"].removeprefix("models/") for m in data.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    names = [n for n in names if n.startswith("gemini") and not any(s in n for s in skip)]
    return sorted(names, key=lambda n: (0 if "flash-lite" in n else 1 if "flash" in n else 2, n))


def models_openrouter():
    out = []
    for m in http_json("https://openrouter.ai/api/v1/models", {}).get("data", []):
        price = m.get("pricing") or {}
        if m.get("id", "").endswith(":free") or (price.get("prompt") == "0" and price.get("completion") == "0"):
            out.append(m["id"])
    return sorted(set(out))


def models_opencode():
    exe = find_opencode()
    if not exe:
        raise RuntimeError("OpenCode was not found.")
    proc = subprocess.run([exe, "models"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=30, stdin=subprocess.DEVNULL, env=clean_env(),
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ids = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip().startswith("opencode/")]
    return sorted(i for i in ids if "free" in i or i == "opencode/big-pickle")


def list_models(backend):
    if backend == "claude":
        return list(CLAUDE_MODELS)
    hit = MODEL_CACHE.get(backend)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    fn = {"gemini": models_gemini, "openrouter": models_openrouter,
          "opencode": models_opencode, "opencode-readonly": models_opencode}[backend]
    models = fn()
    if models:
        MODEL_CACHE[backend] = (time.time(), models)
    return models


RUNNERS = {"mock": run_mock, "openrouter": run_openrouter, "gemini": run_gemini, "claude": run_claude,
           "opencode": run_opencode, "opencode-readonly": lambda a, t: run_opencode(a, t, readonly=True)}


# ---------- tasks ----------

def find_agent(name):
    name = str(name).strip().lower()
    return next((a for a in agents.values() if a["name"].strip().lower() == name), None)


def context_from(names, exclude):
    parts = []
    for n in names[:5] if isinstance(names, list) else []:
        src = find_agent(n)
        if src and src["id"] != exclude and src["summary"]:
            parts.append(f"### {src['name']}\n{src['summary'][:3000]}")
    return "\n\n".join(parts)


def begin_task(a, task, by="user", names=()):
    """Caller must hold the lock."""
    if a["status"] == "working":
        raise ApiError(409, "This agent is already working")
    prompt = task
    ctx = context_from(list(names), a["id"])
    if ctx:
        prompt += "\n\nInformation from teammates (use it if it helps):\n" + ctx
    prompt += SUMMARY_RULE
    a.update(status="working", task=task, output="", error="", startedAt=time.time(), finishedAt=None, by=by)
    snap = dict(a)
    save()
    broadcast()
    threading.Thread(target=worker, args=(a["id"], snap, task, prompt), daemon=True).start()


def worker(agent_id, snap, task, prompt):
    global review_pending
    try:
        output = RUNNERS[snap["backend"]](snap, prompt)
        if not output.strip():
            raise RuntimeError("The model returned an empty response.")
        status, error = "done", ""
    except TimeoutPartial as e:
        output, status, error = (e.partial or ""), "failed", str(e)
    except Exception as e:
        output, status, error = "", "failed", str(e)
    directed = False
    with lock:
        a = agents.get(agent_id)
        if not a:
            return
        finished = time.time()
        summary = extract_summary(output) if status == "done" else ""
        a.update(status=status, output=output[:MAX_OUTPUT], error=error[:2000], finishedAt=finished)
        if status == "done":
            a["summary"] = summary
        a["history"].insert(0, {"task": task, "status": status, "output": a["output"][:4000], "error": a["error"],
                                "summary": summary, "finishedAt": finished})
        del a["history"][MAX_HISTORY:]
        try:
            write_notes(a)
        except OSError as e:
            print(f"Could not write notes: {e}", file=sys.stderr)
        directed = a.get("by") == "director" and not a.get("isDirector")
        if directed:
            add_chat("system", f"{a['name']} {'finished' if status == 'done' else 'failed'}: "
                               f"{(summary or a['error'])[:300] or '(no summary)'}")
            review_pending = settings["autoReview"]
        save()
        broadcast()
    if directed:
        try_review()


# ---------- director ----------

def build_director_prompt(d):
    roster = []
    for a in sorted(agents.values(), key=lambda x: x["created"]):
        if a.get("isDirector"):
            continue
        pname = projects.get(a["project"], {}).get("name", "?")
        roster.append(f"- {a['name']} | platform: {pname} | role: {a['role'] or '-'} | status: {a['status']}"
                      f"\n  latest summary: {(a['summary'] or '(no work yet)')[:600]}".replace("\r", ""))
    platforms = []
    for p in sorted(projects.values(), key=lambda x: x["created"]):
        n = sum(1 for a in agents.values() if a["project"] == p["id"])
        platforms.append(f"- {p['name']} | id: {p['id']} | agents: {n}")
    label = {"user": "Owner", "director": "Director", "system": "System"}
    # Owner messages go to the Director in full (they were clipped to 700 chars before); other roles stay clipped.
    convo = "\n".join(f"{label.get(m['role'], 'System')}: "
                      f"{re.sub(r'\s+', ' ', m['text'])[:None if m['role'] == 'user' else 700]}" for m in chat[-14:])
    extra = f"\n\nExtra instructions from the owner: {d['role']}" if d["role"] else ""
    return (f"{DIRECTOR_RULES}{extra}\n\nPLATFORMS:\n" + ("\n".join(platforms) or "(no platforms yet)") +
            "\n\nAGENTS:\n" + ("\n".join(roster) or "(no agents yet)") +
            "\n\nCONVERSATION (oldest first):\n" + convo + "\n\nWrite the Director's next message.")


def parse_actions(text):
    match = None
    for match in re.finditer(r"```json\s*(\{.*?\})\s*```", text, re.S):
        pass
    if not match:
        i = text.rfind("```json")
        if i != -1:
            return text[:i].strip(), [], True
        return text.strip(), [], False
    cleaned = (text[:match.start()] + text[match.end():]).strip()
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return cleaned, [], True
    acts = data.get("actions") if isinstance(data, dict) else None
    return cleaned, (acts if isinstance(acts, list) else []), not isinstance(acts, list)


def director_turn():
    global director_busy
    with lock:
        d = current_director()
        if not d or director_busy:
            return False
        director_busy = True
        d.update(status="working", task="Thinking...", output="", error="", startedAt=time.time(), finishedAt=None)
        snap, prompt = dict(d), build_director_prompt(d)
        broadcast()
    threading.Thread(target=director_run, args=(snap, prompt), daemon=True).start()
    return True


def director_run(snap, prompt):
    global director_busy
    try:
        reply = RUNNERS[snap["backend"]](snap, prompt)
        error = "" if reply.strip() else "The Director returned an empty reply."
    except Exception as e:
        reply, error = "", str(e)
    with lock:
        d = agents.get(snap["id"])
        if error:
            add_chat("system", f"The Director could not answer: {error[:400]}")
        else:
            text, actions, bad = parse_actions(reply)
            if text:
                add_chat("director", text)
            for act in actions[:8]:
                add_chat("system", run_action(act))
            if bad:
                add_chat("system", "The Director's action block was invalid, so nothing was assigned.")
        if d:
            d.update(status="failed" if error else "done", error=error[:2000], output=reply[:MAX_OUTPUT],
                     finishedAt=time.time())
        director_busy = False
        save()
        broadcast()
    try_review()


DEFAULT_MODELS = {"claude": "sonnet", "mock": "mock", "opencode": "opencode/big-pickle",
                  "opencode-readonly": "opencode/big-pickle", "gemini": "gemini-3.1-flash-lite"}


def auto_slot():
    """Pick the first free hex slot for a new platform (caller must hold the lock)."""
    if not projects:
        return (0, 0)
    taken = {(p["q"], p["r"]) for p in projects.values()}
    for p in projects.values():
        for dq, dr in NEIGHBORS:
            if (p["q"] + dq, p["r"] + dr) not in taken:
                return (p["q"] + dq, p["r"] + dr)
    return None


def find_project(key):
    """Resolve a platform by id or by name (case-insensitive, surrounding whitespace ignored).
    Returns (project dict, None) on success, or (None, error message)."""
    if not key or not str(key).strip():
        return None, "give a platform name or id"
    key = str(key).strip()
    if key in projects:
        return projects[key], None
    matches = [p for p in projects.values() if p["name"].strip().lower() == key.lower()]
    if not matches:
        return None, f"platform '{key[:40]}' not found"
    if len(matches) > 1:
        return None, (f"several platforms are named '{matches[0]['name']}'; give the id instead "
                      f"({', '.join(p['id'] for p in matches)})")
    return matches[0], None


def dir_create_platform(act):
    name = str(act.get("name", "")).strip()
    if not name:
        return "Skipped: create_platform needs a 'name'."
    slot = auto_slot()
    if slot is None:
        return f"Could not create platform '{name}': no free spot next to a platform."
    try:
        p = create_project({"name": name, "description": "", "q": slot[0], "r": slot[1]})
    except ApiError as e:
        return f"Could not create platform '{name}': {e.message}."
    return f"Created platform '{p['name']}'."


def dir_create_agent(act):
    name, platform = str(act.get("name", "")).strip(), act.get("platform")
    if not name:
        return "Skipped: create_agent needs a 'name'."
    if not platform:
        return f"Skipped: create_agent for '{name}' needs a 'platform' (a platform name or id)."
    p, err = find_project(str(platform))
    if not p:
        return (f"Skipped: could not create agent '{name}': {err}. "
                "Create it first with create_platform.")
    backend = str(act.get("backend") or "claude").strip() or "claude"
    model = str(act.get("model") or "").strip() or DEFAULT_MODELS.get(backend, "")
    role = str(act.get("role") or "").strip()
    try:
        agent = create_agent({"name": name, "role": role, "backend": backend, "model": model, "project": p["id"]})
    except ApiError as e:
        return f"Could not create agent '{name}': {e.message}."
    return f"Created agent '{agent['name']}' on platform '{p['name']}' (backend {backend}, role {role or '-'})."


def dir_delete_platform(act):
    if not str(act.get("name", "")).strip():
        return "Skipped: delete_platform needs a 'name' (a platform name or id)."
    p, err = find_project(act.get("name"))
    if not p:
        return f"Could not delete platform '{str(act.get('name'))[:40]}': {err}."
    try:
        delete_project(p["id"])
    except ApiError as e:
        return f"Could not delete platform '{p['name']}': {e.message}."
    return f"Deleted platform '{p['name']}'."


def dir_delete_agent(act):
    name = str(act.get("name", "")).strip()
    if not name:
        return "Skipped: delete_agent needs a 'name'."
    target = find_agent(name)
    if not target:
        return f"Skipped: no agent named '{name[:40]}'."
    if target.get("isDirector"):
        return f"Could not delete agent '{target['name']}': it is the Director. Remove it in the UI if you must."
    if target["status"] == "working":
        return f"Could not delete agent '{target['name']}': it is working right now."
    try:
        delete_agent(target["id"])
    except ApiError as e:
        return f"Could not delete agent '{target['name']}': {e.message}."
    return f"Deleted agent '{target['name']}'."


def dir_move_agent(act):
    name, platform = str(act.get("agent", "")).strip(), act.get("platform")
    if not name:
        return "Skipped: move_agent needs an 'agent' name."
    if not platform:
        return f"Skipped: move_agent for '{name}' needs a 'platform' (a platform name or id)."
    target = find_agent(name)
    if not target:
        return f"Skipped: no agent named '{name[:40]}'."
    try:
        move_agent(target["id"], str(platform))
    except ApiError as e:
        return f"Could not move agent '{target['name']}': {e.message}."
    p = projects[target["project"]]
    return f"Moved agent '{target['name']}' to platform '{p['name']}'."


def run_action(act):
    if not isinstance(act, dict):
        return "Skipped an unknown action."
    kind = act.get("type")
    if kind == "assign":
        target, task = find_agent(act.get("agent", "")), act.get("task")
        if not target or target.get("isDirector"):
            return f"Skipped: no agent named '{str(act.get('agent'))[:40]}'."
        if not isinstance(task, str) or not task.strip():
            return f"Skipped: empty task for {target['name']}."
        try:
            begin_task(target, task.strip()[:MAX_MESSAGE_CHARS], by="director", names=act.get("include_notes_from") or [])
        except ApiError as e:
            return f"Could not assign to {target['name']}: {e.message}."
        return f"Assigned to {target['name']}: {task.strip()[:160]}"
    if kind == "create_platform":
        return dir_create_platform(act)
    if kind == "create_agent":
        return dir_create_agent(act)
    if kind == "delete_platform":
        return dir_delete_platform(act)
    if kind == "delete_agent":
        return dir_delete_agent(act)
    if kind == "move_agent":
        return dir_move_agent(act)
    return "Skipped an unknown action."


def try_review():
    global review_pending, auto_rounds
    with lock:
        if not review_pending or director_busy or not settings["autoReview"] or not current_director():
            return
        if any(a["status"] == "working" and a.get("by") == "director" for a in agents.values()):
            return
        review_pending = False
        if auto_rounds >= MAX_AUTO_ROUNDS:
            add_chat("system", f"Auto-follow-up stopped after {MAX_AUTO_ROUNDS} rounds. Send a message to continue.")
            save()
            broadcast()
            return
        auto_rounds += 1
    director_turn()


# ---------- operations ----------

def create_project(d):
    if not isinstance(d, dict):
        raise ApiError(400, "Invalid request")
    name, desc = str(d.get("name", "")).strip(), str(d.get("description", "")).strip()
    if not 1 <= len(name) <= 40:
        raise ApiError(400, "Name must be 1-40 characters")
    if len(desc) > 500:
        raise ApiError(400, "Description is too long (max 500 characters)")
    q, r = d.get("q"), d.get("r")
    if not all(isinstance(v, int) and not isinstance(v, bool) and -8 <= v <= 8 for v in (q, r)):
        raise ApiError(400, "Invalid platform position")
    with lock:
        existing = next((p for p in projects.values() if p["name"].strip().lower() == name.lower()), None)
        if existing:
            raise ApiError(400, f"A platform named '{existing['name']}' already exists (id {existing['id']})")
        if len(projects) >= MAX_PROJECTS:
            raise ApiError(400, f"Platform limit ({MAX_PROJECTS}) reached")
        taken = {(p["q"], p["r"]) for p in projects.values()}
        if (q, r) in taken:
            raise ApiError(400, "That spot is already taken")
        if taken and not any((q + dq, r + dr) in taken for dq, dr in NEIGHBORS):
            raise ApiError(400, "Place the platform next to an existing one")
        if not taken and (q, r) != (0, 0):
            raise ApiError(400, "The first platform goes in the middle")
        p = {"id": uuid.uuid4().hex[:8], "name": name, "description": desc, "q": q, "r": r, "created": time.time()}
        projects[p["id"]] = p
        save()
        broadcast()
        return dict(p)


def move_project(pid, d):
    """Move a platform to another hex spot. The body must be a JSON object with integer q and r."""
    if not isinstance(d, dict):
        raise ApiError(400, "Invalid request")
    q, r = d.get("q"), d.get("r")
    if not all(isinstance(v, int) and not isinstance(v, bool) and -8 <= v <= 8 for v in (q, r)):
        raise ApiError(400, "Invalid platform position")
    with lock:
        p = projects.get(pid)
        if not p:
            raise ApiError(404, "Platform not found")
        taken = {(x["q"], x["r"]) for x in projects.values() if x["id"] != pid}
        if (q, r) in taken:
            raise ApiError(400, "That spot is already taken")
        if taken and not any((q + dq, r + dr) in taken for dq, dr in NEIGHBORS):
            raise ApiError(400, "Place the platform next to an existing one")
        p["q"], p["r"] = q, r
        save()
        broadcast()
        return dict(p)


def delete_project(pid):
    with lock:
        if pid not in projects:
            raise ApiError(404, "Platform not found")
        if any(a["project"] == pid for a in agents.values()):
            raise ApiError(409, "Delete or move this platform's agents first")
        del projects[pid]
        save()
        broadcast()
    return {"ok": True}


def create_agent(d):
    if not isinstance(d, dict):
        raise ApiError(400, "Invalid request")
    name, role, backend = str(d.get("name", "")).strip(), str(d.get("role", "")).strip(), d.get("backend")
    model = str(d.get("model", "")).strip()
    if not 1 <= len(name) <= 40:
        raise ApiError(400, "Name must be 1-40 characters")
    if len(role) > 2000:
        raise ApiError(400, "Role is too long (max 2000 characters)")
    if backend not in RUNNERS:
        raise ApiError(400, "Unknown worker type")
    if backend == "mock":
        model = "mock"
    elif backend == "claude":
        if model not in CLAUDE_MODELS:
            raise ApiError(400, "Claude model must be opus, sonnet or haiku")
    elif not MODEL_RE.match(model) or model.startswith("-"):
        raise ApiError(400, "Enter a model id (letters, digits and . _ : / - only)")
    elif backend.startswith("opencode") and not model.startswith("opencode/"):
        raise ApiError(400, "OpenCode models must start with 'opencode/' (the free models), e.g. opencode/big-pickle")
    with lock:
        if d.get("project") not in projects:
            raise ApiError(400, "Choose a platform for this agent")
        if len(agents) >= MAX_AGENTS:
            raise ApiError(400, f"Agent limit ({MAX_AGENTS}) reached")
        if any(a["name"].strip().lower() == name.lower() for a in agents.values()):
            raise ApiError(400, "An agent with that name already exists")
        aid = uuid.uuid4().hex[:8]
        agent = {"id": aid, "name": name, "role": role, "backend": backend, "model": model, "project": d["project"],
                 "isDirector": False, "created": time.time(), "status": "idle", "task": "", "output": "",
                 "error": "", "summary": "", "by": "user", "startedAt": None, "finishedAt": None, "history": [],
                 "notesFile": f"{slug(name)}-{aid}.md"}
        agents[aid] = agent
        if d.get("isDirector") is True:
            for other in agents.values():
                other["isDirector"] = other["id"] == aid
        write_notes(agent)
        save()
        broadcast()
        return dict(agent)


def start_task(agent_id, d):
    task = str(d.get("task", "")).strip() if isinstance(d, dict) else ""
    if not task:
        raise ApiError(400, "Task is empty")
    if len(task) > MAX_MESSAGE_CHARS:
        raise ApiError(400, f"Task is too long ({len(task)} characters, max {MAX_MESSAGE_CHARS})")
    with lock:
        a = agents.get(agent_id)
        if not a:
            raise ApiError(404, "Agent not found")
        if a.get("isDirector"):
            raise ApiError(400, "Talk to the Director in the chat bar instead")
        begin_task(a, task, by="user")
    return {"ok": True}


def set_director(agent_id):
    with lock:
        if agent_id not in agents:
            raise ApiError(404, "Agent not found")
        for a in agents.values():
            a["isDirector"] = a["id"] == agent_id
        save()
        broadcast()
    return {"ok": True}


def move_agent(agent_id, platform_key):
    """Move an agent onto another platform. Resolves the platform by id or by unique name."""
    target, err = find_project(platform_key)
    if not target:
        code = 409 if str(err).startswith("several platforms") else 404 if str(err).startswith("platform") else 400
        raise ApiError(code, err)
    with lock:
        a = agents.get(agent_id)
        if not a:
            raise ApiError(404, "Agent not found")
        if a["status"] == "working":
            raise ApiError(409, "This agent is working right now")
        if a["project"] == target["id"]:
            raise ApiError(409, f"{a['name']} is already on platform '{target['name']}'")
        a["project"] = target["id"]
        try:
            write_notes(a)
        except OSError as e:
            print(f"Could not write notes: {e}", file=sys.stderr)
        save()
        broadcast()
    return {"ok": True, "name": a["name"], "project": target["id"], "platform": target["name"]}


def delete_agent(agent_id):
    with lock:
        if agents.pop(agent_id, None) is None:
            raise ApiError(404, "Agent not found")
        save()
        broadcast()
    return {"ok": True}


def send_chat(d):
    global auto_rounds, review_pending
    text = str(d.get("text", "")).strip() if isinstance(d, dict) else ""
    if not text:
        raise ApiError(400, "Message is empty")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ApiError(400, f"Message is too long ({len(text)} characters, max {MAX_MESSAGE_CHARS})")
    with lock:
        if not current_director():
            raise ApiError(400, "Make one agent the Director first")
        if director_busy:
            raise ApiError(409, "The Director is still busy")
        add_chat("user", text)
        auto_rounds, review_pending = 0, False
        director_turn()
    return {"ok": True}


def read_notes(agent_id):
    with lock:
        a = agents.get(agent_id)
        if not a:
            raise ApiError(404, "Agent not found")
        path = NOTES_DIR / a["notesFile"]
    try:
        return {"text": path.read_text(encoding="utf-8")[:20_000]}
    except OSError:
        return {"text": "(no notes yet)"}


# ---------- HTTP ----------

ID = "([0-9a-f]{8})"
TASK_ROUTE = re.compile(rf"^/api/agents/{ID}/task$")
MOV_ROUTE = re.compile(rf"^/api/agents/{ID}/move$")
DIRECTOR_ROUTE = re.compile(rf"^/api/agents/{ID}/director$")
AGENT_ROUTE = re.compile(rf"^/api/agents/{ID}$")
PROJECT_ROUTE = re.compile(rf"^/api/projects/{ID}$")
PROJ_MOV_ROUTE = re.compile(rf"^/api/projects/{ID}/move$")
NOTES_ROUTE = re.compile(rf"^/api/notes/{ID}$")
MODELS_ROUTE = re.compile(r"^/api/models/(gemini|openrouter|opencode|opencode-readonly|claude)$")


PLATFORMS_DIR = ROOT / "platforms"  # experimental variants / screenshots (platforms/coding/)
PLATFORM_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
}
VENDOR_DIR = ROOT / "vendor"
VENDOR_DIR.mkdir(exist_ok=True)
VENDOR_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
}


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
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
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

    def _serve_vendor(self, path):
        rel = urllib.parse.unquote(path[len("/vendor/"):])
        if not rel or "\x00" in rel:
            raise ApiError(404, "Not found")
        try:
            target = (VENDOR_DIR / rel).resolve()
            target.relative_to(VENDOR_DIR.resolve())
        except (ValueError, OSError):
            raise ApiError(403, "Forbidden") from None
        if not target.is_file():
            raise ApiError(404, "Not found")
        ctype = VENDOR_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    def _serve_platforms(self, path):
        rel = urllib.parse.unquote(path[len("/platforms/"):])
        if not rel or "\x00" in rel:
            raise ApiError(404, "Not found")
        try:
            target = (PLATFORMS_DIR / rel).resolve()
            target.relative_to(PLATFORMS_DIR.resolve())
        except (ValueError, OSError):
            raise ApiError(403, "Forbidden") from None
        if not target.is_file():
            raise ApiError(404, "Not found")
        ctype = PLATFORM_TYPES.get(target.suffix.lower())
        if ctype is None:
            raise ApiError(404, "Not found")
        self._send(200, target.read_bytes(), ctype)

    def _get(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/mictest.html":
            self._send(200, (ROOT / "mictest.html").read_bytes(), "text/html; charset=utf-8")
        elif path in ("/index_3d", "/index_3d.html", "/index-daily", "/index-daily.html",
                      "/index_style_a", "/index_style_a.html", "/index_style_b", "/index_style_b.html"):
            # experimental design variants live in platforms/coding/; both /name and /name.html work
            name = path.lstrip("/")
            if not name.endswith(".html"):
                name += ".html"
            self._send(200, (PLATFORMS_DIR / "coding" / name).read_bytes(), "text/html; charset=utf-8")
        elif path.startswith("/platforms/"):
            self._serve_platforms(path)
        elif path.startswith("/vendor/"):
            self._serve_vendor(path)
        elif path == "/api/state":
            self._json(200, snapshot())
        elif path == "/api/events":
            self._events()
        elif NOTES_ROUTE.match(path):
            self._json(200, read_notes(NOTES_ROUTE.match(path).group(1)))
        elif MODELS_ROUTE.match(path):
            try:
                self._json(200, {"models": list_models(MODELS_ROUTE.match(path).group(1))})
            except Exception as e:
                self._json(200, {"models": [], "error": str(e)[:300]})
        else:
            raise ApiError(404, "Not found")

    def _post(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/projects":
            self._json(201, create_project(self._read_json()))
        elif path == "/api/agents":
            self._json(201, create_agent(self._read_json()))
        elif path == "/api/chat":
            self._json(202, send_chat(self._read_json()))
        elif path == "/api/autoreview":
            data = self._read_json()
            with lock:
                settings["autoReview"] = bool(data.get("on")) if isinstance(data, dict) else True
                save()
                broadcast()
            self._json(200, {"ok": True})
        elif TASK_ROUTE.match(path):
            self._json(202, start_task(TASK_ROUTE.match(path).group(1), self._read_json()))
        elif MOV_ROUTE.match(path):
            data = self._read_json()
            if not isinstance(data, dict):
                raise ApiError(400, "Invalid request")
            self._json(200, move_agent(MOV_ROUTE.match(path).group(1), data.get("platform", "")))
        elif PROJ_MOV_ROUTE.match(path):
            data = self._read_json()
            if not isinstance(data, dict):
                raise ApiError(400, "Invalid request")
            self._json(200, move_project(PROJ_MOV_ROUTE.match(path).group(1), data))
        elif DIRECTOR_ROUTE.match(path):
            self._json(200, set_director(DIRECTOR_ROUTE.match(path).group(1)))
        else:
            raise ApiError(404, "Not found")

    def _delete(self):
        path = urllib.parse.urlparse(self.path).path
        if AGENT_ROUTE.match(path):
            self._json(200, delete_agent(AGENT_ROUTE.match(path).group(1)))
        elif PROJECT_ROUTE.match(path):
            self._json(200, delete_project(PROJECT_ROUTE.match(path).group(1)))
        else:
            raise ApiError(404, "Not found")

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


def parse_args():
    p = argparse.ArgumentParser(description="Agent HQ server. Plain HTTP by default; "
                                            "--https enables HTTPS so LAN addresses become a secure context "
                                            "(needed for the microphone / Web Speech API).")
    p.add_argument("--https", action="store_true", help="serve over HTTPS instead of plain HTTP")
    p.add_argument("--certfile", help="TLS certificate PEM file (default: certs/cert.pem next to server.py)")
    p.add_argument("--keyfile", help="TLS private key PEM file (default: certs/key.pem next to server.py)")
    return p.parse_args()


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    return sorted(ips)


def ensure_tls_cert(certfile, keyfile, lan):
    """Return (cert, key) paths. Without --certfile/--keyfile, reuse or generate a self-signed
    pair in certs/ next to server.py; generation needs the optional 'cryptography' package."""
    if bool(certfile) != bool(keyfile):
        sys.exit("Error: --certfile and --keyfile must be given together.")
    certs = ROOT / "certs"
    cert = Path(certfile) if certfile else certs / "cert.pem"
    key = Path(keyfile) if keyfile else certs / "key.pem"
    if cert.exists() and key.exists():
        return cert, key
    extra = "".join(f",IP:{ip}" for ip in lan)
    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        sys.exit(
            "HTTPS needs a TLS certificate, and the optional 'cryptography' package is not installed.\n"
            "Either install it and restart:\n"
            "    pip install cryptography\n"
            "or create the certificate yourself with openssl, then start the server again with --https:\n\n"
            f'    openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes -keyout "{key}" '
            f'-out "{cert}" -subj "/CN=agent-hq" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1{extra}"')
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent-hq")])
    sans = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
    sans += [x509.IPAddress(ipaddress.IPv4Address(ip)) for ip in lan]
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(minutes=5))
         .not_valid_after(now + datetime.timedelta(days=825))
         .add_extension(x509.SubjectAlternativeName(sans), critical=False)
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=False)
         .sign(k, hashes.SHA256()))
    cert.parent.mkdir(parents=True, exist_ok=True)
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return cert, key


def main():
    args = parse_args()
    load_env()
    refresh_timeouts()
    refresh_limits()
    load()
    if not args.https:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        server.daemon_threads = True
        print(f"Agent HQ running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    else:
        global ALLOWED_HOSTS, ALLOWED_ORIGINS
        lan = lan_ips()
        hosts = ("localhost", "127.0.0.1", *lan)
        ALLOWED_HOSTS = {f"{h}:{PORT}" for h in hosts}
        ALLOWED_ORIGINS = {f"https://{h}:{PORT}" for h in hosts}
        cert, key = ensure_tls_cert(args.certfile, args.keyfile, lan)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ctx.load_cert_chain(cert, key)
        except (ssl.SSLError, OSError) as e:
            sys.exit(f"Error: could not load the TLS certificate '{cert}' / key '{key}': {e}")
        server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
        server.daemon_threads = True
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        print(f"Agent HQ running at https://127.0.0.1:{PORT}  (Ctrl+C to stop, self-signed certificate)")
        for ip in lan:
            print(f"  also at https://{ip}:{PORT}  (accept the browser certificate warning once)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
