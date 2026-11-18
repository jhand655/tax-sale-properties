from __future__ import annotations

import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import folium
import pandas as pd
import requests
import streamlit as st
from branca.element import MacroElement, Template
from requests.adapters import HTTPAdapter
from streamlit_folium import st_folium
from urllib3.util.retry import Retry

APP_TITLE = "Spartanburg Tax Sale Deal Finder"
DEFAULT_CSV = Path(__file__).with_name("Cleaned_Spartanburg_Tax_Sale_2024.csv")
PARCEL_QUERY_URL = (
    "https://maps.spartanburgcounty.org/server/rest/services/"
    "OneMap/Tax_Parcels/MapServer/1/query"
)
PARCEL_LAYER_URL = (
    "https://maps.spartanburgcounty.org/server/rest/services/"
    "OneMap/Tax_Parcels/MapServer/1"
)
REQUIRED_COLUMNS = {
    "Item Number",
    "Tax Map Number",
    "Owner Name",
    "Property Address",
    "Bid Amount",
}
MAX_RETURN_BID_COLUMN = "Max Return Bid"
LEGACY_MAX_BID_COLUMN = "Max Bid"
OUT_FIELDS = [
    "MAPNUMBER",
    "OwnerName",
    "PropertyLocation",
    "StreetAddress",
    "City",
    "State",
    "Zip",
    "Acreage",
    "LandUse",
    "YearBuilt",
    "PropertyType",
    "BuildingType",
    "BuildingGrade",
    "TotalArea",
    "LivingArea",
    "Units",
    "StoryHeight",
    "FullBaths",
    "HalfBaths",
    "BedRooms",
    "Fireplaces",
    "Basement",
    "Garage",
    "CurrentAppraisedLandValue",
    "CurrentAppraisedBuildingValue",
]

BID_CATEGORIES = [
    ("Under $1,000", 0, 1_000, "#2A9D8F"),
    ("$1,000–$2,499", 1_000, 2_500, "#457B9D"),
    ("$2,500–$4,999", 2_500, 5_000, "#F4A261"),
    ("$5,000–$9,999", 5_000, 10_000, "#E76F51"),
    ("$10,000 and over", 10_000, float("inf"), "#9B2226"),
]


