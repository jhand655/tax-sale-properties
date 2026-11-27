from __future__ import annotations

import html
import os
import io
import json
from statistics import median
import math
import re
import threading
from time import monotonic
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from urllib.parse import urljoin
from lxml import html as recorder_html, etree
from market_library import SPARTANBURG, fetch_listing, read_list

import folium
import pandas as pd
import requests
import streamlit as st
from branca.element import MacroElement, Template
from requests.adapters import HTTPAdapter
from streamlit_folium import st_folium
from concurrent.futures import ThreadPoolExecutor
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
LIEN_REVIEW_FILE = Path(__file__).with_name("lien_reviews.json")
ROD_SEARCH_URL = "https://search.spartanburgdeeds.com/"
SCDOR_LIEN_URL = "https://dor.sc.gov/LienRegistry"
SC_COURTS_URL = "https://publicindex.sccourts.org/spartanburg/publicindex/"
LIEN_REVIEW_STAGES = [
    "Not Reviewed",
    "Preliminary Review In Progress",
    "Preliminary Review Complete",
    "Needs Human Review",
    "Potential Lien / Judgment",
    "Attorney / Title Search Verified",
]
LIEN_RISK_LEVELS = [
    "Not Assessed",
    "No Obvious Issue Identified",
    "Review Required",
    "Potential Lien / Judgment",
    "High Risk",
]
LIEN_CHECK_RESULTS = [
    "Not Checked",
    "None Identified",
    "Possible Match",
    "Record Found",
    "Released / Satisfied",
    "Not Applicable",
    "Source Unavailable",
]
LIEN_CHECK_FIELDS = [
    ("mortgage", "Mortgage / Deed of Trust"),
    ("mortgage_release", "Mortgage Satisfaction / Release"),
    ("federal_tax_lien", "Federal Tax Lien"),
    ("mechanics_lien", "Mechanic's Lien"),
    ("state_tax_lien", "SC State Tax Lien"),
    ("judgment", "Judgment"),
    ("foreclosure", "Foreclosure / Lis Pendens"),
    ("other_encumbrance", "Other Recorded Encumbrance"),
]
OUT_FIELDS = [
    "MAPNUMBER",
    "OwnerName",
    "PropertyLocation",
    "StreetAddress",
    "City",
    "State",
    "Zip",
    "DeedBook",
    "DeedPage",
    "InstrumentNumber",
    "SaleDate",
    "PreviousOwnerName",
    "LegalDescription",

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
            border-inline-end: 1px solid rgba(104,117,130,0.25);
          }
          [data-testid="stSidebar"] .st-key-filter_count {
            border-inline-start: 3px solid #269577;
            padding-inline-start: .7rem;
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
          <div class="investor-title">BidSift</div>
          <div class="investor-subtitle">Sift the list. Find the deals.</div>
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


MAX_REDEMPTION_RATE = Decimal("0.12")


def full_rate_bid(opening_bid):
    cents = Decimal(str(opening_bid)) * 100
    return float((cents / MAX_REDEMPTION_RATE).to_integral_value(rounding=ROUND_DOWN) / 100)


def capped_bid_return(bid, opening_bid):
    interest = min(Decimal(str(bid)) * MAX_REDEMPTION_RATE, Decimal(str(opening_bid)))
    return float(interest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


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
    county_list = getattr(uploaded_file, "county_list", False)
    if county_list:
        valid_bid |= clean["Bid Amount"].isna()
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
    calculated = clean["Bid Amount"].map(full_rate_bid, na_action="ignore")
    if MAX_RETURN_BID_COLUMN in clean:
        clean[MAX_RETURN_BID_COLUMN] = clean[MAX_RETURN_BID_COLUMN].fillna(calculated)
    else:
        clean[MAX_RETURN_BID_COLUMN] = calculated
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
        bid = numeric_value(sale["Bid Amount"])
        category, color = bid_style(bid) if bid is not None else ("Bid unpublished", "#64748b")
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


def format_arcgis_date(value: Any) -> str:
    number = numeric_value(value)
    if number is None:
        return "—"
    try:
        return datetime.fromtimestamp(number / 1000, tz=timezone.utc).strftime("%m/%d/%Y")
    except (ValueError, OSError, OverflowError):
        return "—"


def load_lien_reviews() -> dict[str, dict[str, Any]]:
    if not LIEN_REVIEW_FILE.exists():
        return {}
    raw = json.loads(LIEN_REVIEW_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid lien review file")
    return raw


@st.cache_resource
def review_write_lock():
    return threading.Lock()


def save_lien_review(parcel, review):
    with review_write_lock():
        records = load_lien_reviews()
        records[parcel] = {**records.get(parcel, {}), **review}
        write_lien_reviews(records)


def write_lien_reviews(records):
    temp = LIEN_REVIEW_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(records, indent=2), encoding="utf-8")
    temp.replace(LIEN_REVIEW_FILE)


def default_lien_review(tax_map: str) -> dict[str, Any]:
    return {
        "tax_map": tax_map,
        "stage": "Not Reviewed",
        "risk": "Not Assessed",
        "checks": {key: "Not Checked" for key, _ in LIEN_CHECK_FIELDS},
        "notes": "",
        "updated_at": "",
    }


def get_lien_review(
    reviews: dict[str, dict[str, Any]],
    tax_map: str,
) -> dict[str, Any]:
    base = default_lien_review(tax_map)
    saved = reviews.get(tax_map, {})
    if not isinstance(saved, dict):
        return base
    base.update({k: v for k, v in saved.items() if k != "checks"})
    saved_checks = saved.get("checks", {})
    if isinstance(saved_checks, dict):
        base["checks"].update(saved_checks)
    return base


def lien_review_badge(review: dict[str, Any]) -> tuple[str, str]:
    risk = str(review.get("risk") or "Not Assessed")
    if risk == "No Obvious Issue Identified":
        return risk, "#167a5b"
    if risk in {"Potential Lien / Judgment", "High Risk"}:
        return risk, "#a94c44"
    if risk == "Review Required":
        return risk, "#b98532"
    return str(review.get("stage") or "Not Reviewed"), "#6f8190"


def find_feature_by_tax_map(
    geojson: dict[str, Any],
    tax_map: str,
) -> dict[str, Any] | None:
    normalized = normalize_tax_map(tax_map)
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        if normalize_tax_map(props.get("TaxMapNumber", "")) == normalized:
            return feature
    return None


def popup_html(props: dict[str, Any], review=None) -> str:
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

    active_review = review or default_lien_review(str(props.get("TaxMapNumber", "")))
    review_label, review_color = lien_review_badge(active_review)
    lien_review_html = (
        section_header("LIEN / TITLE REVIEW")
        + (
            "<div style='display:flex;justify-content:space-between;align-items:center;"
            "gap:10px;padding:3px 0 7px'>"
            "<span style='color:#555'>Status</span>"
            f"<span style='background:{review_color};color:white;border-radius:999px;"
            "padding:4px 8px;font-weight:700;font-size:11px'>"
            f"{html.escape(review_label)}</span></div>"
        )
        + (
            f"<button type='button' class='open-title-review' data-parcel='{esc(props.get('TaxMapNumber'))}' "
            "style='display:block;text-align:center;text-decoration:none;"
            "background:#167a5b;color:white;font-weight:700;border-radius:8px;"
            "padding:8px 10px;margin-top:4px'>Open Lien Review</button>"
        )
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
        "Investor UI v6.3-dev"
        "</div>"
        + tax_sale_html
        + section_header("TAX HISTORY")
        + row("Yearly status", props.get("Tax history", "No history entered"))
        + (row("Distress indicator", props["Distress indicator"]) if "Distress indicator" in props else "")
        + f"<button type='button' class='add-bid-property' data-parcel='{esc(props.get('TaxMapNumber'))}'>Add to bid list</button>"

        + lien_review_html
        + (
            "<button type='button' class='lien-review' style='padding:8px 14px;cursor:pointer' "
            f"data-parcel='{esc(props.get('TaxMapNumber'))}' "
            f"data-owner='{esc(props.get('SaleOwnerName'))}' "
            f"data-county-owner='{esc(props.get('OwnerName'))}' "
            f"data-address='{esc(props.get('SalePropertyAddress'))}'>Browser-local review</button>"
        )
        + property_summary
        + county_values_html
        + section_header("MARKET VALUE · CLOSED SALES")
        + row("Market estimate", value_or_dash(props.get("SoldCompEstimate"), format_currency), strong=True)
        + row("Comparable sales", props.get("SoldCompCount", "—"))
        + "<small>See Value &amp; Comps for sale prices and dates.</small>"
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
        bid = numeric_value(props.get("BidAmount"))
        if bid is not None and not (min_bid <= bid <= max_bid):
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


class LienReview(MacroElement):
    """One research form shared by both popup types and all parcel geometries."""

    _template = Template("""
    {% macro script(this, kwargs) %}
    {{ this._parent.get_name() }}.on("popupopen", function(event) {
        const add = event.popup.getElement().querySelector(".add-bid-property");
        if (add) add.onclick = () => window.parent.postMessage({
            isStreamlitMessage: true, type: "streamlit:setComponentValue",
            dataType: "json", value: {bidParcel: add.dataset.parcel}
        }, "*");
        const open = event.popup.getElement().querySelector(".open-title-review");
        if (open) open.onclick = () => window.parent.postMessage({
            isStreamlitMessage: true, type: "streamlit:setComponentValue",
            dataType: "json", value: {reviewParcel: open.dataset.parcel}
        }, "*");
        const button = event.popup.getElement().querySelector("button.lien-review");
        if (!button) return;
        button.onclick = function() {
            const parcel = button.dataset.parcel;
            const key = "spartanburg:lien-review:v1:" + parcel;
            const dialog = document.createElement("dialog");
            dialog.style.cssText = "width:min(440px,88vw);max-height:84vh;overflow:auto;padding:18px;border:1px solid #ccd5da;border-radius:8px;color:#182633";
            dialog.setAttribute("aria-label", "Parcel lien review");
            dialog.innerHTML = `
              <form>
                <h2>Lien Review</h2><p class="identity" style="white-space:pre-line"></p>
                <p>Search by owner name and compare the legal description and releases with this parcel.</p>
                <fieldset><legend>Records checked</legend>
                  <label><input type="checkbox" name="deeds"> Mortgages, liens and releases</label>
                  <a href="https://search.spartanburgdeeds.com/" target="_blank" rel="noopener noreferrer">Deed records</a><br>
                  <label><input type="checkbox" name="court"> Judgments</label>
                  <a href="https://publicindex.sccourts.org/spartanburg/publicindex/" target="_blank" rel="noopener noreferrer">County court index guidance</a><br>
                  <label><input type="checkbox" name="tax"> State tax liens</label>
                  <a href="https://dor.sc.gov/LienRegistry" target="_blank" rel="noopener noreferrer">State registry</a>
                </fieldset>
                <p><label>Previous owner <input name="previous" type="text"></label></p>
                <p><label>Deed book / page <input name="deedRef" type="text"></label></p>
                <label>Your risk assessment <select name="risk"><option>Unreviewed</option><option>Low</option><option>Review</option><option>High Risk</option></select></label>
                <p><label>Findings and document references<textarea name="notes" rows="3" style="width:100%"></textarea></label></p>
                <p>Manual research only. Save keeps this review in this browser.</p>
                <button type="submit">Save review</button> <button type="button" class="close">Close</button>
                <output aria-live="polite"></output>
              </form>`;
            document.body.append(dialog);
            dialog.querySelector(".identity").textContent = [
                "Tax map: " + parcel, "Sale owner: " + button.dataset.owner,
                "County owner: " + button.dataset.countyOwner, "Address: " + button.dataset.address
            ].join(String.fromCharCode(10));
            const form = dialog.querySelector("form");
            const fields = Array.from(form.elements).filter(field => field.name);
            const status = form.querySelector("output");
            try {
                const saved = JSON.parse(localStorage.getItem(key)) || {};
                for (const field of fields) {
                    if (field.type === "checkbox") field.checked = saved[field.name] === true;
                    else if (typeof saved[field.name] === "string") field.value = saved[field.name];
                }
            } catch { status.textContent = "Browser could not load the saved review."; }
            form.oninput = () => { status.textContent = "Unsaved changes"; };
            form.onsubmit = function(e) {
                e.preventDefault();
                const record = {};
                for (const field of fields)
                    record[field.name] = field.type === "checkbox" ? field.checked : field.value;
                try {
                    localStorage.setItem(key, JSON.stringify(record));
                    status.textContent = "Saved in this browser.";
                    button.textContent = "Browser-local review · " + record.risk;
                } catch { status.textContent = "Save failed. Copy your notes before closing."; }
            };
            form.querySelector(".close").onclick = () => dialog.close();
            dialog.onclose = () => { dialog.remove(); button.focus(); };
            dialog.showModal();
        };
        try {
            const record = JSON.parse(localStorage.getItem("spartanburg:lien-review:v1:" + button.dataset.parcel));
            button.textContent = record && record.risk ? "Browser-local review · " + record.risk : "Browser-local review";
        } catch { button.textContent = "Browser-local review"; }
    });
    {% endmacro %}
    """)


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


def build_map(geojson: dict[str, Any], reviews=None) -> folium.Map:
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
                                            "details": popup_html(props, (reviews or {}).get(str(props.get("TaxMapNumber", ""))))}})
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
                popup=folium.Popup(popup_html(props, (reviews or {}).get(str(props.get("TaxMapNumber", "")))), max_width=460),
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
    map_object.add_child(LienReview())
    folium.LayerControl(collapsed=False).add_to(map_object)
    return map_object


