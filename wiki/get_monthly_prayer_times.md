# 🕌 Tool: `get_monthly_prayer_times`

Fetches the complete prayer schedule for a given month and location, sourced from JAKIM via the Aladhan API. Includes all seven daily prayer times plus the auto-computed Dhuha time, with full Hijri date for each day.

---

## Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `location_name` | string | Optional* | Plain-text location, e.g. `"Kajang, Selangor"` |
| `latitude` | number | Optional* | GPS latitude coordinate |
| `longitude` | number | Optional* | GPS longitude coordinate |
| `month` | integer | Optional | Month number (1–12). Defaults to current month. |
| `year` | integer | Optional | Gregorian year. Defaults to current year. |

> *Provide either `location_name` **or** a `latitude`/`longitude` pair. Both methods are supported.

---

## Response

Returns an array of daily prayer time objects for every day in the requested month.

### Fields Per Day

| Field | Type | Description |
|---|---|---|
| `date` | string | Gregorian date (YYYY-MM-DD) |
| `day_name` | string | Day of the week |
| `hijri_raw` | string | Hijri date in YYYY-MM-DD format |
| `hijri_full` | string | Human-readable Hijri date, e.g. `17 Muharram 1448` |
| `fajr` | string | Subuh time (UTC ISO 8601) |
| `syuruk` | string | Sunrise time (UTC ISO 8601) |
| `dhuha` | string | Dhuha time — Syuruk + 28 minutes (UTC ISO 8601) |
| `dhuhr` | string | Zohor time (UTC ISO 8601) |
| `asr` | string | Asar time (UTC ISO 8601) |
| `maghrib` | string | Maghrib time (UTC ISO 8601) |
| `isha` | string | Isyak time (UTC ISO 8601) |

### Example Response (single day)

```json
{
  "date": "2026-07-03",
  "day_name": "Friday",
  "hijri_raw": "1448-01-17",
  "hijri_full": "17 Muharram 1448",
  "fajr":    "2026-07-02T21:55:00Z",
  "syuruk":  "2026-07-02T23:08:00Z",
  "dhuha":   "2026-07-02T23:36:00Z",
  "dhuhr":   "2026-07-03T05:20:00Z",
  "asr":     "2026-07-03T08:46:00Z",
  "maghrib": "2026-07-03T11:29:00Z",
  "isha":    "2026-07-03T12:45:00Z"
}
```

> ℹ️ All times are in **UTC**. Add `+08:00` for MYT. For example, `05:20 UTC` = `13:20 MYT` (Zohor).

---

## Notes

- **Dhuha** is not returned by the Aladhan API directly. It is automatically computed by this server as **Syuruk + 28 minutes**.
- Prayer times are **location-specific**. The same state may yield slightly different results depending on exact coordinates.
- The Hijri date shown follows **JAKIM's official calendar** for Malaysia.

---

## Example Queries

> *"What time is Subuh tomorrow in Putrajaya?"*
> *"Give me this week's full prayer schedule for Johor Bahru."*
> *"When is Maghrib on the 15th of this month?"*
> *"What are the prayer times for Ramadan this year in Kuala Lumpur?"*

---

## Related Tools

- [`get_current_time`](get_current_time) — use first to get current UTC before comparing with prayer times
- [`get_yearly_islamic_events`](get_yearly_islamic_events) — to identify which month Ramadan or other events fall in
