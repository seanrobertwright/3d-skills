"""CI runs the three hardware-free gates, and does not pretend to run the other two.

`.claude/settings.json` is asserted by ``test_printer_path_is_narrow`` for the same reason this
file exists: a guardrail that lives only in a config file is one edit away from being gone, and
the edit that removes it looks exactly like the edit that fixes a flaky job.

The specific thing being defended is narrow. CI *cannot* run ``-m slicer`` (needs Bambu Studio) or
``-m printer`` (needs the physical P1S, credentials, and Developer Mode), and that is fine and
permanent. What is not fine is CI **appearing** to run them -- by invoking them and letting them
skip themselves for want of hardware, which produces a green check over nothing. So the workflow
must deselect them by name, and must never invoke them.

The other half is the mutation suite. `CLAUDE.md` calls it the real gate, and a `pytest` that is
green while it is absent is precisely the "benchmarks passing proves nothing about the verifier"
failure the suite was built to refuse. It has to be a step, not a habit.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "verify.yml"

# The markers CI must exclude rather than run. Both are hardware gates.
HARDWARE_MARKERS = ("printer", "slicer")


def workflow_text() -> str:
    assert WORKFLOW.is_file(), (
        f"{WORKFLOW.relative_to(REPO)} is missing. Without it `gh pr checks` reports nothing and a "
        f"pull request merges with zero automated verification (issue #5)."
    )
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_workflow_exists_and_is_not_empty():
    """Skipped-layer guard: every assertion below is vacuous over a file that is not there."""
    text = workflow_text()
    assert "runs-on:" in text and "steps:" in text, "the workflow defines no job"


def test_ci_deselects_both_hardware_markers_by_name():
    text = workflow_text()
    for marker in HARDWARE_MARKERS:
        assert f"not {marker}" in text, (
            f"CI does not deselect the '{marker}' marker. Either it is running a gate it cannot "
            f"satisfy, or the gate has gone somewhere this test is not looking."
        )


def marker_expressions(text: str) -> list[str]:
    """Every ``-m`` argument in the workflow, quoted or bare.

    Comment lines are dropped first, for the reason ``test_one_ruler`` strips docstrings: the
    workflow *explains* which markers it excludes and why, and prose naming ``-m slicer`` is
    documentation rather than an invocation. Without this the file fails its own test for
    describing itself accurately, which teaches the next person to delete the comment.
    """
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return [
        double or single or bare
        for double, single, bare in re.findall(r"""-m\s+(?:"([^"]*)"|'([^']*)'|([^\s"']+))""", text)
    ]


def test_ci_never_invokes_a_hardware_lane():
    """The counterpart: deselecting them elsewhere does not help if one is also selected.

    Parsed rather than substring-matched. ``'-m "printer"' not in text`` is satisfied by
    ``-m printer``, ``-m  printer`` and ``-m 'printer'`` alike -- three spellings of the failure
    this is meant to catch, all passing a check that reads like it covers them.
    """
    expressions = marker_expressions(workflow_text())
    assert expressions, "the workflow passes no -m expression at all; nothing is being deselected"
    for expression in expressions:
        for marker in HARDWARE_MARKERS:
            for occurrence in re.finditer(rf"\b{marker}\b", expression):
                before = expression[: occurrence.start()]
                assert re.search(r"\bnot\s+$", before), (
                    f"CI selects the '{marker}' lane in `-m {expression}`. On a runner with no "
                    f"hardware every test in it skips, and a skipped gate wearing a green check is "
                    f"worse than no check at all -- it looks like coverage."
                )


def test_ci_refuses_a_silent_skip():
    """Measured 2026-08-28: the hardware-free lane is 474 passed, 19 deselected, zero skipped.

    470 on 2026-08-06, then +1 for the ``pr-trajectory-audit`` skill (``test_skills_contain_no_
    measurement_logic`` is parametrized over installed skills), +1 for #7's ``tools/`` send-path
    test, +2 for the ``slice-artifacts`` assertions in this file. The intermediate 471 recorded on
    2026-08-28 was measured on a branch cut before #7 merged and was never true of master -- which
    is the hazard in citing a count at all, and the reason nothing here *asserts* one.

    A skip appearing there means a dependency is missing on the runner or a hardware test lost its
    marker and is now skipping itself. Both are the same failure -- something did not run and
    nothing said so -- so the workflow has to assert on it rather than print it.

    It earned itself immediately. The first run on a machine without Bambu Studio reported one
    skip: `test_the_real_profile_tree_flattens_to_the_measured_density` needed the installed
    profile tree but carried no `slicer` marker, so it sat in the lane documented as green
    *without* a slicer and opted out there. Every machine this repo had ever run on had Bambu
    Studio installed, so it passed, and nothing anywhere reported that it was conditional.
    """
    text = workflow_text()
    assert "skipped" in text, (
        "the workflow does not check for skips. Deselecting the hardware markers keeps the *known* "
        "gates out; this is what catches a test that quietly opts itself out for some other reason."
    )
    assert "deselected" in text, (
        "the workflow does not check that anything was deselected. If the markers are ever removed "
        "the exclusion silently becomes a no-op, and this is the assertion that notices."
    )


