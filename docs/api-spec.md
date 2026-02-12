# MODSNOW API - Snow Cover Data Receiver

## Overview

REST API endpoint that receives daily MODIS snow cover analysis (SCA) data for 10 catchments in Central Asia. Data is sent once per day by the MODSNOW pipeline via `POST` request.

---

## Authentication

All requests must include a Bearer token in the `Authorization` header.

```
Authorization: Bearer <API_KEY>
```

If the token is missing or invalid, the server must return `401 Unauthorized`.

---

## Endpoint

### `POST /api/snow-cover`

Receives snow cover data for a single date.

#### Headers

| Header          | Required | Value                      |
|-----------------|----------|----------------------------|
| Content-Type    | Yes      | `application/json`         |
| Authorization   | Yes      | `Bearer <API_KEY>`         |

#### Request Body

```json
{
  "date": "2026-02-09",
  "resource_date": "2026-02-06",
  "catchments": [
    {
      "name": "Chirchik",
      "sca_pct": 99.49,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 83.49},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 96.63},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 100.0},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 100.0},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0},
        {"min_elev": 3500, "max_elev": 4000, "sca_pct": 100.0}
      ]
    }
  ]
}
```

#### Successful Response

```
HTTP/1.1 200 OK
```

```json
{
  "status": "ok"
}
```

#### Error Responses

| Code | When                              |
|------|-----------------------------------|
| 400  | Invalid JSON or missing fields    |
| 401  | Missing or invalid Bearer token   |
| 409  | Data for this date already exists |
| 500  | Internal server error             |

---

## Data Models

### Request: `SnowCoverPayload`

| Field           | Type              | Required | Description                                      |
|-----------------|-------------------|----------|--------------------------------------------------|
| `date`          | `string`          | Yes      | Request date in `YYYY-MM-DD` format              |
| `resource_date` | `string`          | Yes      | MODIS resource date in `YYYY-MM-DD` (`date` − 3 days) |
| `catchments`    | `Catchment[]`     | Yes      | Array of 10 catchments                           |

### `Catchment`

| Field     | Type          | Required | Description                           |
|-----------|---------------|----------|---------------------------------------|
| `name`    | `string`      | Yes      | Catchment name (see list below)       |
| `sca_pct` | `float\|null` | Yes      | Total SCA %, 0.00-100.00. `null` if no valid pixels |
| `zones`   | `Zone[]`      | Yes      | Elevation zones (500m step). Empty `[]` if no DEM data |

### `Zone`

| Field      | Type          | Required | Description                      |
|------------|---------------|----------|----------------------------------|
| `min_elev` | `int`         | Yes      | Zone lower bound, meters (inclusive) |
| `max_elev` | `int`         | Yes      | Zone upper bound, meters (exclusive) |
| `sca_pct`  | `float\|null` | Yes      | SCA % for this zone              |

---

## Catchment Names (10 active)

| Name                  | River basin              |
|-----------------------|--------------------------|
| `Chirchik`            | Chirchik                 |
| `Naryn`               | Naryn                    |
| `Ugam`                | Ugam                     |
| `Ahangaran_Irtash`    | Ahangaran (Irtash gauge) |
| `piskem_mullala`      | Piskem (Mullala gauge)   |
| `Tupalang_zarchob`    | Tupalang (Zarchob gauge) |
| `Zerafshan_Dupuli`    | Zerafshan (Dupuli gauge) |
| `Chatkal_Hudaydodsay` | Chatkal (Hudaydodsay)    |
| `Karadaryo_Andijan`   | Karadaryo (Andijan)      |
| `Akdarya_Gissarak`    | Akdarya (Gissarak)       |

---

## Full Example

### Request

```http
POST /api/snow-cover HTTP/1.1
Host: example.com
Content-Type: application/json
Authorization: Bearer sk-modsnow-abc123def456

{
  "date": "2026-02-09",
  "resource_date": "2026-02-06",
  "catchments": [
    {
      "name": "Chirchik",
      "sca_pct": 99.49,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 83.49},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 96.63},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 100.0},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 100.0},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0},
        {"min_elev": 3500, "max_elev": 4000, "sca_pct": 100.0}
      ]
    },
    {
      "name": "Naryn",
      "sca_pct": 87.23,
      "zones": [
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 45.12},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 72.88},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 91.34},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 98.76},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0},
        {"min_elev": 3500, "max_elev": 4000, "sca_pct": 100.0},
        {"min_elev": 4000, "max_elev": 4500, "sca_pct": 100.0}
      ]
    },
    {
      "name": "Ugam",
      "sca_pct": 95.61,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 70.25},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 94.80},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 100.0},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 100.0},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0}
      ]
    },
    {
      "name": "Ahangaran_Irtash",
      "sca_pct": 92.14,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 58.33},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 89.71},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 99.12},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 100.0},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0}
      ]
    },
    {
      "name": "piskem_mullala",
      "sca_pct": 97.82,
      "zones": [
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 88.15},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 99.44},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 100.0},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0}
      ]
    },
    {
      "name": "Tupalang_zarchob",
      "sca_pct": 88.56,
      "zones": [
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 52.40},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 78.93},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 95.67},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0}
      ]
    },
    {
      "name": "Zerafshan_Dupuli",
      "sca_pct": 91.07,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 41.28},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 76.54},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 93.21},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 99.85},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0},
        {"min_elev": 3500, "max_elev": 4000, "sca_pct": 100.0}
      ]
    },
    {
      "name": "Chatkal_Hudaydodsay",
      "sca_pct": 96.33,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 65.47},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 92.18},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 99.73},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 100.0},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0},
        {"min_elev": 3500, "max_elev": 4000, "sca_pct": 100.0}
      ]
    },
    {
      "name": "Karadaryo_Andijan",
      "sca_pct": 85.41,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 33.12},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 68.90},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 90.54},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 98.22},
        {"min_elev": 2500, "max_elev": 3000, "sca_pct": 100.0},
        {"min_elev": 3000, "max_elev": 3500, "sca_pct": 100.0}
      ]
    },
    {
      "name": "Akdarya_Gissarak",
      "sca_pct": 78.92,
      "zones": [
        {"min_elev": 500, "max_elev": 1000, "sca_pct": 21.56},
        {"min_elev": 1000, "max_elev": 1500, "sca_pct": 64.83},
        {"min_elev": 1500, "max_elev": 2000, "sca_pct": 92.17},
        {"min_elev": 2000, "max_elev": 2500, "sca_pct": 100.0}
      ]
    }
  ]
}
```

### Response

```http
HTTP/1.1 200 OK
Content-Type: application/json

{"status": "ok"}
```

---

## Behavior Notes

- The pipeline sends data **once per day**, typically at 00:00 UTC. `date` is the request date, `resource_date` is `date − 3 days` (MODIS data delay).
- If the server is unavailable, the client retries **3 times** with exponential backoff (2s, 4s, 8s) and then stops. Data is preserved locally for manual retry.
- The `sca_pct` field can be `null` when a catchment has no valid MODIS pixels (e.g. persistent cloud cover despite gap-filling).
- Elevation zones use a **500m step**. The set of zones varies per catchment depending on its elevation range. Zones are always sorted ascending by `min_elev`.
- Catchment names are **case-sensitive** and match exactly as listed above.
- Data source: MODIS MOD10A1F v61 (Cloud-Gap-Filled NDSI Snow Cover, 500m resolution).
