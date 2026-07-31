# The printer gate

`.claude/settings.json` is the harness-enforced half of PRD §9's approval gate. It is committed
deliberately — the guardrail ships **before** the capability, which is the only ordering that
guarantees it is present when `lril3d-print` arrives.

## Why `deny` and not `ask` in Phase 1 (ADR-5)

`deny` takes precedence over `allow`, and permission rules **merge** across scopes rather than
override — so a user-level `allow` cannot silently widen a project-level `deny`. In Phase 1 no
send path exists, so `deny` costs exactly nothing and is strictly stronger than `ask`.

## The Phase 3 conversion — one edit, not a redesign

When `lril3d-print` exists, move the printer-send entries from `deny` to `ask`, leaving the
credential rules under `deny`:

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
transcript.

Do **not** move these rules into `.claude/settings.local.json` — that file is gitignored, and PRD
§9 requires the guardrail to be committed.
