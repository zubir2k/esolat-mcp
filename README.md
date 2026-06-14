![eSolatMCP](https://github.com/user-attachments/assets/622ae01a-4437-4dab-aec0-8e92d77e6b55)

[![GitHub Repo stars](https://img.shields.io/github/stars/zubir2k/esolat-mcp?style=social)](https://github.com/zubir2k/esolat-mcp/stargazers)
![MCP](https://img.shields.io/badge/MCP-Compatible-blue)
![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Docker](https://img.shields.io/badge/Docker-Supported-blue)
[![Buy](https://img.shields.io/badge/Belanja-Coffee-yellow.svg)](https://zubirco.de/buymecoffee)

**MCP server for accurate Malaysian prayer times (official JAKIM/e-Solat), nearest masjid and surau, and Islamic calendar events.**

Gives AI assistants like **Claude Desktop** and **Claude Code** reliable, hallucination-free access to Islamic worship tools with smart Malaysia-first routing.

## Features

- **Official JAKIM data** for Malaysia (via `Waktusolat.app API`)
- **Dhuha time** automatically calculated (+28 minutes after Syuruk)
- **Malay Hijri month names** (Muharram, Safar, etc.)
- **Global fallback** using Aladhan API
- **Nearest mosques/suraus** with Google Maps + Waze deep links
- **Yearly Islamic events** (Eid, etc.)
- Dual mode: **Local (stdio)** + **Remote (Docker + secure HTTP)**
- Health dashboard for upstream APIs

## Tools

The server registers three powerful tools that Claude can discover and call automatically:

1. **`get_monthly_prayer_times`**
   - Get full monthly prayer schedule (Fajr, Syuruk, Dhuha, Dhuhr, Asr, Maghrib, Isha)
   - Accepts place name or latitude/longitude
   - Returns both Gregorian and Hijri dates

2. **`find_nearest_mosques`**
   - Find up to 15 nearest mosques/suraus
   - Default radius: 5 km (configurable)
   - Malaysia uses official e-Solat data; global uses OpenStreetMap
   - Includes distance, coordinates, Google Maps & Waze links

3. **`get_yearly_islamic_events`**
   - Major Islamic dates and holidays for a given year
   - Malaysia-aware routing

## Quick Start

### Option 1: Local / Stdio Mode (Recommended for Claude Desktop)

**No clone needed:**
```bash
uvx --from git+https://github.com/zubir2k/esolat-mcp esolat-mcp
```

**Claude Desktop config example:**
```JSON
{
  "mcpServers": {
    "esolat": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/zubir2k/esolat-mcp", "esolat-mcp"]
    }
  }
}
```

### Option 2: Docker / Remote HTTP Mode (Self-hosted)

**1. Clone the repo and set up token:**
```Bash
git clone https://github.com/zubir2k/esolat-mcp.git
cd esolat-mcp
cp .env.example .env
```

**2. Generate a strong token:**
```Bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# or: openssl rand -hex 32
```

**3. Paste it into `.env` as `MCP_WEBHOOK_TOKEN=your_token_here`**

**4. Build and Start the container:**
```Bash
docker build -t esolat-mcp:latest .
docker compose up -d
```
**5. Endpoints**

**- Streamable MCP HTTP Endpoint (main one for AI clients):**
```
http://your-server-ip:8626/api/webhook/<MCP_WEBHOOK_TOKEN>/mcp
```
**- Health Dashboard (useful for monitoring):**
```
http://your-server-ip:8626/api/webhook/<MCP_WEBHOOK_TOKEN>
```
(GET request without /mcp — shows status of JAKIM, Aladhan, and Overpass APIs)

> [!Caution]
> Always keep your `MCP_WEBHOOK_TOKEN` secret. \
> The token is part of the URL path for simple authentication. \
> You can change the port via the `PORT` environment variable. \
> For production, consider using a reverse proxy (Nginx/Cloudflare) with HTTPS.

## Usage Examples (Claude)
### Prayer Times

_"What are today's prayer times in Kuala Lumpur?" \
"Show me full prayer schedule for Penang this Ramadan." \
"Prayer times for Kota Kinabalu next week."_

### Mosques

_"Find the nearest mosque to me." \
"Mosques within 10km of Petaling Jaya." \
"Nearest surau from KLCC."_

### Events & Planning

_"Major Islamic events in 2026 for Malaysia." \
"Plan my trip to Johor Bahru: prayer times + nearest mosques + Eid dates."_

## Visual
### Claude Config
![ClaudeConfig](https://github.com/user-attachments/assets/e29e9fd0-c549-41d3-87a9-9dbde2717819)

### Claude Prompt
![ClaudePrompt](https://github.com/user-attachments/assets/506e0d46-2b71-43ea-872b-f30839db36a6)

## Credits

- [e-solat](https://www.e-solat.gov.my/) JAKIM - For the official prayer times
- [WaktuSolat.app](https://waktusolat.app/) - Prayer Time by GPS
- [Model Context Protocol](https://modelcontextprotocol.io/) - For the MCP framework

## License

This project is licensed under the MIT License.

## Disclaimer & Data Source

### Important Notice & Reliability Disclaimer
This integration pulls data directly from the official **e-Solat JAKIM (Department of Islamic Development Malaysia)** portal. However, please note:

- **No Liability:** This integration is a community-driven project provided "as is" without any guarantees. The maintainer is **not solely or legally responsible** for any discrepancies, inaccuracies, delays, or omissions in prayer times or calendar dates.
- **Verify Important Times:** Users are strictly advised to regularly check and verify times against the official **[JAKIM eSolat Portal](https://www.e-solat.gov.my/)** or official local announcements, especially for critical obligations (e.g., fasting, community prayers).
- **Network & Upstream Dependencies:** Synchronization depends on upstream API availability and local network connectivity. Discrepancies caused by unexpected server updates from JAKIM or local server downtime are outside the control of this software.

*By using this tool, you acknowledge and agree that the developer holds no liability for missed schedules or data inaccuracies.*
