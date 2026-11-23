"""Discover Spartanburg's published real-estate list and read every table page."""
from html.parser import HTMLParser
from io import BytesIO
import re
from urllib.parse import urljoin, urlparse

import pdfplumber
import requests

PAGE = "https://www.spartanburgcounty.gov/640/2026-Tax-Sale-Info"
HEADINGS = {
    "item number": "Item Number", "item #": "Item Number",
    "map number": "Tax Map Number", "tax map number": "Tax Map Number",
    "owner name": "Owner Name", "defaulting taxpayer owner name": "Owner Name",
    "description": "Property Address", "description best known property address": "Property Address",
    "new owner name": "New Owner Name", "bid amount": "Bid Amount",
    "opening bid": "Bid Amount", "total tax due bid amount needed": "Bid Amount",
}
REQUIRED = {"Item Number", "Tax Map Number", "Owner Name", "Property Address"}


class ListingPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.label = []
        self.links = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data):
        self.text.append(data)
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            label = " ".join(" ".join(self.label).lower().split())
            if re.fullmatch(r"real estate (?:sales? tax |tax sale )?list", label):
                self.links.append(urljoin(PAGE, self.href))
            self.href = None


def download(url):
    if urlparse(url).scheme != "https" or urlparse(url).hostname != urlparse(PAGE).hostname:
        raise ValueError("County source address has changed.")
    with requests.get(url, timeout=(5, 20), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f"County source returned HTTP {response.status_code}.")
        buf = BytesIO()
        for chunk in response.iter_content(65536):
            buf.write(chunk)
            if buf.tell() > 24 * 1024 * 1024:
                raise ValueError("County document exceeds the supported size.")
        return buf.getvalue()


def read_list(pdf):
    rows = []
    seen = set()
    with pdfplumber.open(BytesIO(pdf)) as doc:
        for number, page in enumerate(doc.pages, 1):
            table = page.extract_table()
            if not table or len(table) < 2:
                raise ValueError(f"Unrecognized table on page {number}.")
            columns = [HEADINGS.get(" ".join((s or "").lower().split())) for s in table[0]]
            if None in columns or len(set(columns)) != len(columns) or not REQUIRED <= set(columns):
                raise ValueError(f"Unrecognized columns on page {number}.")
            for cells in table[1:]:
                row = dict(zip(columns, [" ".join((s or "").split()) for s in cells], strict=True))
                parcel = row["Tax Map Number"]
                if not row["Item Number"].isdigit() or not parcel or parcel in seen:
                    raise ValueError(f"Incomplete or duplicate parcel on page {number}.")
                seen.add(parcel)
                bid = row.setdefault("Bid Amount", "").replace("$", "").replace(",", "").strip()
                if bid and not re.fullmatch(r"\d+(?:\.\d{1,2})?", bid):
                    raise ValueError(f"Unreadable bid on page {number}.")
                row["Bid Amount"] = bid
                rows.append(row)
            page.close()
    if not rows:
        raise ValueError("The county document contains no parcel rows.")
    return sorted(rows, key=lambda row: row["Tax Map Number"])


def fetch_listing():
    page = ListingPage()
    page.feed(download(PAGE).decode("utf-8"))
    year = re.search(r"\b(20\d\d)\s+Delinquent Tax Sale Lists", " ".join(page.text), re.I)
    links = set(page.links)
    if len(links) != 1 or not year:
        raise ValueError("The county has not posted a recognizable real-estate list.")
    url = links.pop()
    return {"year": year[1], "url": url, "rows": read_list(download(url))}
