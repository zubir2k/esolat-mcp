# 🕐 Tool: `get_current_time`

Returns the current UTC server timestamp. This is the **anchor tool** — use it first whenever a query involves comparing "now" against prayer times.

---

## Parameters

This tool takes **no parameters**.

---

## Response

| Field | Type | Description |
|---|---|---|
| `current_time_utc` | string | Current time in UTC (ISO 8601 format) |
| `source` | string | Always `"server"` |

### Example Response

```json
{
  "current_time_utc": "2026-07-03T14:20:38Z",
  "source": "server"
}
```

> ℹ️ To convert to **Malaysia Standard Time (MYT)**, add `+08:00` to the UTC value.
> `14:20 UTC` → `22:20 MYT`

---

## When to Use

Use `get_current_time` **before** calling [`get_monthly_prayer_times`](get_monthly_prayer_times) whenever the query involves:

- *"Which prayer is next?"*
- *"Am I still in time for Zohor?"*
- *"How many minutes until Maghrib?"*
- *"Is it currently a valid time for Dhuha?"*

By fetching the current UTC time first, the AI assistant can accurately compare it against prayer times and give a precise, real-time answer.

---

## Related Tools

- [`get_monthly_prayer_times`](get_monthly_prayer_times) — fetch the prayer schedule to compare against current time
