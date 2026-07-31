"""Disable the circularity gate: ``is_circular`` always True.

ADR-1's whole argument in one mutation. With the gate off, a section that is not a circle at all
yields a confident diameter -- the spike's square 20x20 pocket fits as "24.4949mm" with no error,
no warning, and no crash. On this part the base plate's rounded-rectangular profile is the
non-circular section, and with the gate off it is silently promoted to a Ø77mm "cylinder"
concentric with the bore.

No geometry mutation can catch this: the part is *correct*. Only an assertion about the ruler
can, which is why ``EXTRA_ASSERTS`` exists -- ruler integrity is not part of the part's design
intent and does not belong in its ``intent.json``.
"""

import contextlib

EXPECT = "FAIL"
REASON = "with the gate off, a non-circular section reports a confident, plausible, wrong diameter"
KIND = "method"
SOURCE = "stl"

EXTRA_ASSERTS = [
    {
        "noncircular_sections": [1, None],
        "source": "ruler-integrity",
        "measure": {"kind": "noncircular_count"},
        "note": "this part has a rounded-rectangular base; a gate that finds no non-circular "
        "section on it has stopped gating",
    }
]


@contextlib.contextmanager
def method_patch():
    from threedp.measure import CircleFit

    original = CircleFit.is_circular
    CircleFit.is_circular = property(lambda self: True)
    try:
        yield
    finally:
        CircleFit.is_circular = original
