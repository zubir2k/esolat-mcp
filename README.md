# esolat-mcp

MCP server providing Malaysian/global prayer times (JAKIM + Aladhan fallback),
nearest mosque/surau finder, and Islamic calendar events.

## Tools

- `get_monthly_prayer_times` - monthly prayer schedule with Hijri dates and Dhuha times
- `find_nearest_mosques` - nearby mosques/suraus with Google Maps / Waze links
- `get_yearly_islamic_events` - Islamic calendar milestones for a given year

## Running

### Local / stdio (uvx, Claude Desktop, Claude Code)

From a local clone:

```bash
uvx --from . esolat-mcp
```

Directly from GitHub (no local clone needed):

```bash
uvx --from git+https://github.com/zubir2k/esolat-mcp esolat-mcp
```

Or point an MCP client config at either of the above:

```json
{
  "mcpServers": {
    "esolat": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/zubir2k/esolat-mcp", "esolat-mcp"]
    }
  }
}
```

In stdio mode there's no webhook token, port, or health dashboard - the
client owns the process and talks to it directly.

### Docker / remote HTTP

1. Copy `.env.example` to `.env` and set your own webhook token:

   ```bash
   cp .env.example .env
   ```

   Generate a strong random token with any of these:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   openssl rand -hex 32
   ```

   Paste the result into `.env` as `MCP_WEBHOOK_TOKEN=...`. Treat this like
   a password - `.env` is gitignored and should never be committed.

2. Build and start the container:

   ```bash
   docker build -t esolat-mcp:latest .
   docker compose up -d
   ```

3. The server exposes a webhook-token-secured streamable HTTP endpoint at:

   ```
   http://<host>:8626/api/webhook/<MCP_WEBHOOK_TOKEN>/mcp
   ```

   Visiting `http://<host>:8626/api/webhook/<MCP_WEBHOOK_TOKEN>` (GET, no
   `/mcp` suffix) returns a small JSON health dashboard showing the status
   of the upstream JAKIM / Waktu Solat / OpenStreetMap APIs.
