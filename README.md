# Spartanburg County Tax Sale Deal Finder

Development baseline: saved Investor UI v6.2 (October 21, 2026), upgraded to v6.2.1-dev.
Entry point remains `tax_sale_app.py`. Development branch: `development/investor-v6.2-reliability`.
Production `main` has not been modified. Do not change the existing Streamlit deployment's branch until the development build has been reviewed and approved.

## Run locally

Tested with Python 3.12. Create and activate a virtual environment, then:

```sh
python -m pip install -r requirements.txt
python -m streamlit run tax_sale_app.py
```

For tests:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Dependencies are pinned to versions used in validation. Excel support includes `.xlsx`, `.xlsm`, and `.xls`.

## Data and matching

The bundled `Cleaned_Spartanburg_Tax_Sale_2024.csv` is a historical 642-row list recovered from repository commit `b373070`. It is not a current offering list. Uploaded files must supply Item Number, Tax Map Number, Owner Name, Property Address (or legacy Address), and Bid Amount. Optional Max Return Bid and legacy Max Bid are supported. Parcel IDs are read as text to preserve leading zeros; existing Excel numeric cells cannot recover zeros already lost in the source.

Missing parcel IDs and invalid, nonfinite, or negative bids are excluded and reported. All rows sharing a duplicate parcel ID are held for review; the app does not choose one arbitrarily. Correct the source and re-upload. Invalid optional maximum bids are displayed as missing.

Matching is exact after trimming whitespace and uppercasing. The app does not guess punctuation or match by owner/address. County object IDs are resolved first, and every geometry batch is checked against the requested IDs. Incomplete batches stop the load rather than presenting partial success. Multiple county geometries for the same parcel are retained; inventory counts and shortlist rows use unique parcel IDs. Missing or unusable polygon geometry appears in the unmatched/unmappable report.

County responses are cached for 24 hours. The fetched timestamp is shown in UTC; Refresh county data clears the shared cache. Current county records may differ from historical sale records. County appraised totals are only shown when both land and building values are present; a reported zero is valid.

## Property classes

Residential, Commercial, Industrial, Land / Other, and Unknown / Review use explicit text or conservative short-code heuristics from county PropertyType, LandUse, and BuildingType. Unknown numeric codes and conflicting uses remain Unknown / Review. Word boundaries avoid substring matches such as “plant” in “plantation.” These labels are screening aids, not verified zoning or a county-approved code crosswalk. County service metadata supplied no coded domain for these fields during validation. Review original fields in each popup.

## Preserved features

- Clickable parcel boundaries and bid/Max Return bubbles with full property popups.
- Street and satellite basemaps, map legend, bid colors and layer controls.
- Bid, owner/address/parcel search, property classes and residential/commercial quick view.
- Beds, baths, acreage, living area and year-built filters.
- County appraisal details, dashboard statistics, unmatched review and GeoJSON export.
- Added invalid-row CSV export, filtered shortlist CSV export, freshness indicators and refresh.

Polygon rendering uses one GeoJSON collection instead of one layer per geometry. Individual bid bubbles remain clickable. Large lists still have substantial browser payloads; marker virtualization or geometry simplification should be separately evaluated before changing display behavior.

## Development preview and production

Create a separate Streamlit app targeting the development branch and `tax_sale_app.py`; use the pinned requirements and Python 3.12. Do not repoint the existing production app to this branch. Validate uploads, filters, map popups, exports and mobile display in the preview before approving a merge. No production merge or deployment is included in this change.

See `DEVELOPMENT_REVIEW.md` for validation results and follow-up work.
