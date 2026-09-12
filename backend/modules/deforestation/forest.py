from __future__ import annotations

from typing import Any

import ee

from backend.config import initialize_gee

# ===========================
# DATASETS REQUIRED BY THE SUPPLIED GEE LOGIC
# ===========================
# Keep the supplied year list, cloud masks, composite rules, VI formula,
# forest threshold, forest-area calculation, forest-year aggregation,
# and 90 m chart scale unchanged.
YEAR_LIST = [1990, 1995, 2000, 2005, 2010, 2015, 2020]
PALETTE = ["4B0082", "B22222", "FF4500", "FFD700", "FFFF00", "ADFF2F", "228B22"]
LABEL_LIST = [
    "1990 - 1995",
    "1995 - 2000",
    "2000 - 2005",
    "2005 - 2010",
    "2010 - 2015",
    "2015 - 2020",
    "Current forest",
]


def _collections() -> tuple[ee.ImageCollection, ee.ImageCollection, ee.ImageCollection, ee.ImageCollection]:
    """Create EE collections only after Earth Engine has been initialized."""
    return (
        ee.ImageCollection("LANDSAT/LT04/C02/T1_L2"),
        ee.ImageCollection("LANDSAT/LT05/C02/T1_L2"),
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2"),
        ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"),
    )


def filterCol(col: ee.ImageCollection, roi: ee.Geometry, date: list[ee.Date]) -> ee.ImageCollection:
    return col.filterDate(date[0], date[1]).filterBounds(roi)


def cloudMaskTm(image: ee.Image) -> ee.Image:
    qa = image.select("QA_PIXEL")
    dilated = 1 << 1
    cloud = 1 << 3
    shadow = 1 << 4

    mask = (
        qa.bitwiseAnd(dilated).eq(0)
        .And(qa.bitwiseAnd(cloud).eq(0))
        .And(qa.bitwiseAnd(shadow).eq(0))
    )

    return (
        image.select(
            ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"],
            ["B2", "B3", "B4", "B5", "B6", "B7"],
        )
        .updateMask(mask)
        .multiply(0.0000275)
        .add(-0.2)
    )


def cloudMaskOli(image: ee.Image) -> ee.Image:
    qa = image.select("QA_PIXEL")
    dilated = 1 << 1
    cirrus = 1 << 2
    cloud = 1 << 3
    shadow = 1 << 4

    mask = (
        qa.bitwiseAnd(dilated).eq(0)
        .And(qa.bitwiseAnd(cirrus).eq(0))
        .And(qa.bitwiseAnd(cloud).eq(0))
        .And(qa.bitwiseAnd(shadow).eq(0))
    )

    return (
        image.select(
            ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"],
            ["B2", "B3", "B4", "B5", "B6", "B7"],
        )
        .updateMask(mask)
        .multiply(0.0000275)
        .add(-0.2)
    )


def landsat457(
    roi: ee.Geometry,
    date: list[ee.Date],
    l4: ee.ImageCollection,
    l5: ee.ImageCollection,
) -> ee.Image:
    col = filterCol(l4, roi, date).merge(filterCol(l5, roi, date))
    return col.map(cloudMaskTm).median().clip(roi)


def landsat89(
    roi: ee.Geometry,
    date: list[ee.Date],
    l8: ee.ImageCollection,
    l9: ee.ImageCollection,
) -> ee.Image:
    col = filterCol(l8, roi, date).merge(filterCol(l9, roi, date))
    return col.map(cloudMaskOli).median().clip(roi)


def build_forest_collection(roi: ee.Geometry) -> ee.ImageCollection:
    l4, l5, l8, l9 = _collections()
    images: list[ee.Image] = []

    # ===========================
    # GENERATE IMAGE PER YEAR
    # ===========================
    for year in YEAR_LIST:
        start = ee.Date.fromYMD(year - 1, 1, 1)
        end = ee.Date.fromYMD(year + 1, 12, 31)
        date = [start, end]

        landsat = landsat457 if year < 2014 else landsat89
        image = (
            landsat(roi, date, l4, l5)
            if year < 2014
            else landsat(roi, date, l8, l9)
        )

        # Vegetation index (NIR-SWIR)/(NIR+SWIR)
        bandMap = {"NIR": image.select("B5"), "SWIR": image.select("B7")}
        vi = image.expression("(NIR - SWIR) / (NIR + SWIR)", bandMap).rename("VI")

        # Forest mask
        forest = vi.gt(0.7).selfMask().rename("forest").toUint16()

        # Forest area (Ha)
        forestArea = (
            forest.multiply(ee.Image.pixelArea().divide(10000)).rename("area")
        )

        images.append(
            forest.multiply(year)
            .toUint16()
            .addBands(forestArea)
            .set("year", year)
            .set("system:time_start", start)
        )

    return ee.ImageCollection.fromImages(images)


