"""Principle 6, mechanically enforced: there is exactly one ruler.

Two improvised implementations of "measure this bore" once disagreed by 0.088mm -- larger than a
press-fit tolerance, and enough to flip a +/-0.05 assertion (PRD 6.5). A rule with no enforcement
decays, so this test walks the tree and fails the build if a measurement primitive reappears
outside ``src/threedp/measure.py``.

The scanner strips comments and string literals before matching. That is not a nicety: several
modules *discuss* the banned methods in their docstrings -- the ban is documented where it
matters -- and a naive text search would flag the very prose explaining the rule.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# The one ruler. Narrow and explicit on purpose.
RULER = REPO / "src" / "threedp" / "measure.py"

# Measurement-method mutations exist to *be* a known-bad ruler. Excluding them is the point of
# them; they are quarantined to this one filename pattern so the exemption cannot spread.
METHOD_MUTATION = re.compile(r"mutations[/\\]method_[a-z_]+\.py$")

BANNED = (
    (
        re.compile(r"\blstsq\b"),
        "least-squares fitting is the canonical ruler and lives only in measure.py",
    ),
    (
        re.compile(r"\bptp\b"),
        "peak-to-peak (bounding-box) measurement is prohibited for dimensional assertions",
    ),
    (
        re.compile(r"\bdef\s+fit_circle\b"),
        "a second fit_circle is exactly the 0.088mm disagreement, reintroduced",
    ),
    (
        re.compile(r"(?:hypot|norm|sqrt)\s*\(.*\)\s*(?:\.max\(|\.min\()"),
        "max-radius measurement is prohibited (PRD 6.5); use measure.fit_circle",
    ),
    (
        re.compile(r"\bmarching_cubes\b.*\bradius\b"),
        "geometry-to-dimension conversion belongs in measure.py",
    ),
)


_LITERAL_TOKENS = {
    tokenize.STRING,
    tokenize.COMMENT,
    # f-strings tokenize into START / MIDDLE / END on 3.12+. Only MIDDLE is literal text; the
    # replacement fields are real code and must stay scannable -- f"{arr.ptp()}" is a call.
    getattr(tokenize, "FSTRING_MIDDLE", -1),
}


def strip_strings_and_comments(source: str) -> str:
    """Blank out comments and string literals **in place**, preserving rows and columns.

    Rewriting the file by re-joining tokens would be simpler and wrong twice over: it shifts
    every reported line number, and it inserts spaces that break the multi-token idioms this
    scanner exists to match (``np.hypot(...).max()`` becomes ``np . hypot ( ... ) . max ( )``).
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source  # unparseable: scan it raw rather than skipping it

    grid = [list(line) for line in source.splitlines(keepends=True)]
    for token in tokens:
        if token.type not in _LITERAL_TOKENS:
            continue
        (row_start, col_start), (row_end, col_end) = token.start, token.end
        for row in range(row_start - 1, min(row_end, len(grid))):
            first = col_start if row == row_start - 1 else 0
            last = col_end if row == row_end - 1 else len(grid[row])
            for col in range(first, min(last, len(grid[row]))):
                if grid[row][col] != "\n":
                    grid[row][col] = " "
    return "".join("".join(row) for row in grid)


def scan(path: Path) -> list[tuple[int, str, str]]:
    source = path.read_text(encoding="utf-8")
    code = strip_strings_and_comments(source)
    findings = []
    for number, text in enumerate(code.splitlines(), start=1):
        for pattern, reason in BANNED:
            if pattern.search(text):
                findings.append((number, text.strip(), reason))
    return findings


def python_files_under_the_rule() -> list[Path]:
    files = [p for p in (REPO / "src" / "threedp").glob("*.py") if p != RULER]
    files += [p for p in (REPO / "benchmarks").rglob("*.py") if not METHOD_MUTATION.search(str(p))]
    files += [p for p in (REPO / "tests").glob("*.py") if p.name != Path(__file__).name]
    return sorted(files)


def test_the_scan_actually_covers_something():
    """A scanner that walks nothing passes everything. This is the skipped-layer guard."""
    files = python_files_under_the_rule()
    assert len(files) >= 10, f"only {len(files)} files scanned; the walk is broken"
    names = {p.name for p in files}
    for expected in ("features.py", "intent.py", "printability.py", "io.py", "run_mutations.py"):
        assert expected in names, f"{expected} was not scanned"


def test_no_ad_hoc_measurement_outside_measure_py():
    offences = []
    for path in python_files_under_the_rule():
        for number, text, reason in scan(path):
            offences.append(f"{path.relative_to(REPO)}:{number}: {text}\n    -> {reason}")
    assert not offences, "ad-hoc measurement found outside measure.py:\n" + "\n".join(offences)


