"""Multispectral Orthomosaic Discovery, Windowed Spectral Index Computation (NDVI, NDRE, NDWI, GNDVI),
and Spectral-Guided Rice/Tree/Weed/Ditch Classification & Refinement.

Automatically detects companion spectral bands (`_Green.tif`, `_Red.tif`, `_RedEdge.tif`, `_NIR.tif`)
alongside an RGB orthomosaic (`Ortho_..._RGB.tif` or `.jpg`) even when RGB and MS orthomosaics have
different ground sampling distances (e.g., 1.5 cm/px RGB vs 2.46 cm/px MS).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds
from PIL import Image, ImageDraw

from uav_app.domain.detection import spatial_box, estimate_confidence
from uav_app.infrastructure.raster import _write_json

SPECTRAL_BAND_SUFFIXES = {
    "green": ("_Green.tif", "_Green.tiff", "_MS_G.TIF", "_MS_G.tif", "_green.tif"),
    "red": ("_Red.tif", "_Red.tiff", "_MS_R.TIF", "_MS_R.tif", "_red.tif"),
    "red_edge": ("_RedEdge.tif", "_RedEdge.tiff", "_MS_RE.TIF", "_MS_RE.tif", "_rededge.tif"),
    "nir": ("_NIR.tif", "_NIR.tiff", "_MS_NIR.TIF", "_MS_NIR.tif", "_nir.tif"),
}


def find_companion_multispectral(source_path: str | Path) -> dict[str, Any]:
    """Discover companion multispectral bands (`Green`, `Red`, `RedEdge`, `NIR`) in the same folder."""
    src = Path(source_path).expanduser().resolve()
    parent = src.parent
    stem = src.stem

    # Strip known band suffix if the user selected one of the spectral bands directly
    base_stem = stem
    for suffixes in SPECTRAL_BAND_SUFFIXES.values():
        for sfx in suffixes:
            sfx_stem = Path(sfx).stem
            if base_stem.lower().endswith(sfx_stem.lower()):
                base_stem = base_stem[: len(base_stem) - len(sfx_stem)]
                break

    found_bands: dict[str, str] = {}
    for band_name, suffixes in SPECTRAL_BAND_SUFFIXES.items():
        for sfx in suffixes:
            candidate = parent / f"{base_stem}{sfx}"
            if candidate.is_file():
                found_bands[band_name] = str(candidate.resolve())
                break

    # Also check if any RGB companion exists when a spectral band was chosen
    rgb_companion = None
    for ext in (".tif", ".tiff", ".jpg", ".jpeg"):
        cand = parent / f"{base_stem}{ext}"
        if cand.is_file():
            rgb_companion = str(cand.resolve())
            break

    available = len(found_bands) >= 2 and ("nir" in found_bands and ("red" in found_bands or "green" in found_bands))
    return {
        "available": available,
        "base_stem": base_stem,
        "rgb_path": rgb_companion or str(src),
        "bands": found_bands,
        "band_names": list(found_bands.keys()),
        "indices_supported": (
            ["NDVI", "NDRE", "NDWI", "GNDVI"]
            if ("nir" in found_bands and "red" in found_bands and "red_edge" in found_bands and "green" in found_bands)
            else (["NDVI", "NDWI"] if "nir" in found_bands else [])
        ),
    }


def read_spectral_window(
    ms_info: dict[str, Any],
    source_transform: list[float],
    col: float,
    row: float,
    width: float,
    height: float,
    out_w: int,
    out_h: int,
    readers: dict[str, Any] | None = None,
) -> dict[str, np.ndarray] | None:
    """Read aligned `green`, `red`, `red_edge`, `nir` arrays for a given pixel window of the source raster."""
    if not ms_info or not ms_info.get("available"):
        return None

    # Compute geographic bounding box (left, bottom, right, top) of the requested window in source CRS
    a, b, c, d, e, f = source_transform[:6]
    x1 = c + col * a + row * b
    y1 = f + col * d + row * e
    x2 = c + (col + width) * a + (row + height) * b
    y2 = f + (col + width) * d + (row + height) * e
    west, east = min(x1, x2), max(x1, x2)
    south, north = min(y1, y2), max(y1, y2)

    result: dict[str, np.ndarray] = {}
    for band_name, band_path in (ms_info.get("bands") or {}).items():
        try:
            if readers is not None and band_name in readers:
                src = readers[band_name]
                close_after = False
            else:
                src = rasterio.open(band_path)
                close_after = True
            try:
                win = from_bounds(west, south, east, north, transform=src.transform)
                arr = src.read(
                    1,
                    window=win,
                    out_shape=(max(1, int(out_h)), max(1, int(out_w))),
                    resampling=Resampling.bilinear,
                    boundless=True,
                    fill_value=np.nan,
                ).astype(np.float32)
                nodata = src.nodata
                if nodata is not None:
                    arr[np.isclose(arr, float(nodata))] = np.nan
                arr[arr <= -10000] = np.nan
                result[band_name] = arr
            finally:
                if close_after:
                    src.close()
        except Exception:
            continue

    return result if "nir" in result else None


def compute_spectral_indices(bands: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Compute normalized spectral indices (`ndvi`, `ndre`, `ndwi`, `gndvi`) from aligned band arrays."""
    eps = 1e-6
    nir = bands.get("nir")
    if nir is None:
        return {}
    indices: dict[str, np.ndarray] = {}
    if "red" in bands:
        red = bands["red"]
        indices["ndvi"] = np.nan_to_num((nir - red) / (nir + red + eps), nan=-1.0)
    if "red_edge" in bands:
        re = bands["red_edge"]
        indices["ndre"] = np.nan_to_num((nir - re) / (nir + re + eps), nan=-1.0)
    if "green" in bands:
        green = bands["green"]
        indices["ndwi"] = np.nan_to_num((green - nir) / (green + nir + eps), nan=0.0)
        indices["gndvi"] = np.nan_to_num((nir - green) / (nir + green + eps), nan=-1.0)
    return indices


