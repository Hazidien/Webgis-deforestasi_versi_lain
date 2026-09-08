from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

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
        REPORTS[report_id] = build_report(result)
        if len(REPORTS) > 20:
            REPORTS.pop(next(iter(REPORTS)))
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
    pdf = REPORTS.get(report_id)
    if pdf is None:
        raise HTTPException(status_code=404, detail="Report expired or was not found.")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="deforestation_report.pdf"'},
    )


# Serve the complete Leaflet WebGIS frontend from the same port as the API.
# API routes above remain available because they are registered before this mount.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
