from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import ee

from backend.config import initialize_gee

ENDMEMBERS = [
    [0.0119, 0.0475, 0.0169, 0.6250, 0.2399, 0.0675],  # GV
    [0.1514, 0.1597, 0.1421, 0.3053, 0.7707, 0.1975],  # NPV
    [0.1799, 0.2479, 0.3158, 0.5437, 0.7707, 0.6646],  # Soil
    [0.4031, 0.8714, 0.7900, 0.8989, 0.7002, 0.6607],  # Cloud
]

# Course 2 visualization palette/order: background, no-change, logging,
# deforestation, vegetation regrowth.
CLASS_PALETTE = ["000000", "1eaf0c", "ffc239", "ff422f", "74fff9"]
CLASS_LABELS = {
    1: "No forest change",
    2: "Logging",
    3: "Deforestation",
    4: "Vegetation regrowth",
}

NDFI_PALETTE = ["ffffff", "ffff00", "00aa00", "006600"]


def mask_l8sr(image: ee.Image) -> ee.Image:
    qa_mask = image.select("QA_PIXEL").bitwiseAnd(31).eq(0)
    saturation_mask = image.select("QA_RADSAT").eq(0)
    optical_bands = image.select("SR_B.").multiply(0.0000275).add(-0.2)
    return (
        image.addBands(optical_bands, None, True)
        .updateMask(qa_mask)
        .updateMask(saturation_mask)
    )


def get_sma_fractions(image: ee.Image) -> ee.Image:
    unmixed = (
        image.select([0, 1, 2, 3, 4, 5])
        .unmix(ENDMEMBERS)
        .max(0)
        .rename("GV", "NPV", "Soil", "Cloud")
    )
    return ee.Image(unmixed.copyProperties(image))


def get_ndfi(sma_image: ee.Image) -> ee.Image:
    shade = sma_image.reduce(ee.Reducer.sum()).subtract(1.0).abs().rename("Shade")
    gvs = (
        sma_image.select("GV")
        .divide(shade.subtract(1.0).abs())
        .rename("GVs")
    )
    ndfi = sma_image.addBands([shade, gvs]).expression(
        "(GVs - (NPV + Soil)) / (GVs + NPV + Soil)",
        {
            "GVs": gvs,
            "NPV": sma_image.select("NPV"),
            "Soil": sma_image.select("Soil"),
        },
    ).rename("NDFI")
    return ndfi


def _one_year_window(selected_date: str) -> tuple[str, str]:
    """Turn one UI observation date into a one-year compositing window.

    The selected date is treated as the center of the observation period.
    This keeps the UI to two dates while retaining the Course 2 idea of
    building NDFI from an image collection rather than a single scene.
    """
    try:
        center = date.fromisoformat(selected_date)
    except ValueError as exc:
        raise ValueError(f"Invalid observation date: {selected_date}") from exc
    start = center - timedelta(days=182)
    end = center + timedelta(days=183)
    return start.isoformat(), end.isoformat()


def build_period(roi: ee.Geometry, start: str, end: str) -> tuple[ee.Image, ee.Image]:
    collection = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterDate(start, end)
        .filterBounds(roi)
    )
    count = int(collection.size().getInfo())
    if count == 0:
        raise ValueError(f"No Landsat 8 scenes found for {start} to {end} in the selected AOI.")

    image = collection.map(mask_l8sr).median()
    bands = ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]
    image = image.select(bands).clip(roi)
    sma = get_sma_fractions(image)
    ndfi = get_ndfi(sma)
    return image, sma.addBands(ndfi)


def _class_area(classification: ee.Image, roi: ee.Geometry, value: int) -> float:
    mask = classification.eq(value)
    area = (
        ee.Image.pixelArea()
        .divide(10000)
        .updateMask(mask)
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi,
            scale=30,
            bestEffort=True,
            maxPixels=1e8,
        )
        .get("area")
    )
    return float(ee.Number(area or 0).getInfo())


