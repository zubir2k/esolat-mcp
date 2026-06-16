import os
import math
import datetime
import httpx
from cachetools import TTLCache
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

# Conditional import: TransportSecuritySettings requires mcp >= 1.23.0
try:
    from mcp.server.transport_security import TransportSecuritySettings
    HAS_TRANSPORT_SECURITY = True
except ImportError:
    HAS_TRANSPORT_SECURITY = False

# ==================== CONFIGURATION ====================

WEBHOOK_TOKEN = os.environ.get("MCP_WEBHOOK_TOKEN", "esolat_secure_token")
PORT = int(os.environ.get("PORT", "8626"))
TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio").lower()

# ==================== CACHES ====================
# FIX #4 & #6: In-memory TTL caches to protect OSM rate limits and reduce API hammering.
# Nominatim geocoding: 24-hour TTL, max 256 unique location strings.
_geocode_cache: TTLCache = TTLCache(maxsize=256, ttl=86400)

# Prayer times: 1-hour TTL, keyed by (lat, lon, year, month).
# Monthly data rarely changes; 1hr is conservative and safe.
_prayer_cache: TTLCache = TTLCache(maxsize=128, ttl=3600)

# Islamic events: 24-hour TTL, keyed by (route, year).
_events_cache: TTLCache = TTLCache(maxsize=64, ttl=86400)

# ==================== MCP INIT ====================

if TRANSPORT == "http" and HAS_TRANSPORT_SECURITY:
    mcp = FastMCP(
        "esolat-mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    )
elif TRANSPORT == "http":
    mcp = FastMCP("esolat-mcp", stateless_http=True)
else:
    mcp = FastMCP("esolat-mcp")

# ==================== CONSTANTS ====================

HIJRI_MONTHS = {
    "01": "Muharram", "02": "Safar", "03": "Rabi'ul Awwal", "04": "Rabi'ul Akhir",
    "05": "Jamadil Awwal", "06": "Jamadil Akhir", "07": "Rejab", "08": "Sha'aban",
    "09": "Ramadhan", "10": "Syawal", "11": "Zulkaedah", "12": "Zulhijjah"
}

OSM_HEADERS = {"User-Agent": "esolat-mcp-engine/1.0 (Self-Hosted Agent Context)"}

# ==================== HELPERS ====================

def is_malaysia(lat: float, lon: float) -> bool:
    """Geographical boundary box check to route between JAKIM and Global API targets."""
    return (1.0 <= lat <= 7.5) and (99.5 <= lon <= 119.5)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the absolute geodesic distance in kilometers between two GPS nodes."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

async def check_api_status(url: str, method: str = "GET", headers: dict = None) -> str:
    """Helper to check the live status of the upstream APIs for the dashboard."""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            if method == "POST":
                res = await client.post(url, data={"data": "[out:json][timeout:2];out;"}, headers=headers, timeout=2.0)
            else:
                res = await client.get(url, headers=headers, timeout=2.0)
            return "CONNECTED" if res.status_code in [200, 400, 404] else "DEGRADED"
    except Exception:
        return "UNREACHABLE"

async def resolve_location(location_name: str = None, latitude: float = None, longitude: float = None):
    """
    Internal Location Resolver Core.
    If text string is supplied, converts it via OpenStreetMap Nominatim proxy (cached 24hr).
    If raw GPS coordinates are supplied, returns them directly.

    FIX #2: Returns error dict instead of raising HTTPException so stdio transport
            can surface a readable message to the LLM rather than crashing the tool call.
    FIX #4: Results cached in _geocode_cache to prevent OSM rate-limit bans on
            concurrent or repeat LLM calls for the same location string.
    """
    if location_name:
        cache_key = location_name.strip().lower()
        if cache_key in _geocode_cache:
            return _geocode_cache[cache_key]
        url = f"https://nominatim.openstreetmap.org/search?q={location_name}&format=json&limit=1"
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, headers=OSM_HEADERS, timeout=10.0)
                data = response.json()
        except httpx.RequestError:
            return {"error": f"Location lookup failed: could not reach OpenStreetMap. Try again later."}
        if not data:
            return {"error": f"Location '{location_name}' could not be resolved. Try a different name or use coordinates."}
        result = (float(data[0]["lat"]), float(data[0]["lon"]))
        _geocode_cache[cache_key] = result
        return result

    if latitude is not None and longitude is not None:
        return (latitude, longitude)

    return {"error": "Provide either a location_name string or latitude/longitude coordinates."}

# ==================== MCP CORE TOOLS ====================