def render_spectral_composite(
    rgb_img: Image.Image,
    indices: dict[str, np.ndarray],
    bands: dict[str, np.ndarray],
    mode: str = "spectral_fusion",
) -> Image.Image:
    """Create a spectral-enhanced RGB composite for VLM inference or human inspection."""
    rgb = np.array(rgb_img.convert("RGB")).astype(np.float32)
    ndvi = indices.get("ndvi")
    ndre = indices.get("ndre")
    if ndvi is None:
        return rgb_img

    if mode == "ndvi_color":
        lo, hi = np.percentile(ndvi, [3, 99])
        u8 = np.clip((ndvi - lo) * 255.0 / max(1e-5, hi - lo), 0, 255).astype(np.uint8)
        colored = cv2.applyColorMap(u8, cv2.COLORMAP_TURBO)[:, :, ::-1]
        return Image.fromarray(colored)

    if mode == "false_color_nir" and "nir" in bands and "red" in bands and "green" in bands:
        def stretch(arr):
            valid = arr[np.isfinite(arr) & (arr > 0)]
            if not valid.size:
                return np.zeros_like(arr, dtype=np.uint8)
            lo, hi = np.percentile(valid, [2, 98])
            return np.clip((arr - lo) * 255.0 / max(1e-5, hi - lo), 0, 255).astype(np.uint8)
        fc = np.stack([stretch(bands["nir"]), stretch(bands["red"]), stretch(bands["green"])], axis=-1)
        return Image.fromarray(fc)

    # Default `spectral_fusion`: Suppress water sun-glint and boost chlorophyll contrast on RGB
    # Pixels with positive NDVI relative to water background get green-channel reinforcement
    bg_ndvi = float(np.percentile(ndvi, 25))
    veg_boost = np.clip((ndvi - bg_ndvi) * 320.0, 0.0, 75.0)
    if ndre is not None:
        bg_ndre = float(np.percentile(ndre, 25))
        veg_boost = veg_boost + np.clip((ndre - bg_ndre) * 180.0, 0.0, 40.0)

    # Suppress sun-glint where RGB is bright (>215) but NDVI is low (water surface reflection)
    bright_glint = (rgb.mean(axis=2) > 205) & (ndvi <= bg_ndvi + 0.04)
    out = rgb.copy()
    if np.any(bright_glint):
        out[bright_glint] = out[bright_glint] * 0.65

    out[:, :, 1] = np.clip(out[:, :, 1] + veg_boost * 0.75, 0, 255)
    out[:, :, 0] = np.clip(out[:, :, 0] - veg_boost * 0.25, 0, 255)
    return Image.fromarray(out.astype(np.uint8))


