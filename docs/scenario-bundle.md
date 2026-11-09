# Scenario Bundle schema: `ripple-scenario/1.3`

RIPPLE exports a Scenario Bundle as JSON. The schema deliberately separates the **selected event context** from the **proxy input actually evaluated**. Selecting “大手銀行破綻” or “台湾海峡封鎖” does not mean that bank-credit or route-specific propagation was modeled.

## Scenario fields

- `scenario.selectedEvent` records the catalog entry selected by the user: its stable `id`, display `label`, and catalog `support` status (`conditional`, `proxy-only`, or `unavailable`). This is context, not a claim that the event occurred or that its mechanism was calculated.
- `scenario.modeledProxy` identifies the calculation path actually used. Current identifiers are `icio-energy-input-cost-pressure` and `user-specified-country-industry-outage`.
- `scenario.assumptions` contains the engine inputs used for replay: channel, seed nodes, shock range, substitution and inventory assumptions, pass-through range, fixed random seed, sensitivity sample count, and maximum propagation steps.
- `results.input` repeats the event and proxy metadata alongside the engine input, and `results` contains the deterministic conditional sensitivity results. It is not an empirical forecast or event probability.

The JSON also records the schema, code and model revisions, source snapshot identity and generation time, SHA-256 checksums, creation time, and interpretation limits. Consumers should retain the full object rather than extracting results without provenance.

CSV exports start with `record_type` and include `selected_event_id`, `selected_event_label`, `selected_event_support`, `modeled_proxy_id`, and `modeled_proxy_label`. The first data row has `record_type=scenario` and preserves provenance even when there are no impact rows; subsequent `record_type=impact` rows carry the same provenance beside each industry result. They describe the same distinction and should not be labeled as an event-specific result unless a future, separately documented model adds that mechanism.

## Compatibility

Version `1.3` replaces the earlier ambiguous top-level scenario `eventId`/`title` fields with explicit `selectedEvent` and `modeledProxy` objects. Consumers should branch on `schemaVersion` and must not treat an older scenario title as evidence that its event-specific mechanism was modeled.
