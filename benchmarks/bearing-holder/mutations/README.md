# Mutation protocol

Each file in this directory injects one known defect and **declares the verdict it expects**.
`benchmarks/run_mutations.py` scores the verifier on caught / missed / false-positive /
harness-error. Benchmarks passing proves nothing about the verifier if the verifier is only ever
shown parts that happen to be correct (PRD Principle 5).

A mutation module may define:

| Name | Meaning |
|---|---|
| `EXPECT` | **required.** `"FAIL"` or `"PASS"` — the verdict `intent.check` must reach. |
| `REASON` | **required.** Why, in one line, in terms a person can check. |
| `KIND` | `"geometry"` (a dimension or feature is wrong) or `"method"` (the *ruler* is wrong). Default `"geometry"`. |
| `SOURCE` | which exported file to verify: `"stl"` (default) or `"step"`. |
| `PARAMS_OVERRIDE` | `{param: value}` — dimensional defects. Unknown keys are a harness error, never a silent no-op. |
| `BUILD_OPTIONS` | `{option: value}` passed to `model.build` — structural defects. |
| `patch(model, params)` | full control; returns a shape. For structural defects no parameter change can express. |
| `method_patch()` | a context manager that installs a known-bad measurement implementation. |
| `EXTRA_ASSERTS` | assertions appended to `intent.json` for this run only. Used by ruler-integrity mutations, which are not part of the *part's* design intent. |

## The two classes, both required

**Geometry mutations** — a dimension is wrong. **Method mutations** — the ruler is wrong.
Geometry mutations structurally cannot catch a bad ruler: they compare a measured number against
a range, and if the measuring is wrong in a way that happens to stay inside the range, they
report green forever (PRD Risk 2).

## Why `cosmetic_fillet` matters as much as the three defects

It is the **false-positive detector**. A verifier that fails it is over-tight and would cry wolf
on every real part, which makes the whole report ignorable — a slower path to the same place as
no verifier at all.

## `method_keep_dup_vertex` expects PASS, on measured evidence

The spike's 0.088mm error came from **centroid + max-radius** with Shapely's duplicate closing
vertex included. Least-squares fitting was measured on the same 253-point ring to be *immune* to
that duplicate — 29.9973mm with it and 29.9973mm without, identical to four decimal places,
while max-radius moved by 0.114mm. That immunity is the load-bearing reason least-squares is
canonical, so the mutation asserts it: if this one ever flips to FAIL, the fitter is no longer
least-squares and the strip line in `measure.fit_circle` has become load-bearing again.
