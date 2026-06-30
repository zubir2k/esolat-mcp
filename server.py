import os
import math
import logging
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

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logger = logging.getLogger("esolat-mcp")

# ==================== CONFIGURATION ====================

CURRENT_VERSION = "1.0.5"
PYPI_PACKAGE_NAME = "esolat-mcp"

# Token validation -- fail loudly in HTTP mode if unset or still using insecure default
_raw_token = os.environ.get("MCP_WEBHOOK_TOKEN", "")
if os.environ.get("MCP_TRANSPORT", "stdio").lower() == "http":
    if not _raw_token:
        raise RuntimeError(
            "[esolat-mcp] MCP_WEBHOOK_TOKEN is not set. "
            "Set it to a strong random secret before starting the HTTP server. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    if _raw_token == "esolat_secure_token":
        raise RuntimeError(
            "[esolat-mcp] MCP_WEBHOOK_TOKEN is still set to the insecure default 'esolat_secure_token'. "
            "Please change it to a strong random secret."
        )
WEBHOOK_TOKEN = _raw_token or "esolat_secure_token"  # stdio mode: value unused

PORT = int(os.environ.get("PORT", "8626"))
TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio").lower()

# ==================== CONSTANTS ====================

DHUHA_OFFSET_MINUTES = 28
MALAYSIA_LAT_MIN, MALAYSIA_LAT_MAX = 1.0, 7.5
MALAYSIA_LON_MIN, MALAYSIA_LON_MAX = 99.5, 119.5
MAX_MOSQUES_RETURNED = 15
HEALTH_CHECK_TIMEOUT = 5.0

HIJRI_MONTHS = {
    "01": "Muharram", "02": "Safar", "03": "Rabi'ul Awwal", "04": "Rabi'ul Akhir",
    "05": "Jamadil Awwal", "06": "Jamadil Akhir", "07": "Rejab", "08": "Sha'aban",
    "09": "Ramadhan", "10": "Syawal", "11": "Zulkaedah", "12": "Zulhijjah"
}

OSM_HEADERS = {"User-Agent": "esolat-mcp-engine/1.0 (Self-Hosted Agent Context)"}

# ==================== GLOBAL HTTP CLIENT (connection pooling) ====================
# Single shared client enables TCP/TLS connection reuse across all tool calls.
http_client = httpx.AsyncClient(follow_redirects=True, timeout=15.0)

# ==================== CACHES ====================
_geocode_cache: TTLCache = TTLCache(maxsize=256, ttl=86400)
_prayer_cache: TTLCache = TTLCache(maxsize=128, ttl=3600)
_events_cache: TTLCache = TTLCache(maxsize=64, ttl=86400)
_pypi_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)

# ==================== MCP INIT ====================

if TRANSPORT == "http" and HAS_TRANSPORT_SECURITY:
    mcp = FastMCP(
        "esolat-mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            # DNS rebinding protection is intentionally disabled.
            # This server binds to 0.0.0.0 to allow cross-device LAN access
            # (e.g. Hermes on 192.168.0.50 connecting to this server on 192.168.0.179).
            # The SDK's allowed_hosts check does not support CIDR/wildcard IP ranges,
            # so enabling it would block all LAN clients.
            # Security is enforced via the webhook token auth layer instead.
            enable_dns_rebinding_protection=False
        )
    )
elif TRANSPORT == "http":
    mcp = FastMCP("esolat-mcp", stateless_http=True)
else:
    mcp = FastMCP("esolat-mcp")

# ==================== HELPERS ====================

def is_malaysia(lat: float, lon: float) -> bool:
    return (MALAYSIA_LAT_MIN <= lat <= MALAYSIA_LAT_MAX) and (MALAYSIA_LON_MIN <= lon <= MALAYSIA_LON_MAX)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

async def check_api_status(url: str, method: str = "GET", headers: dict = None) -> str:
    try:
        if method == "POST":
            res = await http_client.post(url, data={"data": "[out:json][timeout:2];out;"}, headers=headers, timeout=HEALTH_CHECK_TIMEOUT)
        else:
            res = await http_client.get(url, headers=headers, timeout=HEALTH_CHECK_TIMEOUT)
        return "CONNECTED" if res.status_code in [200, 400, 404] else "DEGRADED"
    except Exception as e:
        logger.warning("Health check failed for %s: %s", url, e)
        return "UNREACHABLE"

