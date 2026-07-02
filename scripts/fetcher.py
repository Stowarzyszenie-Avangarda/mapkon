"""Pull exhibitor data + embedded logos from the Google Sheet into the build output.

Reads the sheet (xlsx export), parses each exhibitor row, extracts the logo image
embedded in its cell, and writes `wystawcy_auto.json` (keyed by stall) plus the logo
files. Run standalone (`uv run scripts/fetcher.py`) or via scripts/build.py.

Output layout (relative to the output dir, default `dist/`):
  wystawcy_auto.json      -- [stall] -> {key, name, stall, description, links, logo_path}
  logos/<key>.<png|jpg>   -- downscaled logo; logo_path in the json stays "logos/<key>.ext"
                             (a serve-relative reference, NOT the on-disk build path)

The 57 MB xlsx is cached in a separate dir (default `.cache/`) so it never lands in
the deployable output. The sheet id comes from the SHEET_ID env var -- it is not
hardcoded so this repo can be public.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
import json

import pandas as pd
import requests
import openpyxl
from openpyxl_image_loader import SheetImageLoader

LOGO_REF_PREFIX = "logos"   # the path prefix stored in the json (serve-relative)
LOGO_MAX = 400              # px; the modal shows ~200px wide, keep 2x for sharpness

DEFAULT_OUT_DIR = os.environ.get("BUILD_OUT", "dist")
DEFAULT_CACHE_DIR = os.environ.get("XLSX_CACHE", ".cache")


COLS_TO_FIELDS = {
    'Lp.': 'key',
    'Nazwa': 'name',
    'Numer stanowiska': 'stall',
    'Krótki opis': 'description',
    'SM': 'links',
    'Podgląd logo': 'logo_container'
}

FIELDS_TO_COLS = { k: v for v, k in COLS_TO_FIELDS.items() }

@dataclass(frozen=True)
class Exhibitor:
    key: int
    name: str
    stall: str
    description: str
    links: list
    logo_path: str

def to_dict(instance):
    return {k: v for k, v in instance.__dict__.items()}


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)


def parse_links(text):
    """Pull URLs out of the free-text SM cell into [{href, label}] (deduped).

    Cells hold one or more URLs, space/newline separated, sometimes numbered
    ("1. …") or labelled ("handle: …") and some missing the scheme ("Www.foo.pl").
    """
    if not text or text == "nan":
        return []
    out, seen = [], set()
    for url in URL_RE.findall(text):
        url = url.rstrip(".,;)")
        href = url if re.match(r"https?://", url, re.I) else "https://" + url
        if href.lower() in seen:
            continue
        seen.add(href.lower())
        label = re.sub(r"^https?://(www\.)?", "", href, flags=re.I).split("?")[0].rstrip("/")
        out.append({"href": href, "label": label})
    return out


def download_xlsx(cache_path):
    """Return the cached spreadsheet, downloading it only if the cache is absent.

    The cache is reused by default; set FORCE_FETCH=1 to re-download and refresh it.
    CI has no cache (fresh runner), so deploys always fetch the latest sheet. SHEET_ID
    is read from the environment so it stays out of source; the export is validated as
    a real xlsx (a restricted sheet returns an HTML login page).
    """
    if cache_path.exists() and not os.environ.get("FORCE_FETCH"):
        return cache_path
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise SystemExit(
            "SHEET_ID is not set. Export it (e.g. `export SHEET_ID=…`) or add it as a "
            "GitHub Actions repository variable. It is intentionally not hardcoded."
        )
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    response = requests.get(url)
    response.raise_for_status()
    if not response.content.startswith(b"PK"):  # xlsx is a zip; PK magic bytes
        raise SystemExit(
            "Downloaded data is not an xlsx (is the sheet public and SHEET_ID correct?)."
        )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(response.content)
    return cache_path


def extract_logo(image_loader, logo_col, excel_row, key, logos_dir):
    """Save this row's embedded logo (downscaled) into logos_dir.

    Returns the SERVE-RELATIVE reference "logos/<key>.ext" (never the on-disk path),
    or "" if the cell has no image.
    """
    cell = f"{logo_col}{excel_row}"
    if not image_loader.image_in(cell):
        return ""
    try:
        img = image_loader.get(cell)
    except Exception:
        return ""
    img.thumbnail((LOGO_MAX, LOGO_MAX))
    if img.mode in ("RGBA", "LA", "P"):  # keep transparency
        ext = "png"
        img.convert("RGBA").save(logos_dir / f"{key}.png")
    else:
        ext = "jpg"
        img.convert("RGB").save(logos_dir / f"{key}.jpg", quality=85)
    return f"{LOGO_REF_PREFIX}/{key}.{ext}"


def parse_exhibitors(df, image_loader, logo_col, logos_dir):
    exhibitors: dict[int, Exhibitor] = {}
    for idx, row in df.iterrows():
        excel_row = idx + 2
        key = row[FIELDS_TO_COLS['key']]
        name = str(row[FIELDS_TO_COLS['name']])
        if name == 'nan':
            continue
        stall = str(row[FIELDS_TO_COLS['stall']])
        if stall == 'nan':
            stall = name
        exhibitors[int(key)] = Exhibitor(
            key=key,
            name=name,
            stall=stall,
            description=str(row[FIELDS_TO_COLS['description']]),
            links=parse_links(str(row[FIELDS_TO_COLS['links']])),
            logo_path=extract_logo(image_loader, logo_col, excel_row, int(key), logos_dir),
        )
    return exhibitors


def run(out_dir=None, cache_dir=None):
    """Build wystawcy_auto.json + logos/ into out_dir; cache the xlsx in cache_dir."""
    out_dir = Path(out_dir or DEFAULT_OUT_DIR)
    cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
    logos_dir = out_dir / LOGO_REF_PREFIX
    logos_dir.mkdir(parents=True, exist_ok=True)

    xlsx = download_xlsx(cache_dir / "wystawcy.xlsx")
    df = pd.read_excel(xlsx)
    sheet = openpyxl.load_workbook(xlsx).active
    image_loader = SheetImageLoader(sheet)
    logo_col = {c.value: c.column_letter for c in sheet[1] if c.value}[FIELDS_TO_COLS['logo_container']]

    exhibitors = parse_exhibitors(df, image_loader, logo_col, logos_dir)
    exhibitors_map = {exh.stall: to_dict(exh) for exh in exhibitors.values()}

    out_json = out_dir / "wystawcy_auto.json"
    out_json.write_text(json.dumps(exhibitors_map, ensure_ascii=False, indent=2), encoding="utf8")
    logos = sum(1 for e in exhibitors.values() if e.logo_path)
    print(f"Fetched {len(exhibitors)} exhibitors ({logos} logos) -> {out_json}")
    return out_json


if __name__ == "__main__":
    run()