def propose_spectral_refinement(
    rgb: np.ndarray,
    box: list[float],
    indices: dict[str, np.ndarray],
    padding: int = 0,
) -> dict[str, Any]:
    """P03 Multispectral Refinement: Use NDVI + NDRE + NDWI to segment vegetation/water and classify Rice vs Weed/Tree."""
    h, w = rgb.shape[:2]
    x1, y1 = max(0, math.floor(box[0])), max(0, math.floor(box[1]))
    x2, y2 = min(w, math.ceil(box[2])), min(h, math.ceil(box[3]))
    result: dict[str, Any] = dict(candidate_box=None, reason="Không đủ vùng ảnh phổ để co khung.", mask=None)
    if x2 - x1 < 3 or y2 - y1 < 3:
        return result

    ndvi_full = indices.get("ndvi")
    ndre_full = indices.get("ndre")
    ndwi_full = indices.get("ndwi")
    if ndvi_full is None:
        from uav_app.infrastructure.refinement import propose_refinement
        return propose_refinement(rgb, box, padding)

    roi_ndvi = ndvi_full[y1:y2, x1:x2]
    roi_ndre = ndre_full[y1:y2, x1:x2] if ndre_full is not None else np.zeros_like(roi_ndvi)
    roi_ndwi = ndwi_full[y1:y2, x1:x2] if ndwi_full is not None else np.zeros_like(roi_ndvi)

    ndvi_span = float(roi_ndvi.max() - roi_ndvi.min())
    if ndvi_span < 0.015:
        result["reason"] = "Phổ NDVI trong khung đồng nhất (nền nước/bùn); giữ khung gốc."
        return result

    # Normalize local NDVI to [0, 255] for Otsu segmentation, rejecting water/mud pixels
    norm_ndvi = np.clip((roi_ndvi - roi_ndvi.min()) * 255.0 / max(1e-5, ndvi_span), 0, 255).astype(np.uint8)
    _, binary = cv2.threshold(norm_ndvi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Include young rice clumps whose NDVI is clearly above local water/mud background
    bg_med = float(np.percentile(roi_ndvi, 30))
    adaptive_veg_floor = max(0.02, bg_med + max(0.04, 0.16 * ndvi_span))
    if roi_ndvi.shape[0] >= 40 or roi_ndvi.shape[1] >= 40:
        binary = np.where((binary > 0) | (roi_ndvi >= adaptive_veg_floor), 255, 0).astype(np.uint8)
    # Exclude pure water/mud background (below local 20th percentile or negative NDVI floor)
    floor_ndvi = max(-0.08, float(np.percentile(roi_ndvi, 20)))
    binary[roi_ndvi <= floor_ndvi] = 0
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    min_cand_area = max(3, int(roi_ndvi.shape[0] * roi_ndvi.shape[1] * 0.0005))
    candidates = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= min_cand_area]
    if not candidates:
        result["reason"] = "Không tìm thấy đỉnh diệp lục NIR/NDVI rõ trong khung."
        return result

    clump_ids = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 12]
    if not clump_ids:
        clump_ids = [max(candidates, key=lambda i: stats[i, cv2.CC_STAT_AREA])]

    clump_boxes: list[list[float]] = []
    rice_clump_boxes: list[list[float]] = []
    grass_boxes: list[list[float]] = []
    for cid in clump_ids:
        cx_i, cy_i, cw_i, ch_i, area_i = map(int, stats[cid])
        cbox = [
            float(max(float(box[0]), x1 + cx_i)),
            float(max(float(box[1]), y1 + cy_i)),
            float(min(float(box[2]), x1 + cx_i + cw_i)),
            float(min(float(box[3]), y1 + cy_i + ch_i)),
        ]
        clump_boxes.append(cbox)
        comp_i = labels == cid
        c_ndvi = float(roi_ndvi[comp_i].mean()) if np.any(comp_i) else 0.2
        c_aspect = max(cw_i / max(1, ch_i), ch_i / max(1, cw_i))
        # Large or elongated dense levee vegetation vs compact young rice clump
        if (max(cw_i, ch_i) >= 44 or area_i >= 700 or (c_aspect >= 2.6 and max(cw_i, ch_i) >= 28)) and c_ndvi >= 0.30:
            grass_boxes.append(cbox)
        else:
            rice_clump_boxes.append(cbox)

    has_partial_grass = bool(len(grass_boxes) >= 1 and len(rice_clump_boxes) >= 2)

    num_clumps = len(clump_boxes)
    if num_clumps >= 2:
        min_x = min(cb[0] for cb in clump_boxes)
        min_y = min(cb[1] for cb in clump_boxes)
        max_x = max(cb[2] for cb in clump_boxes)
        max_y = max(cb[3] for cb in clump_boxes)
        candidate = [
            max(float(box[0]), min_x - padding),
            max(float(box[1]), min_y - padding),
            min(float(box[2]), max_x + padding),
            min(float(box[3]), max_y + padding),
        ]
        comp_mask = np.isin(labels, clump_ids)
        mask = np.where(comp_mask, 255, 0).astype(np.uint8)
        area = int(sum(stats[cid, cv2.CC_STAT_AREA] for cid in clump_ids))
        cw = max(1, int(max_x - min_x))
        ch = max(1, int(max_y - min_y))
    else:
        selected = clump_ids[0]
        cx, cy, cw, ch, area = map(int, stats[selected])
        candidate = [
            max(float(box[0]), x1 + cx - padding),
            max(float(box[1]), y1 + cy - padding),
            min(float(box[2]), x1 + cx + cw + padding),
            min(float(box[3]), y1 + cy + ch + padding),
        ]
        comp_mask = labels == selected
        mask = np.where(comp_mask, 255, 0).astype(np.uint8)

    mean_ndvi = float(roi_ndvi[comp_mask].mean()) if np.any(comp_mask) else float(roi_ndvi.mean())
    max_ndvi = float(roi_ndvi[comp_mask].max()) if np.any(comp_mask) else float(roi_ndvi.max())
    mean_ndre = float(roi_ndre[comp_mask].mean()) if np.any(comp_mask) else float(roi_ndre.mean())
    mean_ndwi = float(roi_ndwi[comp_mask].mean()) if np.any(comp_mask) else float(roi_ndwi.mean())

    # Estimate clump count via connected clump boxes + distance transform on NDVI mask
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    max_dist = float(dist.max()) if dist.size else 0.0
    estimated_plant_count = max(1, num_clumps)
    if max_dist >= 2.5:
        _, peaks = cv2.threshold(dist, 0.48 * max_dist, 255, cv2.THRESH_BINARY)
        peak_count, _, _, _ = cv2.connectedComponentsWithStats(peaks.astype(np.uint8), 8)
        estimated_plant_count = max(estimated_plant_count, peak_count - 1)

    aspect = max(cw / max(1, ch), ch / max(1, cw))
    if mean_ndvi >= 0.35 and max_ndvi >= 0.40 and mean_ndre >= 0.04:
        spectral_class = "Grass" if (aspect < 2.6 or num_clumps >= 3) else "Hedge"
        spectral_note = f"Phổ NIR/RE cao (NDVI={mean_ndvi:.2f}, NDRE={mean_ndre:.2f} → Cỏ dày / Bờ cỏ)"
    else:
        spectral_class = "Newly transplanted rice"
        spectral_note = f"Phổ diệp lục lúa non (NDVI={mean_ndvi:.2f}, NDRE={mean_ndre:.2f} → Khóm lúa mới cấy)"

    plant_structure = (
        "hedge"
        if (aspect >= 2.8 and num_clumps <= 2 and spectral_class != "Newly transplanted rice")
        else ("cluster" if estimated_plant_count >= 2 or num_clumps >= 2 else "individual")
    )
    result.update(
        candidate_box=candidate,
        mask=mask,
        crop=[x1, y1, x2, y2],
        reason=f"Co khung theo Phổ Đa Kênh: {spectral_note}. Tách được ~{estimated_plant_count} khóm.",
        vegetation_fraction=float(area / max(1, roi_ndvi.shape[0] * roi_ndvi.shape[1])),
        components=max(len(candidates), num_clumps),
        estimated_plant_count=int(estimated_plant_count),
        plant_structure=plant_structure,
        ndvi_mean=round(mean_ndvi, 4),
        ndvi_max=round(max_ndvi, 4),
        ndre_mean=round(mean_ndre, 4),
        ndwi_mean=round(mean_ndwi, 4),
        spectral_class=spectral_class,
        clump_boxes=clump_boxes,
        rice_clump_boxes=rice_clump_boxes,
        grass_boxes=grass_boxes,
        has_partial_grass=has_partial_grass,
    )
    return result