async def check_pypi_version() -> tuple[str, bool]:
    cache_key = "pypi_version"
    if cache_key in _pypi_cache:
        return _pypi_cache[cache_key]
    try:
        response = await http_client.get(f"https://pypi.org/pypi/{PYPI_PACKAGE_NAME}/json", timeout=5.0)
        if response.status_code == 200:
            latest = response.json()["info"]["version"]
            update_available = latest != CURRENT_VERSION
            result = (latest, update_available)
            _pypi_cache[cache_key] = result
            return result
    except Exception as e:
        logger.warning("PyPI version check failed: %s", e)
    return (CURRENT_VERSION, False)

async def resolve_location(location_name: str = None, latitude: float = None, longitude: float = None):
    if location_name:
        cache_key = location_name.strip().lower()
        if cache_key in _geocode_cache:
            return _geocode_cache[cache_key]
        try:
            response = await http_client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": location_name, "format": "json", "limit": 1},
                headers=OSM_HEADERS,
                timeout=10.0
            )
            data = response.json()
        except (httpx.RequestError, ValueError) as e:
            logger.error("Geocoding failed for '%s': %s", location_name, e)
            return {"error": "Location lookup failed: could not reach or parse OpenStreetMap data. Try again later."}
        if not data:
            return {"error": f"Location '{location_name}' could not be resolved. Try a different name or use coordinates."}
        result = (float(data[0]["lat"]), float(data[0]["lon"]))
        _geocode_cache[cache_key] = result
        return result
    if latitude is not None and longitude is not None:
        return (latitude, longitude)
    return {"error": "Provide either a location_name string or latitude/longitude coordinates."}
# ==================== CURRENT TIME HELPER ====================