def owner_fields(owner):
    name = " ".join(owner.replace(",", " ").split())
    words = name.split()
    if len(words) < 2 or set(words) & {"LLC", "INC", "CORP", "COMPANY", "TRUST", "ENTERPRISES", "LP"}:
        return name, ""
    return words[0], words[1]


def search_documents(last, first):
    with requests.Session() as session:
        def post(page, fields):
            response = session.post(urljoin(ROD_SEARCH_URL, page), data=fields, timeout=(5, 18))
            response.raise_for_status()
            try:
                return recorder_html.fromstring(response.content)
            except etree.ParserError as exc:
                raise ValueError("The county returned an unreadable recording page.") from exc

        portal = post("index.php", {"Accept": "Accept"})
        if not portal.xpath('//form[@id="name_form"]'):
            raise ValueError("The county name-search form is unavailable.")
        fields = {"searchType": "name", "search_type": "Standard", "sort_type": "Date",
                  "party_type": "Both", "entity_type": "Both", "last_name": last,
                  "first_name": first, "show_pick_list": "on", "start_date": "", "end_date": "",
                  "instType[LIENS][LIEN]": "LIEN", "instType[MORTGAGES][MORTGAGE]": "MORTGAGE"}
        pick = post("content.php", fields)
        forms = pick.xpath('//form[@id="pickListForm"][.//table[@id="plresults"]]')
        if len(forms) != 1:
            raise ValueError("The county did not return a recognizable name index.")
        form = forms[0]
        names = form.xpath('.//input[@name="name[]"]/@value')
        if not names:
            return []
        if len(names) > 30:
            raise ValueError("Too many name variants. Narrow the owner name and search again.")
        fields = [(el.name, el.value or "") for el in form.xpath('.//input[@type="hidden"][@name]')]
        fields.extend(("name[]", name) for name in names)
        results = post("content.php", fields)
        tables = results.xpath('//table[@id="results"]')
        if len(tables) != 1:
            raise ValueError("The county did not return the recording index.")
        table = tables[0]
        headings = [el.text_content().strip() for el in table.xpath("./thead/tr/th")]
        expected = ["Date", "Book Info / FileNum", "Doc Type", "Legal Desc", "Search Party Type",
                    "Searched Party", "Reverse Party", "XRef"]
        if headings[:8] != expected:
            raise ValueError("The county recording columns have changed.")
        documents = []
        for row in table.xpath("./tbody/tr"):
            cells = row.xpath("./td")
            if len(cells) < 8 or not row.get("id"):
                raise ValueError("The county returned an incomplete recording row.")
            values = [" ".join(cell.text_content().split()) for cell in cells[:8]]
            dates = cells[0].xpath(".//a/text()")
            documents.append({"Instrument": row.get("id"), "Document": values[2],
                              "Recorded": " ".join(dates).strip() or values[0],
                              "Book / page": values[1], "Indexed party": values[5],
                              "Other party": values[6], "Legal description": values[3],
                              "Cross-reference": values[7]})
        return documents


@st.cache_data(ttl=3600, max_entries=256, show_spinner=False)
def recorder_matches(last, first):
    return search_documents(last, first)


def notify_findings(parcel, source, identifiers):
    seen = st.session_state.setdefault("notified_title_records", set())
    keys = {(parcel, source, identifier) for identifier in identifiers}
    new = keys - seen
    if new:
        st.toast(f"{parcel} · {len(new)} new {source} finding(s) for review", icon="🔔")
        seen.update(new)


