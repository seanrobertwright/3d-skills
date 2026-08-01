# Execution report — Phase 2: printability and preparation

## Meta

- **Plan file:** `.agents/plans/phase-2-printability-and-preparation.md` (29 tasks, two milestones)
- **Branch:** `phase-2-printability-and-preparation` (from `master` @ `cd03bb7`)
- **Commit:** `5d7a3fc`
- **Lines changed:** +7,350 / −42 across 44 files

**Files added (31)**

| Area | Paths |
|---|---|
| Library | `src/threedp/{dfm,repair,slicer,gcode,coupon}.py` |
| Config | `profiles/{dfm-rules,slicer}.json` |
| Tests | `tests/test_{dfm,repair,coupon,slicer,gcode,no_printer_path}.py`, `tests/fixtures/plate_1_excerpt.gcode` |
| Benchmark | `benchmarks/imported-mesh/{model.py,params.json,intent.json}` + `mutations/` (8 mutations + README) |
| Skills | `.claude/skills/lril3d-{dfm,repair,slice}/SKILL.md` |
| Viewer | `viewer/src/gcode-preview.js` |
| Plan | `.agents/plans/phase-2-printability-and-preparation.md` |

**Files modified (13)** — `pyproject.toml`, `src/threedp/{printability,intent,features}.py`,
`tests/test_{one_ruler,intent}.py`, `viewer/{index.html,src/main.js,server/watch.mjs}`,
`.claude/skills/lril3d-{inspect,viewer}/SKILL.md`, `CLAUDE.md`, `README.md`.

## Validation results

| Level | Command | Result |
|---|---|---|
| 1 | `ruff check .` / `ruff format --check .` | ✓ All checks passed / 65 files formatted |
| 2 | root import + interpreter gate | ✓ `OK 3.13.14`, all 13 modules |
| 3 | `pytest` | ✓ **324 passed** (baseline 184) |
| 3 | `pytest -m slicer` | ✓ **6 passed, 0 skipped** — the real binary was driven |
| 3 | `pytest -m "not slicer"` | ✓ 318 passed, 6 deselected |
| 4 | `run_mutations.py` | ✓ **27 mutations**, caught 19/19, missed 0, false-positives 0, harness-errors 0 |
| 4 | `run_mutations.py --part imported-mesh -v` | ✓ 8 mutations; each `dfm_*` fails on its `dfm_blockers` line |
| 6 | `npx vite build` | ✓ built in 1.43 s |

**Type checking:** not applicable — this repo has no type checker configured; `ruff` (E/F/I/UP/B)
is the static gate `CLAUDE.md` names.

**Integration layers, and whether they actually ran** — the distinction this report exists to make:

- `pytest -m slicer` **executed**, 0 skipped, against Bambu Studio 02.07.01.62. It sliced real
  geometry four ways including a deliberate S6 rejection.
- The mutation suite ran all 27 against real rebuilt geometry.
- The viewer was driven in a real Chrome against a real dev server, not asserted from the source.

## Manual validation (plan Level 5)

| Box | Evidence |
|---|---|
| Real slice of a benchmark part | `25m 28s (1528 s), 10.85 g PLA, density 1.26, filament_id GFA00`; gcode 734,420 B |
| Sliced 3MF export | 135,725 bytes, relative-path form |
| G-code preview in the viewer | 12,837 extruding moves over 250 layers; layer slider verified at 60; re-slice hot-reloaded (`[watch] part.preview.json (681409 bytes)` → `[lril3d] reloading`); zero console errors |
| `lril3d-dfm` end-to-end | `BLOCKER min_feature_mm measured 0.600 mm threshold 0.800 mm … [a feature thinner than one bead does not print]` — not downgraded in prose |
| `lril3d-repair` on a third-party STL | **NOT DONE** — needs fetching someone else's model, an outward-facing action I did not take unprompted. Mechanism covered by 21 unit tests and 5 benchmark mutations on generated damage. |
| Print gate untouched | `git diff master -- .claude/settings.json` empty |

## What went well

- **Writing the tests first genuinely paid.** `tests/test_repair.py` was written against the S10
  spike numbers before `repair.py` existed, and it is what caught the inversion-ordering bug —
  not by failing, but by making the benchmark's `solid_volume` assertion obvious enough to add.
- **Re-running the spike instead of trusting it.** The plan's numbers were transcribed from a
  prior session; re-running the flatten-and-slice script reproduced 10.850234 g, 1528.09 s and
  `filament_id GFA00` exactly, which meant the fixture could be cut from *real* output rather
  than hand-written. Every number in `tests/test_gcode.py` is one the slicer actually wrote.
- **The `PIN_D` design point works.** Giving `imported-mesh` one dimension that no dimensional
  assertion constrains is what makes a DFM mutation scoreable, and the `-v` report confirms it:
  both `dfm_*` mutations fail on `dfm_blockers` and nothing else.
- **Two `cosmetic_*` detectors, one per engine.** `cosmetic_dfm_note` proves a WARNING does not
  gate — a property that would otherwise have been asserted only in a unit test.
- **The ADR-10 fixtures.** Feeding hand-built `result.json` files to `accept_slice` meant the
  three measured failure shapes are tested on a machine with no slicer at all.

## Challenges encountered

- **`fill_holes` does not do what the plan assumed.** It fills only tris and quads unless
  `use_fan=True`; the fan is the ADR-9 hazard. Declining it would make repair unable to close any
  real hole, so both passes run and are named separately in `ops`.
- **The bore-destruction test premise was wrong.** Removing a whole bore wall makes the bore
  unmeasurable in the *input*, so `repair` correctly reports no loss. The ADR-9 lost-feature
  contract had to be tested through `verify()` with a hand-built after-mesh instead, and the
  original scenario became a test documenting the limitation.
