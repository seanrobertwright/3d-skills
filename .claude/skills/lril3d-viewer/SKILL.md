---
name: lril3d-viewer
description: Use when the user wants to see a model live in the browser, watch it update while iterating, or asks to open, start, or stop the 3D viewer.
---

# lril3d-viewer — the live browser viewer

A local Vite + three.js page that loads the exported mesh and hot-reloads it within about a
second of a file write, preserving the camera. Its purpose is that the user can react to a
change immediately instead of describing a problem in text.

**The viewer is a channel, not a gate** — the same rule as renders. Never treat "it looks right
in the viewer" as verification. Use `lril3d-inspect` for that.

## Start it

```bash
cd viewer && npm install          # first run only; Node >= 20
npm run dev -- --model ../models/<name>/out
```

`--model` points at a directory containing `part.stl` or `part.3mf`. It defaults to
`benchmarks/bearing-holder/out`. The dev server prints a local URL; give that to the user rather
than trying to open a browser yourself.

The watcher and the page run together under `npm run dev`. To run only the file watcher (for
example when the page is already open), use `npm run watch`.

## Stop it

Interrupt the dev server process. Do not leave it running across a session without telling the
user it is up.

## What the page offers

- orbit / pan / zoom
- wireframe toggle
- a cross-section slider on Z
- a build-plate grid read from `profiles/printer-p1s.json` — the plate size is **not** hardcoded

## When it does not reload

1. Confirm something actually re-exported — the watcher fires on writes to `out/`.
2. Writes are debounced by ~250 ms on purpose: exporters write an STL in several chunks, and
   reloading mid-write yields a truncated mesh.
3. Check the browser console; the page logs each reload with the file it loaded.

## Notes

- Node v24.18.0 is present on this machine and verified working.
- The viewer reads whatever is in `out/` — which is the **compensated** mesh when a calibration
  was supplied. If the user is checking nominal dimensions, point them at the STEP through
  `lril3d-inspect` instead; the viewer is showing the part plus this printer's error, by design.