def configure_page() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🏠", layout="wide")
    st.markdown(
        """
        <style>
          :root {
            --investor-bg: #f3f5f7;
            --investor-surface: #ffffff;
            --investor-navy: #12202d;
            --investor-navy-2: #1b3143;
            --investor-text: #182633;
            --investor-muted: #687582;
            --investor-border: #dce3e8;
            --investor-green: #167a5b;
            --investor-green-soft: #e8f4ef;
            --investor-gold: #b98532;
            --investor-gold-soft: #f7f0e4;
            --investor-red: #a94c44;
            --investor-shadow: 0 8px 24px rgba(18, 32, 45, 0.08);
          }

          .stApp {
            background: #f3f5f7;
            color: var(--investor-text);
          }

          .block-container {
            padding-top: 1.1rem;
            padding-bottom: 2rem;
            max-width: 1520px;
          }

          [data-testid="stSidebar"] {
            background: #101c27;
            border-right: 1px solid #243747;
          }

          [data-testid="stSidebar"] * {
            color: #eef4f7;
          }

          [data-testid="stSidebar"] .stCaption,
          [data-testid="stSidebar"] small,
          [data-testid="stSidebar"] p {
            color: #b9c7d1 !important;
          }

          [data-testid="stSidebar"] hr {
            border-color: #2b4152;
          }

          [data-testid="stSidebar"] input,
          [data-testid="stSidebar"] [data-baseweb="select"] > div {
            background: #172938;
            border-color: #365064;
            color: #f7fbfd;
          }

          [data-testid="stSidebar"] .stSlider,
          [data-testid="stSidebar"] [data-testid="stFileUploader"] {
            color: #f7fbfd;
          }

          .investor-hero {
            background:
              linear-gradient(112deg, rgba(18,32,45,0.98) 0%, rgba(27,49,67,0.98) 66%, rgba(22,122,91,0.92) 100%);
            color: white;
            border-radius: 18px;
            padding: 24px 28px 22px 28px;
            box-shadow: 0 14px 34px rgba(18,32,45,0.17);
            border: 1px solid rgba(255,255,255,0.08);
            margin-bottom: 16px;
          }

          .investor-eyebrow {
            color: #9bd7c3;
            text-transform: uppercase;
            font-size: 0.74rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            margin-bottom: 7px;
          }

          .investor-title {
            font-size: 2rem;
            line-height: 1.1;
            font-weight: 800;
            letter-spacing: -0.025em;
            margin-bottom: 8px;
          }

          .investor-subtitle {
            color: #dce8ee;
            font-size: 0.98rem;
            line-height: 1.5;
            max-width: 940px;
          }

          .investor-pills {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 14px;
          }

          .investor-pill {
            border: 1px solid rgba(255,255,255,0.15);
            background: rgba(255,255,255,0.08);
            color: #f4f8fa;
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 0.8rem;
            font-weight: 650;
          }

          .deal-stat {
            background: #ffffff;
            border: 1px solid var(--investor-border);
            border-radius: 14px;
            padding: 15px 17px;
            min-height: 108px;
            box-shadow: var(--investor-shadow);
            border-top: 3px solid var(--investor-green);
          }

          .deal-stat.gold {
            border-top-color: var(--investor-gold);
          }

          .deal-stat.neutral {
            border-top-color: #6f8190;
          }

          .deal-stat-label {
            color: var(--investor-muted);
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.065em;
            text-transform: uppercase;
          }

          .deal-stat-value {
            color: var(--investor-navy);
            font-size: 1.85rem;
            line-height: 1.1;
            font-weight: 850;
            margin: 8px 0 5px 0;
          }

          .deal-stat-note {
            color: var(--investor-muted);
            font-size: 0.8rem;
            line-height: 1.35;
          }

          .investor-section {
            display: flex;
            align-items: center;
            gap: 11px;
            margin: 20px 0 10px 0;
          }

          .investor-section-bar {
            width: 5px;
            height: 32px;
            border-radius: 99px;
            background: var(--investor-green);
          }

          .investor-section-title {
            color: var(--investor-navy);
            font-size: 1.1rem;
            font-weight: 850;
            line-height: 1.2;
          }

          .investor-section-subtitle {
            color: var(--investor-muted);
            font-size: 0.87rem;
            margin-top: 2px;
          }

          .investor-note {
            background: #ffffff;
            border: 1px solid var(--investor-border);
            border-radius: 12px;
            padding: 12px 14px;
            color: var(--investor-muted);
            font-size: 0.87rem;
            line-height: 1.45;
          }

          .stDownloadButton > button {
            background: var(--investor-green);
            color: white;
            border: 1px solid var(--investor-green);
            border-radius: 10px;
            font-weight: 750;
          }

          .stDownloadButton > button:hover {
            background: #11674c;
            color: white;
            border-color: #11674c;
          }

          [data-testid="stExpander"] {
            background: white;
            border: 1px solid var(--investor-border);
            border-radius: 13px;
            overflow: hidden;
            box-shadow: 0 4px 14px rgba(18,32,45,0.045);
          }

          [data-testid="stDataFrame"] {
            border: 1px solid var(--investor-border);
            border-radius: 12px;
            overflow: hidden;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    st.markdown(
        """
        <div class="investor-hero">
          <div class="investor-eyebrow">Tax Sale Acquisition Dashboard</div>
          <div class="investor-title">Spartanburg Tax Sale Deal Finder</div>
          <div class="investor-subtitle">
            Screen tax-sale opportunities like an investor: compare bids, review your Max Return Bid,
            inspect parcel and assessor data, and narrow the map to properties that fit your acquisition criteria.
          </div>
          <div class="investor-pills">
            <div class="investor-pill">Bid vs. Max Return</div>
            <div class="investor-pill">Beds / Baths / Sq Ft</div>
            <div class="investor-pill">Acreage & Year Built</div>
            <div class="investor-pill">County Appraised Values</div>
            <div class="investor-pill">Official Parcel Geometry</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_header(title: str, subtitle: str = "") -> None:
    subtitle_html = (
        f'<div class="investor-section-subtitle">{html.escape(subtitle)}</div>'
        if subtitle
        else ""
    )
    st.markdown(
        f"""
        <div class="investor-section">
          <div class="investor-section-bar"></div>
          <div>
            <div class="investor-section-title">{html.escape(title)}</div>
            {subtitle_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_card(
    label: str,
    value: str,
    note: str,
    tone: str = "neutral",
) -> None:
    tone_class = "gold" if tone == "gold" else ("neutral" if tone == "neutral" else "")
    st.markdown(
        f"""
        <div class="deal-stat {tone_class}">
          <div class="deal-stat-label">{html.escape(label)}</div>
          <div class="deal-stat-value">{html.escape(value)}</div>
          <div class="deal-stat-note">{html.escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def normalize_tax_map(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().upper()
    return "" if text in {"NAN", "NONE", "<NA>", "NULL"} else text


def format_currency(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def format_bid_label(value: Any) -> str:
    """Compact map label; the popup retains the exact cents."""
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "$—"


def format_number(value: Any, decimals: int = 2) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def numeric_value(value: Any) -> float | None:
    """Return a usable numeric value, or None for blank/NaN assessor data."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def format_integer(value: Any) -> str:
    number = numeric_value(value)
    if number is None:
        return "—"
    return f"{int(round(number)):,}"


def format_year(value: Any) -> str:
    """Format assessor year values without a thousands separator."""
    number = numeric_value(value)
    if number is None:
        return "—"
    year = int(round(number))
    if year < 1000 or year > 2100:
        return str(year)
    return f"{year:04d}"


def format_sqft(value: Any) -> str:
    number = numeric_value(value)
    if number is None or number <= 0:
        return "—"
    return f"{number:,.0f} sq ft"


def format_acres(value: Any) -> str:
    number = numeric_value(value)
    if number is None or number <= 0:
        return "—"
    return f"{number:,.2f}"


def property_numeric_values(
    geojson: dict[str, Any],
    field: str,
    *,
    positive_only: bool = False,
) -> list[float]:
    values: list[float] = []
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        number = numeric_value(props.get(field))
        if number is None:
            continue
        if positive_only and number <= 0:
            continue
        values.append(number)
    return values


def sanitize_sql_string(value: str) -> str:
    return value.replace("'", "''")


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def get_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"POST"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "SpartanburgTaxSaleMap/1.0"})
    return session


def county_query(session: requests.Session, payload: dict[str, Any]) -> dict[str, Any]:
    response = session.post(PARCEL_QUERY_URL, data=payload, timeout=(10, 60))
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict) or "error" in result:
        error = result.get("error", {}) if isinstance(result, dict) else {}
        raise RuntimeError(error.get("message", "Invalid county response"))
    return result


@st.cache_data(ttl=86_400, show_spinner=False)
def fetch_parcels(tax_maps: tuple[str, ...]) -> dict[str, Any]:
    """Resolve object IDs first; verify every geometry batch is complete."""
    features: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    with get_session() as session:
        for group in chunked(sorted(set(filter(None, tax_maps))), 50):
            quoted = ",".join(f"'{sanitize_sql_string(value)}'" for value in group)
            ids_result = county_query(session, {
                "where": f"MAPNUMBER IN ({quoted})", "returnIdsOnly": "true", "f": "json",
            })
            if "objectIds" not in ids_result:
                raise RuntimeError("County response omitted parcel object IDs. Retry the query.")
            ids = sorted(set(ids_result["objectIds"] or []) - seen_ids)
            id_field = ids_result.get("objectIdFieldName")
            if ids and not id_field:
                raise RuntimeError("County response omitted its object ID field.")
            for batch in chunked(ids, 50):
                result = county_query(session, {
                    "objectIds": ",".join(map(str, batch)),
                    "outFields": ",".join(dict.fromkeys([id_field, *OUT_FIELDS])),
                    "returnGeometry": "true", "outSR": "4326", "f": "geojson",
                })
                returned = result.get("features")
                truncated = result.get("exceededTransferLimit") or (result.get("properties") or {}).get("exceededTransferLimit")
                if not isinstance(returned, list) or truncated:
                    raise RuntimeError("County returned an incomplete parcel batch. No partial results were used.")
                returned_ids = {(f.get("properties") or {}).get(id_field) for f in returned}
                if returned_ids != set(batch) or len(returned) != len(batch):
                    raise RuntimeError("County parcel count changed or results were incomplete. Refresh and retry.")
                features.extend(returned)
                seen_ids.update(batch)
    return {"type": "FeatureCollection", "features": features,
            "fetched_at": datetime.now(timezone.utc).isoformat()}


def load_tax_sale_file(uploaded_file: Any | None) -> pd.DataFrame:
    """Load the included CSV or a user-selected CSV/Excel tax-sale list."""
    source = uploaded_file if uploaded_file is not None else DEFAULT_CSV
    source_name = getattr(source, "name", str(source))
    suffix = Path(source_name).suffix.lower()

    if suffix == ".csv":
        df = pd.read_csv(source, dtype="string")
    elif suffix in {".xlsx", ".xlsm"}:
        df = pd.read_excel(
            source,
            engine="openpyxl",
            dtype="string",
        )
    elif suffix == ".xls":
        df = pd.read_excel(
            source,
            engine="xlrd",
            dtype="string",
        )
    else:
        raise ValueError(
            f"Unsupported file type '{suffix or 'unknown'}'. "
            "Choose a CSV or Excel file (.csv, .xlsx, .xlsm, or .xls). "
            "PDF lists must first be converted to a spreadsheet."
        )

    # Remove leading/trailing spaces from column headings.
    df.columns = [str(column).strip() for column in df.columns]

    if df.columns.duplicated().any():
        raise ValueError("Duplicate column headings are not supported.")
    if "Address" in df.columns and "Property Address" not in df.columns:
        df = df.rename(columns={"Address": "Property Address"})

    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(
            "Missing required column(s): "
            + ", ".join(sorted(missing))
            + ". Required headings are: "
            + ", ".join(sorted(REQUIRED_COLUMNS))
        )

    clean = df.copy()
    clean["Tax Map Number"] = clean["Tax Map Number"].map(normalize_tax_map)

    # Use the new heading while remaining compatible with older lists.
    if LEGACY_MAX_BID_COLUMN in clean.columns:
        if MAX_RETURN_BID_COLUMN not in clean.columns:
            clean = clean.rename(
                columns={LEGACY_MAX_BID_COLUMN: MAX_RETURN_BID_COLUMN}
            )
        else:
            new_values = clean[MAX_RETURN_BID_COLUMN]
            missing_new = new_values.isna() | new_values.astype(str).str.strip().isin(
                {"", "nan", "None", "—"}
            )
            clean.loc[missing_new, MAX_RETURN_BID_COLUMN] = clean.loc[
                missing_new, LEGACY_MAX_BID_COLUMN
            ]
            clean = clean.drop(columns=[LEGACY_MAX_BID_COLUMN])

    currency_columns = ["Bid Amount"]
    if MAX_RETURN_BID_COLUMN in clean.columns:
        currency_columns.append(MAX_RETURN_BID_COLUMN)

    for column in currency_columns:
        clean[column] = (
            clean[column]
            .astype(str)
            .str.strip()
            .str.replace(r"[$,]", "", regex=True)
            .replace({"": None, "nan": None, "None": None, "—": None})
        )
        clean[column] = pd.to_numeric(clean[column], errors="coerce")

    valid_bid = clean["Bid Amount"].map(lambda v: numeric_value(v) is not None and float(v) >= 0)
    valid_id = clean["Tax Map Number"].ne("")
    invalid = clean.loc[~(valid_id & valid_bid)].copy()
    invalid["Review Reason"] = "Missing parcel ID or invalid/negative bid"
    clean = clean.loc[valid_id & valid_bid].copy()
    duplicate_mask = clean["Tax Map Number"].duplicated(keep=False)
    duplicates = clean.loc[duplicate_mask].copy()
    duplicates["Review Reason"] = "Duplicate parcel ID: all related rows held for review"
    clean = clean.loc[~duplicate_mask].copy()
    if MAX_RETURN_BID_COLUMN in clean:
        invalid_max = clean[MAX_RETURN_BID_COLUMN].map(
            lambda v: numeric_value(v) is None or float(v) < 0)
        clean.loc[invalid_max, MAX_RETURN_BID_COLUMN] = float("nan")
    clean.attrs["review_rows"] = pd.concat([invalid, duplicates], ignore_index=True)
    clean.attrs["source_rows"] = len(df)

    return clean


def bid_style(amount: float) -> tuple[str, str]:
    """Return the legend label and exact map color for a bid amount."""
    for label, lower, upper, color in BID_CATEGORIES:
        if lower <= amount < upper:
            return label, color
    return BID_CATEGORIES[-1][0], BID_CATEGORIES[-1][3]


def bid_category(amount: float) -> str:
    return bid_style(amount)[0]


def bid_color(amount: float) -> str:
    return bid_style(amount)[1]


def classify_property_use(props: dict[str, Any]) -> str:
    """Normalize county PropertyType/LandUse into investor-friendly classes."""
    property_type = str(props.get("PropertyType") or "").strip().lower()
    land_use = str(props.get("LandUse") or "").strip().lower()
    building_type = str(props.get("BuildingType") or "").strip().lower()
    combined = " ".join([property_type, land_use, building_type])

    residential_terms = (
        "residential",
        "single family",
        "single-family",
        "multi family",
        "multi-family",
        "multifamily",
        "apartment",
        "condo",
        "condominium",
        "townhouse",
        "townhome",
        "duplex",
        "triplex",
        "fourplex",
        "mobile home",
        "manufactured home",
        "dwelling",
        "residence",
        "homesite",
    )
    commercial_terms = (
        "commercial",
        "retail",
        "office",
        "restaurant",
        "shopping",
        "store",
        "motel",
        "hotel",
        "bank",
        "medical",
        "business",
        "service station",
        "car wash",
    )
    industrial_terms = (
        "industrial",
        "manufacturing",
        "warehouse",
        "distribution",
        "factory",
        "plant",
        "mill",
    )

    matches: set[str] = set()
    code_classes = {"r": "Residential", "res": "Residential", "resi": "Residential",
                    "c": "Commercial", "com": "Commercial", "comm": "Commercial",
                    "i": "Industrial", "ind": "Industrial"}
    if property_type in code_classes:
        matches.add(code_classes[property_type])
    for label, terms in [("Residential", residential_terms),
                         ("Commercial", commercial_terms), ("Industrial", industrial_terms)]:
        if any(re.search(r"\b" + re.escape(term) + r"\b", combined) for term in terms):
            matches.add(label)
    if len(matches) == 1:
        return next(iter(matches))
    if len(matches) > 1:
        return "Unknown / Review"
    if re.search(r"\b(vacant|undeveloped|agricultural|farmland|timberland)\b", combined):
        return "Land / Other"
    return "Unknown / Review"


def merge_tax_data(
    parcel_geojson: dict[str, Any], tax_df: pd.DataFrame
) -> tuple[dict[str, Any], list[str]]:
    sale_lookup = tax_df.set_index("Tax Map Number").to_dict(orient="index")
    matched: set[str] = set()
    merged_features: list[dict[str, Any]] = []

    for feature in parcel_geojson.get("features", []):
        props = dict(feature.get("properties") or {})
        tax_map = normalize_tax_map(props.get("MAPNUMBER", ""))
        sale = sale_lookup.get(tax_map)
        if sale is None:
            continue

        if not valid_geometry(feature.get("geometry")):
            continue
        matched.add(tax_map)
        bid = float(sale["Bid Amount"])
        category, color = bid_style(bid)
        max_bid = sale.get(MAX_RETURN_BID_COLUMN)
        if pd.isna(max_bid):
            max_bid = None
        land = numeric_value(props.get("CurrentAppraisedLandValue"))
        building = numeric_value(props.get("CurrentAppraisedBuildingValue"))
        if land is None or building is None:
            appraised_total = None
        else:
            appraised_total = (land or 0.0) + (building or 0.0)

        props.update(
            {
                "TaxMapNumber": tax_map,
                "ItemNumber": sale["Item Number"],
                "SaleOwnerName": sale["Owner Name"],
                "SalePropertyAddress": sale["Property Address"],
                "BidAmount": bid,
                "MaxReturnBid": max_bid,
                "BidCategory": category,
                "BidColor": color,
                "AppraisedTotal": appraised_total,
                "PropertyClass": classify_property_use(props),
                "ClassificationBasis": "Heuristic from county type/use fields; verify before relying on it",
            }
        )
        merged_features.append(
            {
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": props,
            }
        )

    unmatched = sorted(set(tax_df["Tax Map Number"]) - matched)
    return {"type": "FeatureCollection", "features": merged_features,
            "fetched_at": parcel_geojson.get("fetched_at")}, unmatched


def coordinate_pairs(value: Any) -> Iterable[tuple[float, float]]:
    if not isinstance(value, list) or not value:
        return
    if (
        len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    for child in value:
        yield from coordinate_pairs(child)


def valid_geometry(geometry: Any) -> bool:
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return False
    pairs = list(coordinate_pairs(geometry.get("coordinates")))
    return len(pairs) >= 4 and all(
        math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90
        for x, y in pairs)


def parcel_count(geojson: dict[str, Any]) -> int:
    return len({(f.get("properties") or {}).get("TaxMapNumber")
                for f in geojson.get("features", [])})


def geojson_bounds(geojson: dict[str, Any]) -> list[list[float]] | None:
    pairs: list[tuple[float, float]] = []
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        pairs.extend(coordinate_pairs(geometry.get("coordinates")))
    if not pairs:
        return None
    longitudes = [point[0] for point in pairs]
    latitudes = [point[1] for point in pairs]
    return [[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]]


def ring_centroid(ring: Any) -> tuple[float, tuple[float, float]] | None:
    """Return ring area and a latitude/longitude centroid."""
    if not isinstance(ring, list) or len(ring) < 3:
        return None

    points: list[tuple[float, float]] = []
    for point in ring:
        if (
            isinstance(point, list)
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        ):
            points.append((float(point[0]), float(point[1])))

    if len(points) < 3:
        return None
    if points[0] != points[-1]:
        points.append(points[0])

    twice_area = 0.0
    centroid_x_sum = 0.0
    centroid_y_sum = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        cross = x1 * y2 - x2 * y1
        twice_area += cross
        centroid_x_sum += (x1 + x2) * cross
        centroid_y_sum += (y1 + y2) * cross

    if abs(twice_area) < 1e-14:
        unique_points = points[:-1] or points
        longitude = sum(point[0] for point in unique_points) / len(unique_points)
        latitude = sum(point[1] for point in unique_points) / len(unique_points)
        return 0.0, (latitude, longitude)

    longitude = centroid_x_sum / (3.0 * twice_area)
    latitude = centroid_y_sum / (3.0 * twice_area)
    return abs(twice_area) / 2.0, (latitude, longitude)


def parcel_label_location(geometry: dict[str, Any]) -> tuple[float, float] | None:
    """Choose the centroid of the largest polygon shell for a label."""
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    outer_rings: list[Any] = []
    if geometry_type == "Polygon" and isinstance(coordinates, list) and coordinates:
        outer_rings.append(coordinates[0])
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        for polygon in coordinates:
            if isinstance(polygon, list) and polygon:
                outer_rings.append(polygon[0])

    candidates = [result for ring in outer_rings if (result := ring_centroid(ring))]
    if not candidates:
        return None
    return max(candidates, key=lambda result: result[0])[1]


def bid_bubble_html(
    amount: Any,
    max_return_bid: Any,
    color: str,
) -> str:
    bid_label = html.escape(format_bid_label(amount))
    safe_color = html.escape(color)

    max_number = numeric_value(max_return_bid)
    if max_number is None:
        max_line = ""
    else:
        max_label = html.escape(format_bid_label(max_number))
        max_line = (
            "<div style='font-size:10px;font-weight:600;line-height:13px;"
            "border-top:1px solid rgba(255,255,255,.55);margin-top:2px;"
            "padding-top:1px'>Max Return "
            + max_label
            + "</div>"
        )

    return f"""
    <div style="display:flex;flex-direction:column;align-items:center;
                filter:drop-shadow(0 1px 2px rgba(0,0,0,.45));white-space:nowrap;
                cursor:pointer;">
      <div style="background:{safe_color};color:white;border:2px solid white;
                  border-radius:12px;padding:3px 8px;font-family:Arial,sans-serif;
                  min-width:82px;text-align:center;">
        <div style="font-size:11px;font-weight:700;line-height:15px;">Bid {bid_label}</div>
        {max_line}
      </div>
      <div style="width:0;height:0;border-left:5px solid transparent;
                  border-right:5px solid transparent;border-top:7px solid {safe_color};
                  margin-top:-1px;"></div>
    </div>
    """


def popup_html(props: dict[str, Any]) -> str:
    """Build one shared popup used by BOTH the parcel polygon and the bid bubble."""

    def esc(value: Any) -> str:
        if value is None:
            return "—"
        value_text = str(value).strip()
        if not value_text or value_text.lower() in {"nan", "none"}:
            return "—"
        return html.escape(value_text)

    def value_or_dash(value: Any, formatter=None) -> str:
        if numeric_value(value) is None:
            return "—"
        return formatter(value) if formatter else esc(value)

    def row(label: str, value: Any, strong: bool = False) -> str:
        weight = "700" if strong else "500"
        return (
            "<div style='display:grid;grid-template-columns:128px 1fr;"
            "column-gap:12px;padding:3px 0;align-items:start'>"
            f"<div style='color:#555'>{html.escape(label)}</div>"
            f"<div style='font-weight:{weight};text-align:right'>{esc(value)}</div>"
            "</div>"
        )

    def section_header(title: str) -> str:
        return (
            "<div style='margin:10px 0 6px;padding:5px 8px;"
            "background:#f0f0f0;border-left:4px solid #444;"
            "font-weight:700;font-size:13px'>"
            + html.escape(title)
            + "</div>"
        )

    max_return_bid = props.get("MaxReturnBid")
    max_return_display = (
        format_currency(max_return_bid)
        if numeric_value(max_return_bid) is not None
        else "—"
    )

    tax_sale_html = (
        section_header("TAX SALE")
        + row("Bid", format_currency(props.get("BidAmount")), strong=True)
        + row("Max Return Bid", max_return_display, strong=True)
        + row("Item", props.get("ItemNumber", "—"))
        + row("Tax Map", props.get("TaxMapNumber", "—"))
        + row("Owner", props.get("SaleOwnerName", "—"))
        + row("Address", props.get("SalePropertyAddress", "—"))
    )

    beds = value_or_dash(props.get("BedRooms"), format_integer)
    full_baths = value_or_dash(props.get("FullBaths"), format_integer)
    half_baths = value_or_dash(props.get("HalfBaths"), format_integer)
    living_area = value_or_dash(props.get("LivingArea"), format_sqft)
    acreage = value_or_dash(props.get("Acreage"), format_acres)
    year_built = value_or_dash(props.get("YearBuilt"), format_year)
    stories = esc(props.get("StoryHeight"))

    property_summary = (
        section_header("PROPERTY")
        + (
            "<div style='padding:2px 0 6px;font-weight:700;font-size:14px'>"
            f"{beds} Beds &nbsp;•&nbsp; {full_baths} Full Baths"
            f" &nbsp;•&nbsp; {half_baths} Half Baths"
            "</div>"
        )
        + (
            "<div style='padding:0 0 6px;font-size:13px'>"
            f"{living_area} &nbsp;•&nbsp; {acreage} Acres"
            f" &nbsp;•&nbsp; Built {year_built}"
            f" &nbsp;•&nbsp; {stories} Stories"
            "</div>"
        )
        + row(
            "County Location",
            props.get("PropertyLocation")
            or props.get("StreetAddress")
            or "—",
        )
        + row("Property Class", props.get("PropertyClass") or "Unknown / Review", strong=True)
        + row("Class basis", props.get("ClassificationBasis", "Heuristic; verify county record"))
        + row("Garage", props.get("Garage") or "—")
        + row("Basement", props.get("Basement") or "—")
        + row("County Property Type", props.get("PropertyType") or "—")
        + row("Building Type", props.get("BuildingType") or "—")
        + row("Building Grade", props.get("BuildingGrade") or "—")
        + row("Land Use", props.get("LandUse") or "—")
    )

    county_values_html = (
        section_header("COUNTY VALUES")
        + row(
            "Land",
            value_or_dash(
                props.get("CurrentAppraisedLandValue"),
                format_currency,
            ),
        )
        + row(
            "Building",
            value_or_dash(
                props.get("CurrentAppraisedBuildingValue"),
                format_currency,
            ),
        )
        + row(
            "Total",
            value_or_dash(props.get("AppraisedTotal"), format_currency),
            strong=True,
        )
    )

    return (
        "<div style='font-family:Arial,sans-serif;font-size:12px;"
        "min-width:380px;max-width:430px;color:#111'>"
        "<div style='font-size:10px;color:#777;text-align:right;margin-bottom:2px'>"
        "Investor UI v6.2.1-dev"
        "</div>"
        + tax_sale_html
        + property_summary
        + county_values_html
        + (
            f"<div style='margin-top:10px;font-size:11px'>"
            f"<a href='{PARCEL_LAYER_URL}' target='_blank' rel='noopener noreferrer'>"
            "County parcel service</a></div>"
        )
        + "</div>"
    )


def filter_geojson(
    geojson: dict[str, Any],
    min_bid: float,
    max_bid: float,
    selected_categories: list[str],
    search_text: str,
    property_classes: list[str] | None = None,
    min_bedrooms: int | None = None,
    min_full_baths: int | None = None,
    acreage_range: tuple[float, float] | None = None,
    living_area_range: tuple[float, float] | None = None,
    year_built_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    query = search_text.strip().lower()
    features: list[dict[str, Any]] = []

    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        bid = float(props.get("BidAmount", 0))
        if not (min_bid <= bid <= max_bid):
            continue
        if props.get("BidCategory") not in selected_categories:
            continue

        if property_classes is not None:
            if props.get("PropertyClass", "Unknown / Review") not in property_classes:
                continue

        if min_bedrooms is not None:
            bedrooms = numeric_value(props.get("BedRooms"))
            if bedrooms is None or bedrooms < min_bedrooms:
                continue

        if min_full_baths is not None:
            baths = numeric_value(props.get("FullBaths"))
            if baths is None or baths < min_full_baths:
                continue

        if acreage_range is not None:
            acreage = numeric_value(props.get("Acreage"))
            if acreage is None or not (acreage_range[0] <= acreage <= acreage_range[1]):
                continue

        if living_area_range is not None:
            living_area = numeric_value(props.get("LivingArea"))
            if living_area is None or not (
                living_area_range[0] <= living_area <= living_area_range[1]
            ):
                continue

        if year_built_range is not None:
            year_built = numeric_value(props.get("YearBuilt"))
            if year_built is None or not (
                year_built_range[0] <= year_built <= year_built_range[1]
            ):
                continue

        haystack = " ".join(
            str(props.get(field, ""))
            for field in (
                "TaxMapNumber",
                "ItemNumber",
                "SaleOwnerName",
                "SalePropertyAddress",
                "PropertyLocation",
                "City",
                "LandUse",
                "PropertyType",
                "BuildingType",
            )
        ).lower()
        if query and query not in haystack:
            continue

        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


class MapLegend(MacroElement):
    def __init__(self) -> None:
        super().__init__()
        self._name = "MapLegend"
        rows = "".join(
            f"<div style='display:flex;align-items:center;gap:7px;margin:3px 0'>"
            f"<span style='width:12px;height:12px;background:{color};border:1px solid #333;display:inline-block'></span>"
            f"<span>{html.escape(label)}</span></div>"
            for label, _, _, color in BID_CATEGORIES
        )
        self._template = Template(
            """
            {% macro html(this, kwargs) %}
            <div style="position: fixed; bottom: 28px; left: 28px; z-index:9999;
                        background:white; border:1px solid #777; border-radius:5px;
                        padding:10px 12px; font-size:12px; box-shadow:0 1px 4px rgba(0,0,0,.25)">
              <div style="font-weight:bold;margin-bottom:5px">Bid amount</div>
              """
            + rows
            + """
            </div>
            {% endmacro %}
            """
        )


def build_map(geojson: dict[str, Any]) -> folium.Map:
    map_object = folium.Map(
        location=[34.95, -81.93],
        zoom_start=10,
        tiles="OpenStreetMap",
        control_scale=True,
        prefer_canvas=True,
    )
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Esri World Imagery",
        name="Satellite",
        overlay=False,
        control=True,
    ).add_to(map_object)

    parcel_layer = folium.FeatureGroup(
        name="Tax-sale parcels", overlay=True, show=True
    ).add_to(map_object)
    bid_label_layer = folium.FeatureGroup(
        name="Bid amount bubbles", overlay=True, show=True
    ).add_to(map_object)

    # Bid bubbles are deliberately clickable and open the same full details
    # as clicking the parcel polygon. The parcel polygons remain clickable too.
    map_object.get_root().html.add_child(
        folium.Element(
            """
            <style>
              .tax-bid-div-icon {
                background: transparent !important;
                border: none !important;
                cursor: pointer !important;
              }
              .tax-bid-div-icon:hover > div {
                transform: scale(1.06);
                transform-origin: bottom center;
              }
            </style>
            """
        )
    )

    map_features = []
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        map_features.append({"type": "Feature", "geometry": feature["geometry"],
                             "properties": {"color": props.get("BidColor", "#457B9D"),
                                            "label": html.escape(str(props.get("TaxMapNumber", ""))) + " · " + format_currency(props.get("BidAmount")),
                                            "details": popup_html(props)}})
    if map_features:
        folium.GeoJson(
            {"type": "FeatureCollection", "features": map_features},
            style_function=lambda f: {"color": f["properties"]["color"], "weight": 2,
                                      "fillColor": f["properties"]["color"], "fillOpacity": 0.48},
            highlight_function=lambda f: {"weight": 4, "fillOpacity": 0.68},
            tooltip=folium.GeoJsonTooltip(fields=["label"], labels=False),
            popup=folium.GeoJsonPopup(fields=["details"], labels=False, max_width=460),
        ).add_to(parcel_layer)

    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        color = props.get("BidColor", "#457B9D")
        label_location = parcel_label_location(feature.get("geometry") or {})
        if label_location:
            folium.Marker(
                location=label_location,
                icon=folium.DivIcon(
                    html=bid_bubble_html(
                        props.get("BidAmount"),
                        props.get("MaxReturnBid"),
                        color,
                    ),
                    icon_size=(138, 54),
                    icon_anchor=(69, 54),
                    class_name="tax-bid-div-icon",
                ),
                tooltip=folium.Tooltip(
                    f"{html.escape(str(props.get('TaxMapNumber', '')))} · "
                    f"Bid {format_currency(props.get('BidAmount'))} · "
                    f"Max Return {format_currency(props.get('MaxReturnBid'))}"
                ),
                popup=folium.Popup(popup_html(props), max_width=460),
                interactive=True,
                keyboard=True,
                bubblingMouseEvents=False,
                riseOnHover=True,
                zIndexOffset=1000,
            ).add_to(bid_label_layer)

    bounds = geojson_bounds(geojson)
    if bounds:
        map_object.fit_bounds(bounds, padding=(18, 18))
    map_object.add_child(MapLegend())
    folium.LayerControl(collapsed=False).add_to(map_object)
    return map_object


def main() -> None:
    configure_page()
    render_hero()

    with st.sidebar:
        st.markdown(
            """
            <div style="padding:8px 0 8px 0">
              <div style="font-size:0.72rem;color:#7fc8ae;font-weight:800;letter-spacing:.11em;text-transform:uppercase">
                Investor Workspace
              </div>
              <div style="font-size:1.28rem;font-weight:850;color:#ffffff;margin-top:3px">
                Deal Filters
              </div>
              <div style="font-size:0.88rem;color:#b9c7d1;margin-top:5px;line-height:1.45">
                Load a sale list and narrow opportunities by price, property characteristics, and county data.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.header("Sale List")
        uploaded = st.file_uploader(
            "Use another tax-sale list",
            help=(
                "The file picker shows all files. The app can directly load "
                "CSV and Excel files: .csv, .xlsx, .xlsm, and .xls. "
                "Leave blank to use the included 2024 cleaned list."
            ),
        )
        st.caption(
            "Supported uploads: CSV and Excel. Use the optional column heading "
            "'Max Return Bid' to show that value in parcel details. Older files "
            "using 'Max Bid' remain compatible. PDF lists must be converted to "
            "a spreadsheet before loading."
        )

    try:
        tax_df = load_tax_sale_file(uploaded)
    except Exception as exc:
        st.error(f"The tax-sale file could not be loaded: {exc}")
        st.stop()

    if uploaded is None:
        st.warning("Historical 2024 sale list — these properties are not presented as a current sale. Upload a current list to evaluate another sale.")
    else:
        st.caption(f"Sale source: {uploaded.name}. Confirm its sale year and current availability.")
    review_rows = tax_df.attrs.get("review_rows", pd.DataFrame())
    if not review_rows.empty:
        st.warning(f"{len(review_rows)} source rows need review and were excluded from mapping.")
        with st.expander("Review invalid or duplicate sale rows", expanded=True):
            st.dataframe(review_rows, hide_index=True)
            st.download_button("Download rows for review", review_rows.to_csv(index=False),
                               "sale_rows_for_review.csv", "text/csv")
    if tax_df.empty:
        st.info("No usable unique parcels remain. Upload a list with parcel IDs and nonnegative numeric bids.")
        st.stop()
    if st.sidebar.button("Refresh county data"):
        fetch_parcels.clear()

    with st.spinner("Matching tax map numbers to official county parcel polygons…"):
        try:
            parcel_geojson = fetch_parcels(tuple(sorted(tax_df["Tax Map Number"])))
            merged_geojson, unmatched = merge_tax_data(parcel_geojson, tax_df)
        except Exception as exc:
            st.error(
                "County parcel data could not be loaded completely. "
                "Refresh or retry; details are shown below."
            )
            st.code(str(exc))
            st.caption(f"Parcel service: {PARCEL_LAYER_URL}")
            st.stop()

    matched_count = parcel_count(merged_geojson)
    st.caption(f"County data fetched (UTC): {parcel_geojson.get('fetched_at', 'unavailable')}. Cached for up to 24 hours.")
    bid_min = float(tax_df["Bid Amount"].min())
    bid_max = float(tax_df["Bid Amount"].max())

    acreage_values = property_numeric_values(
        merged_geojson, "Acreage", positive_only=True
    )
    living_area_values = property_numeric_values(
        merged_geojson, "LivingArea", positive_only=True
    )
    year_built_values = [
        value
        for value in property_numeric_values(
            merged_geojson, "YearBuilt", positive_only=True
        )
        if 1700 <= value <= 2100
    ]

    with st.sidebar:
        st.header("Acquisition Filters")
        st.caption("Investor UI development · v6.2.1")
        search_text = st.text_input(
            "Search",
            placeholder="Owner, address, item, parcel…",
        )
        st.subheader("Bid ranges")
        st.caption("Choose the ranges to display. Colors match the map key.")
        st.markdown(
            """
            <style>
              [data-testid="stSidebar"] [data-testid="stCheckbox"] {
                margin-top: -0.45rem;
                margin-bottom: -0.35rem;
              }
              [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
                gap: 0.45rem;
              }
            </style>
            """,
            unsafe_allow_html=True,
        )

        selected_categories: list[str] = []
        filter_columns = st.columns(2, gap="small")
        for idx, (label, _, _, color) in enumerate(BID_CATEGORIES):
            with filter_columns[idx % 2]:
                swatch_col, checkbox_col = st.columns([0.12, 0.88], gap="small")
                with swatch_col:
                    st.markdown(
                        (
                            "<div style='width:15px;height:15px;"
                            f"background:{color};border:1px solid #444;"
                            "border-radius:4px;margin-top:7px;'></div>"
                        ),
                        unsafe_allow_html=True,
                    )
                with checkbox_col:
                    checked = st.checkbox(
                        label,
                        value=True,
                        key=f"bid_range_{idx}",
                    )
                if checked:
                    selected_categories.append(label)
        if bid_min == bid_max:
            selected_bid = (bid_min, bid_max)
            st.caption(f"All loaded bids: {format_currency(bid_min)}")
        else:
            selected_bid = st.slider(
                "Bid amount", min_value=bid_min, max_value=bid_max,
                value=(bid_min, bid_max), format="$%.2f",
            )

        st.divider()
        st.subheader("Property Criteria")

        property_class_options = [
            "Residential",
            "Commercial",
            "Industrial",
            "Land / Other",
            "Unknown / Review",
        ]

        quick_property_view = st.radio(
            "Quick view",
            options=["All", "Residential", "Commercial"],
            horizontal=True,
            index=0,
            help=(
                "Use this for a fast Residential or Commercial view. "
                "Choose All to use the detailed Property Class selections below."
            ),
        )

        detailed_property_classes = st.multiselect(
            "Property class",
            options=property_class_options,
            default=property_class_options,
            disabled=quick_property_view != "All",
            help=(
                "Investor-friendly classification derived from the county's "
                "Property Type, Land Use, and Building Type fields. These are heuristic classifications, not verified zoning. "
                "This detailed selector is active when Quick view is set to All."
            ),
        )

        if quick_property_view == "Residential":
            selected_property_classes = ["Residential"]
        elif quick_property_view == "Commercial":
            selected_property_classes = ["Commercial"]
        else:
            selected_property_classes = detailed_property_classes

        if quick_property_view != "All":
            st.caption(
                f"Quick View active: {quick_property_view} properties only."
            )

        bedroom_choice = st.selectbox(
            "Minimum bedrooms",
            options=["Any", 1, 2, 3, 4, 5],
            index=0,
            format_func=lambda value: "5+" if value == 5 else str(value),
        )
        min_bedrooms = None if bedroom_choice == "Any" else int(bedroom_choice)

        bath_choice = st.selectbox(
            "Minimum full baths",
            options=["Any", 1, 2, 3, 4],
            index=0,
            format_func=lambda value: "4+" if value == 4 else str(value),
        )
        min_full_baths = None if bath_choice == "Any" else int(bath_choice)

        acreage_filter = None
        if acreage_values:
            acreage_default = (
                float(math.floor(min(acreage_values) * 10) / 10),
                float(math.ceil(max(acreage_values) * 10) / 10),
            )
            if acreage_default[0] < acreage_default[1]:
                selected_acreage = st.slider(
                    "Acreage",
                    min_value=acreage_default[0],
                    max_value=acreage_default[1],
                    value=acreage_default,
                    step=0.1,
                    format="%.1f ac",
                )
                if selected_acreage != acreage_default:
                    acreage_filter = selected_acreage

        living_area_filter = None
        if living_area_values:
            living_min = int(math.floor(min(living_area_values) / 100) * 100)
            living_max = int(math.ceil(max(living_area_values) / 100) * 100)
            if living_min < living_max:
                selected_living = st.slider(
                    "Living area",
                    min_value=living_min,
                    max_value=living_max,
                    value=(living_min, living_max),
                    step=100,
                    format="%d sq ft",
                )
                if selected_living != (living_min, living_max):
                    living_area_filter = (
                        float(selected_living[0]),
                        float(selected_living[1]),
                    )

        year_built_filter = None
        if year_built_values:
            year_min = int(min(year_built_values))
            year_max = int(max(year_built_values))
            if year_min < year_max:
                selected_year = st.slider(
                    "Year built",
                    min_value=year_min,
                    max_value=year_max,
                    value=(year_min, year_max),
                    step=1,
                )
                if selected_year != (year_min, year_max):
                    year_built_filter = selected_year

        st.caption(
            "Property filters use county assessor data. Parcels with missing "
            "building data remain visible until you narrow a related filter."
        )

    filtered_geojson = filter_geojson(
        merged_geojson,
        min_bid=selected_bid[0],
        max_bid=selected_bid[1],
        selected_categories=selected_categories,
        search_text=search_text,
        property_classes=selected_property_classes,
        min_bedrooms=min_bedrooms,
        min_full_baths=min_full_baths,
        acreage_range=acreage_filter,
        living_area_range=living_area_filter,
        year_built_range=year_built_filter,
    )
    visible_count = parcel_count(filtered_geojson)

    avg_bid = (
        f"{tax_df['Bid Amount'].mean():,.0f}"
        if not tax_df.empty
        else "0"
    )
    max_return_series = (
        pd.to_numeric(tax_df[MAX_RETURN_BID_COLUMN], errors="coerce")
        if MAX_RETURN_BID_COLUMN in tax_df.columns
        else pd.Series(dtype=float)
    )
    opportunity_count = 0
    if not max_return_series.empty:
        comparable = tax_df.copy()
        comparable["_max_return_numeric"] = max_return_series
        opportunity_count = int(
            (
                comparable["_max_return_numeric"].notna()
                & (comparable["Bid Amount"] <= comparable["_max_return_numeric"])
            ).sum()
        )

    stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
    with stat_col1:
        render_stat_card(
            "Sale Inventory",
            f"{len(tax_df):,}",
            "Properties loaded into the acquisition list.",
            tone="neutral",
        )
    with stat_col2:
        render_stat_card(
            "Mapped Parcels",
            f"{matched_count:,}",
            "Properties matched to official county geometry.",
            tone="neutral",
        )
    with stat_col3:
        render_stat_card(
            "Current Shortlist",
            f"{visible_count:,}",
            "Deals remaining after your active filters.",
            tone="green",
        )
    with stat_col4:
        if MAX_RETURN_BID_COLUMN in tax_df.columns:
            render_stat_card(
                "Within Max Return",
                f"{opportunity_count:,}",
                "Loaded properties where current bid is at or below Max Return Bid.",
                tone="gold",
            )
        else:
            render_stat_card(
                "Average Bid",
                f"${avg_bid}",
                "Average bid across the loaded sale list.",
                tone="gold",
            )

    render_section_header(
        "Opportunity Map",
        "Scan deals visually, then click any parcel or bid bubble for acquisition and property details.",
    )
    if visible_count:
        map_object = build_map(filtered_geojson)
        st_folium(map_object, height=720, use_container_width=True, returned_objects=[])
    else:
        st.warning("No parcels match the current filters.")

    render_section_header(
        "Deal Data & Export",
        "Export the matched parcel layer or review records that need additional research.",
    )
    download_col, info_col = st.columns([1, 2])
    with download_col:
        st.download_button(
            "Export mapped deals (GeoJSON)",
            data=json.dumps(merged_geojson),
            file_name="spartanburg_tax_sale_parcels.geojson",
            mime="application/geo+json",
            width="stretch",
        )
    with info_col:
        st.markdown(
            """
            <div class="footer-note">
              Parcel boundaries, acreage, building characteristics, and county values come from
              Spartanburg County GIS/assessor data. Tax-sale owner, address, item number, bid,
              and optional Max Return Bid come from the uploaded spreadsheet.
            </div>
            """,
            unsafe_allow_html=True,
        )

    if unmatched:
        with st.expander(f"Review {len(unmatched)} unmatched or unmappable tax map number(s)"):
            unmatched_df = tax_df[tax_df["Tax Map Number"].isin(unmatched)].copy()
            unmatched_df.attrs = {}
            unmatched_columns = {
                "Bid Amount": st.column_config.NumberColumn(format="$%.2f")
            }
            if MAX_RETURN_BID_COLUMN in unmatched_df.columns:
                unmatched_columns[MAX_RETURN_BID_COLUMN] = st.column_config.NumberColumn(
                    format="$%.2f"
                )
            st.dataframe(
                unmatched_df,
                width="stretch",
                hide_index=True,
                column_config=unmatched_columns,
            )

    render_section_header(
        "Current Deal Shortlist",
        "Review the properties still in play after applying your acquisition filters.",
    )
    with st.expander("Open deal shortlist table"):
        table_rows: list[dict[str, Any]] = []
        for feature in filtered_geojson.get("features", []):
            props = feature.get("properties") or {}
            table_rows.append(
                {
                    "Item Number": props.get("ItemNumber"),
                    "Tax Map Number": props.get("TaxMapNumber"),
                    "Owner Name": props.get("SaleOwnerName"),
                    "Property Address": props.get("SalePropertyAddress"),
                    "Property Class": props.get("PropertyClass"),
                    "Bid Amount": props.get("BidAmount"),
                    "Max Return Bid": props.get("MaxReturnBid"),
                    "Bedrooms": props.get("BedRooms"),
                    "Full Baths": props.get("FullBaths"),
                    "Half Baths": props.get("HalfBaths"),
                    "Living Area": props.get("LivingArea"),
                    "Acreage": props.get("Acreage"),
                    "Year Built": props.get("YearBuilt"),
                    "Garage": props.get("Garage"),
                    "Basement": props.get("Basement"),
                    "Land Use": props.get("LandUse"),
                    "County Appraised Value": props.get("AppraisedTotal"),
                }
            )

        visible_df = pd.DataFrame(table_rows)
        if not visible_df.empty:
            visible_df = visible_df.drop_duplicates(subset=["Tax Map Number"])
        if not visible_df.empty:
            if visible_df["Max Return Bid"].isna().all():
                visible_df = visible_df.drop(columns=["Max Return Bid"])

            table_columns = {
                "Bid Amount": st.column_config.NumberColumn(format="$%.2f"),
                "County Appraised Value": st.column_config.NumberColumn(format="$%.0f"),
                "Living Area": st.column_config.NumberColumn(format="%.0f sq ft"),
                "Acreage": st.column_config.NumberColumn(format="%.2f"),
            }
            if "Max Return Bid" in visible_df.columns:
                table_columns["Max Return Bid"] = st.column_config.NumberColumn(
                    format="$%.2f"
                )

            st.dataframe(
                visible_df.sort_values("Bid Amount"),
                width="stretch",
                hide_index=True,
                column_config=table_columns,
            )
            st.download_button("Export current shortlist (CSV)", visible_df.to_csv(index=False),
                               "spartanburg_shortlist.csv", "text/csv")
        else:
            st.caption("No filtered properties to display.")



if __name__ == "__main__":
    main()