- **A flared cone has a knife edge.** The first `dfm_unprintable_overhang` produced two BLOCKERs —
  the overhang *and* a genuine 0.006 mm `min_feature` at the rim — which would have made the mild
  variant unable to isolate the overhang rule. Both variants gained a collar.
- **Duration and mass live in different places depending on input format.** `total_predication` is
  top-level for a `.3mf` and per-plate for a `.stl`. Found only because a real slice reported
  `0m 00s`.

## Divergences from plan

**Repair op ordering**
- Planned: `merge_vertices → fix_inversion/fix_winding → fix_normals → fill_holes → remove_*`
- Actual: `merge_vertices → fix_winding → fill_holes → fill_holes_fan → fix_normals → remove_*`
- Reason: inversion is detected from the sign of the enclosed volume, which an open surface does
  not have. The planned order returned a **watertight mesh of −23065.76 mm³** — closed, plausible,
  inside out, with every upward face reading as a 90° overhang downstream.
- Type: Plan assumption wrong

**DFM assertion location**
- Planned: Task 11 puts `dfm_blockers` in `intent.json`; Task 14 puts it in `EXTRA_ASSERTS`
- Actual: `intent.json`
- Reason: the two tasks contradict each other. ADR-8's own wording ("where a benchmark's
  `intent.json` asserts on them") settles it, and it gives all 8 mutations DFM coverage rather
  than 3 — more false-positive surface, fewer moving parts.
- Type: Better approach found

**`test_one_ruler` module list grown per milestone**
- Planned: Task 9 adds all five new module names at once, accepting a red test until 2B
- Actual: three at Task 9, two at Task 23
- Reason: the plan's own Task 18 requires a green 2A gate, which a deliberately-red test defeats.
  Final state is identical. A comment in the test records the rule.
- Type: Plan assumption wrong (internal contradiction)

**`gcode.py` built before `slicer.py`**
- Planned: `slicer.py` at Task 21, `gcode.py` at Task 23
- Actual: reversed
- Reason: ADR-10 condition 4 reads the G-code header's density, and duplicating that parse in
  `slicer.py` would violate ADR-11's own reasoning.
- Type: Better approach found

**`evaluate()` signature**
- Planned: `evaluate(mesh, material, rules_path=None, printer=None)`
- Actual: `evaluate(mesh, material, rules_path=None, part="<mesh>")`
- Reason: no rule consumes the printer profile at runtime — the nozzle is baked into the cited
  sources. A parameter that does nothing is a parameter that later gets silently ignored. `part`
  replaces it and is used, in every report header.
- Type: Better approach found

**`coupon.DEFAULT_TOL` 0.05 → 0.04**
- Planned: ±0.05, "half a step"
- Actual: ±0.04
- Reason: at exactly half a step adjacent assertion bands touch, so a reading on the boundary
  satisfies two assertions. Still 25× the measured 0.0016 mm ruler error.
- Type: Plan assumption wrong

**`min_wall_mm` and `min_feature_mm` share one ray cast**
- Planned: implied as two measurements
- Actual: one cast at the higher sample count feeds both rules
- Reason: a ray cannot distinguish a thin wall from a thin pin — both are "how much material lies
  in the direction the surface faces". Two casts would produce two near-identical numbers and
  imply a distinction that does not exist. They stay separate *rules* because the fix differs.
- Type: Better approach found

## Defects found during implementation

Five, all now covered by named regression tests. Listed because each is a fact about the
environment that outlived the task that found it, and all five are now in `CLAUDE.md`:

1. Repair op ordering → watertight mesh of −23065.76 mm³ (above).
2. `total_predication` per-plate vs top-level → a real print reported `0m 00s`.
3. Relative `--outputdir` resolved twice under the cwd `--export-3mf` requires → no `result.json`
   where the caller looked.
4. The G-code word scanner read coordinates out of inline comments — `G1 Z20 F9000 ;Move up to X50`
   moved to X50.
5. `lril3d-viewer`'s `--model ../…` example (pre-existing, Phase 1) resolved outside the repo, so
   the watcher watched `D:\repos\benchmarks\…` and Vite would have 403'd it anyway.

## Skipped items

- **`lril3d-repair` end-to-end on a real third-party STL** (Level 5, box 5). Requires downloading a
  third party's model; not done unprompted. The licence-provenance requirement it was meant to
  demonstrate is documented in the skill but has never been exercised on a real file.
- **Nothing else.** All 29 tasks completed in order, each with its `VALIDATE` run at the time
  rather than batched to the end.

## Recommendations

**For the plan command**

- Two tasks in this plan contradicted each other (Task 11 vs 14 on where the DFM assertion lives)
  and one contradicted a checkpoint (Task 9's known-red test vs Task 18's green gate). A
  consistency pass over cross-task references would have caught both — they are cheap to spot
  when the plan is whole and expensive to discover mid-execution.
- Task ordering should follow the dependency graph, not the narrative: `slicer.py` was scheduled
  before the module it imports.
- Where a plan transcribes spike numbers, it should say which are load-bearing. The plan's
  `time_s == 1507` was right about the header and wrong about `result.json`, and only re-running
  the spike separated them.

**For the execute command**

- The instruction to add an explicit embedded-delimiter test for hand-written parsers found a real
  bug (#4 above) that 100% line coverage would not have. Worth keeping, and worth extending: the
  same reasoning found the untested `bridge_spans` path in code review — "which branch has never
  produced a non-empty result?" is a distinct question from coverage.

**For `CLAUDE.md`** — already added in this change: the eight Bambu CLI facts, the three repair
facts, and the two DFM facts. One more worth considering as a rule rather than a gotcha: *a
measurement that has never been observed returning a value is not tested*, which is the
generalisation of finding #2 in the code review.
