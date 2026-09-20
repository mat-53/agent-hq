# Debug-Bericht: Agent-Laueufe werden nach 5 / 15 Minuten hart beendet

Nur-Lese-Analyse (nichts geaendert). Alle Belege als Datei:Zeile mit zitiertem Code.

## 1. Alle Timeouts/Limits im Code

**server.py (Produktionspfad):**
- server.py:35 - `PROVIDER_TIMEOUT, OPENCODE_TIMEOUT, CLAUDE_TIMEOUT = 120, 900, 300` (2 min / 15 min / 5 min)
- server.py:230 - `with urllib.request.urlopen(req, timeout=PROVIDER_TIMEOUT) as resp:` (OpenRouter/Gemini-HTTP)
- server.py:310-312 - `proc = subprocess.run(cmd, input=task, capture_output=True, text=True, ..., timeout=CLAUDE_TIMEOUT, ...)` (run_claude)
- server.py:313-314 - `except subprocess.TimeoutExpired: raise RuntimeError(f"The claude CLI took longer than {CLAUDE_TIMEOUT // 60} minutes and was stopped.")`
- server.py:335-337 - `proc = subprocess.run(cmd, capture_output=True, text=True, ..., timeout=OPENCODE_TIMEOUT, ...)` (run_opencode)
- server.py:338-339 - `except subprocess.TimeoutExpired: raise RuntimeError(f"OpenCode took longer than {OPENCODE_TIMEOUT // 60} minutes and was stopped.")`
- server.py:404 - `timeout=30` in `models_opencode` (nur Modelllisten-Abruf, unkritisch)
- server.py:1084 - `q.get(timeout=15)` in SSE `_events` (sendet nur `: ping` Keepalive, killt nichts)
- server.py:32-33 - `MAX_BODY, MAX_OUTPUT, MAX_HISTORY = 100_000, 20_000, 10`; `MAX_CHAT, MAX_AUTO_ROUNDS = 200, 4` (Groessen-Limits, keine Zeit-Kills)
- server.py:183-184 - `if a.get("status") == "working": a.update(status="failed", error="The server restarted while this task was running.", ...)` (Kill bei Server-Neustart; in data/state.json nachweisbar)

**Nicht-Produktionspfad (nur der Vollstaendigkeit halber):**
- bench.py:315 - `--timeout-min` default 15; bench.py:334 - `server.OPENCODE_TIMEOUT = max(60, args.timeout_min * 60)`
- bench_v2.py:1260/1296 - `--timeout-min` default 10, setzt ebenfalls `server.OPENCODE_TIMEOUT`
- tests/conftest.py:81,85 - Test-Stubs ("stub ... gate timeout"), irrelevant

**index.html (Browser):** KEIN einziger Kill-Timeout. Nur visuell:
- index.html:319 - `const DONE_VISUAL_MS = 30000;` ("done"-Haekchen wird nach 30 s optisch zu idle, index.html:338-339; Kommentar index.html:316-318)

## 2. Was erklaert 5 min und was 15 min

- **15 Minuten = OPENCODE_TIMEOUT**: server.py:35 (`900`) -> server.py:336 (`timeout=OPENCODE_TIMEOUT`). Betrifft die Backends `opencode` und `opencode-readonly`.
- **5 Minuten = CLAUDE_TIMEOUT**: server.py:35 (`300`) -> server.py:311 (`timeout=CLAUDE_TIMEOUT`). Betrifft Backend `claude`.
- **2 Minuten = PROVIDER_TIMEOUT**: server.py:35 (`120`) -> server.py:230. Betrifft `openrouter`/`gemini`.
- **Kausalkette** (identisch fuer beide): Task per UI/Director -> `start_task` (server.py:848) bzw. `run_action` -> `begin_task` setzt `status="working"` (server.py:453) und startet Daemon-Thread `worker` (server.py:457) -> `worker` ruft `RUNNERS[backend]` (server.py:463) -> `subprocess.run(..., timeout=...)` startet claude/opencode CLI und wartet auf Prozessende -> nach Ablauf toetet `subprocess.run` den CLI-Prozess und wirft `TimeoutExpired` -> server.py:313-314 bzw. 338-339 macht daraus `RuntimeError` -> `worker` faengt sie (server.py:467-468) und setzt `status="failed"`.
- **Hard evidence aus data/state.json** (Live-Daten): vier Agents mit `status = "failed"`, `error = "OpenCode took longer than 15 minutes and was stopped."` - exakt der String aus server.py:339. Der 5-min-Fall (claude) ist im Code gleich gebaut (server.py:314).

## 3. Client, Server oder Subprozess?

- **Serverseitig (Python)** - das ist die Ursache: `subprocess.run(timeout=...)` toetet den CLI-Prozess und wirft selbst die Exception (server.py:310-314, 335-339).
- **Browser (index.html): unschuldig.** `api()` nutzt `fetch` ohne AbortController/Timeout (index.html:568-573); `EventSource('/api/events')` reconnectet automatisch und macht bei `onerror` nur `$('#conn').classList.remove('on')` (index.html:601-604). Die Arbeit laeuft ohnehin im Server-Thread, ein Browser-Reload beeinflusst sie nicht.
- **Subprozess (CLI): unschuldig** als Initiator - er wird vom Python-Elternteil gekillt (kill durch `subprocess.run` bei Timeout). Eigene interne Limits der CLI sind im agent-hq-Code nicht konfiguriert; die beobachteten Fehler-Strings in state.json stammen woertlich aus server.py:314/339.

## 4. Was passiert mit der Teilarbeit beim Kill?

