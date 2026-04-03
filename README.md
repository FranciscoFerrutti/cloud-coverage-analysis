# Cloud Probability API

Estimates the historical probability of cloud coverage for a given date and geographic region, using multi-year Sentinel-2 satellite imagery processed via **Google Earth Engine (GEE)**.

## Overview

Given a target date and a region of interest, the system queries the `COPERNICUS/S2_CLOUD_PROBABILITY` dataset across a configurable historical range (default: 2019–2024). It filters images to a ±N day window around the target day-of-year, computes per-image cloud coverage statistics, and returns aggregate results.

The default region is **Villa Carlos Paz, Córdoba, Argentina**.

## How it works

```
Historical satellite data (5 years)
        │
        ▼
Filter by region + year range
        │
        ▼
Filter by day-of-year window (± N days)
        │
        ▼
Per image: probability band → threshold (>60) → mean over region
        │
        ▼
Aggregate: mean + std dev across all images
        │
        ▼
Rank images by distance to mean → top N
```

## Requirements

- Python 3.9+
- A Google Earth Engine account with an active project
- Dependencies:

```
earthengine-api
geemap
matplotlib
```

Install with:

```bash
pip install earthengine-api geemap matplotlib
```

## Authentication

Run once per session before using the API:

```python
import ee
ee.Authenticate()
ee.Initialize(project='your-gee-project-id')
```

## Usage

```python
from datetime import datetime
import ee
from cloud_probability_api import CloudProbabilityAPI

# Define region of interest (Villa Carlos Paz bounding box)
region = ee.Geometry.Rectangle([-64.55, -31.45, -64.35, -31.30])

# Instantiate with 5-year historical range
api = CloudProbabilityAPI(region=region, start_year=2019, end_year=2024)

target = datetime(2024, 1, 15)

# Cloud coverage statistics
prob = api.get_cloud_probability(target, window_days=15)
# → {"mean": 34.2, "std": 18.7}

# Top-5 most representative historical images
images = api.get_similar_images(target, n=5, window_days=15)
```

## API Reference

### `CloudProbabilityAPI(region, start_year=2019, end_year=2024)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `region` | `ee.Geometry` | Area of interest |
| `start_year` | `int` | Start of historical range (inclusive) |
| `end_year` | `int` | End of historical range (inclusive) |

---

### `get_cloud_probability(target_date, window_days=15)`

Returns mean and standard deviation of cloud coverage (%) for the target day-of-year, computed from all historical images within ±`window_days`.

```python
{"mean": float, "std": float}
```

---

### `get_similar_images(target_date, n=5, window_days=15)`

Returns the N historical images whose cloud coverage is closest to the expected mean. Each entry contains standard GEE image metadata plus a `cloud_percentage` property.

---

### `visualize(target_date, n=1, window_days=15)` *(bonus)*

Returns an interactive `geemap.Map` displaying the most representative image(s) with a green–yellow–red cloud probability colour scale.

---

### `plot_time_series(target_date, window_days=15)` *(bonus)*

Renders a matplotlib chart of cloud coverage over time for all images in the window, with mean and ±1 std dev bands overlaid.

## Dataset

| Property | Value |
|----------|-------|
| Source | `COPERNICUS/S2_CLOUD_PROBABILITY` |
| Sensor | Sentinel-2 (ESA) |
| Band | `probability` (0–100 per pixel) |
| Resolution | 10–20 m native / 100 m for statistics |
| Coverage | Global |

A pixel is classified as cloudy when its probability value exceeds **60**.

## Project structure

```
.
├── cloud_probability_api.py   # Main implementation
├── demo.ipynb                 # Interactive demo notebook (Colab-ready)
└── docs/
    ├── PROJECT_CONTEXT.md
    ├── API_DESIGN.md
    ├── DATA_PIPELINE.md
    ├── TECH_STACK.md
    ├── COLAB_SETUP.md
    └── GEOSPATIAL_SETUP.md
```
