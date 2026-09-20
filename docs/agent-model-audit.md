# Agent-Modell-Audit agent-hq (2026-09-20)

Nur gelesen; einzige geschriebene Datei ist diese. Nichts committet, Server nicht neu gestartet.

## 1. Zentrale Definitionen (Defaults / Mapping)

- `server.py:35`: `PROVIDER_TIMEOUT, OPENCODE_TIMEOUT, CLAUDE_TIMEOUT = 120, 900, 300` – kein Modell, aber belegt 15-Min-Kill (OPENCODE) vs 5-Min-Kill (CLAUDE).
- `server.py:37`: `CLAUDE_MODELS = ("opus", "sonnet", "haiku")`.
- `server.py:330`: `run_opencode` baut `cmd = [exe, "run", "-m", agent["model"], ...]` – Backend `opencode` heisst: Modell-ID wird 1:1 an `opencode run -m` uebergeben.
- `server.py:270`: `run_openrouter` sendet `{"model": agent["model"], ...}` direkt an OpenRouter.
- `server.py:579-580`: `DEFAULT_MODELS = {"claude": "sonnet", "mock": "mock", "opencode": "opencode/big-pickle", "opencode-readonly": "opencode/big-pickle", "gemini": "gemini-3.1-flash-lite"}` – greift, wenn bei create_agent kein Modell angegeben (`server.py:636-637`).
- `server.py:824-825`: Validierung – `opencode*`-Backend braucht Modell mit Prefix `opencode/`, sonst 400.
- `server.py:636`: Backend-Default bei create_agent ist `claude`.
- `index.html:884`: gleiche Defaults im Frontend (`modelDefaults`).
- `tools/switch_to_glm.py:18-20`: `NEW_MODEL = "openrouter/z-ai/glm-5.3-flash"`, `BACKEND = "opencode"`, Targets Sophie/Theo/Mara/Jonas/Noah/Elif/Finn/Ravi/Nina (9 Agenten; Lena/Kai/Muse Spark bewusst ausgenommen).
- Plattform-IDs: `data/state.json:2-42` (Main=c3cf1477, Research=a0345598, Coding=6d1fe0d0, Debugging=73a8f77a, Tester=d38e9869).

## 2. Agent-Tabelle (alle zwoelf)

Hinweis zu Spalte 5: `data/state.json` speichert pro Agent nur EIN Modell-Feld (`backend`+`model`); ein separates Feld "zuletzt tatsaechlich benutzte Modell-ID" existiert im Code nicht (`worker` in `server.py:460-463` nutzt einen Snapshot des Agenten zum Task-Start). Daher Spalte 5 = `unbekannt` (kein separates Feld), ausser es ist anders belegt.

| Agent | Plattform | Backend | Modell-ID (konfiguriert) | Modell-ID (tatsaechlich benutzt) | Quelle |
|---|---|---|---|---|---|
| Muse Spark | Coding | opencode | opencode/muse-spark-1.3-contributor-free | unbekannt (kein separates Feld) | data/state.json:67-70 |
| Sophie | Main | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:168-171 |
| Theo | Tester | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:197-200 |
| Mara | Debugging | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:226-229 |
| Jonas | Main | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:263-266 |
| Lena | Research | opencode | opencode/ling-3.0-flash-fin-free | unbekannt (kein separates Feld) | data/state.json:292-295 |
| Kai | Research | opencode | opencode/ling-3.0-flash-fin-free | unbekannt (kein separates Feld) | data/state.json:337-340 |
| Noah | Coding | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:357-360 |
| Elif | Coding | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:410-413 |
| Finn | Coding | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:463-466 |
| Ravi | Debugging | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:508-511 |
| Nina | Tester | opencode | openrouter/z-ai/glm-5.3-flash | unbekannt (kein separates Feld) | data/state.json:537-540 |

Ausserhalb der Zwoelf (nur zur Vollstaendigkeit): Director Opus 5, Main, backend `claude`, model `opus` – `data/state.json:47-50`.

## 3. Ling-Markierung

- Auf Ling (`opencode/ling-3.0-flash-fin-free`, die einzig als funktionierend ermittelte ID – siehe `data/state.json:96` History-Eintrag Muse Spark: "Working ID: opencode/ling-3.0-flash-fin-free (wrong was opencode/ling-3.0-flash-free)"): **Lena, Kai** (je 2 von 12).
- NICHT auf Ling (10 von 12): **Muse Spark** (`opencode/muse-spark-1.3-contributor-free`) sowie **Sophie, Theo, Mara, Jonas, Noah, Elif, Finn, Ravi, Nina** (alle `openrouter/z-ai/glm-5.3-flash` ueber Backend `opencode`, d.h. OpenCode routet auf OpenRouter-GLM – `server.py:330` + `tools/switch_to_glm.py:18-19`).
- Historie: vor dem GLM-Switch liefen die 9 GLM-Agenten auf `opencode/ling-3.0-flash-fin-free` (belegt in `data/notes/vera-cd09dcc8.md:9` und Backup `data/state.backup-20260919-235446.json:163,192,221,241,261,281,301,338,367,396,425`).

## 4. Zusatzfrage: GLM / Ring / Terminal / Flash / DeepSeek / Ling im Repo

Volltextsuche case-insensitive ueber das Repo (ohne .git/__pycache__/.pytest_cache, Dateien >2MB uebersprungen). Jeder Treffer mit Datei:Zeile:

