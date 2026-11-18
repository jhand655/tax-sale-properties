# v6.2.1 development review — November 17, 2026

## Baseline and scope

Repository main at `4ccbf18bedbf3ac6b3e7145b77b7a6c1a13a3e8c` held an older 52-line app with a missing CSV. The user approved using the saved v6.2 application as the development baseline and addressing the audited reliability, matching, classification and rendering issues. The recovered v6.2 source SHA-256 is `5aaf7282a21fefdf7cb457479a9e53d9ebac5658924180576d6adcc3dc7e5059`. Its existing features were retained. Work is isolated on `development/investor-v6.2-reliability`.

## Implemented

1. Restored the historical dataset, stable entry point and full v6.2 UI; supplied pinned runtime/Excel dependencies and setup documentation.
2. Preserved parcel ID strings, handled absent/nonfinite values and empty/single-bid lists, added source-row reports and duplicate review rather than silent first-row selection.
3. Resolved county object IDs before fetching geometry, checked completeness, retained multiple geometries per parcel, reported unusable geometry and exposed cache age/refresh.
4. Added Unknown / Review and conflict detection; kept the original detailed selectors and quick toggles. Classified by word boundaries rather than broad substrings; disclosed heuristic basis in popups.
5. Replaced per-polygon GeoJSON layers with one feature collection; retained individual clickable bid bubbles, detailed popups and basemap controls. Added filtered shortlist CSV export while retaining the full matched GeoJSON export.
6. Avoided reporting partial county appraisal values as complete totals.

## Validation

- Python compilation, 29 passing pytest unit/integration checks, Streamlit AppTest interactions, and dependency consistency checks. The full 642-row dataset also passed AppTest startup and Residential/Commercial quick-view interactions without exceptions.
- Live county metadata and three-parcel query verified the expected fields and object ID behavior.
- Full historical list: 642 source rows; 640 county geometry features; 639 unique mapped parcels; 3 unmatched/unmappable parcel IDs. Multiple geometries were preserved rather than collapsed. Matching does not establish current sale eligibility.
- Classification counts by geometry: 470 Residential, 94 Land / Other, 56 Unknown / Review, 20 Commercial. These counts include the extra geometry and are not unique-property inventory counts.
- Same 640-feature dataset, same environment, one measured rendering run: original v6.2 3.664 seconds / 10,732,764 HTML bytes / 640 GeoJSON layers; updated build 2.293 seconds / 9,851,958 bytes / 1 GeoJSON layer (before the final tooltip wording update). About 37% less server map-generation time and 8% fewer bytes. This is not a browser frame-rate measurement or a guaranteed speedup.
- No browser/mobile visual acceptance test or production deployment has been performed. AppTest exercises Streamlit execution and controls, not Leaflet browser interactions.

## Follow-up priorities

- Review a separate Streamlit development preview on desktop and phone, including actual polygon and bubble popup interaction.
- Obtain authoritative classification code mappings if available; no coded domains were supplied by the county service for the three classification inputs.
- Validate a current sale list and compare unmatched IDs with official sale records.
- Benchmark browser interaction before introducing zoom-dependent labels or simplified geometry; these would alter map behavior.
- Investment analysis additions (cost assumptions, return scenarios, saved notes) remain a separate feature decision. Max Return Bid continues to be supplied by the uploaded list, not calculated or represented as a guaranteed return.

Production main must remain unchanged until separately approved.
