# GLM 5.2 via OpenRouter — Feasibility Check

**Date:** 2026-09-21 | **Repo:** `C:\Users\tepeg\agent-hq` | **Status: Research only, no code changes.**

---

## 1. All GLM Slugs on OpenRouter (21 total, raw API data)

| Slug | Name | Prompt ($/tok) | Completion ($/tok) | Context |
|------|------|---------------|-------------------|---------|
| z-ai/glm-5.3-flashx | GLM 5.3 FlashX | 0.00000037 | 0.00000125 | 1,048,576 |
| z-ai/glm-flash-latest | GLM Flash Latest | 0.000000075 | 0.00000025 | 1,310,720 |
| z-ai/glm-5.3-flash | GLM 5.3 Flash | 0.00000009 | 0.00000030 | 1,310,720 |
| z-ai/glm-5.3-flash:batch | GLM 5.3 Flash (batch) | 0.000000075 | 0.00000025 | 1,048,576 |
| z-ai/glm-latest | GLM Latest | 0.0000007728 | 0.0000024288 | 1,310,720 |
| z-ai/glm-5.3 | GLM 5.3 | 0.00000091 | 0.00000286 | 1,310,720 |
| z-ai/glm-5.3:batch | GLM 5.3 (batch) | 0.00000070 | 0.00000220 | 1,048,576 |
| **z-ai/glm-5.2** | **GLM 5.2** | **0.0000006496** | **0.0000020416** | **1,048,576** |
| z-ai/glm-5.2:batch | GLM 5.2 (batch) | 0.00000070 | 0.00000220 | 1,048,576 |
| **z-ai/glm-5.2:free** | **GLM 5.2 (free)** | **0** | **0** | **32,768** |
| z-ai/glm-5.1 | GLM 5.1 | 0.000000966 | 0.000003036 | 204,800 |
| z-ai/glm-5v-turbo | GLM 5V Turbo | 0.0000012 | 0.000004 | 202,752 |
| z-ai/glm-5-turbo | GLM 5 Turbo | 0.0000012 | 0.000004 | 202,752 |
| z-ai/glm-5 | GLM 5 | 0.0000006 | 0.00000192 | 204,800 |
| z-ai/glm-4.7-flash | GLM 4.7 Flash | 0.0000000605 | 0.0000004 | 200,000 |
| z-ai/glm-4.7 | GLM 4.7 | 0.0000004 | 0.00000175 | 204,800 |
| z-ai/glm-4.6v | GLM 4.6V | 0.0000003 | 0.0000009 | 131,072 |
| z-ai/glm-4.6 | GLM 4.6 | 0.00000043 | 0.00000175 | 204,800 |
| z-ai/glm-4.5v | GLM 4.5V | 0.0000006 | 0.0000018 | 65,536 |
| z-ai/glm-4.5 | GLM 4.5 | 0.0000006 | 0.0000022 | 131,072 |
| z-ai/glm-4.5-air | GLM 4.5 Air | 0.00000013 | 0.00000085 | 131,072 |

Source: `https://openrouter.ai/api/v1/models` (dumped to `openrouter_models.json`)

---

## 2. Does GLM 5.2 exist? Is it free?

**GLM 5.2 exists:** YES — as `z-ai/glm-5.2` (paid, 0.0000006496/0.0000020416, 1M ctx).

**GLM 5.2 :free exists:** YES — as `z-ai/glm-5.2:free` with **prompt=0, completion=0**. This is the only `:free` variant in the GLM family. It has a **32,768-token context window**.

The `:free` suffix is OpenRouter's official free-model variant marker (`server.py:528` — `models_openrouter()` detects `m.get("id","").endswith(":free")`).

---

## 3. Free-Tier Limits (from OpenRouter docs)

| Limit | Free account | After $10+ credits |
|-------|-------------|-------------------|
| Requests/day | **50** | **1,000** |
| Requests/minute | **20** | **20** |
| $10 threshold | Once purchased, permanent | |
| Failed requests | **Count against daily quota** | Same |
| Context window (free variant) | **32,768 tokens** (smaller than paid 1M) | |
| SLA | None — provider availability varies | |
| Key check | `GET /api/v1/key` | |

**Critical for agent-hq:** 20 RPM = one request every 3 seconds. 50 RPD is extremely tight for tool-heavy agent runs. Failed/retried requests consume quota. The 32K context window is a hard limit — long-running tasks with large tool outputs will truncate.

---

## 4. Comparison vs. Current Setup

| | Current (9/12 agents) | GLM 5.2 :free |
|---|---|---|
| **Model** | `openrouter/z-ai/glm-5.3-flash` | `openrouter/z-ai/glm-5.2:free` |
| **Backend** | `opencode` | `opencode` (same) |
| **Prompt cost** | 0.00000009 | **0** |
| **Completion cost** | 0.00000030 | **0** |
| **Context window** | **1,310,720** | **32,768** |
| **Speed/quality** | GLM 5.3 (newer) | GLM 5.2 (older) |
| **Rate limits** | Paid, no platform cap | 50 RPD / 20 RPM |

