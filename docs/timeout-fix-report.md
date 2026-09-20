# Timeout-Fix Report (CODE-FIX)

Stand: ALLE 5 Punkte umgesetzt. Pflicht-Pruefung bestanden. Kein Commit, kein Server-Neustart.

## 1. Timeouts per Env konfigurierbar, 0/leer = kein Timeout – ERLEDIGT
- `server.py:37-54`: `_parse_timeout(raw, default)` + `_get_timeout(name, default)` mit `os.environ.get`; `""`/`0`/negativ → `None` (= kein Timeout); ungueltig/nicht gesetzt → Default.
- `server.py:72-74`: Konstanten via `_get_timeout(...)` initialisiert; `server.py:77-82` + `server.py:1282` (`refresh_timeouts()` nach `load_env()` in `main()`), damit `.env`-Werte greifen.
- `server.py:291` (`http_json`), `server.py:371` (`run_claude`), `server.py:432` (`run_opencode`): Timeout je Aufruf frisch gelesen; `timeout=None` direkt an `subprocess.run`/`urlopen` (kein Crash; Formatierung via `server.py:57-62` `_fmt_timeout` statt `// 60` auf `None`).
- Verifiziert: `_parse_timeout('',3600)→None`, `'0'→None`, `None→Default`, `'abc'→Default`, `env OPENCODE_TIMEOUT=0→None`.

## 2. Neue Defaults 3600/3600/600 – ERLEDIGT
- `server.py:72-74` und `server.py:80-82`: `OPENCODE_TIMEOUT=3600`, `CLAUDE_TIMEOUT=3600`, `PROVIDER_TIMEOUT=600` (vorher 900/300/120). Verifiziert: Import zeigt `defaults: 3600 3600 600`.

## 3. TimeoutExpired: Teilergebnis retten – ERLEDIGT
- `server.py:65-69`: `TimeoutPartial(RuntimeError)` mit `.partial`-Payload.
- `server.py:373-382` (`run_claude`): `except TimeoutExpired as e` sichert `e.stdout`/`e.stderr`, wirft `TimeoutPartial("... abgebrochen nach X s, Teilergebnis erhalten.", partial)`.
- `server.py:389-411`: `_partial_opencode_output(...)` parst auch gekuerzte JSON-Lines (Texte/Dateien/Shell-Zaehler); `server.py:436-443` (`run_opencode`) wirft `TimeoutPartial` mit Teil-Output.
- `server.py:571-572` (`worker`): `except TimeoutPartial` → `output=partial`, `status="failed"`, `error=Hinweis` (statt `output=""` wie bisher in `server.py:573-574`).

## 4. `extract_summary` 6000/3000 + Satzgrenze – ERLEDIGT
- `server.py:264-274`: `_smart_truncate(text, limit)` schneidet an `\n`/Satzzeichen/Leerzeichen (nie mitten im Wort).
- `server.py:277-281`: `extract_summary` → `_smart_truncate(body, 6000)` (mit `SUMMARY:`) bzw. `_smart_truncate(body, 3000)` (ohne), statt `[:1200]`/`[:500]`. Verifiziert: Summary-Laenge ≤6000, endet an Wortgrenze.

## 5. `.env.example` + Pflicht-Pruefung – ERLEDIGT
- `.env.example:5-8`: `OPENCODE_TIMEOUT=3600`, `CLAUDE_TIMEOUT=3600`, `PROVIDER_TIMEOUT=600` mit Kommentar `0/leer = kein Timeout` eingetragen.
- Pflicht-Pruefung: `py -m py_compile server.py` → `PY_COMPILE_OK` (Hinweis: `python` ist auf diesem Rechner kein Alias, `py` wurde verwendet). Ergebnis fehlerfrei.

## Veraenderte Dateien
- Nur `server.py` und `.env.example` geaendert (+ dieser Report `docs/timeout-fix-report.md`). Hinweis: `git status` zeigt zusaetzlich aeltere, NICHT von mir stammende Aenderungen (`index.html`, `.gitignore`, untracked Dateien) – diese habe ich nicht angefasst. Kein Commit, Server nicht neu gestartet.
