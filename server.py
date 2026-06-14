import os
import math
import datetime
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

# Conditional import: TransportSecuritySettings requires mcp >= 1.23.0
# Falls back gracefully if not available in the installed version
try:
    from mcp.server.transport_security import TransportSecuritySettings
    HAS_TRANSPORT_SECURITY = True
except ImportError:
    HAS_TRANSPORT_SECURITY = False

# Initialize Configurations from Environment Variables
WEBHOOK_TOKEN = os.environ.get("MCP_WEBHOOK_TOKEN", "esolat_secure_token")
PORT = int(os.environ.get("PORT", "8626"))
TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio").lower()

# Initialize FastMCP Server
# - stateless_http=True + DNS-rebinding protection disabled: only relevant for
#   the streamable-HTTP transport (self-hosted backend, no session persistence).
#   These options are HTTP-specific and must NOT be passed when running over
#   stdio, or FastMCP raises an internal error during initialize.
if TRANSPORT == "http" and HAS_TRANSPORT_SECURITY:
    mcp = FastMCP(
        "esolat-mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    )
elif TRANSPORT == "http":
    mcp = FastMCP(
        "esolat-mcp",
        stateless_http=True,
    )
else:
    mcp = FastMCP("esolat-mcp")

# Custom Hijri Month Mapping Translation Matrix
HIJRI_MONTHS = {
    "01": "Muharram", "02": "Safar", "03": "Rabi'ul Awwal", "04": "Rabi'ul Akhir",
    "05": "Jamadil Awwal", "06": "Jamadil Akhir", "07": "Rejab", "08": "Sha'aban",
    "09": "Ramadhan", "10": "Syawal", "11": "Zulkaedah", "12": "Zulhijjah"
}

# HTTP Header Requirements for OpenStreetMap API Policy Compliance
OSM_HEADERS = {"User-Agent": "esolat-mcp-engine/1.0 (Self-Hosted Agent Context)"}

def is_malaysia(lat: float, lon: float) -> bool:
    """Geographical boundary box check to route between JAKIM and Global API targets."""
    return (1.0 <= lat <= 7.5) and (99.5 <= lon <= 119.5)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the absolute geodesic distance in kilometers between two GPS nodes."""
    R = 6371.0  # Earth's radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

async def check_api_status(url: str, method: str = "GET", headers: dict = None) -> str:
    """Helper to check the live status of the upstream APIs for the dashboard."""
    try:
        async with httpx.AsyncClient() as client:
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
    If text string is supplied, converts it via OpenStreetMap Nominatim proxy.
    If raw GPS coordinates are supplied, returns them directly.
    """
    if location_name:
        url = f"https://nominatim.openstreetmap.org/search?q={location_name}&format=json&limit=1"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=OSM_HEADERS)
            data = response.json()
            if not data:
                raise HTTPException(status_code=400, detail=f"Location '{location_name}' could not be resolved.")
            return float(data[0]["lat"]), float(data[0]["lon"])

    if latitude is not None and longitude is not None:
        return latitude, longitude

    raise HTTPException(status_code=400, detail="Provide either a location_name string or latitude/longitude coordinates.")


# ==================== MCP CORE TOOLS ====================

@mcp.tool()
async def get_monthly_prayer_times(location_name: str = None, latitude: float = None, longitude: float = None, month: int = None, year: int = None) -> list:
    """
    Fetches comprehensive monthly prayer times based on raw GPS coordinates or location name string text.
    Computes precise Dhuha intervals (+28 mins from Syuruk) and normalizes Hijri month texts.
    """
    lat, lon = await resolve_location(location_name, latitude, longitude)
    current_date = datetime.date.today()
    target_month = month or current_date.month
    target_year = year or current_date.year

    processed_prayers = []

    async with httpx.AsyncClient() as client:
        if is_malaysia(lat, lon):
            url = f"https://api.waktusolat.app/v2/solat/gps/{lat}/{lon}?year={target_year}&month={target_month}"
            response = await client.get(url)
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to reach Malaysian prayer API cluster node.")

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
            response = await client.get(url)
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to reach Global fallback prayer API node.")

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

    return processed_prayers


@mcp.tool()
async def find_nearest_mosques(location_name: str = None, latitude: float = None, longitude: float = None, distance_km: int = 5) -> list:
    """
    Finds verified mosques, masjids, or suraus within a target search radius.
    Injects map routing navigation strings for Google Maps and native Waze applications.
    """
    lat, lon = await resolve_location(location_name, latitude, longitude)
    mosque_list = []

    async with httpx.AsyncClient() as client:
        if is_malaysia(lat, lon):
            url = f"https://www.e-solat.gov.my/index.php?r=esolatApi/nearestMosque&lat={lat}&long={lon}&dist={distance_km}"
            response = await client.get(url)
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
            response = await client.post(overpass_url, data={"data": query}, headers=OSM_HEADERS)
            if response.status_code == 200:
                raw_data = response.json()
                for element in raw_data.get("elements", []):
                    m_lat = element.get("lat") or element.get("center", {}).get("lat")
                    m_lon = element.get("lon") or element.get("center", {}).get("lon")
                    if m_lat and m_lon:
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

    mosque_list.sort(key=lambda x: x["distance_km"])
    return mosque_list[:15]


