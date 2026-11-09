# Archived 3D prototype

This folder preserves the earlier standalone Three.js view and the data exports it consumed. It is not loaded by the current Vite application under `viz/`. Its company ownership graph, proxy edges, firm-level loss values, random completion of missing exposures, market-cap scaling and layout are historical prototype behavior—not observed procurement flows, validated economic losses or forecast evidence.

The current 2D corporate mesh reuses only the archived listed-company IDs and x/y/z display positions as a deterministic PCA layout. It does not export historical market values, node sizes, colors or edge payloads. The source relation table retains 5,836 evidence records / 5,573 unique pairs. Only 2,002 pairs have both endpoints in the 3,893-company displayed population; the other 3,571 off-mesh pairs are not assigned invented coordinates. Capital relations never transmit shocks in the current input-output model.

The current workbench and its model boundaries are documented in the repository-root `README.md`, `docs/data-sources.md` and `viz/src/`. `scripts/export_viz.py` can regenerate the old graph into this archive only; it must not be used as the current product data pipeline.