def analyze_ndfi_change(request: dict[str, Any]) -> dict[str, Any]:
    initialize_gee()

    roi = ee.Geometry(request["aoi"])
    observation0 = request.get("time0_date")
    observation1 = request.get("time1_date")

    if not all(isinstance(v, str) and v for v in (observation0, observation1)):
        raise ValueError("NDFI analysis requires one observation date for Time 0 and one for Time 1.")
    if observation0 == observation1:
        raise ValueError("Time 0 and Time 1 must be different observation dates.")
    if observation0 > observation1:
        raise ValueError("Time 0 must be earlier than Time 1.")

    start0, end0 = _one_year_window(observation0)
    start1, end1 = _one_year_window(observation1)

    image_time0, sma_time0 = build_period(roi, start0, end0)
    image_time1, sma_time1 = build_period(roi, start1, end1)

    ndfi_t0 = sma_time0.select("NDFI")
    ndfi_t1 = sma_time1.select("NDFI")
    ndfi_pair = ndfi_t0.addBands(ndfi_t1).rename("NDFI_t0", "NDFI_t1")
    ndfi_change = ndfi_t1.subtract(ndfi_t0).rename("NDFI Change")

    # Course 2 thresholds derived from the NDFI-difference histogram.
    classification = ndfi_change.expression(
        "(b(0) >= -0.095 && b(0) <= 0.095) ? 1 :"
        "(b(0) >= -0.250 && b(0) <= -0.095) ? 2 :"
        "(b(0) <= -0.250) ? 3 :"
        "(b(0) >= 0.095) ? 4 : 0"
    ).updateMask(ndfi_t0.gt(0.60)).rename("change_class")

    forest_t0 = ndfi_t0.gt(0.60).selfMask().rename("forest_t0")
    forest_t0_area_ha = float(
        forest_t0.multiply(ee.Image.pixelArea().divide(10000))
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi,
            scale=30,
            bestEffort=True,
            maxPixels=1e8,
        )
        .get("forest_t0")
        .getInfo()
        or 0
    )

    aoi_area_ha = float(roi.area(1).divide(10000).getInfo() or 0)
    areas = {value: _class_area(classification, roi, value) for value in CLASS_LABELS}

    layer_specs = [
        (
            f"Landsat RGB · Time 0 ({observation0})",
            image_time0,
            {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 0.4, "gamma": 1},
        ),
        (
            "Soil Fraction · Time 0",
            sma_time0.select("Soil"),
            {"min": 0, "max": 0.5},
        ),
        (
            "GV Fraction · Time 0",
            sma_time0.select("GV"),
            {"min": 0, "max": 0.5},
        ),
        (
            "NPV Fraction · Time 0",
            sma_time0.select("NPV"),
            {"min": 0, "max": 0.5},
        ),
        (
            "NDFI · Time 0",
            ndfi_t0,
            {"min": -1, "max": 1, "palette": NDFI_PALETTE},
        ),
        (
            f"Landsat RGB · Time 1 ({observation1})",
            image_time1,
            {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 0.4, "gamma": 1},
        ),
        (
            "NDFI · Time 1",
            ndfi_t1,
            {"min": -1, "max": 1, "palette": NDFI_PALETTE},
        ),
        (
            "NDFI Change (RGB)",
            ndfi_pair,
            {"bands": ["NDFI_t0", "NDFI_t1", "NDFI_t1"], "min": -1, "max": 1},
        ),
        (
            "NDFI Difference",
            ndfi_change,
            {"min": -0.5, "max": 0.5, "palette": ["ff0000", "ffffff", "00ffff"]},
        ),
        (
            "Forest · Time 0",
            forest_t0,
            {"min": 0, "max": 1, "palette": ["228B22"]},
        ),
        (
            "Change Classification",
            classification,
            {"min": 0, "max": 4, "palette": CLASS_PALETTE},
        ),
    ]

    layers: list[dict[str, str]] = []
    for label, image, vis in layer_specs:
        map_info = image.getMapId(vis)
        layers.append({"label": label, "tile_url": map_info["tile_fetcher"].url_format})

    primary_map = classification.getMapId({"min": 0, "max": 4, "palette": CLASS_PALETTE})
    geotiff_url = classification.getDownloadURL(
        {
            "scale": 30,
            "region": request["aoi"],
            "fileFormat": "GeoTIFF",
            "maxPixels": 1e13,
        }
    )

    try:
        map_image_url = classification.getThumbURL({
            "region": request["aoi"],
            "dimensions": 1100,
            "format": "png",
            "min": 0,
            "max": 4,
            "palette": CLASS_PALETTE,
        })
    except Exception:
        map_image_url = None

    return {
        "success": True,
        "module": "ndfi_change",
        "aoi_area_ha": aoi_area_ha,
        "time0": {"date": observation0, "start": start0, "end": end0},
        "time1": {"date": observation1, "start": start1, "end": end1},
        "forest_t0_area_ha": forest_t0_area_ha,
        "area_by_class_ha": areas,
        "classes": CLASS_LABELS,
        "thresholds": {
            "no_change": [-0.095, 0.095],
            "logging": [-0.250, -0.095],
            "deforestation": [-999, -0.250],
            "regrowth": [0.095, 999],
            "forest_mask": 0.60,
        },
        "dataset": "LANDSAT/LC08/C02/T1_L2",
        "composite": "One-year Landsat 8 median window centered on each selected observation date",
        "method": "Landsat 8 → cloud/saturation mask → median composite → SMA → GV/NPV/Soil/Cloud → Shade/GVs → NDFI → NDFI t1 - NDFI t0",
        "classification_map": {
            "tile_url": primary_map["tile_fetcher"].url_format,
            "palette": CLASS_PALETTE,
        },
        "layers": layers,
        "geotiff_url": geotiff_url,
        "map_image_url": map_image_url,
        "note": (
            "The UI uses two observation dates. Each date is expanded to a one-year compositing window centered on that date, "
            "while the SMA, NDFI formula, thresholds and Time 0 forest mask follow the supplied Course 1 and Course 2 workflow. "
            "The output is a remote-sensing screening result and should be validated before formal reporting."
        ),
    }
