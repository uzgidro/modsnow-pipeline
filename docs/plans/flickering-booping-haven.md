# ERA5-Land Snow Depth Integration

## Context

The existing pipeline calculates Snow Cover Area (SCA %) from MODIS satellite imagery at 500m resolution. The user wants to add snow depth (meters) per catchment using ERA5-Land reanalysis data (~9 km / 0.1° grid). This will be a complementary metric — coarser but provides depth information that MODIS cannot.

ERA5-Land variables:
- `snow_depth` (`sde`, paramId 3066) — snow depth in **meters**
- Data is on a regular 0.1° x 0.1° lat/lon grid (no reprojection needed)
- Latency: ~5 days behind real-time (similar to MODIS `days_behind`)
- CDS API credentials already in `config/.cdsapirc`

## Files to Create

### 1. `download_era5.py` — ERA5-Land snow depth downloader

Downloads a single day's snow depth for the Central Asia bbox via CDS API.

```python
def download_snow_depth(
    date_str: str,              # "2026-02-07"
    download_dir: str = "era5_data",
    bbox: tuple = (55, 33, 85, 50),   # (west, south, east, north) — same as config
    cdsapirc_path: str = "config/.cdsapirc",
) -> Path:
```

- Parse `.cdsapirc` to get `url` and `key`, create `cdsapi.Client(url=..., key=...)`
- CDS `area` param format: `[north, west, south, east]` — transform from our bbox `(west, south, east, north)`
- Request: `reanalysis-era5-land`, variable `snow_depth`, single day, time `12:00` (midday snapshot)
- Format: NetCDF
- Save to `era5_data/{date_str}/snow_depth.nc`
- Return Path to the NC file

### 2. `process_era5.py` — Snow depth per catchment

Computes mean snow depth for each active catchment from the ERA5-Land NetCDF.

```python
def process_snow_depth(nc_path: str, data_dir: str = "data") -> dict:
```

- Read NetCDF with `netCDF4` (already a dependency): lat, lon, `sde` arrays
- Load catchments from `data/ca_catchments.shp` (PROCESS=1), same as `process_modis.py`
- For each catchment:
  - Get bounding box of polygon
  - Select ERA5 grid cells within bbox
  - Test which cells' centers fall inside the polygon (shapely `contains`)
  - Compute mean snow depth (meters) over matching cells
- Return `dict[name, float]` — e.g. `{"Chirchik": 0.42, "Naryn": 0.15}`

No CRS transformation needed — ERA5-Land is already in WGS84 lat/lon, same as catchments.

## Files to Modify

### 3. `run.py` — Integrate ERA5 into pipeline

In `run_pipeline()`, after MODIS processing (step 2), add ERA5 step:

```python
# 2b. ERA5 Snow Depth (optional, non-blocking)
snow_depth_map = {}
try:
    from download_era5 import download_snow_depth
    from process_era5 import process_snow_depth

    nc_path = download_snow_depth(
        date_str=resource_date_str,
        download_dir=paths_cfg.get("era5_dir", "era5_data"),
        bbox=tuple(modis_cfg.get("bbox", [55, 33, 85, 50])),
    )
    snow_depth_map = process_snow_depth(str(nc_path), data_dir=paths_cfg.get("data_dir", "data"))
except Exception as e:
    logger.warning("ERA5 snow depth unavailable: %s", e)
```

Then enrich results before sending:

```python
for r in results:
    r["snow_depth_m"] = snow_depth_map.get(r["name"])
```

Key: ERA5 failure must NOT block the MODIS pipeline. Wrapped in try/except, `snow_depth_m` will be `None` if unavailable.

### 4. `config/config.yaml` — Add ERA5 section

```yaml
era5:
  enabled: true
  days_behind: 5     # ERA5-Land latency
```

### 5. `config/config.yaml.example` — Same addition

### 6. `requirements.txt` — Add cdsapi

```
cdsapi>=0.7
```

### 7. `Dockerfile` — Add cdsapi to pip install

## Output Payload (updated)

```json
{
  "date": "2026-02-12",
  "resource_date": "2026-02-07",
  "catchments": [
    {
      "name": "Chirchik",
      "sca_pct": 99.49,
      "snow_depth_m": 0.42,
      "zones": [...]
    }
  ]
}
```

`snow_depth_m` = `null` if ERA5 data unavailable for that catchment/date.

## Verification

1. `python download_era5.py 2026-02-05` — test standalone download
2. `python process_era5.py era5_data/2026-02-05/snow_depth.nc` — test standalone processing
3. `python run.py 2026-02-12` — full pipeline with both MODIS + ERA5
4. Check output payload includes `snow_depth_m` values
