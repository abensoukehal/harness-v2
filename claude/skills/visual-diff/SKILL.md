---
name: visual-diff
description: Screenshot, region compare, report, accepted gap.
---

# Visual diff

Inputs: `design/<screen>.png`, `design/regions.json` mapping region ids to bounding boxes, the running stack, `visual` from the config.

1. Render the screen at `visual.viewport`. Inject a stylesheet that disables animations and transitions. Wait for fonts. Use the seeded data. Hide any element rendering a timestamp.
2. Capture the screen as PNG.
3. Per region: crop reference and capture to the box, count differing pixels. Divergence = differing pixels / region pixels × 100.
4. Report per region: id, divergence, pass when under `visual.threshold_pct`.
5. On a failing region: adjust the code, rerun. At most `visual.max_attempts` rounds.
6. Past the cap: save the pair as `product/features/<slug>/gaps/<region>-reference.png` and `<region>-actual.png`, append `{subtask, region, divergence_pct}` to `accepted_gaps` in `state.json`, continue.

Never compare whole screens. Never pass a region by eye.
