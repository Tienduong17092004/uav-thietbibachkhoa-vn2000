"""DEM (Digital Elevation Model) integration for height estimation & vegetation hierarchy."""
from __future__ import annotations

import math
import shutil
from pathlib import Path

import cv2
import numpy as np
import rasterio
from rasterio.windows import Window


def find_companion_dem(ortho_path: str | Path) -> Path | None:
    """Auto-discover a companion DEM GeoTIFF in the same folder as the orthomosaic."""
    source = Path(ortho_path).expanduser().resolve()
    parent = source.parent
    if not parent.is_dir():
        return None
    candidates = sorted(
        p for p in parent.iterdir()
        if p.is_file() and p.suffix.lower() in {".tif", ".tiff"} and p != source and "dem" in p.stem.lower()
    )
    return candidates[0] if candidates else None


def repair_dem_noise(
    dem_path: str | Path,
    output_path: str | Path | None = None,
    min_valid_z: float | None = None,
    create_backup: bool = True,
) -> dict:
    """Seamlessly remove low-elevation/negative photogrammetric noise pits (green/yellow/blue anomalies)
    and replace them with adjacent valid ('red') paddy elevation + natural micro-roughness texture."""
    resolved = Path(dem_path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"Không tìm thấy tệp DEM: {resolved}")

    target = Path(output_path).expanduser().resolve() if output_path else resolved
    backup_path = resolved.with_name(resolved.name + ".bak")
    if create_backup and target == resolved and not backup_path.exists():
        shutil.copy2(resolved, backup_path)

    source_to_read = backup_path if (target == resolved and backup_path.exists()) else resolved

    with rasterio.open(source_to_read) as src:
        profile = src.profile.copy()
        tags = src.tags()
        count = src.count
        nodata = src.nodata

        if count >= 3 and src.dtypes[0] == "uint8":
            # Color-rendered DEM or Global Mapper Segment DEM (uint8 RGB)
            rgb = np.transpose(src.read([1, 2, 3]), (1, 2, 0))
            u_vals = np.unique(rgb[:, :, 0])
            if set(u_vals.tolist()).issubset({0, 1, 2, 3, 4, 255}):
                valid_field = rgb[:, :, 0] != 255
                pit_mask = valid_field & (rgb[:, :, 0] != 0)
                repaired_px = int(pit_mask.sum())
                rgb[pit_mask] = [0, 0, 0]
            else:
                hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
                H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
                fg = ((rgb[:, :, 0] < 215) | (rgb[:, :, 1] < 215) | (rgb[:, :, 2] < 215)) & (rgb.mean(axis=2) < 225)
                fg_inner = cv2.erode(fg.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
                anom = fg & (H >= 14) & (H <= 155) & (V > 18) & (S > 35)
                closed = cv2.morphologyEx(anom.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (19, 19)))
                mask_dil = cv2.dilate(closed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0
                mask_dil &= fg
                repaired_px = int(mask_dil.sum())
                if repaired_px > 0:
                    r_f, g_f, b_f = rgb[:, :, 0].astype(float), rgb[:, :, 1].astype(float), rgb[:, :, 2].astype(float)
                    clean_paddy = fg_inner & (~mask_dil) & (r_f >= 135) & (g_f >= 25) & (b_f <= 20) & (r_f > g_f * 2.5)
                    canvas = rgb.copy().astype(np.float32)
                    med_rgb = np.median(rgb[clean_paddy], axis=0) if np.any(clean_paddy) else np.array([171.0, 42.0, 5.0], dtype=np.float32)
                    canvas[~clean_paddy] = med_rgb
                    base_low = cv2.GaussianBlur(canvas, (45, 45), 0)
                    high_freq = rgb.astype(np.float32) - cv2.GaussianBlur(rgb.astype(np.float32), (35, 35), 0)
                    clean_hf = high_freq[clean_paddy] if np.any(clean_paddy) else np.zeros((100, 3), dtype=np.float32)
                    rng = np.random.default_rng(42)
                    idx = rng.integers(0, len(clean_hf), size=rgb.shape[:2])
                    sampled_hf = cv2.GaussianBlur(clean_hf[idx], (3, 3), 0)
                    rgb[mask_dil] = np.clip(base_low[mask_dil] + sampled_hf[mask_dil], 0, 255).astype(np.uint8)

            out_bands = np.transpose(rgb, (2, 0, 1))
            with rasterio.open(target, "w", **profile) as dst:
                dst.write(out_bands[:count])
                if tags:
                    dst.update_tags(**tags)
            return {
                "dem_path": str(target),
                "backup_path": str(backup_path) if backup_path.exists() else None,
                "mode": "rgb_segment_dem",
                "repaired_pixels": repaired_px,
            }

        # Single-band float/int elevation DEM
        arr = src.read(1).astype(np.float32)
        eff_nodata = nodata if (nodata is not None and math.isfinite(nodata)) else -32767.0
        valid = np.isfinite(arr) & (np.abs(arr - eff_nodata) > 1.0)
        valid_vals = arr[valid]
        if valid_vals.size == 0:
            raise ValueError("Tệp DEM không có pixel cao độ hợp lệ.")

        p10, p50, p90 = [float(x) for x in np.percentile(valid_vals, [10, 50, 90])]
        # Automatic threshold: in flat paddy fields, negative or deep drop-off pits (< 0.5m when median > 1.5m) are water/reflection noise
        if min_valid_z is None:
            auto_thresh = max(0.50 if p50 > 1.5 else p50 - 1.5, p10 - 1.2)
            threshold_z = float(auto_thresh)
        else:
            threshold_z = float(min_valid_z)

        noise_pits = valid & (arr < threshold_z)
        repaired_px = int(noise_pits.sum())
        if repaired_px > 0:
            ys, xs = np.where(noise_pits)
            r1, r2 = max(0, int(ys.min()) - 64), min(arr.shape[0], int(ys.max()) + 64)
            c1, c2 = max(0, int(xs.min()) - 64), min(arr.shape[1], int(xs.max()) + 64)
            sub = arr[r1:r2, c1:c2].copy()
            sub_valid = valid[r1:r2, c1:c2]
            sub_pits = noise_pits[r1:r2, c1:c2]
            sub_pits_dil = cv2.dilate(sub_pits.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) > 0
            sub_pits_dil &= sub_valid
            repaired_px = int(sub_pits_dil.sum())

            clean_neighbors = sub_valid & (~sub_pits_dil) & (sub <= p90)
            fill_val = float(np.median(sub[clean_neighbors])) if np.any(clean_neighbors) else p50
            rough_std = float(np.clip(np.std(sub[clean_neighbors]) * 0.15, 0.015, 0.05)) if np.any(clean_neighbors) else 0.03

            temp = sub.copy()
            temp[~clean_neighbors] = fill_val
            smooth_ground = cv2.GaussianBlur(temp, (31, 31), 0)
            rng = np.random.default_rng(42)
            micro = cv2.GaussianBlur(rng.normal(0.0, rough_std, size=sub.shape).astype(np.float32), (3, 3), 0)
            sub[sub_pits_dil] = smooth_ground[sub_pits_dil] + micro[sub_pits_dil]
            arr[r1:r2, c1:c2] = sub

        new_valid = arr[valid]
        min_after = float(new_valid.min())
        max_after = float(new_valid.max())

    with rasterio.open(target, "w", **profile) as dst:
        dst.write(arr, 1)
        if tags:
            dst.update_tags(**tags)

    return {
        "dem_path": str(target),
        "backup_path": str(backup_path) if backup_path.exists() else None,
        "mode": "elevation_float_dem",
        "threshold_z_m": round(threshold_z, 3),
        "repaired_pixels": repaired_px,
        "min_elevation_after_m": round(min_after, 3),
        "max_elevation_after_m": round(max_after, 3),
        "median_elevation_m": round(p50, 3),
    }


def enrich_records_with_dem(
    records: list[dict],
    ortho_metadata: dict,
    dem_path: str | Path | None = None,
) -> dict:
    """Sample elevation and local object height from a co-registered DEM raster."""
    source_ortho = Path(ortho_metadata["path"])
    resolved_dem = Path(dem_path).expanduser().resolve() if dem_path else find_companion_dem(source_ortho)
    if resolved_dem is None or not resolved_dem.is_file():
        raise ValueError("Không tìm thấy tệp DEM (.tif). Hãy đặt tệp DEM cùng thư mục ảnh hoặc nhập đường dẫn DEM.")

    ortho_transform = ortho_metadata["transform"]
    a, b, c, d, e, f = ortho_transform

    def pixel_to_map(px: float, py: float) -> tuple[float, float]:
        return a * px + b * py + c, d * px + e * py + f

    enriched_count = 0
    class_counts: dict[str, int] = {}

    with rasterio.open(resolved_dem) as dem_src:
        nodata = dem_src.nodata
        inv_transform = ~dem_src.transform

        for record in records:
            box = record.get("candidate_box") if record.get("review_status") == "accepted_candidate" and record.get("candidate_box") else record["box"]
            x1_map, y1_map = pixel_to_map(box[0], box[1])
            x2_map, y2_map = pixel_to_map(box[2], box[3])

            dc1, dr1 = inv_transform * (x1_map, y1_map)
            dc2, dr2 = inv_transform * (x2_map, y2_map)
            col_min = max(0, int(math.floor(min(dc1, dc2))))
            col_max = min(dem_src.width, int(math.ceil(max(dc1, dc2))) + 1)
            row_min = max(0, int(math.floor(min(dr1, dr2))))
            row_max = min(dem_src.height, int(math.ceil(max(dr1, dr2))) + 1)

            if col_max <= col_min or row_max <= row_min:
                continue

            # Expand a ring around the object box (~1.5m margin) to estimate local ground level
            dem_gsd_m = max(abs(dem_src.transform.a), abs(dem_src.transform.e), 0.01)
            pad_px = max(3, int(round(1.5 / dem_gsd_m)))
            outer_c1 = max(0, col_min - pad_px)
            outer_c2 = min(dem_src.width, col_max + pad_px)
            outer_r1 = max(0, row_min - pad_px)
            outer_r2 = min(dem_src.height, row_max + pad_px)

            win = Window(outer_c1, outer_r1, outer_c2 - outer_c1, outer_r2 - outer_r1)
            arr = dem_src.read(1, window=win).astype(np.float64)
            valid = np.isfinite(arr)
            if nodata is not None and math.isfinite(nodata):
                valid &= np.abs(arr - nodata) > 1e-3
            if np.any(valid) and float(np.percentile(arr[valid], 75)) > 0.5:
                no_pit = valid & (arr >= 0.0)
                if np.any(no_pit):
                    valid = no_pit

            inner_r1, inner_r2 = row_min - outer_r1, row_max - outer_r1
            inner_c1, inner_c2 = col_min - outer_c1, col_max - outer_c1
            inner_arr = arr[inner_r1:inner_r2, inner_c1:inner_c2]
            inner_valid = valid[inner_r1:inner_r2, inner_c1:inner_c2]

            if not np.any(inner_valid):
                continue

            inner_vals = inner_arr[inner_valid]
            # Object top elevation (85th percentile inside box)
            top_elev = float(np.percentile(inner_vals, 85))

            ring_mask = valid.copy()
            ring_mask[inner_r1:inner_r2, inner_c1:inner_c2] = False
            if np.any(ring_mask):
                ground_elev = float(np.percentile(arr[ring_mask], 15))
            else:
                ground_elev = float(np.percentile(inner_vals, 10))

            height_m = max(0.0, round(top_elev - ground_elev, 3))
            record["elevation_m"] = round(top_elev, 3)
            record["ground_elevation_m"] = round(ground_elev, 3)
            record["height_m"] = height_m

            # Hierarchical classification: Tree / Hedge / Grass & Individual tree / Tree cluster
            sub_class = classify_vegetation_hierarchy(record, ortho_metadata)
            record["sub_class"] = sub_class
            class_counts[sub_class] = class_counts.get(sub_class, 0) + 1
            enriched_count += 1

    return {
        "dem_path": str(resolved_dem),
        "enriched_count": enriched_count,
        "total": len(records),
        "class_counts": class_counts,
    }


def classify_vegetation_hierarchy(record: dict, ortho_metadata: dict) -> str:
    """Classify into Individual tree, Tree cluster, Hedge, Grass, or Rice using geometry + ExG + DEM."""
    cat = (record.get("category") or "").lower()
    label = (record.get("label") or "").lower()
    has_veg_kw = any(k in cat for k in ("rice", "lúa", "grass", "cỏ", "tree", "cây", "hedge", "plant"))
    has_rice_kw = "rice" in cat or "lúa" in cat or "rice" in label or "lúa" in label
    has_grass_kw = "grass" in cat or "weed" in cat or "cỏ" in cat or "grass" in label
    has_tree_kw = "tree" in cat or "cây" in cat or "tree" in label

    box = record.get("candidate_box") or record["box"]
    gsd_x_m = (ortho_metadata.get("gsd_x_cm") or 2.0) / 100.0
    gsd_y_m = (ortho_metadata.get("gsd_y_cm") or 2.0) / 100.0
    width_m = max(0.01, (box[2] - box[0]) * gsd_x_m)
    height_box_m = max(0.01, (box[3] - box[1]) * gsd_y_m)
    aspect = max(width_m / height_box_m, height_box_m / width_m)
    area_m2 = width_m * height_box_m

    height_m = record.get("height_m")
    refinement = record.get("refinement") or {}
    plant_count = refinement.get("estimated_plant_count") or refinement.get("components") or 1
    ndvi_mean = record.get("ndvi_mean") if isinstance(record.get("ndvi_mean"), (int, float)) else refinement.get("ndvi_mean")
    ndvi_max = record.get("ndvi_max") if isinstance(record.get("ndvi_max"), (int, float)) else refinement.get("ndvi_max")
    ndre_mean = record.get("ndre_mean") if isinstance(record.get("ndre_mean"), (int, float)) else refinement.get("ndre_mean")
    veg_frac = refinement.get("vegetation_fraction")

    has_veg_signal = (
        (isinstance(ndvi_mean, (int, float)) and ndvi_mean >= 0.14)
        or (isinstance(ndvi_max, (int, float)) and ndvi_max >= 0.24)
        or (isinstance(veg_frac, (int, float)) and veg_frac >= 0.15 and isinstance(height_m, (int, float)) and height_m < 0.35)
    )

    if not has_veg_signal:
        if ("person" in label or ("person" in cat and not has_veg_kw)) and (
            height_m is None or (0.40 <= float(height_m) <= 2.1)
        ) and area_m2 <= 2.5:
            return "Person"
        if (
            any(k in label for k in ("vehicle", "car", "truck"))
            or (any(k in cat for k in ("vehicle", "car", "truck")) and not has_veg_kw)
        ) and (height_m is None or float(height_m) >= 0.40):
            return "Vehicle"

    if isinstance(height_m, (int, float)):
        if height_m < 0.35:
            if has_rice_kw:
                if (
                    isinstance(ndvi_mean, (int, float))
                    and ndvi_mean >= 0.35
                    and isinstance(ndvi_max, (int, float))
                    and ndvi_max >= 0.40
                    and (ndre_mean or 0.0) >= 0.04
                ):
                    return "Grass"
                return "Newly transplanted rice"
            return "Grass"
        if aspect >= 2.6 and height_m >= 0.35 and plant_count <= 2:
            return "Hedge"
        if has_tree_kw or height_m >= 1.25:
            if area_m2 >= 6.0 or plant_count >= 3:
                return "Tree cluster"
            return "Individual tree"
        if has_grass_kw or has_rice_kw:
            return "Grass"
        if area_m2 >= 6.0 or plant_count >= 3:
            return "Tree cluster"
        return "Individual tree"

    if has_rice_kw:
        if isinstance(ndvi_mean, (int, float)) and ndvi_mean >= 0.35 and (ndre_mean or 0.0) >= 0.04:
            return "Grass"
        return "Newly transplanted rice"
    if has_grass_kw:
        return "Grass"
    if "hedge" in cat or aspect >= 2.8:
        return "Hedge"
    if area_m2 >= 6.0 or plant_count >= 3:
        return "Tree cluster"
    return "Individual tree"