def _get_current_time_utc() -> dict:
    """
    Shared helper returning current UTC time. Zero external calls.
    Hijri date is intentionally NOT included here: it is region-dependent
    (moonsighting-based, can differ by +/-1 day between JAKIM, Saudi, etc.),
    so a pure arithmetic approximation would be misleading and inconsistent
    with the authoritative Hijri dates returned by get_monthly_prayer_times
    and get_yearly_islamic_events (sourced directly from JAKIM/Aladhan).
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    current_time_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "current_time_utc": current_time_utc,
        "source": "server"
    }

# ==================== MCP CORE TOOLS ====================

@mcp.tool()
async def get_current_time() -> dict:
    """
    Returns the current server UTC time.
    Use this tool first when the user asks about current prayer status, time remaining to next prayer,
    or any query that requires comparing current time against prayer times.
    For the Hijri date, use get_monthly_prayer_times or get_yearly_islamic_events instead,
    since the Hijri calendar is region-dependent (moonsighting-based) and those tools
    return the authoritative date sourced from JAKIM/Aladhan.
    """
    return _get_current_time_utc()


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
    location = await resolve_location(location_name, latitude, longitude)
    if isinstance(location, dict):
        return location
    lat, lon = location

    current_date = datetime.date.today()
    target_month = month or current_date.month
    target_year = year or current_date.year

    cache_key = (round(lat, 4), round(lon, 4), target_year, target_month)
    if cache_key in _prayer_cache:
        return _prayer_cache[cache_key]

    processed_prayers = []

    try:
        if is_malaysia(lat, lon):
            url = f"https://api.waktusolat.app/v2/solat/gps/{lat}/{lon}?year={target_year}&month={target_month}"
            response = await http_client.get(url, timeout=15.0)
            if response.status_code != 200:
                return {"error": "The Malaysian prayer time API (WaktuSolat) is currently unreachable. Please try again later."}
            raw_data = response.json()
            for day_entry in raw_data.get("prayers", []):
                syuruk_ts = day_entry["syuruk"]
                dhuha_ts = syuruk_ts + (DHUHA_OFFSET_MINUTES * 60)
                def parse_epoch(ts):
                    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            response = await http_client.get(url, timeout=15.0)
            if response.status_code != 200:
                return {"error": "The global prayer time API (Aladhan) is currently unreachable. Please try again later."}
            raw_data = response.json()
            for day_entry in raw_data.get("data", []):
                timings = day_entry["timings"]
                greg_date = day_entry["date"]["gregorian"]["date"]
                parsed_greg = datetime.datetime.strptime(greg_date, "%d-%m-%Y").strftime("%Y-%m-%d")
                def to_iso(t: str) -> str:
                    h, m = map(int, t.split(":"))
                    return datetime.datetime(int(parsed_greg[:4]), int(parsed_greg[5:7]), int(parsed_greg[8:10]), h - 8, m, tzinfo=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                syuruk_str = timings["Sunrise"].split(" ")[0]
                syuruk_time = datetime.datetime.strptime(syuruk_str, "%H:%M")
                dhuha_time = (syuruk_time + datetime.timedelta(minutes=DHUHA_OFFSET_MINUTES)).strftime("%H:%M")
                hijri_meta = day_entry["date"]["hijri"]
                h_month_num = str(hijri_meta["month"]["number"]).zfill(2)
                hijri_full = f"{hijri_meta['day']} {HIJRI_MONTHS.get(h_month_num, hijri_meta['month']['en'])} {hijri_meta['year']}"
                processed_prayers.append({
                    "date": parsed_greg,
                    "day_name": day_entry["date"]["gregorian"]["weekday"]["en"],
                    "hijri_raw": f"{hijri_meta['year']}-{h_month_num}-{str(hijri_meta['day']).zfill(2)}",
                    "hijri_full": hijri_full,
                    "fajr": to_iso(timings["Fajr"].split(" ")[0]),
                    "syuruk": to_iso(syuruk_str),
                    "dhuha": to_iso(dhuha_time),
                    "dhuhr": to_iso(timings["Dhuhr"].split(" ")[0]),
                    "asr": to_iso(timings["Asr"].split(" ")[0]),
                    "maghrib": to_iso(timings["Maghrib"].split(" ")[0]),
                    "isha": to_iso(timings["Isha"].split(" ")[0])
                })
    except httpx.RequestError as e:
        logger.error("Network error fetching prayer times: %s", e)
        return {"error": "Network error while fetching prayer times. Please try again later."}

    # Inject current_time_utc so agent can compare without a separate tool call
    result = {
        "current_time_utc": _get_current_time_utc()["current_time_utc"],
        "prayers": processed_prayers
    }
    _prayer_cache[cache_key] = result
    return result


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
    location = await resolve_location(location_name, latitude, longitude)
    if isinstance(location, dict):
        return location
    lat, lon = location

    mosque_list = []

    try:
        if is_malaysia(lat, lon):
            url = f"https://www.e-solat.gov.my/index.php?r=esolatApi/nearestMosque&lat={lat}&long={lon}&dist={distance_km}"
            response = await http_client.get(url, timeout=15.0)
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
            response = await http_client.post(overpass_url, data={"data": query}, headers=OSM_HEADERS, timeout=30.0)
            if response.status_code == 200:
                raw_data = response.json()
                for element in raw_data.get("elements", []):
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
    except httpx.RequestError as e:
        logger.error("Network error fetching mosques: %s", e)
        return {"error": "Network error while searching for mosques. Please try again later."}

    mosque_list.sort(key=lambda x: x["distance_km"])
    return mosque_list[:MAX_MOSQUES_RETURNED]

@mcp.tool()
async def get_yearly_islamic_events(
    location_name: str = None,
    latitude: float = None,
    longitude: float = None,
    target_year: int = None
) -> list | dict:
    """
    Retrieves significant Islamic calendar milestones for a target year.
    Defaults to the current year if not specified.
    """
    target_year = target_year or datetime.date.today().year

    try:
        location = await resolve_location(location_name, latitude, longitude)
        if isinstance(location, dict):
            local_route = True
        else:
            lat, lon = location
            local_route = is_malaysia(lat, lon)
    except Exception:
        local_route = True

    cache_key = (local_route, target_year)
    if cache_key in _events_cache:
        return _events_cache[cache_key]

    event_list = []

    try:
        if local_route:
            url = "https://www.e-solat.gov.my/index.php?r=esolatApi/islamicevent&type=all"
            response = await http_client.get(url, timeout=15.0)
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
            response = await http_client.get(url, timeout=15.0)
            if response.status_code != 200:
                return {"error": "The Aladhan Islamic events API is currently unreachable. Please try again later."}
            raw_data = response.json()
            for item in raw_data.get("data", []):
                greg_date = datetime.datetime.strptime(item["gregorianDate"], "%d-%m-%Y").strftime("%Y-%m-%d")
                event_name = (item.get("arahName") or item.get("label") or "").strip()
                event_list.append({
                    "event_name": event_name,
                    "gregorian_date": greg_date,
                    "hijri_date": f"{item['hijriYear']}-{str(item['hijriMonth']).zfill(2)}-{str(item['hijriDay']).zfill(2)}"
                })
    except httpx.RequestError as e:
        logger.error("Network error fetching Islamic events: %s", e)
        return {"error": "Network error while fetching Islamic events. Please try again later."}

    event_list.sort(key=lambda x: x["gregorian_date"])
    _events_cache[cache_key] = event_list
    return event_list


# ==================== MCP RESOURCE: SERVER STATUS ====================

@mcp.resource("esolat://server-status")
async def get_server_status() -> dict:
    """
    MCP Resource: Returns live health status of the esolat-mcp server and all upstream APIs.
    Also reports the current version and whether a newer version is available on PyPI.
    Use this resource to proactively check if JAKIM or other APIs are down before calling prayer time tools.
    """
    return await _build_status_payload()


# ==================== SHARED STATUS BUILDER ====================

async def _build_status_payload() -> dict:
    import asyncio
    current_date = datetime.date.today()

    jakim_task = check_api_status("https://www.e-solat.gov.my/index.php?r=esolatApi/islamicevent&type=all")
    waktu_task = check_api_status(f"https://api.waktusolat.app/v2/solat/gps/3.0219423/101.791623?year={current_date.year}&month={current_date.month}")
    osm_task = check_api_status("https://nominatim.openstreetmap.org/search?q=Kajang&format=json&limit=1", headers=OSM_HEADERS)
    pypi_task = check_pypi_version()

    jakim_status, waktu_status, osm_status, (latest_version, update_available) = await asyncio.gather(
        jakim_task, waktu_task, osm_task, pypi_task
    )

    return {
        "server": "esolat-mcp",
        "status": "ONLINE",
        "version": CURRENT_VERSION,
        "latest_version": latest_version,
        "update_available": update_available,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()[:-6] + "Z",
        "upstream_apis": {
            "jakim_e_solat": jakim_status,
            "waktu_solat_app": waktu_status,
            "openstreetmap_nominatim": osm_status
        }
    }


# ==================== WEBHOOK TRANSPORT LAYER MIDDLEWARE ====================

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, JSONResponse as StarletteJSONResponse

class SecurePathAndDashboardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        expected_prefix = f"/api/webhook/{WEBHOOK_TOKEN}"

        if path == "/favicon.ico":
            return StarletteJSONResponse(status_code=204, content=None)

        if path == "/":
            if method == "GET":
                landing_text = (
                    "esolat-mcp server is up and running!\n\n"
                    "To connect, use your configured MCP_WEBHOOK_TOKEN to construct the endpoint:\n"
                    f"  Health dashboard : http://<YOUR_IP_OR_DOMAIN>:{PORT}/api/webhook/<TOKEN>/\n"
                    f"  MCP endpoint     : http://<YOUR_IP_OR_DOMAIN>:{PORT}/api/webhook/<TOKEN>/mcp\n\n"
                    "Refer to your .env or docker-compose.yml for the configured token."
                )
                return PlainTextResponse(status_code=200, content=landing_text)
            else:
                return StarletteJSONResponse(
                    status_code=400,
                    content={"error": "Use your secure webhook token path to access this server."}
                )

        if not path.startswith(expected_prefix):
            return StarletteJSONResponse(
                status_code=401,
                content={"error": "Forbidden: Unauthorized Webhook Signature Path."}
            )

        if path.rstrip("/") == expected_prefix.rstrip("/") and method == "GET":
            payload = await _build_status_payload()
            return StarletteJSONResponse(status_code=200, content=payload)

        if path.startswith(expected_prefix):
            request.scope["path"] = path[len(expected_prefix):] or "/"
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
        logger.info("Starting esolat-mcp HTTP server on 0.0.0.0:%s", PORT)
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=PORT,
            proxy_headers=True,
            forwarded_allow_ips="*"
        )

if __name__ == "__main__":
    main()