**Assessment:** GLM 5.2 :free is **only useful as a fallback**, not a swap:
- **Context window drops from 1.3M to 32K** — a ~40x reduction. Tool-heavy agent runs will truncate.
- **Rate limits (50 RPD)** will exhaust instantly with 12 agents making concurrent requests.
- **GLM 5.2 is a downgrade** from GLM 5.3 in capability.
- **Lena/Kai** on `opencode/ling-3.0-flash-fin-free` are unaffected — they don't use GLM.
- The 9 GLM agents (`Sophie, Theo, Mara, Jonas, Noah, Elif, Finn, Ravi, Nina`) would be severely impaired.

**Recommendation: DO NOT switch to GLM 5.2 :free for production agents.** It could serve as an emergency fallback for trivial one-off tasks if all other options fail, but the 32K context and 50 RPD cap make it unsuitable for the team's tool-heavy agent workload. If free models are needed, `z-ai/glm-5.3-flash` (0.00000009/0.0000003, 1.3M ctx) is the only free GLM variant that is even remotely viable — but it's not free on OpenRouter (it has a price).

---

## 5. Config Locations for Switching Agent Models

### Primary config file — `data/state.json`
The 9 GLM agents store their model ID here. Each agent entry has `"backend": "opencode"` and `"model": "openrouter/z-ai/glm-5.3-flash"`.

**Lines in `data/state.json`** (agent model fields): 171, 200, 229, 266, 360, 413, 466, 511, 540 — all contain `"model": "openrouter/z-ai/glm-5.3-flash"`.

To switch to GLM 5.2 :free, change all 9 occurrences from `"openrouter/z-ai/glm-5.3-flash"` to `"openrouter/z-ai/glm-5.2:free"`.

### Switch script — `tools/switch_to_glm.py`
- **Line 18:** `NEW_MODEL = "openrouter/z-ai/glm-5.3-flash"` → change to `"openrouter/z-ai/glm-5.2:free"`
- **Line 19:** `BACKEND = "opencode"` (unchanged)
- **Lines 20:** `TARGETS = ["Sophie", "Theo", "Mara", "Jonas", "Noah", "Elif", "Finn", "Ravi", "Nina"]` (the 9 agents)
- **Line 66:** `agent["model"] = NEW_MODEL` (assignment point)

### Server code — `server.py`
- **Line 721-722:** `DEFAULT_MODELS` dict — default model per backend (no GLM here; defaults are `opencode/big-pickle`, etc.)
- **Line 779:** `dir_create_agent()` — `model = str(act.get("model") or "").strip() or DEFAULT_MODELS.get(backend, "")`
- **Line 357:** `def run_openrouter(agent, task):` — sends `{"model": agent["model"], ...}` directly to OpenRouter API
- **Line 948:** `def create_agent(d):` — API-level agent creation
- **Line 966-967:** Validation — `elif backend.startswith("opencode") and not model.startswith("opencode/"): raise ApiError(400, ...)` — **IMPORTANT**: This validation would block creating new agents with backend `opencode` and model `openrouter/z-ai/glm-5.2:free`. Switching existing agents in `state.json` directly (like `switch_to_glm.py` does) bypasses this check.
- **Line 528-500:** `models_openrouter()` — free model detection (`m.get("id","").endswith(":free")`)
- **Line 562:** `RUNNERS` dict — maps `opencode` backend to `run_opencode()`
- **Line 396:** `run_opencode()` — passes `agent["model"]` to `opencode run -m` CLI

### Frontend — `index.html`
- **Line 964:** `const modelDefaults = { gemini: 'gemini-3.1-flash-lite', opencode: 'opencode/big-pickle', ... }` — frontend dropdown defaults (doesn't affect configured agents)

### Tests — `tests/conftest.py`
- **Lines 59-61:** `DEFAULT_MODEL = {"mock": "mock", "claude": "sonnet", "opencode": "opencode/big-pickle", "opencode-readonly": "opencode/big-pickle", "openrouter": "vendor/model:free", "gemini": "gemini-test"}` — test fixture only

### Documentation — `docs/agent-model-audit.md`
- Lines 1-89: Full audit of all agent model configurations

### Other notes
- `data/state.json` lines 1120, 1235, 1240, 1245, 1260: Chat history entries referencing GLM 5.3 Flash
- `data/notes/lena-g-3bbd3144.md:7`: Historical note about `glm-4-flash`
- `data/notes/vera-cd09dcc8.md:7-9,15-17`: GLM switch protocol documentation

---

## SUMMARY

- **GLM 5.2 :free exists** (`z-ai/glm-5.2:free`, prompt=0, completion=0) but has only **32K context** and **50 RPD / 20 RPM** rate limits.
- **DO NOT switch** the 9 GLM agents to GLM 5.2 :free — the 40x context reduction and severe rate caps make it unsuitable for tool-heavy agent runs. It is only a last-resort fallback.
- **Current GLM 5.3 Flash** (1.3M ctx, paid) is the viable free-ish option; `z-ai/glm-5.3-flash` is NOT free on OpenRouter but is affordable and far more capable.
- **Config change location:** `data/state.json` (9 agent model fields) + `tools/switch_to_glm.py:18` (NEW_MODEL constant). `server.py:966-967` blocks new API-created agents with `openrouter/` models on `opencode` backend, so direct `state.json` editing is the only switch method.