@mcp.tool()
async def get_monthly_prayer_times(
    location_name: str = None,
    latitude: float = None,
    longitude: float = None,
    month: int = None,
    year: int = None
) -> list | dict:
    """
    Fetches comprehensive monthly prayer times based on raw GPS coordinates or location name string text.
    Computes precise Dhuha intervals (+28 mins from Syuruk) and normalizes Hijri month texts.
    Use this tool whenever the user asks for today's prayer times, this week's schedule,
    or a specific month's prayer schedule.
    """
    # FIX #2: resolve_location now returns error dict on failure instead of raising
    location = await resolve_location(location_name, latitude, longitude)
    if isinstance(location, dict):
        return location
    lat, lon = location

    current_date = datetime.date.today()
    target_month = month or current_date.month
    target_year = year or current_date.year

    # FIX #6: Cache prayer times by coordinates + month/year (1hr TTL)
    cache_key = (round(lat, 4), round(lon, 4), target_year, target_month)
    if cache_key in _prayer_cache:
        return _prayer_cache[cache_key]

    processed_prayers = []

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            if is_malaysia(lat, lon):
                url = f"https://api.waktusolat.app/v2/solat/gps/{lat}/{lon}?year={target_year}&month={target_month}"
                response = await client.get(url, timeout=15.0)
                if response.status_code != 200:
                    # FIX #2: return structured error instead of raise HTTPException
                    return {"error": "The Malaysian prayer time API (WaktuSolat) is currently unreachable. Please try again later."}
                raw_data = response.json()
                for day_entry in raw_data.get("prayers", []):
                    syuruk_ts = day_entry["syuruk"]
                    dhuha_ts = syuruk_ts + (28 * 60)
                    def parse_epoch(ts):
                        return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone(datetime.timedelta(hours=8))).strftime("%H:%M")
                    hijri_raw = day_entry["hijri"]
                    h_y, h_m, h_d = hijri_raw.split("-")
                    hijri_full = f"{int(h_d)} {HIJRI_MONTHS.get(h_m, h_m)} {h_y}"
                    processed_prayers.append({
                        "date": f"{target_year}-{str(target_month).zfill(2)}-{str(day_entry['day']).zfill(2)}",
                        "day_name": datetime.datetime.strptime(f"{target_year}-{target_month}-{day_entry['day']}", "%Y-%m-%d").strftime("%A"),
                        "hijri_raw": hijri_raw,
                        "hijri_full": hijri_full,
                        "fajr": parse_epoch(day_entry["fajr"]),
                        "syuruk": parse_epoch(syuruk_ts),
                        "dhuha": parse_epoch(dhuha_ts),
                        "dhuhr": parse_epoch(day_entry["dhuhr"]),
                        "asr": parse_epoch(day_entry["asr"]),
                        "maghrib": parse_epoch(day_entry["maghrib"]),
                        "isha": parse_epoch(day_entry["isha"])
                    })
            else:
                url = f"https://api.aladhan.com/v1/calendar?latitude={lat}&longitude={lon}&method=2&month={target_month}&year={target_year}"
                response = await client.get(url, timeout=15.0)
                if response.status_code != 200:
                    return {"error": "The global prayer time API (Aladhan) is currently unreachable. Please try again later."}
                raw_data = response.json()
                for day_entry in raw_data.get("data", []):
                    timings = day_entry["timings"]
                    greg_date = day_entry["date"]["gregorian"]["date"]
                    parsed_greg = datetime.datetime.strptime(greg_date, "%d-%m-%Y").strftime("%Y-%m-%d")
                    syuruk_str = timings["Sunrise"].split(" ")[0]
                    syuruk_time = datetime.datetime.strptime(syuruk_str, "%H:%M")
                    dhuha_time = (syuruk_time + datetime.timedelta(minutes=28)).strftime("%H:%M")
                    hijri_meta = day_entry["date"]["hijri"]
                    h_month_num = str(hijri_meta["month"]["number"]).zfill(2)
                    hijri_full = f"{hijri_meta['day']} {HIJRI_MONTHS.get(h_month_num, hijri_meta['month']['en'])} {hijri_meta['year']}"
                    processed_prayers.append({
                        "date": parsed_greg,
                        "day_name": day_entry["date"]["gregorian"]["weekday"]["en"],
                        "hijri_raw": f"{hijri_meta['year']}-{h_month_num}-{str(hijri_meta['day']).zfill(2)}",
                        "hijri_full": hijri_full,
                        "fajr": timings["Fajr"].split(" ")[0],
                        "syuruk": syuruk_str,
                        "dhuha": dhuha_time,
                        "dhuhr": timings["Dhuhr"].split(" ")[0],
                        "asr": timings["Asr"].split(" ")[0],
                        "maghrib": timings["Maghrib"].split(" ")[0],
                        "isha": timings["Isha"].split(" ")[0]
                    })
    except httpx.RequestError:
        return {"error": "Network error while fetching prayer times. Please try again later."}

    _prayer_cache[cache_key] = processed_prayers
    return processed_prayers


