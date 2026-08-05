# The printer gate

`.claude/settings.json` is the harness-enforced half of PRD §9's approval gate. It is committed
deliberately — the guardrail shipped **before** the capability, which is the only ordering that
guarantees it was present when `lril3d-print` arrived.

## Why `deny` and not `ask` in Phases 1 and 2 (ADR-5)

`deny` takes precedence over `allow`, and permission rules **merge** across scopes rather than
override — so a user-level `allow` cannot silently widen a project-level `deny`. With no send path
in the repository, `deny` cost exactly nothing and was strictly stronger than `ask`.

## The Phase 3 conversion — done

`lril3d-print` and `src/threedp/printer.py` exist, so the printer-send entries have moved from
`deny` to `ask`. The credential rules did not move:

```json
{
  "permissions": {
    "deny": [
      "Read(.env)",
      "Read(.env.*)"
    ],
    "ask": [
      "Bash(uv run lril3d-send*)",
      "Bash(python*send_to_printer*)",
      "Bash(python*lril3d_print*)",
      "Bash(curl*://*/upload*)",
      "Bash(ftp*)",
      "Bash(lftp*)"
    ]
  }
}
```

`Read(.env)` stays denied permanently: printer IP, serial, and access code are never read into a
transcript. `printer.credentials()` reads them into the *process* from the environment and returns
a dataclass that redacts in `repr` and has no `__dict__` to dump.

This block is asserted, entry by entry, by `tests/test_printer_path_is_narrow.py` — including that
nothing appears under both `ask` and `deny`, and that the conversion is only justified because the
capability it guards actually exists.

## `ask` is the harness half, and it is the weaker half

The gate a person actually meets is `lril3d-print`'s: the pre-send summary, the reconciliation
report, and an explicit confirmation before anything is uploaded or published. The harness rule
catches a shell command that tries to route around the library; it cannot see a Python call. Do
not treat a green harness as consent.

Do **not** move these rules into `.claude/settings.local.json` — that file is gitignored, and PRD
§9 requires the guardrail to be committed. The migration guard in the test file catches it.