@mcp.tool()
async def get_yearly_islamic_events(location_name: str = None, latitude: float = None, longitude: float = None, target_year: int = 2026) -> list:
    """
    Retrieves significant Islamic calendar milestones filtered tightly to a target year (Default: 2026).
    Discards historical multi-year server overhead arrays.
    """
    try:
        lat, lon = await resolve_location(location_name, latitude, longitude)
        local_route = is_malaysia(lat, lon)
    except Exception:
        local_route = True

    event_list = []

    async with httpx.AsyncClient() as client:
        if local_route:
            url = "https://www.e-solat.gov.my/index.php?r=esolatApi/islamicevent&type=all"
            response = await client.get(url)
            if response.status_code == 200:
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
            response = await client.get(url)
            if response.status_code == 200:
                raw_data = response.json()
                for item in raw_data.get("data", []):
                    greg_date = datetime.datetime.strptime(item["gregorianDate"], "%d-%m-%Y").strftime("%Y-%m-%d")
                    event_list.append({
                        "event_name": item["arahName"].strip() or item["label"].strip(),
                        "gregorian_date": greg_date,
                        "hijri_date": f"{item['hijriYear']}-{str(item['hijriMonth']).zfill(2)}-{str(item['hijriDay']).zfill(2)}"
                    })

    event_list.sort(key=lambda x: x["gregorian_date"])
    return event_list


# ==================== WEBHOOK TRANSPORT LAYER MIDDLEWARE ====================

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, JSONResponse as StarletteJSONResponse

class SecurePathAndDashboardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        expected_prefix = f"/api/webhook/{WEBHOOK_TOKEN}"

        # 1. SILENCE FAVICON NOISE: Instantly resolve browser icon requests quietly
        if path == "/favicon.ico":
            return StarletteJSONResponse(status_code=204, content=None)

        # 2. ADDRESS ROOT PATH (/) SCENARIOS
        if path == "/":
            if method == "GET":
                # Clear plain text instructions for browser visitors
                landing_text = (
                    "esolat-mcp server is up and running!\n\n"
                    "To connect, paste the full URL (including your secret /api/webhook/ token key)\n"
                    "into the connector or MCP settings of your AI/LLM client. No username or password required.\n\n"
                    "Your private browser health dashboard endpoint:\n"
                    f"http://<YOUR_IP_OR_DOMAIN>:{PORT}{expected_prefix}/\n\n"
                    "Your private AI agent connection endpoint:\n"
                    f"http://<YOUR_IP_OR_DOMAIN>:{PORT}{expected_prefix}/mcp"
                )
                return PlainTextResponse(status_code=200, content=landing_text)
            else:
                # Structured JSON error for direct programmatic client attempts
                return StarletteJSONResponse(
                    status_code=400,
                    content={"error": "This endpoint is only reachable through your secure webhook token path. For direct client configuration access, use your specific MCP secret path."}
                )

        # 3. ALLOW CORE MCP PROBES: Let standard base MCP/SSE endpoints slide through
        # so clients like Hermes can successfully probe the root application layout
        if path in ["/mcp", "/sse", "/events"]:
            return await call_next(request)

        # 4. Reject anything else attempting to access outside the authenticated token framework
        if not path.startswith(expected_prefix):
            return StarletteJSONResponse(
                status_code=401,
                content={"error": "Forbidden: Unauthorized Webhook Signature Path."}
            )

        # 5. INTERCEPT: If the user visits the exact secure path via GET (Browser lookup)
        if path.rstrip("/") == expected_prefix.rstrip("/") and method == "GET":
            current_date = datetime.date.today()
            target_month = current_date.month
            target_year = current_date.year
            # Query upstreams concurrently to assemble a live health matrix payload
            jakim_status = await check_api_status("https://www.e-solat.gov.my/index.php?r=esolatApi/islamicevent&type=all")
            waktu_status = await check_api_status(f"https://api.waktusolat.app/v2/solat/gps/3.0219423/101.791623?year={target_year}&month={target_month}")
            osm_status = await check_api_status("https://nominatim.openstreetmap.org/search?q=Kajang&format=json&limit=1", headers=OSM_HEADERS)

            return StarletteJSONResponse(status_code=200, content={
                "server": "esolat-mcp",
                "status": "ONLINE",
                "version": "1.0.0",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()[:-6] + "Z",
                "upstream_apis": {
                    "jakim_e_solat": jakim_status,
                    "waktu_solat_app": waktu_status,
                    "openstreetmap_nominatim": osm_status
                }
            })

        # 6. Standard Processing Operation: Flatten route back to target MCP application endpoints
        if path.startswith(expected_prefix):
            request.scope["path"] = path.replace(expected_prefix, "") or "/"

        return await call_next(request)

# ==================== ENTRYPOINT ====================

def main():
    """
    Dual-mode entrypoint.

    - MCP_TRANSPORT=stdio (default): runs as a local stdio subprocess,
      spawned on-demand by an MCP client (e.g. `uvx esolat-mcp` or a
      Claude Desktop / Claude Code config entry). No network port,
      no webhook token, no health dashboard - the client owns the
      process lifecycle.

    - MCP_TRANSPORT=http: runs the streamable-HTTP server behind the
      webhook-token + health-dashboard middleware, for the Docker
      deployment (Hermes, remote clients, etc.).
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