**glm (Modell-IDs / Skript):**
- `tools/switch_to_glm.py:2`: Docstring "Switch nine named agents ... to the GLM model"
- `tools/switch_to_glm.py:18`: `NEW_MODEL = "openrouter/z-ai/glm-5.3-flash"`
- `data/state.json:171,200,229,266,360,413,466,511,540`: 9x `"model": "openrouter/z-ai/glm-5.3-flash"` (Sophie/Theo/Mara/Jonas/Noah/Elif/Finn/Ravi/Nina)
- `data/notes/vera-cd09dcc8.md:7-9,15-17`: Umschalt-Protokoll (Skriptpfad, dry-run 9 Agenten ling→glm, Test `ok` mit Header `z-ai/glm-5.3-flash`)
- `data/notes/lena-g-3bbd3144.md:7`: `(a) Model ID: glm-4-flash (5.3 not found).`
- `data/state.json:1120,1235,1240,1245,1260`: Chatverlauf zum GLM-Switch ("GLM 5.3 flash", "coders are now GLM 5.3 Flash", "Nina ... is on GLM 5.3 Flash")
- `make_presentation.py:153`: nur Prosa `z.ai/GLM, Kimi/Moonshot, ...` (keine Modell-ID)
- `make_hermes_v2.py:358`: nur Prosa `Also DeepSeek, xAI, ...` (keine Modell-ID)

**deepseek:**
- `data/agents.json:4`: `"name": "Director Deepseek V4 Flash"` (Legacy-Datei, nicht state.json)
- `data/agents.json:7`: `"model": "deepseek/deepseek-v4-flash-0731:free"` mit `"backend": "openrouter"` (`data/agents.json:6`) – EINZIGE DeepSeek-V4-Flash-0731-ID im Repo; liegt in der Legacy-Datei `data/agents.json`, die `server.py:159-160` nur laedt, wenn `state.json` fehlt. Aktuell ist `state.json` massgeblich, dort steht diese ID nirgends als konfiguriertes Agenten-Modell.
- `data/agents.json:34,42`: nur Erwaehnungen in Agent-Output-Text (`DeepSeek V4 Flash` in Bestenliste), keine Konfiguration.

**flash (Modell-IDs, ohne reine Prosa):**
- `bench_v2.py:48-50`: `DEFAULT_MODELS = ["opencode/ling-3.0-flash-fin-free", "opencode/muse-spark-1.2-contributor-free", "opencode/muse-spark-1.3-contributor-free", "opencode/big-pickle", "opencode/mimo-v2.5-free", ...]` – Bench-Defaults, keine Agenten-Konfiguration.
- `server.py:387`: Sortierschluessel `"flash-lite"/"flash"` in `models_gemini()` (Code, keine ID).
- `server.py:580`: `"gemini": "gemini-3.1-flash-lite"` (Default, kein Agent nutzt ihn aktuell).
- `index.html:884,886` (+ Varianten `platforms/coding/index_3d.html:965,967`, `platforms/coding/index_style_a.html:850,852`, `platforms/coding/index_style_b.html:852,854`): Frontend-Defaults/Hinweistext zu Flash/Flash-Lite (kein Agent nutzt sie).
- `tests/test_notes_models_limits.py:103-104,111`: Test-Fixture `gemini-2.5-flash(-lite)` (nur Test).
- `data/bench_results.json:190,208,227,245,264` + `data/bench_v2_results.json:5,9,33,37,63,67,93,97,123,127`: historische Bench-Laeufe mit `"model": "opencode/ling-3.0-flash-fin-free"`.

**ling:**
- `data/state.json:295,340`: `opencode/ling-3.0-flash-fin-free` (Lena, Kai – aktuell).
- `data/notes/muse-spark-1d53dc1a.md:13-14`: Working-ID-Befund.
- `data/state.json:92,94,96,895,910,955,960,965,970`: History zum falschen `opencode/ling-3.0-flash-free` vs korrekten `-fin-`.
- `data/state.backup-20260919-235446.json`: diverse History-Zeilen (56,75,78,84,86,88,163ff,1109,1124,1149,1169,1174,1179,1184,1229,1234) – alte (falsche + korrekte) Ling-IDs nur in Verlauf/Backup, nicht aktuell konfiguriert ausser Lena/Kai.

**ring- / terminal als Modell-ID: KEIN TREFFER.**
- `grep -i "ring-"`: keine Modell-ID im Repo. Einzige "Ring"-Naehe: keine.
- `grep -i "terminal"`: nur Prosa – `make_presentation.py:122,177,224`, `make_hermes_v2.py:271,290,364` ("Seven terminal backends", "Reached from a terminal", "60+ built-in tools: terminal, files, web, browser"). KEINE Modell-ID wie `ring/terminal 3.8 flash` steht irgendwo im Repo.
- Aussage: Wenn im Router-Account `Ring/Terminal 3.8 Flash` auftaucht, kommt das NICHT aus einer im Repo gespeicherten Modell-ID – entweder Routing beim Anbieter (OpenCode/OpenRouter waehlt intern ein anderes Modell) oder Aufrufe von ausserhalb dieses Repos/States.

## SUMMARY

- Alle 12 Agenten laufen auf Backend `opencode`; 9x GLM (`openrouter/z-ai/glm-5.3-flash`), 2x Ling-fin (Lena, Kai), 1x Muse Spark.
- Ling-Agenten: nur Lena + Kai; alle anderen zehn nicht auf Ling.
- GLM-ID im Repo: `tools/switch_to_glm.py:18`, aktiv in `data/state.json` (9 Stellen).
- DeepSeek-V4-Flash-0731-ID steht NUR in Legacy `data/agents.json:7`, nicht in aktivem `state.json`.
- Ring/Terminal-3.8-Flash-ID steht NIRGENDS im Repo – Routing passiert beim Anbieter oder ausserhalb.