def judgment_numbers(text):
    lines = text.strip().splitlines()
    if not lines:
        return []
    numbers = lines
    if "\t" in lines[0]:
        headers = [field.strip().lower() for field in lines[0].split("\t")]
        column = next((idx for idx, field in enumerate(headers)
                       if field in {"judgment #", "judgment number", "judgment#"}), None)
        if column is None or "name" not in headers:
            raise ValueError("Include the Public Index table header with Name and Judgment #.")
        numbers = []
        for line in lines[1:]:
            cells = line.split("\t")
            if len(cells) <= column:
                raise ValueError("Incomplete result row. Copy the full table or enter judgment numbers.")
            if cells[column].strip():
                numbers.append(cells[column])
    refs = list(dict.fromkeys(value.strip().upper() for value in numbers if value.strip()))
    if any(not re.fullmatch(r"(?=[A-Z0-9 /-]*[0-9])[A-Z0-9][A-Z0-9 /-]{0,63}", ref) for ref in refs):
        raise ValueError("Enter one judgment number per line or copy the results with their headers.")
    return refs


def court_lookup(parcel, owner, key):
    with st.expander("Judgments · Spartanburg Public Index"):
        st.code(owner or "Owner unavailable")
        st.link_button("Search Spartanburg Public Index", SC_COURTS_URL, key=key + "_court")
        st.caption("Search each owner under Civil Cases → Judgments → Judgment Against. Verify the party and check the Judgments tab for satisfaction.")
        with st.form(key + "_judgment"):
            reference = st.text_area("Paste Judgment Against results for this owner, including the table header, or enter one judgment number per line")
            saved = st.form_submit_button("Flag results for this owner")
        if saved:
            try:
                numbers = judgment_numbers(reference)
            except ValueError as exc:
                st.error(str(exc))
                numbers = []
            if not numbers:
                st.info("No judgment numbers imported.")
            else:
                try:
                    with review_write_lock():
                        reviews = load_lien_reviews()
                        review = get_lien_review(reviews, parcel)
                        refs = review.setdefault("court_references", [])
                        if any(number not in refs for number in numbers):
                            refs.extend(number for number in numbers if number not in refs)
                            review["checks"]["judgment"] = "Possible Match"
                            review["updated_at"] = datetime.now(timezone.utc).isoformat()
                            reviews[parcel] = review
                            write_lien_reviews(reviews)
                    st.session_state.pop(f"lien_check_{parcel}_judgment", None)
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(f"Could not save judgment: {exc}")
        try:
            review = get_lien_review(load_lien_reviews(), parcel)
        except (ValueError, OSError):
            st.warning("Saved judgment checks are unavailable.")
            return
        if review["checks"]["judgment"] in ("Possible Match", "Record Found"):
            refs = review.get("court_references") or ["See parcel review"]
            notify_findings(parcel, "judgment", refs)
            st.warning("Saved judgment finding · " + ", ".join(refs))


bid_watch = st.components.v2.component(
    "bid_watch", html="<span></span>",
    js="""export default function({parentElement, data, setStateValue}) {
      const root = parentElement.querySelector("span");
      function sync() {
        try {
          const ids = [];
          for (const key of Object.keys(localStorage)) {
            if (!key.startsWith("spartanburg:bid-list:v1:")) continue;
            const [sale, id] = JSON.parse(key.slice("spartanburg:bid-list:v1:".length));
            if (sale === data.sale) ids.push(id);
          }
          const value = JSON.stringify(ids.sort());
          if (root.dataset.sent !== value) {root.dataset.sent = value; setStateValue("ids", ids);}
        } catch {root.textContent = "Browser bid storage unavailable for title checks.";}
      }
      sync(); window.addEventListener("storage", sync);
      return () => window.removeEventListener("storage", sync);
    }"""
)


@st.fragment(run_every="1m")
def bid_record_alerts(sale, owners):
    watch = bid_watch(data={"sale": sale}, key="bid_watch", on_ids_change=lambda: None)
    parcels = [p for p in (watch.ids or []) if p in owners]
    if not parcels:
        return
    st.markdown("#### Bid list title alerts")
    st.caption("Checks one due parcel per minute while the app is open. Successful owner searches refresh hourly. Verify the indexed party, legal description and releases.")
    scans = st.session_state.setdefault("bid_record_scans", {})
    now = monotonic()
    due = [(scans.get((p, owners[p]), {}).get("next", 0), p) for p in parcels if owners[p]]
    if due and min(due)[0] <= now:
        _, parcel = min(due)
        owner = owners[parcel]
        state = scans.setdefault((parcel, owner), {})
        try:
            docs = recorder_matches(*owner_fields(owner))
            state.update(docs=docs, error="", next=now + 3600)
            notify_findings(parcel, "recorder", [d["Instrument"] for d in docs])
        except (ValueError, requests.RequestException) as exc:
            state.update(error=str(exc), next=now + 900)
    try:
        reviews = load_lien_reviews()
    except (OSError, ValueError):
        reviews = {}
        st.warning("Saved court checks are unavailable.")
    rows = []
    for parcel in parcels:
        state = scans.get((parcel, owners[parcel]), {})
        docs = state.get("docs")
        status = ("Owner missing" if not owners[parcel] else "Queued") if docs is None else (
            f"{len(docs)} possible matches" if docs else "No indexed match")
        if state.get("error"):
            status = "Check unavailable" + (f" · last result: {status}" if docs is not None else "")
        review = get_lien_review(reviews, parcel)
        judgment = review["checks"]["judgment"]
        refs = review.get("court_references") or []
        if judgment in ("Possible Match", "Record Found"):
            notify_findings(parcel, "judgment", refs or ["See parcel review"])
        state_lien = review["checks"]["state_tax_lien"]
        if state_lien in ("Possible Match", "Record Found"):
            notify_findings(parcel, "state tax lien", [state_lien])
        rows.append({"Parcel": parcel, "Owner": owners[parcel], "Recorded liens / mortgages": status,
                     "State tax lien review": state_lien, "Court judgment review": judgment, "Judgment references": ", ".join(refs)})
    st.dataframe(rows, hide_index=True, width="stretch")
    parcel = st.selectbox("Inspect a bid-list title check", parcels, index=None)
    if parcel:
        render_recorder_search(parcel, owners[parcel], "bid")


def render_recorder_search(parcel, owner, location):
    key = f"recorder_{location}_{parcel}"
    st.markdown("#### Recorded liens and mortgages")
    court_lookup(parcel, owner, key)
    last, first = owner_fields(owner)
    with st.form(key):
        left, right = st.columns(2)
        last = left.text_input("Last or company name", last).strip().upper()
        first = right.text_input("First name", first).strip().upper()
        submitted = st.form_submit_button("Search recorded liens and mortgages")
    if not last:
        st.info("Enter an owner name to search the county index.")
        return
    st.caption(f"County name-index search for {last} {first}. Compare the legal description and check for releases before relying on a match.")
    try:
        if submitted:
            recorder_matches.clear(last, first)
        with st.spinner("Searching Spartanburg County recorded documents…"):
            records = recorder_matches(last, first)
    except (requests.RequestException, ValueError) as exc:
        st.warning(f"County search incomplete. {exc}")
        st.link_button("Open the county recorder", ROD_SEARCH_URL, key=key + "_source")
        return
    if records:
        notify_findings(parcel, "recorder", [r["Instrument"] for r in records])
        st.warning(f"{len(records)} possible recorded lien or mortgage matches for this owner search.")
        st.dataframe(records, hide_index=True, width="stretch")
        st.caption(f"{len(records)} possible recording matches. These entries do not establish an outstanding balance or clear title.")
    else:
        st.info("The county index returned no lien or mortgage entries for this name search.")
    st.link_button("Verify recording with the county", ROD_SEARCH_URL, key=key + "_source")