def _classify_record_from_spectral_and_dem(
    rec: dict[str, Any],
    ndvi_mean: float,
    ndvi_max: float,
    ndre_mean: float,
    ndwi_mean: float,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Classify a detection record accurately, avoiding false 'Person' or 'ditch' on compound categories."""
    cat_low = (rec.get("category") or "").lower()
    label_low = (rec.get("label") or "").lower()
    has_veg_kw = any(k in cat_low for k in ("rice", "lúa", "grass", "cỏ", "tree", "cây", "hedge", "plant"))
    has_rice_or_grass_kw = any(k in cat_low for k in ("rice", "lúa", "grass", "cỏ")) or any(
        k in label_low for k in ("rice", "lúa", "grass", "cỏ")
    )

    box = rec.get("candidate_box") or rec.get("box") or [0.0, 0.0, 10.0, 10.0]
    gsd_x_m = ((metadata or {}).get("gsd_x_cm") or 1.5) / 100.0
    gsd_y_m = ((metadata or {}).get("gsd_y_cm") or 1.5) / 100.0
    width_m = max(0.01, (box[2] - box[0]) * gsd_x_m)
    height_box_m = max(0.01, (box[3] - box[1]) * gsd_y_m)
    aspect = max(width_m / height_box_m, height_box_m / width_m)
    area_m2 = width_m * height_box_m
    height_m = rec.get("height_m")
    ref = rec.get("refinement") or {}
    clump_count = int(ref.get("estimated_plant_count") or ref.get("components") or 1)

    # Check non-vegetation classes ONLY when NDVI confirms absence of chlorophyll
    is_non_veg_spectral = ndvi_mean < 0.14 and ndvi_max < 0.24
    if is_non_veg_spectral:
        if ("person" in label_low or ("person" in cat_low and not has_veg_kw)) and (
            height_m is None or (0.40 <= float(height_m) <= 2.1)
        ) and area_m2 <= 2.5:
            return "Person"
        if (
            any(k in label_low for k in ("vehicle", "car", "truck"))
            or (any(k in cat_low for k in ("vehicle", "car", "truck")) and not has_veg_kw)
        ) and (height_m is None or float(height_m) >= 0.40):
            return "Vehicle"

    # Ditch only if explicitly a ditch category/label without veg keywords OR pure elongated water channel with no plant crown
    if (
        "ditch" in label_low
        or "mương" in label_low
        or (("ditch" in cat_low or "mương" in cat_low) and not has_veg_kw)
        or (ndwi_mean > 0.22 and ndvi_max < 0.12 and aspect >= 3.0 and (height_m is None or float(height_m) <= 0.05))
    ):
        return "ditch"

    # Low paddy vegetation (height_m < 0.35m)
    if isinstance(height_m, (int, float)):
        if float(height_m) < 0.35:
            if ndvi_mean >= 0.35 and ndvi_max >= 0.40 and ndre_mean >= 0.04:
                return "Grass"
            if has_rice_or_grass_kw or ndvi_max >= -0.05:
                return "Newly transplanted rice"
            return "Grass"
        # Taller vegetation (height_m >= 0.35m) on levees / banks / trees
        if "tree" in label_low or ("tree" in cat_low and not has_rice_or_grass_kw) or float(height_m) >= 1.25:
            return "Tree cluster" if (area_m2 >= 6.0 or clump_count >= 3) else "Individual tree"
        if aspect >= 2.8 and clump_count <= 2:
            return "Hedge"
        return "Grass"

    # No DEM height available -> classify by spectral indices
    if ndvi_mean >= 0.35 and ndvi_max >= 0.40 and ndre_mean >= 0.04:
        if "tree" in label_low or ("tree" in cat_low and not has_rice_or_grass_kw):
            return "Individual tree"
        return "Hedge" if (aspect >= 2.8 and clump_count <= 2) else "Grass"
    if ndvi_max >= -0.05:
        if has_rice_or_grass_kw:
            return "Newly transplanted rice"
        if "tree" in cat_low:
            return "Individual tree"
    return rec.get("sub_class") or rec.get("category") or "Newly transplanted rice"


def analyze_full_orthomosaic_multispectral(
    source_path: str | Path,
    output_dir: str | Path | None = None,
    max_overview_size: int = 1600,
) -> dict[str, Any]:
    """Analyze the entire orthomosaic (multispectral 4-band or RGB ExG fallback) at overview resolution
    and generate a full-field spectral summary + 5-zone land-cover breakdown + `spectral_overview.png`."""
    src_path = Path(source_path).expanduser().resolve()
    if not src_path.is_file():
        raise ValueError(f"Không tìm thấy tệp ảnh nguồn: {src_path}")

    ms_info = find_companion_multispectral(src_path)
    with rasterio.open(src_path) as src_ds:
        full_w, full_h = src_ds.width, src_ds.height
        scale = min(1.0, float(max_overview_size) / max(1, full_w, full_h))
        out_w = max(16, int(round(full_w * scale)))
        out_h = max(16, int(round(full_h * scale)))

    if ms_info["available"]:
        bands: dict[str, np.ndarray] = {}
        for b_name, b_path in ms_info["bands"].items():
            try:
                with rasterio.open(b_path) as b_ds:
                    arr = b_ds.read(
                        1,
                        out_shape=(out_h, out_w),
                        resampling=Resampling.bilinear,
                    ).astype(np.float32)
                    nodata = b_ds.nodata
                    if nodata is not None:
                        arr[np.isclose(arr, float(nodata))] = np.nan
                    arr[arr <= -10000] = np.nan
                    bands[b_name] = arr
            except Exception:
                continue
        if "nir" not in bands:
            ms_info["available"] = False

    if ms_info["available"]:
        nir = bands["nir"]
        red = bands.get("red", bands.get("green", nir))
        re = bands.get("red_edge", red)
        green = bands.get("green", red)
        valid_mask = np.isfinite(nir) & np.isfinite(red) & (nir > 0) & (red > 0)
        indices = compute_spectral_indices({"nir": nir, "red": red, "red_edge": re, "green": green})
        ndvi = indices["ndvi"]
        ndre = indices.get("ndre", np.zeros_like(ndvi))
        ndwi = indices.get("ndwi", np.zeros_like(ndvi))
        mode = "multispectral_4band"
        bands_used = ms_info["band_names"]
        indices_computed = ms_info["indices_supported"]
    else:
        with rasterio.open(src_path) as src_ds:
            count = min(3, src_ds.count)
            raw_rgb = src_ds.read(
                list(range(1, count + 1)),
                out_shape=(count, out_h, out_w),
                resampling=Resampling.bilinear,
            ).astype(np.float32)
            if count == 1:
                raw_rgb = np.repeat(raw_rgb, 3, axis=0)
            r_ch, g_ch, b_ch = raw_rgb[0], raw_rgb[1], raw_rgb[2]
            valid_mask = np.isfinite(r_ch) & ((r_ch > 4) | (g_ch > 4) | (b_ch > 4)) & ((r_ch < 252) | (g_ch < 252) | (b_ch < 252))
            eps = 1e-6
            # Proxy NDVI/NDRE/NDWI from RGB Excess Green & Normalized Green-Red Difference
            ngrdi = (g_ch - r_ch) / (g_ch + r_ch + eps)
            exg_norm = (2.0 * g_ch - r_ch - b_ch) / (r_ch + g_ch + b_ch + eps)
            ndvi = np.clip(ngrdi * 1.4 + exg_norm * 0.8, -1.0, 1.0)
            ndre = np.clip(ngrdi * 0.7, -1.0, 1.0)
            ndwi = np.clip((b_ch - g_ch) / (b_ch + g_ch + eps), -1.0, 1.0)
            mode = "rgb_exg_fallback"
            bands_used = ["red", "green", "blue"]
            indices_computed = ["ExG", "NGRDI"]

    if not np.any(valid_mask):
        valid_mask = np.ones((out_h, out_w), dtype=bool)

    ndvi_v = ndvi[valid_mask]
    ndre_v = ndre[valid_mask]
    ndwi_v = ndwi[valid_mask]
    total_valid = max(1, int(valid_mask.sum()))

    def _stats(arr_1d: np.ndarray) -> dict[str, float]:
        if arr_1d.size == 0:
            return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p25": 0.0, "p75": 0.0, "p90": 0.0}
        p10, p25, p50, p75, p90 = [round(float(x), 4) for x in np.percentile(arr_1d, [10, 25, 50, 75, 90])]
        return {
            "mean": round(float(arr_1d.mean()), 4),
            "median": p50,
            "p10": p10,
            "p25": p25,
            "p75": p75,
            "p90": p90,
        }

    ndvi_stats = _stats(ndvi_v)
    ndre_stats = _stats(ndre_v)
    ndwi_stats = _stats(ndwi_v)

    # 5-zone land cover segmentation over valid field pixels
    water_mask = valid_mask & (ndwi > 0.08) & (ndvi < 0.0)
    bare_mud_mask = valid_mask & (~water_mask) & (ndvi < 0.08)
    young_rice_mask = valid_mask & (~water_mask) & (ndvi >= 0.08) & (ndvi < 0.35)
    healthy_veg_mask = valid_mask & (~water_mask) & (ndvi >= 0.35) & (ndvi < 0.60)
    dense_weed_mask = valid_mask & (~water_mask) & (ndvi >= 0.60)

    young_rice_pct = round(float(young_rice_mask.sum()) * 100.0 / total_valid, 2)
    healthy_veg_pct = round(float(healthy_veg_mask.sum()) * 100.0 / total_valid, 2)
    dense_weed_pct = round(float(dense_weed_mask.sum()) * 100.0 / total_valid, 2)
    bare_mud_pct = round(float(bare_mud_mask.sum()) * 100.0 / total_valid, 2)
    water_pct = round(max(0.0, 100.0 - (young_rice_pct + healthy_veg_pct + dense_weed_pct + bare_mud_pct)), 2)

    land_cover_pct = {
        "Lúa mới cấy / Thực vật non (%)": young_rice_pct,
        "Lúa khỏe / Tán cây dày (%)": healthy_veg_pct,
        "Cỏ bờ / Bụi rậm (%)": dense_weed_pct,
        "Đất bùn / Đất trống (%)": bare_mud_pct,
        "Mặt nước (%)": water_pct,
    }
    zones = [
        {"label": "Lúa mới cấy / Thực vật non (%)", "key": "young_rice", "percent": young_rice_pct, "color": "#78e15f"},
        {"label": "Lúa khỏe / Tán cây dày (%)", "key": "healthy_vegetation", "percent": healthy_veg_pct, "color": "#22a84b"},
        {"label": "Cỏ bờ / Bụi rậm (%)", "key": "weed_bush", "percent": dense_weed_pct, "color": "#eba824"},
        {"label": "Đất bùn / Đất trống (%)", "key": "bare_mud", "percent": bare_mud_pct, "color": "#967352"},
        {"label": "Mặt nước (%)", "key": "water", "percent": water_pct, "color": "#2482d7"},
    ]

    overview_rel = None
    overview_abs = None
    if output_dir is not None:
        out_dir_path = Path(output_dir).expanduser().resolve()
        out_dir_path.mkdir(parents=True, exist_ok=True)
        canvas = np.full((out_h, out_w, 3), [24, 28, 36], dtype=np.uint8)
        canvas[water_mask] = [36, 130, 215]
        canvas[bare_mud_mask] = [150, 115, 82]
        canvas[young_rice_mask] = [120, 225, 95]
        canvas[healthy_veg_mask] = [34, 168, 75]
        canvas[dense_weed_mask] = [235, 168, 36]

        # Modulate brightness slightly with continuous NDVI for crisp field row texture
        lo, hi = float(ndvi_stats["p10"]), max(float(ndvi_stats["p10"]) + 0.05, float(ndvi_stats["p90"]))
        shade = np.clip((ndvi - lo) / (hi - lo), 0.0, 1.0)
        mod = (0.82 + 0.32 * shade)[:, :, None]
        blended = np.where(valid_mask[:, :, None], np.clip(canvas.astype(np.float32) * mod, 0, 255), canvas).astype(np.uint8)

        overview_file = out_dir_path / "spectral_overview.png"
        Image.fromarray(blended).save(overview_file, format="PNG")
        overview_rel = "spectral_overview.png"
        overview_abs = str(overview_file)

    return {
        "available": bool(ms_info["available"]),
        "mode": mode,
        "source_path": str(src_path),
        "bands_used": bands_used,
        "indices_computed": indices_computed,
        "overview_size": [out_w, out_h],
        "valid_pixels": total_valid,
        "indices_summary": {
            "ndvi": ndvi_stats,
            "ndre": ndre_stats,
            "ndwi": ndwi_stats,
        },
        "ndvi_mean": ndvi_stats["mean"],
        "ndvi_median": ndvi_stats["median"],
        "ndre_mean": ndre_stats["mean"],
        "ndwi_mean": ndwi_stats["mean"],
        "land_cover_pct": land_cover_pct,
        "zones": zones,
        "overview_image": overview_rel,
        "overview_path": overview_abs,
    }


def enrich_records_with_multispectral(
    records: list[dict[str, Any]],
    metadata: dict[str, Any],
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Enrich existing detection records with Multispectral NDVI, NDRE, NDWI (or RGB ExG fallback)
    and auto-classify Rice vs Grass/Weed/Tree/Ditch."""
    path = source_path or metadata.get("path")
    if not path:
        raise ValueError("Không xác định được đường dẫn ảnh nguồn để đọc kênh phổ.")
    ms_info = find_companion_multispectral(path)
    transform = metadata["transform"]
    class_counts: dict[str, int] = {}
    enriched = 0

    if ms_info["available"]:
        readers = {k: rasterio.open(v) for k, v in ms_info["bands"].items()}
        try:
            for rec in records:
                box = rec.get("candidate_box") or rec["box"]
                col = max(0.0, float(box[0]) - 4.0)
                row = max(0.0, float(box[1]) - 4.0)
                w = max(4.0, float(box[2] - box[0]) + 8.0)
                h = max(4.0, float(box[3] - box[1]) + 8.0)

                bands = read_spectral_window(
                    ms_info, transform, col, row, w, h, out_w=max(8, int(round(w))), out_h=max(8, int(round(h))), readers=readers
                )
                if not bands:
                    continue
                indices = compute_spectral_indices(bands)
                ndvi = indices.get("ndvi")
                if ndvi is None or not ndvi.size:
                    continue
                ndre = indices.get("ndre", np.zeros_like(ndvi))
                ndwi = indices.get("ndwi", np.zeros_like(ndvi))

                # Focus on the top 35% chlorophyll pixels inside the box (the plant crown)
                p65 = float(np.percentile(ndvi, 65))
                crown_mask = ndvi >= p65
                ndvi_mean = float(ndvi[crown_mask].mean()) if np.any(crown_mask) else float(ndvi.mean())
                ndvi_max = float(ndvi.max())
                ndre_mean = float(ndre[crown_mask].mean()) if np.any(crown_mask) else float(ndre.mean())
                ndwi_mean = float(ndwi.mean())

                rec["ndvi_mean"] = round(ndvi_mean, 4)
                rec["ndvi_max"] = round(ndvi_max, 4)
                rec["ndre_mean"] = round(ndre_mean, 4)
                rec["ndwi_mean"] = round(ndwi_mean, 4)

                sub = _classify_record_from_spectral_and_dem(rec, ndvi_mean, ndvi_max, ndre_mean, ndwi_mean, metadata=metadata)
                rec["sub_class"] = sub
                rec["spectral_verified"] = True
                class_counts[sub] = class_counts.get(sub, 0) + 1
                enriched += 1
        finally:
            for r in readers.values():
                r.close()
        bands_used = ms_info["band_names"]
        indices_computed = ms_info["indices_supported"]
    else:
        src_p = Path(path).expanduser().resolve()
        if not src_p.is_file():
            raise ValueError("Không tìm thấy bộ kênh ảnh ghép đa phổ (_Green.tif, _Red.tif, _RedEdge.tif, _NIR.tif) đi kèm ảnh này.")
        with rasterio.open(src_p) as rgb_src:
            for rec in records:
                box = rec.get("candidate_box") or rec["box"]
                col = max(0, int(math.floor(float(box[0]) - 2)))
                row = max(0, int(math.floor(float(box[1]) - 2)))
                w = max(4, min(rgb_src.width - col, int(math.ceil(float(box[2] - box[0]) + 4))))
                h = max(4, min(rgb_src.height - row, int(math.ceil(float(box[3] - box[1]) + 4))))
                if w <= 0 or h <= 0:
                    continue
                cnt = min(3, rgb_src.count)
                arr = rgb_src.read(list(range(1, cnt + 1)), window=rasterio.windows.Window(col, row, w, h)).astype(np.float32)
                if cnt == 1:
                    arr = np.repeat(arr, 3, axis=0)
                r_c, g_c, b_c = arr[0], arr[1], arr[2]
                eps = 1e-6
                ngrdi = (g_c - r_c) / (g_c + r_c + eps)
                exg_norm = (2.0 * g_c - r_c - b_c) / (r_c + g_c + b_c + eps)
                ndvi = np.clip(ngrdi * 1.4 + exg_norm * 0.8, -1.0, 1.0)
                ndre = np.clip(ngrdi * 0.7, -1.0, 1.0)
                ndwi = np.clip((b_c - g_c) / (b_c + g_c + eps), -1.0, 1.0)
                p65 = float(np.percentile(ndvi, 65))
                crown_mask = ndvi >= p65
                ndvi_mean = float(ndvi[crown_mask].mean()) if np.any(crown_mask) else float(ndvi.mean())
                ndvi_max = float(ndvi.max())
                ndre_mean = float(ndre[crown_mask].mean()) if np.any(crown_mask) else float(ndre.mean())
                ndwi_mean = float(ndwi.mean())
                rec["ndvi_mean"] = round(ndvi_mean, 4)
                rec["ndvi_max"] = round(ndvi_max, 4)
                rec["ndre_mean"] = round(ndre_mean, 4)
                rec["ndwi_mean"] = round(ndwi_mean, 4)
                sub = _classify_record_from_spectral_and_dem(rec, ndvi_mean, ndvi_max, ndre_mean, ndwi_mean, metadata=metadata)
                rec["sub_class"] = sub
                rec["spectral_verified"] = True
                class_counts[sub] = class_counts.get(sub, 0) + 1
                enriched += 1
        bands_used = ["red", "green", "blue"]
        indices_computed = ["ExG", "NGRDI"]

    return {
        "enriched_count": enriched,
        "total": len(records),
        "bands_used": bands_used,
        "indices_computed": indices_computed,
        "class_counts": class_counts,
    }


def compute_illumination_invariant_rgb_indices(rgb_u8: np.ndarray) -> dict[str, np.ndarray]:
    """Normalize UAV RGB orthomosaic via 2%–98% percentile stretch and compute illumination-invariant indices.

    Ensures consistent radiometric separation across DJI Mavic 3E, Phantom 4 RTK, and Matrice 300/350
    flights under varying solar elevation or cloud cover.
    """
    rgb_f = rgb_u8.astype(np.float32)
    r, g, b = rgb_f[:, :, 0], rgb_f[:, :, 1], rgb_f[:, :, 2]
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    nodata_mask = (cmax < 6.0) | (cmin > 252.0)
    valid_px = ~nodata_mask

    if np.any(valid_px):
        norm_ch = []
        for ch in (r, g, b):
            p2, p98 = np.percentile(ch[valid_px], [2.0, 98.0])
            if (p98 - p2) > 25.0:
                norm_ch.append(np.clip((ch - p2) / (p98 - p2) * 255.0, 0.0, 255.0))
            else:
                norm_ch.append(ch)
        rn, gn, bn = norm_ch
    else:
        rn, gn, bn = r, g, b

    sum_rgb = np.maximum(rn + gn + bn, 1.0)
    lum = 0.299 * rn + 0.587 * gn + 0.114 * bn
    exg = 2.0 * gn - rn - bn
    exg_norm = exg / sum_rgb
    ngrdi = (gn - rn) / np.maximum(gn + rn, 1.0)
    denom_vari = gn + rn - bn
    vari = np.clip((gn - rn) / np.where(np.abs(denom_vari) < 5.0, np.where(denom_vari >= 0, 5.0, -5.0), denom_vari), -1.0, 1.0)
    cive = 0.441 * rn - 0.811 * gn + 0.385 * bn + 18.787

    lum_blur = cv2.GaussianBlur(lum, (7, 7), 0)
    local_std = np.sqrt(np.maximum(0.0, cv2.GaussianBlur((lum - lum_blur) ** 2, (7, 7), 0)))

    return {
        "r_norm": rn,
        "g_norm": gn,
        "b_norm": bn,
        "lum": lum,
        "exg": exg,
        "exg_norm": exg_norm,
        "ngrdi": ngrdi,
        "vari": vari,
        "cive": cive,
        "local_std": local_std,
        "nodata_mask": nodata_mask,
    }


def classify_vegetation_block_subtype(
    exg_norm: float,
    ngrdi: float,
    vari: float,
    cive: float,
    lum: float,
    texture_std: float,
    dem_rel_m: float = 0.0,
    in_water_or_pond: bool = False,
    near_road_corridor: bool = False,
) -> dict[str, Any]:
    """Classify a vegetation patch/crown into the exact CAD block & layer schema of `ACAD_KHU TAM GIAC.dwg`.

    Calibrated directly against 1,740 reference BLOCK INSERTs on `ORTHO_KHU TAM GIAC (03-10-2026).jpg`
    and `DEM_TAM GIAC (03-10-2026).tif`.
    """
    if in_water_or_pond or dem_rel_m <= -0.25:
        return {
            "block_name": "Hoasen",
            "layer": "1.BK. THUC VAT",
            "base_scale": 1.0,
            "grid_dx_m": 4.5,
            "grid_dy_m": 3.5,
        }

    # Elevated street / urban trees (`cdt2`, `cdt39`)
    if near_road_corridor or dem_rel_m >= 2.2 or (exg_norm >= 0.30 and texture_std >= 12.0 and lum < 82.0):
        if texture_std >= 17.5 or dem_rel_m >= 5.3:
            return {
                "block_name": "cdt39",
                "layer": "Thuvien",
                "base_scale": 1.0,
                "grid_dx_m": 10.0,
                "grid_dy_m": 10.0,
            }
        return {
            "block_name": "cdt2",
            "layer": "Thuvien",
            "base_scale": 1.0,
            "grid_dx_m": 10.0,
            "grid_dy_m": 10.0,
        }

    # Broadleaf / banana / nipa palm (`caylato`: rough texture std >= 12.5, moderate height 0.45..2.2m)
    if texture_std >= 12.5 and (0.35 <= dem_rel_m < 2.2 or exg_norm < 0.16):
        return {
            "block_name": "caylato",
            "layer": "1.BK. THUC VAT",
            "base_scale": 0.5,
            "grid_dx_m": 10.0,
            "grid_dy_m": 10.0,
        }

    # Dense shrub / tree cluster (`cumcay1` vs `cumcay2`)
    if exg_norm >= 0.24 and ngrdi >= 0.10 and cive <= -3.0:
        return {
            "block_name": "cumcay1",
            "layer": "THUCVAT",
            "base_scale": 1.0,
            "grid_dx_m": 20.0,
            "grid_dy_m": 10.0,
        }
    if texture_std >= 10.2 and exg_norm >= 0.13 and cive <= 5.5:
        return {
            "block_name": "cumcay2",
            "layer": "Thuc_vat",
            "base_scale": 1.0,
            "grid_dx_m": 20.0,
            "grid_dy_m": 10.0,
        }

    # Smooth, vivid green flowerbed / groundcover (`hoa`: low texture_std < 9.8, high exg_norm >= 0.14, cive <= 2.0)
    if exg_norm >= 0.14 and cive <= 2.0 and texture_std < 10.2:
        return {
            "block_name": "hoa",
            "layer": "1.BK. THUC VAT",
            "base_scale": 1.0,
            "grid_dx_m": 10.0,
            "grid_dy_m": 5.0,
        }

    # Tall grass (`cocao`) vs Short grass (`cothap`)
    if exg_norm >= 0.095 or (lum < 102.0 and ngrdi >= 0.0):
        return {
            "block_name": "cocao",
            "layer": "1.BK. THUC VAT",
            "base_scale": 1.0,
            "grid_dx_m": 10.0,
            "grid_dy_m": 5.0,
        }
    return {
        "block_name": "cothap",
        "layer": "1.BK. THUC VAT",
        "base_scale": 1.0,
        "grid_dx_m": 10.0,
        "grid_dy_m": 5.0,
    }

