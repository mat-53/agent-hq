# Dictation (Microphone) Troubleshooting

Record of the completed dictation debug so nobody re-debugs it.
Conclusion up front: the code is correct; the failure is environmental
(non-secure origin). Do not re-verify the JS.

## Symptom

- Mic button activates (recording state), but no text ever appears in the input.
- No error message is shown; Chrome aborts silently.

## Root Cause

- The Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`) requires a **secure context**.
- `http://192.168.x.x` (LAN IP) is **NOT** a secure context. Chrome fires `onerror` with `'not-allowed'` and stops without user-visible feedback.
- `localhost` **IS** a secure context; LAN IPs are not. `https://` is.
- `getUserMedia` has the same restriction, so a MediaRecorder -> POST -> server-side workaround does **NOT** avoid the problem (that option is dead).

## Things Ruled Out (with evidence)

- **Wrong file served?** No. `server.py:20` sets `ROOT = Path(__file__).resolve().parent`, and `server.py:1008-1009` serves `ROOT / "index.html"` for `/` and `/index.html`. That is exactly the edited file. No `static/` or `templates/` copy exists, no stale file.
- **Broken inline script?** No. The extracted inline script (~40k chars) parses cleanly via `node --check`.
- **Fix missing from served file?** No. The guard exists in the served file:
  - `index.html:653-660` - secure-context / SpeechRecognition support guard in `micInit` (disables button, explains why, `console.error`).
  - `index.html:662-668` - `micShowError` helper (`console.error` + placeholder/title + toast).
  - `index.html:695-699` - `micStart` re-checks the guard before `start()`.

  So the remaining failure is the origin, not the code.

## Fixes (ordered by effort)

1. **On the server machine:** browse `http://localhost:<port>` instead of the LAN IP. Zero setup; localhost is a secure context.
2. **From another machine or phone:** SSH port-forward so the browser origin becomes localhost:
   ```
   ssh -L 8080:localhost:80 <host>
   ```
   then open `http://localhost:8080`. No certs, no code changes, ~2 min setup.
3. **Permanent option:** run the server with the `--https` flag and a self-signed certificate, then browse via `https://...` (accept the cert warning once per browser).

## Browser Support Note

Firefox and Brave do not support the Web Speech API the same way as
Chrome/Edge (Brave blocks Google's speech backend; Firefox has no
comparable `SpeechRecognition`). Dictation requires Chrome or Edge
regardless of origin.