def _reduce_year_area(image: ee.Image, roi: ee.Geometry) -> ee.Feature:
    area = image.select("area").reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=roi,
        scale=90,
        bestEffort=True,
        maxPixels=1e8,
    ).get("area")
    return ee.Feature(None, {"year": image.get("year"), "area_ha": area})


def analyze_deforestation(request: dict[str, Any]) -> dict[str, Any]:
    # IMPORTANT: initialize GEE before creating any ImageCollection objects.
    initialize_gee()

    roi = ee.Geometry(request["aoi"])
    forestCol = build_forest_collection(roi)

    # ===========================
    # VISUALIZATION FOR FOREST YEAR
    # ===========================
    vis = {
        "forest_class_values": YEAR_LIST,
        "forest_class_palette": PALETTE,
    }
    forestYear = forestCol.select("forest").max().set(vis).clip(roi)

    # ===========================
    # FOREST AREA CHART (same 90 m scale)
    # ===========================
    yearly_features = ee.FeatureCollection(
        [
            _reduce_year_area(
                forestCol.filter(ee.Filter.eq("year", year)).first(), roi
            )
            for year in YEAR_LIST
        ]
    )
    feature_info = yearly_features.getInfo().get("features", [])
    area_by_year = {
        int(f["properties"]["year"]): float(f["properties"].get("area_ha") or 0)
        for f in feature_info
    }

    aoi_area_ha = float(roi.area(1).divide(10000).getInfo() or 0)
    baseline = area_by_year.get(1990, 0.0)
    current = area_by_year.get(2020, 0.0)
    change_ha = current - baseline
    change_pct = (change_ha / baseline * 100) if baseline else None
    forest_cover_pct = (current / aoi_area_ha * 100) if aoi_area_ha else None

    forest_year_map = forestYear.getMapId({
        "min": 1990,
        "max": 2020,
        "palette": PALETTE,
    })

    layers: list[dict[str, Any]] = []
    for year, palette in zip(YEAR_LIST, PALETTE):
        image = forestCol.filter(ee.Filter.eq("year", year)).first().select("forest")
        map_info = image.getMapId({"min": 0, "max": year, "palette": [palette]})
        layers.append({
            "year": year,
            "label": f"Forest {year}",
            "tile_url": map_info["tile_fetcher"].url_format,
        })

    try:
        geotiff_url = forestYear.getDownloadURL({
            "scale": 30,
            "region": request["aoi"],
            "fileFormat": "GeoTIFF",
            "maxPixels": 1e13,
        })
    except Exception:
        geotiff_url = None

    try:
        map_image_url = forestYear.getThumbURL({
            "region": request["aoi"],
            "dimensions": 1100,
            "format": "png",
            "min": 1990,
            "max": 2020,
            "palette": PALETTE,
        })
    except Exception:
        map_image_url = None

    return {
        "success": True,
        "module": "deforestation",
        "years": YEAR_LIST,
        "aoi_area_ha": aoi_area_ha,
        "area_by_year": area_by_year,
        "baseline_area_ha": baseline,
        "current_area_ha": current,
        "change_ha": change_ha,
        "change_pct": change_pct,
        "forest_cover_pct": forest_cover_pct,
        "dataset": [
            "LANDSAT/LT04/C02/T1_L2",
            "LANDSAT/LT05/C02/T1_L2",
            "LANDSAT/LC08/C02/T1_L2",
            "LANDSAT/LC09/C02/T1_L2",
        ],
        "threshold": 0.7,
        "composite": "Median, with a ±1 year window around each benchmark year",
        "forest_year": {
            "tile_url": forest_year_map["tile_fetcher"].url_format,
            "palette": PALETTE,
            "labels": LABEL_LIST,
        },
        "layers": layers,
        "geotiff_url": geotiff_url,
        "map_image_url": map_image_url,
        "note": (
            "Forest is screened where (NIR - SWIR) / (NIR + SWIR) > 0.7. "
            "The map and area series are remote-sensing screening outputs and should be field-validated before certified reporting."
        ),
    }
