"""Met Office severe weather warnings, from the public regional RSS feeds (no key; not DataHub).

    https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/<code>

The point's warning region comes from postcodes.io: the English region, the nation for
Wales and Northern Ireland, and the council area for Scotland (REGION_BY_* below). Each
warning lists the local authorities it covers; `district_listed` says whether the point's
district, county or (old) county police area is among them, since a regional warning may
cover only part of the region. Contains public sector information licensed under the
Open Government Licence v3 (Crown copyright, Met Office).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from coverage_detective.sources import live

SOURCE = "met_office_warnings"
FEED = "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/{code}"
TTL_S = 15 * 60
UK_TZ = ZoneInfo("Europe/London")

REGIONS = {
    "os": "Orkney & Shetland", "he": "Highlands & Eilean Siar", "gr": "Grampian", "st": "Strathclyde",
    "ta": "Central, Tayside & Fife", "dg": "Dumfries, Galloway, Lothian & Borders", "ni": "Northern Ireland",
    "wl": "Wales", "nw": "North West England", "ne": "North East England", "yh": "Yorkshire & Humber",
    "wm": "West Midlands", "em": "East Midlands", "ee": "East of England", "sw": "South West England",
    "se": "London & South East England",
}
# postcodes.io `region` (England) -> feed code
REGION_BY_ENGLISH_REGION = {
    "North West": "nw", "North East": "ne", "Yorkshire and The Humber": "yh", "West Midlands": "wm",
    "East Midlands": "em", "East of England": "ee", "South West": "sw", "London": "se", "South East": "se",
}
REGION_BY_COUNTRY = {"Wales": "wl", "Northern Ireland": "ni"}
# postcodes.io `admin_district` (Scottish council area) -> feed code
REGION_BY_SCOTTISH_COUNCIL = {
    "Orkney Islands": "os", "Shetland Islands": "os",
    "Highland": "he", "Na h-Eileanan Siar": "he",
    "Aberdeen City": "gr", "Aberdeenshire": "gr", "Moray": "gr",
    "Angus": "ta", "Dundee City": "ta", "Perth and Kinross": "ta", "Fife": "ta", "Clackmannanshire": "ta",
    "Falkirk": "ta", "Stirling": "ta",
    "Argyll and Bute": "st", "East Ayrshire": "st", "North Ayrshire": "st", "South Ayrshire": "st",
    "East Dunbartonshire": "st", "West Dunbartonshire": "st", "East Renfrewshire": "st", "Renfrewshire": "st",
    "Inverclyde": "st", "Glasgow City": "st", "North Lanarkshire": "st", "South Lanarkshire": "st",
    "Dumfries and Galloway": "dg", "Scottish Borders": "dg", "East Lothian": "dg", "City of Edinburgh": "dg",
    "Midlothian": "dg", "West Lothian": "dg",
}

TITLE_RE = re.compile(r"^(Yellow|Amber|Red) warning of (.+?) affecting (.+)$", re.I)
VALID_RE = re.compile(r"valid from (\d{4}) \w{3} (\d{1,2}) (\w{3}) to (\d{4}) \w{3} (\d{1,2}) (\w{3})", re.I)
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                                      "Nov", "Dec"], start=1)}


def region_for(place: dict | None) -> str | None:
    """Met Office feed code for a postcodes.io result (geocode._from_postcode)."""
    if not place:
        return None
    if place.get("country") == "Scotland":
        return REGION_BY_SCOTTISH_COUNCIL.get(place.get("admin_district") or "")
    if place.get("country") in REGION_BY_COUNTRY:
        return REGION_BY_COUNTRY[place["country"]]
    return REGION_BY_ENGLISH_REGION.get(place.get("region") or "")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]+", " ", name.lower().replace("&", " and ")).strip()


def _when(hhmm: str, day: str, month: str, year: int) -> datetime:
    local = datetime(year, MONTHS[month.title()], int(day), int(hhmm[:2]), int(hhmm[2:]), tzinfo=UK_TZ)
    return local.astimezone(timezone.utc)


def parse_feed(xml: str) -> list[dict]:
    """Every warning in one RSS feed."""
    channel = ET.fromstring(xml).find("channel")
    pub = channel.findtext("pubDate")
    year = parsedate_to_datetime(pub).year if pub else datetime.now(timezone.utc).year
    out = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        m = TITLE_RE.match(title)
        if not m:
            continue
        level, kinds, region = m.groups()
        types = [t.strip().lower() for t in re.split(r",| and ", kinds) if t.strip()]
        areas_text = desc.split(": ", 1)[1] if ": " in desc else ""
        areas_text = re.split(r" valid from ", areas_text, flags=re.I)[0]
        v = VALID_RE.search(desc)
        valid_from = valid_to = None
        if v:
            valid_from = _when(v[1], v[2], v[3], year)
            valid_to = _when(v[4], v[5], v[6], year)
            if valid_to < valid_from:  # runs over new year
                valid_to = valid_to.replace(year=valid_to.year + 1)
        out.append({
            "level": level.lower(), "types": types, "region": region, "headline": title,
            "areas": [a.strip() for a in areas_text.split(",") if a.strip()],
            "valid_from": valid_from.isoformat() if valid_from else None,
            "valid_to": valid_to.isoformat() if valid_to else None,
            "link": item.findtext("link"),
        })
    return out


def active(warnings: list[dict], now: datetime | None = None) -> list[dict]:
    """Warnings not yet expired; `in_force` = already started."""
    now = now or datetime.now(timezone.utc)
    out = []
    for w in warnings:
        if w["valid_to"] and datetime.fromisoformat(w["valid_to"]) <= now:
            continue
        started = w["valid_from"] is None or datetime.fromisoformat(w["valid_from"]) <= now
        out.append({**w, "in_force": started})
    return out


def for_place(place: dict | None, lat: float | None = None, lon: float | None = None) -> live.LiveResult:
    """Active warnings for the point's Met Office region. `place` is a postcodes.io result."""
    code = region_for(place)
    if code is None:
        return live.LiveResult(SOURCE, FEED.format(code="UK"), "unavailable", live.now_iso(),
                               error="could not work out the Met Office warning region for this point")
    url = FEED.format(code=code)
    res = live.get(SOURCE, url, ttl_s=TTL_S, sample=live.nearest_sample(lat, lon), text=True)
    if res.body is None:
        return res
    try:
        # A saved sample is judged at the time it was saved, so offline runs stay reproducible.
        at = datetime.fromisoformat(res.fetched_at) if res.status == "sample" and res.fetched_at else None
        warnings = active(parse_feed(res.body), at)
    except ET.ParseError as e:
        res.status, res.error = "unavailable", f"bad RSS: {e}"
        return res
    names = {_norm(n) for n in (place.get("admin_district"), place.get("admin_county"), place.get("pfa")) if n}
    for w in warnings:
        w["district_listed"] = any(_norm(a) in names for a in w["areas"])
    order = {"red": 0, "amber": 1, "yellow": 2}
    warnings.sort(key=lambda w: (order.get(w["level"], 3), not w["district_listed"]))
    res.data = {"region_code": code, "region": REGIONS[code], "warnings": warnings, "count": len(warnings),
                "highest_level": warnings[0]["level"] if warnings else None}
    return res
