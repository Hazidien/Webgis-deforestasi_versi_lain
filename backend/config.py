from __future__ import annotations

import json
import os
from pathlib import Path

import ee
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PROJECT_ID = os.getenv("GEE_PROJECT_ID", "").strip()
CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
SERVICE_ACCOUNT = os.getenv("GEE_SERVICE_ACCOUNT", "").strip()


def initialize_gee() -> None:
    """Initialize Earth Engine using a service account key or persistent OAuth/ADC credentials."""
    if not PROJECT_ID:
        raise RuntimeError(
            "GEE_PROJECT_ID is not configured. Add your registered Earth Engine Cloud project ID to .env."
        )

    try:
        if CREDENTIALS:
            credential_path = Path(CREDENTIALS)
            if not credential_path.is_file():
                raise RuntimeError(
                    f"GEE credential file was not found at: {credential_path}"
                )

            service_account = SERVICE_ACCOUNT
            if not service_account:
                with credential_path.open("r", encoding="utf-8") as handle:
                    service_account = json.load(handle).get("client_email", "").strip()
            if not service_account:
                raise RuntimeError(
                    "GEE_SERVICE_ACCOUNT is missing and client_email was not found in the JSON key."
                )

            credentials = ee.ServiceAccountCredentials(service_account, str(credential_path))
            ee.Initialize(credentials=credentials, project=PROJECT_ID)
        else:
            # Uses credentials previously saved by `earthengine authenticate`
            # or ambient Google Application Default Credentials.
            ee.Initialize(project=PROJECT_ID)
    except RuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - depends on remote EE auth
        raise RuntimeError(
            "Google Earth Engine authentication failed. In Codespaces, authenticate with "
            "`earthengine authenticate --auth_mode=notebook` and keep GEE_PROJECT_ID in .env. "
            f"Details: {exc}"
        ) from exc