@mcp.tool()
async def find_nearest_mosques(
    location_name: str = None,
    latitude: float = None,
    longitude: float = None,
    distance_km: int = 5
) -> list | dict:
    """
    Finds verified mosques, masjids, or suraus within a target search radius.
    Injects map routing navigation strings for Google Maps and native Waze applications.
    """
    # FIX #2: resolve_location now returns error dict on failure
    location = await resolve_location(location_name, latitude, longitude)
    if isinstance(location, dict):
        return location
    lat, lon = location

    mosque_list = []

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            if is_malaysia(lat, lon):
                url = f"https://www.e-solat.gov.my/index.php?r=esolatApi/nearestMosque&lat={lat}&long={lon}&dist={distance_km}"
                response = await client.get(url, timeout=15.0)
                if response.status_code == 200:
                    raw_data = response.json()
                    for item in raw_data.get("locationData", []):
                        m_lat = float(item["latitud"])
                        m_lon = float(item["longitud"])
                        mosque_list.append({
                            "name": item["nama_masjid"].strip(),
                            "distance_km": round(float(item["distance"]), 2),
                            "coordinates": {"latitude": m_lat, "longitude": m_lon},
                            "google_maps_link": f"https://maps.google.com/?q={m_lat},{m_lon}",
                            "waze_link": f"https://waze.com/ul?ll={m_lat},{m_lon}&navigate=yes&z=10"
                        })
            else:
                radius_meters = distance_km * 1000
                overpass_url = "https://overpass-api.de/api/interpreter"
                query = f"""
[out:json][timeout:25];
(
  node["amenity"="place_of_worship"]["religion"="muslim"](around:{radius_meters},{lat},{lon});
  way["amenity"="place_of_worship"]["religion"="muslim"](around:{radius_meters},{lat},{lon});
);
out body center;
"""
                response = await client.post(overpass_url, data={"data": query}, headers=OSM_HEADERS, timeout=30.0)
                if response.status_code == 200:
                    raw_data = response.json()
                    for element in raw_data.get("elements", []):
                        # FIX #5 (partial): use explicit None checks instead of falsy
                        # so lat/lon of 0.0 (equator) is not silently dropped
                        m_lat = element.get("lat") if element.get("lat") is not None else element.get("center", {}).get("lat")
                        m_lon = element.get("lon") if element.get("lon") is not None else element.get("center", {}).get("lon")
                        if m_lat is not None and m_lon is not None:
                            tags = element.get("tags", {})
                            name = tags.get("name", tags.get("official_name", "Mosque / Muslim Place of Worship"))
                            computed_dist = haversine_distance(lat, lon, m_lat, m_lon)
                            mosque_list.append({
                                "name": name.strip(),
                                "distance_km": computed_dist,
                                "coordinates": {"latitude": m_lat, "longitude": m_lon},
                                "google_maps_link": f"https://maps.google.com/?q={m_lat},{m_lon}",
                                "waze_link": f"https://waze.com/ul?ll={m_lat},{m_lon}&navigate=yes&z=10"
                            })
    except httpx.RequestError:
        return {"error": "Network error while searching for mosques. Please try again later."}

    mosque_list.sort(key=lambda x: x["distance_km"])
    return mosque_list[:15]


@mcp.tool()
async def get_yearly_islamic_events(
    location_name: str = None,
    latitude: float = None,
    longitude: float = None,
    target_year: int = None   # FIX #3: was hardcoded 2026
) -> list | dict:
    """
    Retrieves significant Islamic calendar milestones for a target year.
    Defaults to the current year if not specified.
    """
    # FIX #3: Default to current year instead of hardcoded 2026
    target_year = target_year or datetime.date.today().year

    try:
        location = await resolve_location(location_name, latitude, longitude)
        if isinstance(location, dict):
            local_route = True  # fallback to Malaysia route if location fails
        else:
            lat, lon = location
            local_route = is_malaysia(lat, lon)
    except Exception:
        local_route = True

    # FIX #6: Cache events by (route, year) — 24hr TTL since events don't change
    cache_key = (local_route, target_year)
    if cache_key in _events_cache:
        return _events_cache[cache_key]

    event_list = []

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            if local_route:
                url = "https://www.e-solat.gov.my/index.php?r=esolatApi/islamicevent&type=all"
                response = await client.get(url, timeout=15.0)
                if response.status_code != 200:
                    return {"error": "The JAKIM Islamic events API is currently unreachable. Please try again later."}
                raw_data = response.json()
                for item in raw_data.get("event", []):
                    greg_date = item.get("tarikh_miladi", "")
                    if greg_date.startswith(str(target_year)):
                        event_list.append({
                            "event_name": item["hari_peristiwa"].replace("*", "").strip(),
                            "gregorian_date": greg_date,
                            "hijri_date": item["tarikh_hijri"]
                        })
            else:
                url = f"https://api.aladhan.com/v1/islamicEvents?year={target_year}"
                response = await client.get(url, timeout=15.0)
                if response.status_code != 200:
                    return {"error": "The Aladhan Islamic events API is currently unreachable. Please try again later."}
                raw_data = response.json()
                for item in raw_data.get("data", []):
                    greg_date = datetime.datetime.strptime(item["gregorianDate"], "%d-%m-%Y").strftime("%Y-%m-%d")
                    # FIX #5: Safe null-guard for arahName — avoids AttributeError if field is None
                    event_name = (item.get("arahName") or item.get("label") or "").strip()
                    event_list.append({
                        "event_name": event_name,
                        "gregorian_date": greg_date,
                        "hijri_date": f"{item['hijriYear']}-{str(item['hijriMonth']).zfill(2)}-{str(item['hijriDay']).zfill(2)}"
                    })
    except httpx.RequestError:
        return {"error": "Network error while fetching Islamic events. Please try again later."}

    event_list.sort(key=lambda x: x["gregorian_date"])
    _events_cache[cache_key] = event_list
    return event_list


