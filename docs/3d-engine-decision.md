# Decision: 3D view — stay browser-based (three.js) or go native?

Date: 2026-09-21 · Status: recommendation, awaiting owner sign-off · Scope: `index_3d.html` + `server.py` data layer. No code changed for this document.

## TL;DR

**Stay with three.js in the browser.** The complaint was visual quality, and that is an *art-asset* problem, not an engine problem: today's scene is untextured primitives under even lighting. The fix — rigged glTF robots, desert terrain, sky gradient, bloom — is achievable in three.js, and every art asset produced along the way is portable to Godot/Unity later if we ever change our mind. Going native would not improve the visuals by itself, but it would force a ~100% UI rebuild (chat, panels, voice dictation) and re-wiring the live data layer.

## Where we actually are (facts from the repo)

- `index_3d.html` uses three.js r160 with `WebGLRenderer` (PCF soft shadows, sRGB output, fog) and `OrbitControls`: drag-orbit, wheel-zoom, right-drag-pan, plus WASD/arrow camera movement (`index_3d.html:333-353, 382-408`). **The camera is already fully free-moving — nobody's complaint is the camera.**
- The scene itself is primitives only: gray ground plane + grid, box/cylinder robots animated procedurally (idle bob, typing motion). No glTF models, no terrain, no post-processing. That is why it reads as "programmer art."
- Data layer: `server.py` (stdlib `http.server`) serves a JSON snapshot at `/api/state`, live updates over SSE at `/api/events`, and REST actions (chat, tasks, moves, notes, models) — all already consumed by the 3D page (`index_3d.html:288, 908-913`). `.glb`/`.gltf` MIME types are already registered (`server.py:1103-1104`); only `/vendor/` is served as static files today.
- UI: chat with voice dictation (Web Speech API — browser-only feature), agent/project panels, modals, toasts — plain HTML/CSS overlay, roughly 1,000 lines duplicated across the `index*.html` variants.

## Comparison

| Axis | **three.js (stay)** | Godot 4 | Unity (URP) | Bevy (Rust) |
|---|---|---|---|---|
| Stylized desert + rigged robots (Astroneer-like) | Good, but DIY: glTF assets + `EffectComposer` (bloom/SSAO), `Sky` addon, vertex-color terrain. High ceiling; same art carries anywhere. | **Best turnkey of the natives**: glTF import, Skeleton3D + AnimationPlayer, WorldEnvironment (glow, volumetric fog, tonemaps). Best stylized quality-per-effort. | Best tooling & marketplace (Shader Graph, Mecanim, asset store); highest ceiling, heaviest install (~10 GB editor). | Capable PBR, but stylized look means hand-written WGSL; skinned animation works, tooling thin. Most effort per visual result. |
| Porting the live data layer | **Zero — already wired.** | Small (0.5-1 d): `HTTPRequest` polling of `/api/state`. No native SSE — poll or add WebSocket to server.py. | Small (0.5-1 d): `UnityWebRequest` coroutine; SSE needs a plugin. | Medium (1-2 d): `reqwest` + eventsource crate; most friction, idiomatic Rust. |
| How the native app gets live state | n/a (browser SSE today) | Poll `/api/state` at ~1 Hz — agent statuses change on the scale of seconds, so polling is honest and sufficient. server.py unchanged. | Same. | Same. |
| Windows 11 build & distribution | **None** (browser). Optional Tauri wrapper ≈ 10 MB if an "app icon" is wanted. | Export templates → single exe ~40-80 MB; SmartScreen warning while unsigned. | One-click build; ~70-150 MB player; SmartScreen warning. | `cargo build` → single small exe (~10-30 MB) — but no editor, everything hand-coded. |
| Licensing | MIT, $0 | MIT, $0 | Personal free (< $200k revenue, splash screen); Pro $2.2k/seat/yr beyond | MIT/Apache-2.0, $0 |
| Rebuilding the HTML UI | **0%** — chat, panels, modals, dictation stay as-is. | ~100% re-implemented in Control nodes; dictation lost. Est. 5-10 d. | ~100% in UI Toolkit/uGUI; dictation lost. Est. 5-10 d. | ~100% in egui, lowest fidelity; dictation lost. Est. 8-15 d. |

The two rows that decide this: **UI rebuild** is the biggest hidden cost of any native move (working chat + panels + dictation, redone per engine), while **art assets are engine-portable** — they get made once regardless of renderer.

## Per-option verdict

- **three.js** — The gap is assets, not the engine. Astroneer-style is a palette, terrain, lighting and rigging problem; three.js has every primitive needed (GLTFLoader, SkinnedMesh, AnimationMixer, EffectComposer, Sky).
- **Godot 4** — Best native fallback: MIT, lightweight, excellent stylized tooling, glTF-first pipeline. Weak spot: no native SSE and a full UI rewrite.
- **Unity** — Fastest route to fancy visuals *if buying assets*, but oversized for a personal dashboard: heavy editor, splash screen, biggest builds, full UI rewrite.
- **Bevy** — Wrong tool here: DIY everything, thin UI story (egui), and the team already speaks Python/JS, not Rust.

## Recommendation

**Stay with three.js.** (1) The visual target is reachable in-engine; (2) the data layer and UI are already done — a native port re-pays that debt for zero visual gain by itself; (3) licensing and distribution stay trivial; (4) if we ever do go native, Godot 4 is the path (not Unity, not Bevy), and all art made now ports over.

## Phased plan

**This week (browser path — no code changes yet, art groundwork):**
1. Author/obtain 1-2 rigged glTF robots (Blender, or CC0 from Sketchfab/Quaternius) with idle/walk/type clips. Keep the primitive figures as fallback if loading fails.
2. Desert terrain: heightmap-displaced plane with vertex colors + `three/addons Sky` gradient sky + warm key light; keep existing fog. Same palette discipline across props.
3. Post-processing: `EffectComposer` with bloom (UnrealBloomPass), optional SSAO, ACES tone mapping.
4. Deployment detail: assets must be reachable — either drop them under `/vendor/` (already served) or add a ~5-line `/assets/` static route in server.py; MIME types are ready.
5. Hygiene: fully vendor three.js r160 (a vendored fallback already exists at `vendor/three.module.js`) so the page no longer depends on unpkg.

**Only if we go native (Godot 4 spike, timeboxed ~1-2 weeks, do not start before the art pass ships):**
1. Import the same glTF robots + terrain into a Godot orbit-camera scene; compare side-by-side with the browser build.
2. `HTTPRequest` polling of `/api/state` at 1 Hz (drop SSE); read-only first — no actions.
3. Rebuild UI progressively: agent panels before chat; accept losing voice dictation or keep the browser page for voice.
4. Kill criteria for staying on three.js: the art pass ships and still disappoints, or WebGL performance becomes a real problem. server.py needs no changes in either world.
