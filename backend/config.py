from pathlib import Path
import os

import ee
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PROJECT_ID = os.getenv("GEE_PROJECT_ID", "").strip()
CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()


def initialize_gee() -> None:
    """Initialize Earth Engine with a service-account key configured in .env."""
    if not PROJECT_ID:
        raise RuntimeError("GEE_PROJECT_ID is not configured.")
    if not CREDENTIALS:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not configured.")
    if not Path(CREDENTIALS).is_file():
        raise RuntimeError("GEE credential file was not found at the configured path.")
    try:
        credentials = ee.ServiceAccountCredentials(None, CREDENTIALS)
        ee.Initialize(credentials=credentials, project=PROJECT_ID)
    except Exception as exc:  # pragma: no cover - depends on remote EE auth
        raise RuntimeError(f"Google Earth Engine authentication failed: {exc}") from exc
