"""The pin grows from 10mm to 400mm tall: a 10.25:1 part that wobbles under the nozzle.

The companion to ``dfm_thin_pin``, and it scores a different thing. ``PIN_H`` is the only
parameter that moves the part's *stance* without moving anything ``intent.json`` asserts, so this
is the only way the mutation suite can reach ``max_aspect_ratio`` at all -- a rule that, before
this mutation existed, had never produced a finding anywhere in the repository.

**It expects PASS, and that is the point.** ``max_aspect_ratio`` is a WARNING, and a WARNING does
not gate (ADR-8). Measured here: ``max_aspect_ratio measured 10.250 threshold 8.000``, reported
with its number and its source, on a part that still passes its intent -- because whether to risk
a tall print is the operator's call and not the verifier's.

So this is a false-positive detector for the *severity system* rather than for a measurement. If
it ever flips to FAIL, one of two things happened: ``max_aspect_ratio`` was promoted to BLOCKER
without anyone deciding to, or a dimensional assertion has started depending on the pin. Both are
worth being told about.
"""

EXPECT = "PASS"
REASON = "slenderness is a warning about the print, not a defect in the part"
PARAMS_OVERRIDE = {"PIN_H": 400.0}