def render_lien_review_workspace(
    tax_map: str,
    merged_geojson: dict[str, Any],
    reviews: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    feature = find_feature_by_tax_map(merged_geojson, tax_map)
    if feature is None:
        st.error(f"Parcel {tax_map} was not found in the currently loaded sale list.")
        if st.button("Close Lien Review"):
            st.session_state.pop("review_selection", None)
            st.query_params.pop("lien_review", None)
            st.rerun()
        return reviews

    props = feature.get("properties") or {}
    tax_map = str(props.get("TaxMapNumber", tax_map))
    review = get_lien_review(reviews, tax_map)
    review_label, review_color = lien_review_badge(review)

    st.markdown(
        f"""
        <div style="background:#ffffff;border:1px solid #dce3e8;border-left:5px solid {review_color};
                    border-radius:14px;padding:16px 18px;margin:12px 0 16px;
                    box-shadow:0 6px 20px rgba(18,32,45,.06)">
          <div style="font-size:.73rem;font-weight:800;letter-spacing:.09em;
                      text-transform:uppercase;color:#687582">Preliminary Title Screening</div>
          <div style="font-size:1.35rem;font-weight:850;color:#12202d;margin-top:3px">
            Lien Review · {html.escape(tax_map)}
          </div>
          <div style="font-size:.9rem;color:#687582;margin-top:4px">
            {html.escape(str(props.get("SalePropertyAddress") or props.get("PropertyLocation") or "Address unavailable"))}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top1, top2, top3, top4 = st.columns([1.25, 1.25, 1, 0.8])
    top1.metric("Current Bid", format_currency(props.get("BidAmount")))
    top2.metric("Max Return Bid", format_currency(props.get("MaxReturnBid")))
    top3.metric("Review Status", review.get("stage", "Not Reviewed"))
    with top4:
        st.write("")
        st.write("")
        if st.button("Close Review", use_container_width=True):
            st.session_state.pop("review_selection", None)
            st.query_params.pop("lien_review", None)
            st.rerun()

    opening_bid = props.get("BidAmount")
    if opening_bid is None:
        st.caption("The county has not published an opening bid for this parcel.")
    else:
        with st.expander("Bid return calculator"):
            st.write(f"Opening tax bid and interest cap: {format_currency(opening_bid)}")
            st.write(f"Highest bid earning the full 12%: {format_currency(full_rate_bid(opening_bid))}")
            proposed = st.number_input("Your proposed bid ($)", min_value=0.0, step=0.01,
                                       value=full_rate_bid(opening_bid), key=f"proposed_bid_{tax_map}")
            st.metric("Maximum redemption interest", format_currency(capped_bid_return(proposed, opening_bid)))
            st.caption("Assumes redemption in months 10–12. Earlier redemption uses a lower rate.")


    render_recorder_search(tax_map, str(props.get("SaleOwnerName") or props.get("OwnerName") or ""), "map")
    st.markdown("#### Automatic parcel/title identifiers")
    id1, id2, id3 = st.columns(3)
    with id1:
        st.markdown("**Current owner**")
        st.code(str(props.get("OwnerName") or props.get("SaleOwnerName") or "—"))
        st.markdown("**Previous owner**")
        st.code(str(props.get("PreviousOwnerName") or "—"))
    with id2:
        st.markdown("**Deed book / page**")
        deed_book = str(props.get("DeedBook") or "—")
        deed_page = str(props.get("DeedPage") or "—")
        st.code(f"{deed_book} / {deed_page}")
        st.markdown("**Instrument number**")
        st.code(str(props.get("InstrumentNumber") or "—"))
    with id3:
        st.markdown("**County sale date**")
        st.code(format_arcgis_date(props.get("SaleDate")))
        st.markdown("**Tax map number**")
        st.code(tax_map)

    legal_description = str(props.get("LegalDescription") or "").strip()
    if legal_description:
        with st.expander("Legal description"):
            st.write(legal_description)

    st.caption("Saved workspace reviews are shared on this app instance. Hosting restarts or redeploys can erase local files.")
    st.markdown("#### Official research sources")
    st.caption(
        "Use the state registry and court index separately for state tax liens and judgments."
    )
    src1, src2, src3 = st.columns(3)
    with src1:
        st.link_button(
            "Register of Deeds",
            ROD_SEARCH_URL,
            use_container_width=True,
            help="Search mortgages, releases, federal tax liens, mechanic's liens, and other recorded documents.",
        )
        st.caption("Search current and previous owner names; verify deed book/page and instrument references.")
    with src2:
        st.link_button(
            "SC State Tax Lien Registry",
            SCDOR_LIEN_URL,
            use_container_width=True,
        )
        st.caption("Search the owner or business name for South Carolina state tax liens.")
    with src3:
        st.link_button(
            "SC Courts Public Index",
            SC_COURTS_URL,
            use_container_width=True,
        )
        st.caption("Search Spartanburg County judgments, foreclosures, lis pendens, owner name, or tax map.")

    st.info(
        "This workspace is a preliminary screening tool. A saved green status means only that "
        "no obvious issue was identified in the sources reviewed; it is not a certification of clear title."
    )

    stage_index = (
        LIEN_REVIEW_STAGES.index(review.get("stage"))
        if review.get("stage") in LIEN_REVIEW_STAGES
        else 0
    )
    risk_index = (
        LIEN_RISK_LEVELS.index(review.get("risk"))
        if review.get("risk") in LIEN_RISK_LEVELS
        else 0
    )

    with st.form(f"lien_review_form_{tax_map}", clear_on_submit=False):
        st.markdown("#### Review findings")
        status_col, risk_col = st.columns(2)
        with status_col:
            stage = st.selectbox(
                "Review stage",
                LIEN_REVIEW_STAGES,
                index=stage_index,
            )
        with risk_col:
            risk = st.selectbox(
                "Overall risk",
                LIEN_RISK_LEVELS,
                index=risk_index,
            )

        check_values: dict[str, str] = {}
        left_col, right_col = st.columns(2)
        for idx, (key, label) in enumerate(LIEN_CHECK_FIELDS):
            saved_value = review.get("checks", {}).get(key, "Not Checked")
            result_index = (
                LIEN_CHECK_RESULTS.index(saved_value)
                if saved_value in LIEN_CHECK_RESULTS
                else 0
            )
            target_col = left_col if idx % 2 == 0 else right_col
            with target_col:
                check_values[key] = st.selectbox(
                    label,
                    LIEN_CHECK_RESULTS,
                    index=result_index,
                    key=f"lien_check_{tax_map}_{key}",
                )

        notes = st.text_area(
            "Review notes",
            value=str(review.get("notes") or ""),
            height=130,
            placeholder=(
                "Record instrument numbers, creditor names, amounts, release references, "
                "possible name matches, attorney/title-search notes, etc."
            ),
        )

        save_clicked = st.form_submit_button(
            "Save Lien Review",
            type="primary",
            use_container_width=True,
        )

    if save_clicked:
        reviews[tax_map] = {
            "tax_map": tax_map,
            "stage": stage,
            "risk": risk,
            "checks": check_values,
            "notes": notes.strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            save_lien_review(tax_map, reviews[tax_map])
        except (OSError, ValueError) as exc:
            st.error(f"Could not save this review: {exc}")
            return reviews
        st.success("Lien review saved.")
        st.rerun()

    updated_at = str(review.get("updated_at") or "")
    if updated_at:
        try:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            st.caption(f"Last saved: {dt.astimezone().strftime('%m/%d/%Y %I:%M %p')}")
        except ValueError:
            pass

    return reviews


SOLD_DATA_PAGE = "https://realestatedataset.com/south-carolina/spartanburg-county"
SOLD_DATA_URL = "https://realestatedataset.com/data/latest/county=45083.csv"
SOLD_TYPES = {"single_family", "manufactured", "townhouse", "condo", "multi_family", "land"}


def comp_apn(value):
    # Spartanburg formats the same ten digits with or without punctuation.
    value = re.sub(r"[-.\s]", "", str(value))
    return value if re.fullmatch(r"[0-9]{10}", value) else ""


def sold_catalog(as_of):
    columns = ["parcel_apn", "county_fips", "street", "unit", "city", "lat", "lng",
               "property_type", "sqft", "lot_sqft", "beds", "year_built", "last_sold_price", "last_sold_date"]
    with requests.get(SOLD_DATA_URL, stream=True, timeout=(5, 35)) as response:
        response.raise_for_status()
        response.raw.decode_content = True
        frame = pd.read_csv(response.raw, usecols=columns, dtype={"parcel_apn": "string", "county_fips": "string", "unit": "string"})
    frame = frame.loc[frame.county_fips.eq("45083")].copy()
    if frame.empty:
        raise ValueError("The sales feed returned no Spartanburg County records.")
    frame["parcel_apn"] = frame.parcel_apn.map(comp_apn)
    frame = frame.loc[frame.parcel_apn.ne("") & ~frame.parcel_apn.duplicated(keep=False)
                      & frame.property_type.isin(SOLD_TYPES)].copy()
    for field in ("lat", "lng", "sqft", "lot_sqft", "beds", "year_built", "last_sold_price"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame["size"] = frame.sqft.where(frame.property_type.ne("land"), frame.lot_sqft)
    frame = frame.loc[frame["size"].gt(0) & frame.lat.between(34, 36) & frame.lng.between(-83, -81)]
    frame["last_sold_date"] = pd.to_datetime(frame.last_sold_date, errors="coerce")
    latest = frame.last_sold_date.where(frame.last_sold_date.le(pd.Timestamp(as_of))).max()
    if frame.empty or pd.isna(latest):
        raise ValueError("The sales feed contains no usable dated parcel records.")
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=365)
    sales = frame.loc[frame.last_sold_date.between(cutoff, pd.Timestamp(as_of)) & frame.last_sold_price.ge(1000)
                      & (frame.property_type.eq("land") | frame.year_built.isna()
                         | frame.year_built.le(frame.last_sold_date.dt.year))]
    cells = {}
    for record in sales.itertuples(index=False):
        cell = (record.property_type, math.floor(record.lat * 20), math.floor(record.lng * 20))
        cells.setdefault(cell, []).append(record)
    return frame.set_index("parcel_apn"), cells, latest


def sold_comparison(parcel, catalog):
    subjects, cells, _ = catalog
    apn = comp_apn(parcel)
    if apn not in subjects.index:
        return None, [], "No unique parcel match with usable type, size and coordinates."
    subject = subjects.loc[apn]
    kind, size = subject.property_type, subject["size"]
    x, y = math.floor(subject.lat * 20), math.floor(subject.lng * 20)
    nearby = []
    for i in range(x - 1, x + 2):
        for j in range(y - 1, y + 2):
            for comp in cells.get((kind, i, j), ()):
                if comp.parcel_apn == apn or abs(comp.size / size - 1) > .25:
                    continue
                if pd.notna(subject.beds) and pd.notna(comp.beds) and abs(subject.beds - comp.beds) > 1:
                    continue
                miles = math.hypot((comp.lat - subject.lat) * 69.09,
                                   (comp.lng - subject.lng) * 69.09 * math.cos(math.radians(subject.lat)))
                if miles > 2:
                    continue
                nearby.append((miles, -comp.last_sold_date.value, comp.parcel_apn, comp))
    rows = []
    for miles, _, _, c in sorted(nearby)[:5]:
        rows.append({"Parcel": c.parcel_apn, "Address": " ".join(str(v) for v in (c.street, c.unit, c.city) if pd.notna(v)),
                     "Sold date": c.last_sold_date.date().isoformat(), "Sold price": c.last_sold_price,
                     "Size (sq ft)": c.size, "$ / sq ft": c.last_sold_price / c.size, "Miles": round(miles, 2)})
    estimate = round(size * median(row["$ / sq ft"] for row in rows)) if len(rows) >= 3 else None
    basis = "lot area" if kind == "land" else "floor area"
    return estimate, rows, f"{kind.replace('_', ' ')} · {size:,.0f} sq ft {basis}"


class SoldValuations:
    def __init__(self):
        self.lock = threading.Lock()
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.job = None
        self.catalog = None
        self.results = {}
        self.updated = None
        self.refresh_at = 0
        self.retry_at = 0
        self.error = ""

    def calculate(self, catalog, parcels):
        if catalog is None:
            catalog = sold_catalog(datetime.now(ZoneInfo("America/New_York")).date())
        return catalog, {parcel: sold_comparison(parcel, catalog) for parcel in parcels}

    def snapshot(self, parcels, retry=False):
        with self.lock:
            now = monotonic()
            if self.job is not None and self.job.done():
                try:
                    catalog, results = self.job.result()
                    if catalog is not self.catalog:
                        self.results = {}
                        self.updated = datetime.now(ZoneInfo("America/New_York"))
                        self.refresh_at = now + 86400
                    self.catalog = catalog
                    self.results.update(results)
                    self.error = ""
                    self.retry_at = 0
                except Exception as exc:
                    self.error = str(exc) or type(exc).__name__
                    self.retry_at = now + 900
                self.job = None
            refresh = now >= self.refresh_at
            missing = parcels if refresh else parcels.difference(self.results)
            if missing and self.job is None and (retry or now >= self.retry_at):
                self.job = self.worker.submit(self.calculate, None if refresh else self.catalog, missing)
            values = {p: self.results[p] for p in parcels if p in self.results}
            return values, self.catalog[2] if self.catalog is not None else None, self.updated, self.error, self.job is not None


@st.cache_resource
def shared_valuations():
    return SoldValuations()


@st.fragment(run_every="5s")
def valuation_status(parcels, displayed):
    service = shared_valuations()
    values, _, updated, error, busy = service.snapshot(parcels)
    if (len(values), updated) != displayed:
        st.rerun()
    if updated:
        st.caption(f"Closed-sale data last loaded {updated:%b %d, %Y at %I:%M %p %Z}.")
    if busy:
        st.caption("Updating closed-sale estimates in the background…")
    elif error:
        st.warning(f"Closed-sale update unavailable. Retrying in 15 minutes. {error}")
        if st.button("Retry closed-sale update"):
            service.snapshot(parcels, retry=True)
            st.rerun()


def county_comps(props, center, radius, days):
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    lat, lon = center
    fields = "MAPNUMBER,PropertyLocation,BuildingType,SaleDate,SaleAmount,LivingArea,BedRooms,FullBaths,HalfBaths,YearBuilt,Acreage"
    with get_session() as session:
        data = county_query(session, {
            "where": f"SaleDate >= DATE '{cutoff.isoformat()}' AND SaleAmount > 0 AND LivingArea > 0",
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
            "distance": radius, "units": "esriSRUnit_StatuteMile", "spatialRel": "esriSpatialRelIntersects",
            "outFields": fields, "returnGeometry": "false", "f": "json",
        })
    if data.get("exceededTransferLimit") or "features" not in data:
        raise ValueError("County results were incomplete. Try a smaller search.")
    rows = []
    subject_type = str(props.get("BuildingType") or "").strip().lower()
    subject_size = numeric_value(props.get("LivingArea"))
    seen = {normalize_tax_map(props["TaxMapNumber"])}
    for feature in data["features"]:
        p = feature.get("attributes") or {}
        parcel = normalize_tax_map(p.get("MAPNUMBER"))
        size = numeric_value(p.get("LivingArea"))
        if not parcel or parcel in seen or not size:
            continue
        if not subject_type or str(p.get("BuildingType") or "").strip().lower() != subject_type:
            continue
        if subject_size and abs(size / subject_size - 1) > .25:
            continue
        if any(abs(a - b) > 1 for field in ("BedRooms", "FullBaths")
               if (a := numeric_value(props.get(field))) is not None
               and (b := numeric_value(p.get(field))) is not None):
            continue
        seen.add(parcel)
        rows.append({"Parcel": parcel, "Address": p.get("PropertyLocation"), "Price": p["SaleAmount"],
                     "Sq ft": size, "Date": format_arcgis_date(p["SaleDate"]), "Beds": p.get("BedRooms"),
                     "Full baths": p.get("FullBaths"), "Year built": p.get("YearBuilt"), "Acres": p.get("Acreage")})
    return rows


def render_comps(feature, sold_details=None, latest=None):
    props = feature["properties"]
    st.write(props.get("SalePropertyAddress") or props["TaxMapNumber"])
    county_metric, market_metric = st.columns(2)
    county_metric.metric("County appraised value", format_currency(props.get("AppraisedTotal")))
    estimate, evidence, basis = sold_details or (None, [], "Sold-property data unavailable for this parcel.")
    market_metric.metric("Market estimate · closed sales", format_currency(estimate) if estimate is not None else "—")
    st.caption(basis)
    if evidence:
        st.dataframe(evidence, hide_index=True, width="stretch", column_config={
            "Sold price": st.column_config.NumberColumn(format="dollar"),
            "$ / sq ft": st.column_config.NumberColumn(format="$%.2f")})
    if estimate is None:
        st.caption(f"{len(evidence)} qualifying sales. A market estimate requires at least three.")
    st.caption("Uses the nearest five same-type sales within two miles and the past 365 days, with sizes within 25%. Median sold price per square foot × subject size. Land uses lot area. Sale terms and property condition require review.")
    if pd.notna(latest):
        st.caption(f"Latest sale date in the source data: {latest.date()}")
    st.markdown(f"[View Spartanburg sold-property data]({SOLD_DATA_PAGE})")
    st.markdown("#### Additional comp searches")
    if props.get("PropertyClass") != "Residential":
        st.info("Residential comps require a parcel classified as Residential.")
        return
    center = parcel_label_location(feature["geometry"])
    if not center:
        st.info("Parcel coordinates unavailable.")
        return
    source = st.radio("Comp source", ["County recorded sales", "RentCast listings"], horizontal=True)
    county = source == "County recorded sales"
    radius = st.selectbox("Radius (miles)", [0.5, 1.0, 2.0, 5.0], index=1)
    days = st.selectbox("Lookback (days)", [90, 180, 365, 730], index=2)
    count = None
    key = None
    if county:
        st.caption("County transfers within the radius, matched by building type, living area (±25%) and available bed/full-bath counts (±1). Inspect transfers for non-market prices.")
    else:
        count = st.slider("Requested listings", 5, 25, 10)
        st.caption("RentCast prices are listing prices. Lookback measures days since the listing was seen.")
        key = os.environ.get("RENTCAST_API_KEY")
        if not key:
            try:
                key = st.secrets.get("RENTCAST_API_KEY")
            except FileNotFoundError:
                pass
        if not key:
            st.info("Add RENTCAST_API_KEY to Streamlit Secrets to enable RentCast.")
    query = (props["TaxMapNumber"], center, source, radius, days, count, props.get("LivingArea"), props.get("BuildingType"), props.get("BedRooms"), props.get("FullBaths"))
    cache = st.session_state.setdefault("comp_results", {})
    if query not in cache and st.button("Find comps", disabled=not county and not key):
        try:
            avm = {}
            if county:
                rows = county_comps(props, center, radius, days)
            else:
                params = dict(latitude=center[0], longitude=center[1], maxRadius=radius, daysOld=days, compCount=count)
                for field, attr in [("squareFootage", "LivingArea"), ("bedrooms", "BedRooms")]:
                    value = numeric_value(props.get(attr))
                    if value and value > 0:
                        params[field] = value
                response = requests.get("https://api.rentcast.io/v1/avm/value", params=params,
                                        headers={"X-Api-Key": key}, timeout=(5, 25))
                response.raise_for_status()
                avm = response.json()
                if not isinstance(avm, dict) or not isinstance(avm.get("comparables"), list):
                    raise ValueError("Unexpected RentCast response.")
                rows = [{"Address": c.get("formattedAddress"), "Price": c.get("price"),
                         "Sq ft": c.get("squareFootage"), "Last seen": c.get("lastSeenDate"),
                         "Distance (mi)": c.get("distance"), "Type": c.get("propertyType")}
                        for c in avm["comparables"] if isinstance(c, dict)]
            cache[query] = rows, avm
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            st.error(f"Lookup failed: {exc}")
    if query not in cache:
        return
    rows, avm = cache[query]
    if avm:
        st.metric("RentCast estimated value", format_currency(avm.get("price")))
        st.caption(f"Provider range: {format_currency(avm.get('priceRangeLow'))} to {format_currency(avm.get('priceRangeHigh'))}")
    if not rows:
        st.info("No qualifying comps returned for these settings.")
        return
    df = pd.DataFrame(rows)
    df.insert(0, "Include", True)
    edited = st.data_editor(df, hide_index=True, disabled=list(df.columns[1:]),
                            key=f"comps_{query}", width="stretch")
    selected = edited[edited["Include"]]
    prices = pd.to_numeric(selected["Price"], errors="coerce")
    areas = pd.to_numeric(selected["Sq ft"], errors="coerce")
    unit = (prices / areas)[(prices > 0) & (areas > 0)]
    st.write(f"Median included price: {format_currency(prices[prices > 0].median())}" if any(prices > 0) else "No priced comps selected.")
    size = numeric_value(props.get("LivingArea"))
    if len(unit):
        st.write(f"Median price per sq ft: {format_currency(unit.median())} · {len(unit)} usable comps")
    if len(unit) >= 3 and size and size > 0:
        estimate = unit.median() * size
        st.metric("Comp-based value estimate", format_currency(estimate))
        if props.get("BidAmount") is not None:
            st.write(f"Opening bid / comp-based value: {props['BidAmount'] / estimate:.1%}")
    else:
        st.caption("A value estimate needs subject living area and at least three included comps with price and area.")


def reset_property_filters():
    for key in list(st.session_state):
        if key.startswith(("filter_", "bid_range_")):
            del st.session_state[key]


HISTORY_COLUMNS = ["Tax Map Number", "Tax Year", "Status"]
TAX_STATUSES = ["Outstanding delinquent", "Paid after delinquency", "Paid", "Unknown"]
TAX_FILTERS = ["All histories", "2+ outstanding years", "3+ outstanding years",
               "Repeated delinquency (any years)", "Consecutive delinquent years"]


def summarize_tax_history(rows):
    records = {}
    for parcel, year, status in rows[HISTORY_COLUMNS].itertuples(index=False, name=None):
        if all(pd.isna(value) or not str(value).strip() for value in (parcel, year, status)):
            continue
        parcel = normalize_tax_map(parcel)
        year_text = str(year).strip()
        status = str(status).strip()
        if not parcel or not re.fullmatch(r"(19|20)\d{2}", year_text) or status not in TAX_STATUSES:
            raise ValueError("Each row needs a parcel ID, four-digit tax year and a listed status.")
        year = int(year_text)
        years = records.setdefault(parcel, {})
        if year in years and years[year] != status:
            raise ValueError(f"Conflicting statuses for {parcel} in {year}. Reconcile that year before applying.")
        years[year] = status

    result = {}
    for parcel, years in records.items():
        delinquent = {year for year, status in years.items() if status in TAX_STATUSES[:2]}
        outstanding = sum(status == TAX_STATUSES[0] for status in years.values())
        result[parcel] = {
            "Tax history": " · ".join(f"{year}: {years[year]}" for year in sorted(years, reverse=True)),
            "Outstanding years": outstanding, "Delinquent years": len(delinquent),
            "Consecutive delinquency": any(year - 1 in delinquent for year in delinquent),
            "Distress indicator": ("3+ outstanding · deeper review" if outstanding >= 3 else
                                   "2 outstanding · moderate" if outstanding == 2 else
                                   "1 outstanding" if outstanding else "No confirmed outstanding years"),
        }
    return result


def tax_history_workspace(tax_df):
    st.subheader("Tax delinquency history")
    st.caption("Record one row per parcel and tax year. Use Paid after delinquency only when late payment is documented. Missing years are unknown. Counts reflect the records you enter.")
    st.link_button("Check Spartanburg County tax records", "https://spartanburgcountytax.qpaybill.com/")
    uploaded = st.file_uploader("Import tax history (CSV)", type="csv", key="tax_history_csv")
    scope = "manual" if uploaded is None else uploaded.file_id
    try:
        rows = (pd.read_csv(io.BytesIO(uploaded.getvalue()), dtype=str, keep_default_na=False)
                if uploaded else pd.DataFrame(columns=HISTORY_COLUMNS, dtype=str))
        if not set(HISTORY_COLUMNS).issubset(rows.columns):
            raise ValueError("Required headings: " + ", ".join(HISTORY_COLUMNS))
        edited = st.data_editor(rows[HISTORY_COLUMNS], num_rows="dynamic", hide_index=True,
                                column_config={"Status": st.column_config.SelectboxColumn(options=TAX_STATUSES),
                                               "Tax Year": st.column_config.TextColumn(),
                                               "Tax Map Number": st.column_config.TextColumn()},
                                key=f"tax_history_rows_{scope}", width="stretch")
        st.download_button("Download history CSV", edited.to_csv(index=False), "parcel_tax_history.csv", "text/csv")
        st.caption("Download your edits to keep them between sessions. Import the CSV to resume.")
        history = summarize_tax_history(edited)
    except (ValueError, UnicodeError) as exc:
        st.error(f"Tax history could not be applied. {exc}")
        return {}
    matched = set(history).intersection(tax_df["Tax Map Number"])
    if history:
        st.caption(f"{len(matched)} of {len(history)} history parcels match the loaded sale list.")
        if matched:
            st.dataframe([{"Tax Map Number": parcel, **history[parcel]} for parcel in sorted(matched)],
                         hide_index=True, width="stretch")
    return history


def county_candidate():
    try:
        candidate, error = fetch_listing(), None
    except Exception as exc:
        candidate, error = None, str(exc)
    checked = datetime.now(ZoneInfo("America/New_York")).strftime("%B %d, %Y at %I:%M:%S %p %Z")
    return candidate, error, checked


def market_check(state, manual):
    previous = state.get("county_check")
    if manual or previous is None or monotonic() >= previous["due"]:
        with st.spinner("Checking the county page and reading the latest sale lists…", show_time=True):
            candidate, error, checked = county_candidate()
        interval = 15 * 60 if error is not None else 24 * 60 * 60
        previous = {"candidate": candidate, "error": error, "checked": checked,
                    "due": monotonic() + interval, "mode": "Manual" if manual else "Automatic"}
        state["county_check"] = previous
    return previous


@st.cache_data(show_spinner=False)
def bundled_market():
    path = Path(__file__).with_name("Spartanburg_2026_11_23.csv")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    homes = frame["Sale list"].eq("Mobile homes")
    return {"year": "2026", "name": "2026 county list · verified November 23, 2026",
            "rows": frame.loc[~homes].drop(columns="Sale list").to_dict("records"),
            "mobile": {"rows": frame.loc[homes].to_dict("records")}}




market_card = st.components.v2.component(
    "market_library_card", html="<section></section>",
    css="""section{padding:1rem;border:1px solid #84929c;border-radius:.6rem}
    .update{border-left:5px solid #d28a13}h3{margin-top:0}
    button,summary{cursor:pointer}button{margin-top:1rem;padding:.6rem .85rem}
    .scroll{max-height:21rem;overflow:auto}td,th{text-align:left;padding:.3rem .5rem}""",
    js=Path(__file__).with_name("market_library.js").read_text(encoding="utf-8"),
)


@st.cache_data(max_entries=4, show_spinner="Reading county PDF…")
def read_uploaded_county_pdf(content, kind):
    if len(content) > 24 * 1024 * 1024:
        raise ValueError("Choose a county PDF smaller than 24 MB.")
    rows = read_list(content, upload_kind=kind)
    if kind == "Mobile homes":
        for row in rows:
            row["Sale list"] = kind
    return rows


def county_pdf_fallback(candidate):
    with st.expander("Use a downloaded county PDF", expanded=True):
        st.caption("Open the county sale list page, download the published PDF, and upload it here to preview changes.")
        if candidate is None:
            year = st.number_input("County PDF sale year", min_value=2000, max_value=2100,
                                   value=datetime.now(ZoneInfo("America/New_York")).year)
            land = st.file_uploader("Real estate PDF", type="pdf", key="county_land_pdf")
        else:
            land = None
        homes = st.file_uploader("Mobile-home PDF (optional)", type="pdf", key="county_home_pdf")
        try:
            if candidate is None:
                if land is None:
                    return None
                candidate = {"year": str(year), "rows": read_uploaded_county_pdf(land.getvalue(), "Real estate"),
                             "mobile": {"error": "Upload the mobile-home PDF to include those listings."}}
            if homes is not None:
                rows = read_uploaded_county_pdf(homes.getvalue(), "Mobile homes")
                if {r["Tax Map Number"] for r in rows}.intersection(r["Tax Map Number"] for r in candidate["rows"]):
                    raise ValueError("The two lists contain overlapping sale identifiers.")
                candidate = {**candidate, "mobile": {"rows": rows}}
        except Exception as exc:
            st.warning(f"PDF could not be used. {exc}")
            return None
        if land or homes:
            st.caption("Preview includes the PDF you supplied. Choose Replace current list to apply it.")
        return candidate


@st.fragment(run_every="1m")
def market_workspace(manual_name, tax_df, loaded_label):
    st.subheader("My Markets")
    st.caption("Checks the county on opening a session and every 24 hours after a successful check. Failed checks retry after 15 minutes while the app is open. Your selected list is saved in this browser.")
    st.markdown(f"**Loaded sale list** · {loaded_label} · {len(tax_df):,} listings")
    with st.expander("View loaded listings"):
        rows = tax_df[["Item Number", "Tax Map Number", "Owner Name", "Property Address", "Bid Amount"]]
        rows.attrs = {}
        st.dataframe(rows, hide_index=True, width="stretch", height=300)
    owners = tax_df.set_index("Tax Map Number")["Owner Name"].fillna("").to_dict()
    parcel = st.selectbox("Lien and mortgage search · choose a parcel", list(owners),
                          index=None, key="market_recorder_parcel",
                          format_func=lambda number: f"{number} · {owners[number]}")
    if parcel:
        render_recorder_search(parcel, owners[parcel], "market")
    def request_check():
        st.session_state.county_check_requested = True

    st.button("Check county now", key="check_market_now", on_click=request_check)
    manual_check = st.session_state.get("county_check_requested", False)
    if manual_check:
        progress = st.empty()
        progress.info("Contacting Spartanburg County for the latest lists…")
    result = market_check(st.session_state, manual_check)
    if manual_check:
        st.session_state.county_check_requested = False
        progress.empty()
    candidate, error = result["candidate"], result["error"]
    status = f"{result['mode']} check · {result['checked']}"
    st.caption(f"Last checked: {result['checked']} (Eastern time)")
    if candidate:
        totals = [f"{len(candidate['rows']):,} real estate listings"]
        mobile = candidate.get("mobile", {})
        if "rows" in mobile:
            totals.append(f"{len(mobile['rows']):,} mobile homes")
        st.success(f"{status} · Found " + " and ".join(totals) + ".")
        if mobile.get("error"):
            st.warning(f"Mobile-home check failed. {mobile['error']}")
    st.link_button("County sale list page", SPARTANBURG["page"])
    if error:
        st.error(f"{status} · County check failed. {error}")
    if candidate:
        st.link_button("Real estate list", candidate["url"])
        if candidate.get("mobile", {}).get("url"):
            st.link_button("Mobile-home list", candidate["mobile"]["url"])
    if "HTTP 403" in str(error) or "HTTP 403" in str((candidate or {}).get("mobile", {}).get("error", "")):
        candidate = county_pdf_fallback(candidate)
    manual = None
    if manual_name:
        comparison = tax_df.copy(deep=False)
        comparison.attrs = {}
        manual = {"name": manual_name, "rows": comparison.astype("string").fillna("").to_dict("records")}
    result = market_card(key=f"{SPARTANBURG['key']}_market", data={
        "market": {"key": SPARTANBURG["key"], "name": SPARTANBURG["name"]},
        "manual": manual, "baseline": bundled_market(), "candidate": candidate,
    }, on_selection_change=lambda: None)
    selection = result.selection
    if selection and (selection != st.session_state.get("last_market_selection")):
        st.session_state.last_market_selection = selection
        active = selection.get("active")
        if active != st.session_state.get("active_market_list") or (manual_name and selection.get("replaced")):
            st.session_state.active_market_list = active
            if selection.get("replaced"):
                st.session_state.market_imports = st.session_state.get("market_imports", 0) + 1
            st.rerun()


def main() -> None:
    configure_page()
    render_hero()

    active = st.session_state.get("active_market_list") or bundled_market()
    with st.sidebar:
        st.subheader("Property filters")
        count_slot = st.container(key="filter_count")
        filter_panel = st.container()
        with st.expander("Sale list & county data"):
            manual = st.file_uploader("Upload a sale list", key=f"manual_sale_{st.session_state.get('market_imports', 0)}", help="CSV or Excel. Convert PDFs before upload. Max Return Bid or Max Bid can override the calculated threshold.")
            archive = st.checkbox("View historical 2024 list", key=f"archive_sale_{st.session_state.get('market_imports', 0)}",
                                  disabled=manual is not None)
            uploaded = manual
            if manual is None and not archive:
                uploaded = io.BytesIO(pd.DataFrame(active["rows"]).to_csv(index=False).encode())
                uploaded.name = f"Spartanburg {active['year']} real estate.csv"
                uploaded.county_list = True
                uploaded.display_name = active.get("name") or uploaded.name
                if active.get("includeMobile"):
                    uploaded.display_name += " · Includes mobile homes"
            st.caption(getattr(uploaded, "display_name", uploaded.name) if uploaded else "Historical 2024 sale list")
            refresh = st.button("Refresh county data")
            st.caption("Investor UI development · v6.3")

    try:
        tax_df = load_tax_sale_file(uploaded)
    except Exception as exc:
        st.error(f"The tax-sale file could not be loaded: {exc}")
        st.stop()

    map_tab, bid_tab, history_tab, markets_tab = st.tabs(["Property map", "My bid list", "Tax history", "My Markets"], key="deal_page", on_change="rerun")
    with markets_tab:
        override = manual.name if manual else ("Historical 2024" if archive else None)
        loaded_label = override or active.get("name") or f"Spartanburg {active['year']} county list"
        market_workspace(override, tax_df, loaded_label)
    mobile = tax_df.get("Sale list", pd.Series("", index=tax_df.index)).eq("Mobile homes").fillna(False)
    with bid_tab:
        st.caption("Saved in this browser on this device. Total spent includes winning bids across your saved sale lists.")
        addresses = tax_df["Property Address"].fillna("").where(~mobile, "Mobile home · " + tax_df["Property Address"].fillna(""))
        properties = [{"id": str(parcel), "address": str(address)}
                      for parcel, address in zip(tax_df["Tax Map Number"], addresses)]
        data = {"sale": uploaded.name if uploaded else "Historical 2024", "properties": properties,
                "pending": st.session_state.pop("bid_to_add", None)}
        template = Path(__file__).with_name("bid_list.html").read_text(encoding="utf-8")
        st.iframe(template.replace("__BID_DATA__", json.dumps(data).replace("<", r"\u003c")), height=660,
                  alt="Bid list, notes and total spent")
        bid_record_alerts(data["sale"], dict(zip(tax_df["Tax Map Number"].astype(str), tax_df["Owner Name"].fillna(""))))
    with history_tab:
        history = tax_history_workspace(tax_df)
    with map_tab:
        if mobile.any():
            homes = tax_df.loc[mobile]
            with st.expander(f"Mobile homes · {len(homes):,} listings"):
                st.caption("The county lists each home under its combined map and mobile-home number. Use that number in My bid list. The map below shows real estate.")
                st.dataframe(homes[["Item Number", "Tax Map Number", "Owner Name", "Property Address", "Bid Amount"]],
                             hide_index=True, width="stretch")
        land = tax_df.loc[~mobile]
        if not land.empty or not mobile.any():
            render_property_map(land, uploaded, refresh, filter_panel, count_slot, history)


def render_property_map(tax_df, uploaded, refresh, filter_panel, count_slot, history):
    if uploaded is None:
        st.warning("Historical 2024 sale list — these properties are not presented as a current sale. Upload a current list to evaluate another sale.")
    else:
        st.caption(f"Sale source: {getattr(uploaded, 'display_name', uploaded.name)}. Confirm its sale year and current availability.")
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
    if refresh:
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

    sold_details = {}
    latest_sale = None
    parcels = frozenset(apn for f in merged_geojson["features"]
                       if (apn := comp_apn(f["properties"]["TaxMapNumber"])))
    if parcels:
        values, latest_sale, updated, _, _ = shared_valuations().snapshot(parcels)
        valuation_status(parcels, (len(values), updated))
        for feature in merged_geojson["features"]:
            props = feature["properties"]
            parcel = props["TaxMapNumber"]
            result = values.get(comp_apn(parcel))
            if result is not None:
                sold_details[parcel] = result
                props.update({"SoldCompEstimate": result[0], "SoldCompCount": len(result[1])})
    for feature in merged_geojson["features"]:
        props = feature["properties"]
        props.update(history.get(props["TaxMapNumber"], {}))

    try:
        lien_reviews = load_lien_reviews()
    except (ValueError, OSError) as exc:
        st.warning(f"Saved lien reviews could not be loaded: {exc}")
        lien_reviews = {}
    matched_count = parcel_count(merged_geojson)
    st.caption(f"County data fetched (UTC): {parcel_geojson.get('fetched_at', 'unavailable')}. Cached for up to 24 hours.")
    has_bids = tax_df["Bid Amount"].notna().any()
    bid_min = float(tax_df["Bid Amount"].min()) if has_bids else 0.0
    bid_max = float(tax_df["Bid Amount"].max()) if has_bids else 0.0

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

    with filter_panel:
        search_text = st.text_input("Search properties", placeholder="Address, owner, item or parcel", key="filter_search", type="search")
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
            horizontal=True, key="filter_view",
            index=0,
            help=(
                "Use this for a fast Residential or Commercial view. "
                "Choose All to use the detailed Property Class selections below."
            ),
        )

        with st.expander("Bid filters"):
            selected_categories = []
            for idx, (label, _, _, color) in enumerate(BID_CATEGORIES):
                st.markdown(f"<style>.st-key-bid_range_{idx} label p::before {{content:' ';display:inline-block;width:.65rem;height:.65rem;background:{color};border-radius:2px;margin-right:.45rem}}</style>", unsafe_allow_html=True)
                if st.checkbox(label, value=True, key=f"bid_range_{idx}"):
                    selected_categories.append(label)
            if tax_df["Bid Amount"].isna().any() and st.checkbox("Bid unpublished", value=True):
                selected_categories.append("Bid unpublished")
            if not has_bids:
                selected_bid = (0.0, 0.0)
                st.caption("Opening bids have not been published.")
            elif bid_min == bid_max:
                selected_bid = (bid_min, bid_max)
                st.caption(f"All loaded bids: {format_currency(bid_min)}")
            else:
                selected_bid = st.slider(
                    "Bid amount", key="filter_bid", min_value=bid_min, max_value=bid_max,
                    value=(bid_min, bid_max), format="$%.2f",
                )

        with st.expander("Property details"):
            detailed_property_classes = st.multiselect(
                "Property class", key="filter_classes",
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

            bedroom_choice = st.selectbox(
                "Minimum bedrooms", key="filter_beds",
                options=["Any", 1, 2, 3, 4, 5],
                index=0,
                format_func=lambda value: "5+" if value == 5 else str(value),
            )
            min_bedrooms = None if bedroom_choice == "Any" else int(bedroom_choice)

            bath_choice = st.selectbox(
                "Minimum full baths", key="filter_baths",
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
                        "Acreage", key="filter_acres",
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
                        "Living area", key="filter_area",
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
                        "Year built", key="filter_year",
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

        tax_filter = st.selectbox("Tax delinquency", TAX_FILTERS, key="filter_tax_history")
        st.button("Reset filters", on_click=reset_property_filters)

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
    if tax_filter != TAX_FILTERS[0]:
        tests = {
            TAX_FILTERS[1]: lambda p: p.get("Outstanding years", 0) >= 2,
            TAX_FILTERS[2]: lambda p: p.get("Outstanding years", 0) >= 3,
            TAX_FILTERS[3]: lambda p: p.get("Delinquent years", 0) >= 2,
            TAX_FILTERS[4]: lambda p: p.get("Consecutive delinquency", False),
        }
        filtered_geojson["features"] = [f for f in filtered_geojson["features"] if tests[tax_filter](f["properties"])]
    visible_count = parcel_count(filtered_geojson)
    count_slot.markdown(f"**{visible_count:,}** of {matched_count:,} mapped parcels")

    avg_bid = (
        f"{tax_df['Bid Amount'].mean():,.0f}"
        if has_bids
        else "—"
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
                f"{opportunity_count:,}" if has_bids else "—",
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

    review_ids = sorted({str(f["properties"]["TaxMapNumber"]) for f in merged_geojson["features"]})
    with st.expander("Value & Comps"):
        comp_id = st.selectbox("Choose a parcel for comps", review_ids, index=None)
        if comp_id:
            render_comps(find_feature_by_tax_map(merged_geojson, comp_id), sold_details.get(comp_id), latest_sale)
    selection = st.selectbox("Open lien review by tax map number", review_ids, index=None, key="review_selection")
    selected_review = selection or st.query_params.get("lien_review")
    if selected_review:
        render_lien_review_workspace(selected_review, merged_geojson, lien_reviews)

    render_section_header(
        "Opportunity Map",
        "Scan deals visually, then click any parcel or bid bubble for acquisition and property details.",
    )
    if visible_count:
        map_object = build_map(filtered_geojson, lien_reviews)

        def open_map_review():
            action = st.session_state.get("opportunity_map") or {}
            if action.get("bidParcel") in review_ids:
                st.session_state["bid_to_add"] = action["bidParcel"]
                st.session_state["deal_page"] = "My bid list"
            selected = action.get("reviewParcel")
            if selected in review_ids:
                st.session_state["review_selection"] = selected

        st_folium(map_object, height=720, use_container_width=True, returned_objects=[],
                  key="opportunity_map", on_change=open_map_review)
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
              and opening tax bid come from the sale list. Max Return Bid uses the supplied override or the opening bid divided by 12%, rounded down to cents.
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
                    **{field: props.get(field) for field in ("Tax history", "Outstanding years", "Delinquent years", "Consecutive delinquency", "Distress indicator")},
                    "Lien Review": get_lien_review(lien_reviews, str(props.get("TaxMapNumber", "")))["stage"],
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
                    "Closed-sale estimate": props.get("SoldCompEstimate"),
                    "Comparable sales": props.get("SoldCompCount"),
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
                "Closed-sale estimate": st.column_config.NumberColumn(format="$%.0f"),
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