def test_the_ruler_itself_is_allowed_to_fit_circles():
    """Sanity: the patterns really do match, so a green result above means something."""
    findings = scan(RULER)
    assert findings, "measure.py contains no least-squares fit; the banned patterns are wrong"
    assert any("lstsq" in text for _n, text, _r in findings)


def test_method_mutations_are_the_only_exemption():
    """The exemption is one filename pattern, and it is load-bearing that it stays that way."""
    exempt = [p for p in (REPO / "benchmarks").rglob("*.py") if METHOD_MUTATION.search(str(p))]
    assert exempt, "no method mutations found; the highest-value tests in the suite are missing"
    for path in exempt:
        assert path.parent.name == "mutations"
        assert path.name.startswith("method_")
        source = path.read_text(encoding="utf-8")
        # Each one must actually substitute part of the ruler, or it is exempt for nothing. Note
        # that not every method mutation contains a *banned primitive*: disabling the
        # circularity gate corrupts the ruler's verdict rather than its arithmetic.
        assert "def method_patch" in source, f"{path.name} installs no method patch"
        assert "threedp.measure" in source or "threedp import measure" in source, (
            f"{path.name} is exempt from the one-ruler rule but never touches the ruler"
        )


def test_at_least_one_method_mutation_substitutes_the_arithmetic():
    """The exemption must be earned: a genuinely wrong fit, not only a wrong gate."""
    exempt = [p for p in (REPO / "benchmarks").rglob("*.py") if METHOD_MUTATION.search(str(p))]
    assert any(scan(p) for p in exempt), (
        "no method mutation contains a bad measurement implementation; the highest-value class "
        "of test in the suite is not actually exercising a wrong ruler"
    )


# --- the scanner's own edge cases ---------------------------------------------------------


def test_banned_token_inside_a_comment_is_not_flagged(tmp_path):
    """The rule is documented in prose next to the code it governs.

    A naive text search flags the sentence explaining the ban -- so the scanner must strip
    comments before matching.
    """
    p = tmp_path / "sample.py"
    p.write_text("x = 1  # never use arr.ptp() for a dimension\n", encoding="utf-8")
    assert scan(p) == []


def test_banned_token_inside_a_string_literal_is_not_flagged(tmp_path):
    p = tmp_path / "sample.py"
    p.write_text('MESSAGE = "lstsq and .ptp() are prohibited here"\n', encoding="utf-8")
    assert scan(p) == []


def test_banned_token_inside_a_docstring_is_not_flagged(tmp_path):
    p = tmp_path / "sample.py"
    p.write_text('"""Do not call np.linalg.lstsq to fit a circle."""\nx = 1\n', encoding="utf-8")
    assert scan(p) == []


def test_banned_token_inside_an_fstring_is_not_flagged(tmp_path):
    p = tmp_path / "sample.py"
    p.write_text('n = 2\nmsg = f"{n} uses of .ptp() were banned"\n', encoding="utf-8")
    assert scan(p) == []


def test_banned_token_in_real_code_is_flagged(tmp_path):
    """The counterpart: stripping strings must not strip the code as well."""
    p = tmp_path / "sample.py"
    p.write_text("import numpy as np\nwidth = arr.ptp()\n", encoding="utf-8")
    findings = scan(p)
    assert len(findings) == 1
    assert findings[0][0] == 2


def test_max_radius_idiom_in_real_code_is_flagged(tmp_path):
    p = tmp_path / "sample.py"
    p.write_text("import numpy as np\nd = 2 * np.hypot(x - cx, y - cy).max()\n", encoding="utf-8")
    assert scan(p), "the max-radius idiom must be caught; it is the 0.088mm bug"


def test_a_second_fit_circle_definition_is_flagged(tmp_path):
    p = tmp_path / "sample.py"
    p.write_text("def fit_circle(pts):\n    return 1.0\n", encoding="utf-8")
    assert scan(p)


def test_unparseable_file_is_scanned_rather_than_skipped(tmp_path):
    """A syntax error must not become a way to smuggle a second ruler past the check."""
    p = tmp_path / "broken.py"
    p.write_text("def f(:\n    d = arr.ptp()\n", encoding="utf-8")
    assert scan(p), "an unparseable file was silently skipped"


# --- thin skills, thick library -----------------------------------------------------------


@pytest.mark.parametrize("skill", ["lril3d-model", "lril3d-inspect", "lril3d-viewer"])
def test_skills_contain_no_measurement_logic(skill):
    """SKILL.md handles intent and narration. Geometry and measurement live in the package."""
    text = (REPO / ".claude" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    for banned in ("lstsq", "def fit_circle", ".ptp(", "marching_cubes"):
        assert banned not in text, f"{skill}/SKILL.md contains measurement logic: {banned}"
