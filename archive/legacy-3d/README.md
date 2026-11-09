# Historical 3D viewer and data snapshot

This folder preserves a copy of the earlier standalone Three.js viewer and its data exports. The active static viewer under `viz/` was restored to the application tree from commit `9563fef`; this archive copy is not loaded by it. `scripts/export_viz.py` writes active viewer data to `viz/data/`.

The historical graph, proxy edges, firm-level loss values, random completion of missing exposures, market-cap scaling and layout are prototype behavior—not observed procurement flows, validated economic losses or forecast evidence. The precomputed scenario outputs must not be interpreted as event probabilities, realized losses or calibrated forecasts.

The later React/TypeScript 2D prototype was removed from the active application tree during the requested rollback. Its design, data-provenance and Scenario Bundle documents are retained as historical/reference materials; they do not describe features of the active viewer.
