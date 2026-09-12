from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.modules.deforestation.forest import analyze_deforestation
from backend.modules.ndfi_change.analysis import analyze_ndfi_change
from backend.report import build_report

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="GeoAI Deforestation WebGIS", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

REPORTS: dict[str, bytes] = {}
REPORT_RESULTS: dict[str, dict] = {}
GEOTIFF_URLS: dict[str, str] = {}


class AnalysisRequest(BaseModel):
    # Exactly one module is selected for each request. The backend dispatches
    # only that engine; it never executes both analysis methods in one run.
    module: Literal["deforestation", "ndfi_change"] = "deforestation"
    aoi: dict = Field(...)
    # NDFI uses exactly two user-facing observation dates. The backend expands
    # them into one-year centered compositing windows.
    time0_date: str | None = None
    time1_date: str | None = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze(request: AnalysisRequest) -> dict:
    if request.aoi.get("type") not in {"Polygon", "MultiPolygon"}:
        raise HTTPException(
            status_code=400,
            detail="AOI must be a GeoJSON Polygon or MultiPolygon.",
        )

    try:
        payload = request.model_dump()

        if request.module == "deforestation":
            # Only the forest-extent engine is executed for this request.
            result = analyze_deforestation(payload)
        else:
            # Only the SMA/NDFI engine is executed for this request.
            result = analyze_ndfi_change(payload)

        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        report_id = uuid4().hex

        # Keep the Earth Engine download URL server-side and expose a local
        # endpoint. This makes the browser download a real attachment instead
        # of navigating to an expiring/cross-origin Earth Engine URL.
        geotiff_url = result.get("geotiff_url")
        if geotiff_url:
            GEOTIFF_URLS[report_id] = geotiff_url
            result["geotiff_url"] = f"/api/geotiff/{report_id}"

        # IMPORTANT: do not download the PDF map image here. The analysis
        # response must return as soon as the original GEE analysis finishes.
        # The map thumbnail is downloaded only when the user opens the PDF.
        # This prevents a slow thumbnail request from making /api/analyze
        # return an empty/timeout response in Codespaces for large AOIs.
        REPORT_RESULTS[report_id] = dict(result)

        if len(REPORTS) > 20:
            REPORTS.pop(next(iter(REPORTS)))
        if len(REPORT_RESULTS) > 20:
            REPORT_RESULTS.pop(next(iter(REPORT_RESULTS)))
        if len(GEOTIFF_URLS) > 20:
            GEOTIFF_URLS.pop(next(iter(GEOTIFF_URLS)))

        result.pop("map_image_url", None)
        result["report_url"] = f"/api/report/{report_id}"
        return result
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"GEE processing failed: {exc}",
        ) from exc


@app.get("/api/report/{report_id}")
def report(report_id: str) -> Response:
    cached_pdf = REPORTS.get(report_id)
    if cached_pdf is not None:
        return Response(
            content=cached_pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="deforestation_report.pdf"'},
        )

    result = REPORT_RESULTS.get(report_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Report expired or was not found.")

    # Generate the report lazily so the expensive thumbnail download cannot
    # block the analysis endpoint. If the thumbnail is unavailable, report.py
    # still creates the PDF and states that the map image was unavailable.
    report_result = dict(result)
    map_image_url = report_result.get("map_image_url")
    if map_image_url:
        try:
            image_request = Request(
                map_image_url,
                headers={"User-Agent": "GeoAI-Deforestation-WebGIS/1.0"},
            )
            with urlopen(image_request, timeout=120) as upstream:
                report_result["map_image_bytes"] = upstream.read()
        except Exception:
            report_result["map_image_bytes"] = None

    try:
        pdf = build_report(report_result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc

    REPORTS[report_id] = pdf
    REPORT_RESULTS.pop(report_id, None)

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="deforestation_report.pdf"'},
    )


@app.get("/api/geotiff/{report_id}")
def geotiff(report_id: str) -> Response:
    url = GEOTIFF_URLS.get(report_id)
    if not url:
        raise HTTPException(status_code=404, detail="GeoTIFF download expired or was not found.")

    try:
        request = Request(url, headers={"User-Agent": "GeoAI-Deforestation-WebGIS/1.0"})
        with urlopen(request, timeout=120) as upstream:
            data = upstream.read()
            content_type = upstream.headers.get("Content-Type", "image/tiff")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Earth Engine GeoTIFF download failed: {exc}") from exc

    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": 'attachment; filename="geoai_deforestation.tif"'},
    )


# Serve the complete Leaflet WebGIS frontend from the same port as the API.
# API routes above remain available because they are registered before this mount.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