def test_ci_runs_the_mutation_suite():
    """The real gate. Benchmarks passing says nothing about a verifier shown only correct parts."""
    text = workflow_text()
    assert "run_mutations.py" in text, (
        "CI does not run the mutation suite. It is the only check that scores the verifier rather "
        "than the parts, and a green pytest without it is not evidence the verifier works."
    )


def test_ci_runs_the_interpreter_gate():
    text = workflow_text()
    assert "version_info[:2]==(3,13)" in text, (
        "CI does not pin the interpreter. bpy ships cp313 wheels only, and a resolver that "
        "wandered onto 3.14 should fail with the version printed rather than somewhere obscure."
    )


def test_the_markers_ci_excludes_are_the_markers_that_exist():
    """Ties the workflow to `pyproject.toml`, so renaming a marker cannot half-land.

    Renaming `printer` to `hardware` in pyproject and the tests, but not in the workflow, leaves a
    marker expression that deselects nothing and a CI job that runs the printer suite against a
    runner with no printer. Every test in it would skip, and the check would be green.
    """
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {entry.split(":")[0] for entry in config["tool"]["pytest"]["ini_options"]["markers"]}
    for marker in HARDWARE_MARKERS:
        assert marker in declared, (
            f"'{marker}' is excluded by CI but is not declared in pyproject.toml; one of the two "
            f"has been renamed and the other has not"
        )


def test_ci_asserts_every_slice_wrote_its_review_and_report():
    """`CLAUDE.md`'s "Shipping a slice" rule, made mechanical.

    Measured 2026-08-28 by the trajectory audit in ``.agents/audits/``: all three phase PRs wrote
    both artifacts and both non-phase PRs wrote neither, 2 of 2. The rule existed the whole time --
    in ``.claude/post-execute.json``, which names the paths, and in a ship-pipeline skill installed
    at user level *outside this repository*. An agent reading ``CLAUDE.md`` cover to cover could
    not learn it existed. So the rule moved into ``CLAUDE.md`` and the check moved in here, which
    is the arrangement ``.claude/settings.json`` already has via ``test_printer_path_is_narrow``.
    """
    text = workflow_text()
    assert "slice-artifacts:" in text, (
        "CI no longer has the slice-artifacts job. Without it the code review and execution report "
        "are prose in CLAUDE.md, which is exactly the state the 2026-08-28 audit found failing on "
        "2 of 2 non-phase PRs."
    )
    for path in (".agents/code-reviews/", ".agents/execution-reports/"):
        assert path in text, f"the slice-artifacts job no longer checks {path}"
    assert "github.event_name == 'pull_request'" in text, (
        "the slice-artifacts job is not gated on pull_request. `github.head_ref` is empty on a "
        "push, and an empty slice name makes every path `.agents/code-reviews/.md` -- the check "
        "would pass by accident on every push to master."
    )


def test_this_repository_has_the_artifacts_the_ci_job_demands():
    """The skipped-layer guard for the check above: CI asserts a pairing this repo must satisfy.

    A slice writes two files. A directory holding one of a pair means a slice shipped half its
    record -- and that half is invisible in CI, which only ever looks at the branch in front of it.
    """
    reviews = {p.stem for p in (REPO / ".agents" / "code-reviews").glob("*.md")}
    reports = {p.stem for p in (REPO / ".agents" / "execution-reports").glob("*.md")}
    assert reviews, "no code reviews found; the path is wrong"

    # Slices that shipped before the rule existed. Grandfathered by *name*, never by a tolerance:
    # a new unpaired slice fails, and removing a name from here can only make the check stricter.
    # `pr-1-review` is PR #1's PHASE 6 diff review, which has no execution-report counterpart by
    # design -- it is a second review of one slice, not a slice of its own.
    PRE_RULE = {"pr-1-review", "ci-hardware-free-lanes", "ams-feed-bisect-tooling"}

    unpaired = (reviews ^ reports) - PRE_RULE
    assert not unpaired, (
        f"these slices have a code review or an execution report but not both: {sorted(unpaired)}. "
        f"CLAUDE.md's 'Shipping a slice' section requires the pair."
    )
