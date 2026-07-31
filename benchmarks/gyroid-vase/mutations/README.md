# Why there are no dimensional mutations here

The gyroid vase is **Tier 2**. Its `intent.json` claims topology and statistics and explicitly
labels every feature-level dimensional number **ESTIMATE**.

Writing a dimensional mutation for it — moving a wall by 0.3mm and declaring MUST FAIL — would
score the verifier against a promise it never made. It would either produce a permanent miss, or
tempt someone to tighten the Tier 2 gate until it "catches" something it cannot actually measure.
Both are worse than the honest gap.

The mutations here therefore attack only what Tier 2 genuinely covers: **watertightness, bounding
box, and volume**. That is a real and useful gate — it is what catches an unmerged triangle soup,
a truncated generation, or a lattice that thinned away to nothing.
