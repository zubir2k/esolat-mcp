# 📅 Tool: `get_yearly_islamic_events`

Returns significant Islamic calendar milestones for a given year in both Gregorian and Hijri dates, based on **JAKIM's official Malaysian Islamic calendar**.

---

## Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `location_name` | string | Optional* | Plain-text location, e.g. `"Kuala Lumpur"` |
| `latitude` | number | Optional* | GPS latitude coordinate |
| `longitude` | number | Optional* | GPS longitude coordinate |
| `target_year` | integer | Optional | Gregorian year. Defaults to current year. |

> *Provide either `location_name` **or** a `latitude`/`longitude` pair.

---

## Response

Returns a list of Islamic event objects for the requested year.

### Fields Per Event

| Field | Type | Description |
|---|---|---|
| `event_name` | string | Name of the Islamic event (in Malay) |
| `gregorian_date` | string | Gregorian date (YYYY-MM-DD) |
| `hijri_date` | string | Hijri date (YYYY-MM-DD) |

### Example Response

```json
[
  { "event_name": "Israk dan Mikraj",          "gregorian_date": "2026-01-17", "hijri_date": "1447-07-27" },
  { "event_name": "Awal Ramadan/Berpuasa",      "gregorian_date": "2026-02-19", "hijri_date": "1447-09-01" },
  { "event_name": "Nuzul al-Quran",             "gregorian_date": "2026-03-07", "hijri_date": "1447-09-17" },
  { "event_name": "Hari Raya Puasa/Aidilfitri", "gregorian_date": "2026-03-21", "hijri_date": "1447-10-01" },
  { "event_name": "Awal Zulhijah",              "gregorian_date": "2026-05-18", "hijri_date": "1447-12-01" },
  { "event_name": "Hari Raya Korban/Aidiladha", "gregorian_date": "2026-05-27", "hijri_date": "1447-12-10" },
  { "event_name": "Awal Muharam/ Maal Hijrah",  "gregorian_date": "2026-06-17", "hijri_date": "1448-01-01" },
  { "event_name": "Maulidur Rasul",             "gregorian_date": "2026-08-25", "hijri_date": "1448-03-12" }
]
```

---

## Events Covered

| Event | Description |
|---|---|
| **Israk dan Mikraj** | The Prophet's Night Journey — 27 Rejab |
| **Awal Ramadan / Berpuasa** | First day of fasting — 1 Ramadan |
| **Nuzul al-Quran** | Revelation of the Quran — 17 Ramadan |
| **Hari Raya Aidilfitri** | End of Ramadan celebration — 1 Syawal |
| **Awal Zulhijah** | Beginning of the month of Hajj — 1 Zulhijah |
| **Hari Raya Aidiladha** | Feast of Sacrifice — 10 Zulhijah |
| **Awal Muharam / Maal Hijrah** | Islamic New Year — 1 Muharram |
| **Maulidur Rasul** | Birthday of the Prophet ﷺ — 12 Rabi'ul Awwal |

---

## Notes

- Dates follow **JAKIM's official rukyah (moonsighting) calendar** for Malaysia and may differ from astronomical calculation-based calendars used in other countries.
- This tool is ideal for **annual planning** — public holidays, leave scheduling, and event reminders.

---

## Example Queries

> *"When does Ramadan start this year?"*
> *"What Islamic public holidays are coming up?"*
> *"When is Hari Raya Aidiladha? I need to book my flights."*
> *"What is today's Hijri date equivalent?"*

---

## Related Tools

- [`get_monthly_prayer_times`](get_monthly_prayer_times) — once you know which month an event falls in, fetch detailed prayer times for that month
