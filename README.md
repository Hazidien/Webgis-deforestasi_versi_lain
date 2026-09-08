# GeoAI Deforestation WebGIS

WebGIS deforestation built around the supplied Google Earth Engine workflow, using the UI/UX pattern of `Hazidien/tes-geoai-polusi` and an evidence-first remote-sensing workflow.

## Features
- Draw polygon/rectangle AOI with Leaflet-Geoman.
- Upload Shapefile ZIP (`.shp + .shx + .dbf + .prj`).
- Benchmark years: 1990, 1995, 2000, 2005, 2010, 2015, 2020.
- Landsat 4/5 before 2014 and Landsat 8/9 from 2014 onward.
- Supplied QA_PIXEL masks, ±1-year median composites, VI formula, `VI > 0.7`, hectare area calculation and 90 m area-chart scale are retained.
- Forest-year map, benchmark layers, area chart, PDF report and GeoTIFF download URL.

## Architecture
```text
Leaflet + Geoman + shp.js
          │
          ▼
 FastAPI /api/analyze
          │
          ▼
backend/modules/deforestation/forest.py
          │
          ▼
 Google Earth Engine
          │
     ┌────┴────┐
     ▼         ▼
 map tiles  area series
     └────┬────┘
          ▼
      WebGIS UI
       │       │
       ▼       ▼
      PDF    GeoTIFF
```

## Run in Codespaces
1. Copy `.env.example` to `.env`; set `GEE_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS` to a Google Earth Engine service-account JSON path. Never commit the key.
2. `pip install -r requirements.txt`
3. `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
4. Open forwarded port **8000**.

## Scientific note
This is a remote-sensing screening workflow, not a certified land-cover product. High VI can be affected by seasonality, drought, harvest, residual cloud/shadow, mixed pixels and edge effects. Validate outputs before formal reporting.
