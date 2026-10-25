"""Open-Meteo forecast: current weather and the next 24 hours at a point.

Open-Meteo is free for non-commercial use with no key; attribution required
("Weather data by Open-Meteo.com", CC BY 4.0). Models for the UK include the Met Office
UKV, blended by Open-Meteo's "best match".

Severity (worst of now and the next 24 h), documented in data/README.md:
  severe    gusts >= 70 km/h, or precipitation >= 8 mm/h, or snowfall >= 1 cm/h,
            or a thunderstorm (WMO weather codes 95-99)
  moderate  gusts >= 50 km/h, or precipitation >= 2 mm/h, or any snowfall
  none      otherwise
Only "severe" can support the `weather` cause; "moderate" is context.
"""

from __future__ import annotations

from coverage_detective.sources import live

SOURCE = "open_meteo"
URL = "https://api.open-meteo.com/v1/forecast"
TTL_S = 30 * 60
VARIABLES = "precipitation,rain,snowfall,wind_speed_10m,wind_gusts_10m,weather_code"

SEVERE = {"gust_kmh": 70.0, "precip_mm_h": 8.0, "snow_cm_h": 1.0}
MODERATE = {"gust_kmh": 50.0, "precip_mm_h": 2.0, "snow_cm_h": 0.0}
THUNDER_CODES = range(95, 100)

# WMO weather interpretation codes (Open-Meteo docs).
WMO = {0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
       51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers",
       81: "showers", 82: "violent showers", 85: "snow showers", 86: "heavy snow showers",
       95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}


def severity(gust_kmh: float, precip_mm_h: float, snow_cm_h: float, codes: list[int]) -> tuple[str, list[str]]:
    """('none'|'moderate'|'severe', reasons)."""
    reasons = []
    if gust_kmh >= SEVERE["gust_kmh"]:
        reasons.append(f"gusts up to {gust_kmh:.1f} km/h")
    if precip_mm_h >= SEVERE["precip_mm_h"]:
        reasons.append(f"heavy rain up to {precip_mm_h:.1f} mm/h")
    if snow_cm_h >= SEVERE["snow_cm_h"]:
        reasons.append(f"heavy snow up to {snow_cm_h:.1f} cm/h")
    if any(c in THUNDER_CODES for c in codes):
        reasons.append("thunderstorms")
    if reasons:
        return "severe", reasons
    if gust_kmh >= MODERATE["gust_kmh"]:
        reasons.append(f"gusts up to {gust_kmh:.1f} km/h")
    if precip_mm_h >= MODERATE["precip_mm_h"]:
        reasons.append(f"rain up to {precip_mm_h:.1f} mm/h")
    if snow_cm_h > MODERATE["snow_cm_h"]:
        reasons.append(f"snow up to {snow_cm_h:.1f} cm/h")
    return ("moderate", reasons) if reasons else ("none", [])


def summarise(body: dict) -> dict:
    cur, hourly = body["current"], body["hourly"]
    per_hour = 3600 / (cur.get("interval") or 3600)  # current precipitation covers `interval` seconds
    now = {
        "time": cur["time"],
        "precipitation_mm_h": round(cur["precipitation"] * per_hour, 1),
        "rain_mm_h": round(cur["rain"] * per_hour, 1),
        "snowfall_cm_h": round(cur["snowfall"] * per_hour, 1),
        "wind_kmh": cur["wind_speed_10m"],
        "gust_kmh": cur["wind_gusts_10m"],
        "weather_code": cur["weather_code"],
        "weather": WMO.get(cur["weather_code"], f"code {cur['weather_code']}"),
    }

    def worst(name):
        vals = [v for v in hourly[name] if v is not None]
        if not vals:
            return None, None
        i = hourly[name].index(max(vals))
        return max(vals), hourly["time"][i]

    max_precip, max_precip_at = worst("precipitation")
    max_gust, max_gust_at = worst("wind_gusts_10m")
    max_snow, _ = worst("snowfall")
    codes = [c for c in hourly["weather_code"] if c is not None]
    next_24h = {
        "hours": len(hourly["time"]),
        "max_precipitation_mm_h": max_precip, "max_precipitation_at": max_precip_at,
        "max_gust_kmh": max_gust, "max_gust_at": max_gust_at,
        "max_snowfall_cm_h": max_snow,
        "total_precipitation_mm": round(sum(v for v in hourly["precipitation"] if v is not None), 1),
        "thunderstorm_expected": any(c in THUNDER_CODES for c in codes),
    }
    level, reasons = severity(
        max(now["gust_kmh"], max_gust or 0), max(now["precipitation_mm_h"], max_precip or 0),
        max(now["snowfall_cm_h"], max_snow or 0), [now["weather_code"], *codes])
    return {"now": now, "next_24h": next_24h, "severity": level, "reasons": reasons,
            "model_lat": body.get("latitude"), "model_lon": body.get("longitude"),
            "thresholds": {"severe": SEVERE, "moderate": MODERATE}}


def forecast(lat: float, lon: float) -> live.LiveResult:
    params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "current": VARIABLES, "hourly": VARIABLES,
              "forecast_hours": 24, "timezone": "Europe/London"}
    res = live.get(SOURCE, URL, params, ttl_s=TTL_S, sample=live.nearest_sample(lat, lon))
    if res.body:
        try:
            res.data = summarise(res.body)
        except (KeyError, TypeError, ValueError) as e:
            res.status, res.error = "unavailable", f"unexpected response: {e}"
    return res