- **Beim Timeout wird ALLE Teilarbeit verworfen, Status wird `failed` (nicht `done`):** server.py:467-468 - `except Exception as e: output, status, error = "", "failed", str(e)`. Die bis zum Kill gestreamte CLI-Ausgabe geht verloren, weil `subprocess.run` bei Timeout keine Ausgabe zurueckgibt. Keine Zusammenfassung, kein History-Eintrag mit Inhalt - nur der Fehlertext.
- **"Zusammenfassungen mitten im Satz" haben eine ZWEITE, von Timeout unabhaengige Ursache: Truncation.** `extract_summary` (server.py:217-220): `return body.strip()[:1200] if idx != -1 else body.strip()[:500]` - schneidet hart ohne Ellipse. Beweis in data/state.json: zwei `done`-Summaries mit ~1200 Zeichen, endend mitten im Code `...$('#micBtn').disab`; eine mit exakt 500 Zeichen, endend `...server.py actually ser`. Auch: output-Kuerzung auf 20000 (server.py:476), History auf 4000 (server.py:479), Notes auf 800 (server.py:213), Chat auf 300 (server.py:489), Teammate-Kontext auf 3000 (server.py:440).
- **Es gibt DOCH einen "done trotz Abbruch"-Pfad:** in `run_opencode` wird bei Crash (`proc.returncode != 0`) die bereits gestreamte Teilausgabe trotzdem verwendet, solange `texts` oder `files` nicht leer sind - server.py:365-367: `if proc.returncode != 0 and not texts and not files: raise ...`; sonst `out = "\n\n".join(texts).strip()`. Ein extern getoeteter/gestauchter CLI-Lauf kann so mit `status="done"` und abgeschnittener Summary enden (server.py:466, 477-478). Der regelmaessige 5/15-min-Kill fuehrt dagegen sauber zu `failed`.

## 5. Fix-Vorschlaege (kleinster Eingriff zuerst) - NICHTS davon umgesetzt

1. **Timeout-Werte erhoehen / konfigurierbar machen (1 Zeile):** server.py:35, z. B. `PROVIDER_TIMEOUT, OPENCODE_TIMEOUT, CLAUDE_TIMEOUT = 120, int(os.environ.get("AGENT_HQ_OPENCODE_TIMEOUT", "7200")), int(os.environ.get("AGENT_HQ_CLAUDE_TIMEOUT", "7200"))`. `subprocess.run` akzeptiert auch `timeout=None` (= kein Kill). Kleinste Aenderung, sofortiger Effekt; Risiko: endlos laufende Prozesse werden nie aufgeraeumt.
2. **Status `timeout` statt `failed` (klein):** server.py:313-314 und 338-339 einen eigenen Fehlertyp werfen (z. B. `class RunTimeout(RuntimeError)`) und in `worker` server.py:467-468 darauf `status="timeout"` setzen; index.html:338-339 (`visualStatus`) und 585-588 um den neuen Status ergaenzen. Owner sieht den Unterschied zwischen echtem Fehler und Zeit-Abbruch.
3. **Teilausgabe beim Timeout retten (mittel):** statt `subprocess.run` `Popen` + `proc.communicate(timeout=...)` in try/except verwenden - `TimeoutExpired.e.output` enthaelt die bis dahin gesammelte Ausgabe. Stellen: server.py:309-318 (`run_claude`) und server.py:334-339 (`run_opencode`); Weiterverarbeitung in server.py:340-372 und 463-468. Teilarbeit + Summary ueberleben den Kill.
4. **Streaming/Heartbeat statt Wanduhr-Timeout (am saubersten):** `run_opencode` liest die JSON-Events (`--format json`, server.py:330) zeilenweise via `Popen.stdout` und aktualisiert periodisch `agent["output"]` + `broadcast()`; Timeout nur, wenn N Minuten lang KEIN Event kommt (Idle-Timeout statt Gesamtdauer). Stellen: server.py:321-372 (`run_opencode`), server.py:460-494 (`worker`), optional server.py:190-196 (`broadcast`). Aufwand am hoechsten, entspricht aber dem Wunsch "Agent laeuft wie ein offenes Terminal".
5. **Begleitfix (winzig, unabhaengig):** Truncation kenntlich machen: server.py:219-220 bei Zuschnitt `"…"` anhaengen; verhindert, dass abgeschnittene Zusammenfassungen wie vollstaendige aussehen.

## SUMMARY

- 15 min: `OPENCODE_TIMEOUT=900` (server.py:35) killt opencode-CLI via `subprocess.run(timeout=...)` (server.py:336) -> `failed`.
- 5 min: `CLAUDE_TIMEOUT=300` (server.py:35) killt claude-CLI (server.py:311) -> `failed`. 2 min: `PROVIDER_TIMEOUT=120` (server.py:230).
- Abbruch ist serverseitig (Python); Browser (index.html:569,601-604) und CLI sind unschuldig. Beweis: 4x `"OpenCode took longer than 15 minutes"` in data/state.json.
- Beim Timeout wird Teilarbeit verworfen und `failed` gesetzt (server.py:468); mid-sentence-Summaries stammen aus hartem Zuschnitt in `extract_summary` [:1200]/[:500] (server.py:220) - in state.json nachweisbar; Crash-Pfad kann `done` mit Teilausgabe liefern (server.py:365-367).
- Kleinster Fix: Timeout-Werte in server.py:35 erhoehen/env-konfigurierbar; sauberer: Status `timeout`, Teilausgabe retten, Streaming mit Idle-Timeout.