# ==================== WEBHOOK TRANSPORT LAYER MIDDLEWARE ====================

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, JSONResponse as StarletteJSONResponse

class SecurePathAndDashboardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        expected_prefix = f"/api/webhook/{WEBHOOK_TOKEN}"

        # 1. Silence favicon noise
        if path == "/favicon.ico":
            return StarletteJSONResponse(status_code=204, content=None)

        # 2. Root path landing page
        if path == "/":
            if method == "GET":
                landing_text = (
                    "esolat-mcp server is up and running!\n\n"
                    "To connect, paste the full URL (including your secret /api/webhook/ token key)\n"
                    "into the connector or MCP settings of your AI/LLM client.\n\n"
                    "Your private browser health dashboard endpoint:\n"
                    f"http://<YOUR_IP_OR_DOMAIN>:{PORT}{expected_prefix}/\n\n"
                    "Your private AI agent connection endpoint:\n"
                    f"http://<YOUR_IP_OR_DOMAIN>:{PORT}{expected_prefix}/mcp"
                )
                return PlainTextResponse(status_code=200, content=landing_text)
            else:
                return StarletteJSONResponse(
                    status_code=400,
                    content={"error": "Use your secure webhook token path to access this server."}
                )

        # FIX #1: REMOVED the /mcp /sse /events passthrough that bypassed token auth.
        # Previously these paths were allowed through without token verification,
        # meaning anyone could reach the live MCP endpoint without a token.
        # Now ALL paths except "/" and "/favicon.ico" must carry the token prefix.

        # 3. Reject anything outside the authenticated token namespace
        if not path.startswith(expected_prefix):
            return StarletteJSONResponse(
                status_code=401,
                content={"error": "Forbidden: Unauthorized Webhook Signature Path."}
            )

        # 4. Health dashboard — GET on the exact token prefix
        if path.rstrip("/") == expected_prefix.rstrip("/") and method == "GET":
            current_date = datetime.date.today()
            target_month = current_date.month
            target_year = current_date.year
            jakim_status = await check_api_status("https://www.e-solat.gov.my/index.php?r=esolatApi/islamicevent&type=all")
            waktu_status = await check_api_status(f"https://api.waktusolat.app/v2/solat/gps/3.0219423/101.791623?year={target_year}&month={target_month}")
            osm_status = await check_api_status("https://nominatim.openstreetmap.org/search?q=Kajang&format=json&limit=1", headers=OSM_HEADERS)
            return StarletteJSONResponse(status_code=200, content={
                "server": "esolat-mcp",
                "status": "ONLINE",
                "version": "1.0.1",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()[:-6] + "Z",
                "upstream_apis": {
                    "jakim_e_solat": jakim_status,
                    "waktu_solat_app": waktu_status,
                    "openstreetmap_nominatim": osm_status
                }
            })

        # 5. Strip token prefix and forward to FastMCP app
        if path.startswith(expected_prefix):
            request.scope["path"] = path.replace(expected_prefix, "") or "/"
            return await call_next(request)


# ==================== ENTRYPOINT ====================

def main():
    """
    Dual-mode entrypoint.
    - MCP_TRANSPORT=stdio (default): local subprocess for Claude Desktop / Claude Code.
    - MCP_TRANSPORT=http: Streamable HTTP behind webhook-token middleware (Docker).
    """
    if TRANSPORT == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn
        app = mcp.streamable_http_app()
        app.add_middleware(SecurePathAndDashboardMiddleware)
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=PORT,
            proxy_headers=True,
            forwarded_allow_ips="*"
        )

if __name__ == "__main__":
    main()
