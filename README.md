# esolat-mcp

MCP server providing Malaysian/global prayer times (JAKIM + Aladhan fallback),
nearest mosque/surau finder, and Islamic calendar events.

## Tools

- `get_monthly_prayer_times` - monthly prayer schedule with Hijri dates and Dhuha times
- `find_nearest_mosques` - nearby mosques/suraus with Google Maps / Waze links
- `get_yearly_islamic_events` - Islamic calendar milestones for a given year

## Running

### Local / stdio (uvx, Claude Desktop, Claude Code)

```bash
uvx --from . esolat-mcp
```

Or point an MCP client config at it directly:

```json
{
  "mcpServers": {
    "esolat": {
      "command": "uvx",
      "args": ["--from", "/path/to/esolat-local", "esolat-mcp"]
    }
  }
}
```

### Docker / remote HTTP

```bash
docker compose up -d
```

Exposes a webhook-token-secured streamable HTTP endpoint at
`http://<host>:8626/api/webhook/<MCP_WEBHOOK_TOKEN>/mcp`.
