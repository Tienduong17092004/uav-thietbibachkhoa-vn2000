"""Bounded previews and lossless, windowed GeoTIFF export. No model execution."""
from datetime import datetime, timezone
from contextlib import nullcontext
import io
import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image
import rasterio
from rasterio.crs import CRS
from rasterio.enums import ColorInterp, MaskFlags, Resampling
from rasterio.windows import Window

from uav_app.domain.geometry import create_plan


MAX_PREVIEW_SIZE = 32768


def _local_path(path: str) -> Path:
    if not isinstance(path, (str, os.PathLike)):
        raise ValueError("Raster path must identify a local file")
    result = Path(str(path).strip().strip('"')).expanduser().resolve()
    if result.is_dir():
        cands = sorted(
            (
                p
                for p in result.iterdir()
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".tif", ".tiff"}
            ),
            key=lambda p: (
                0 if "ortho" in p.stem.lower() else (2 if "dem" in p.stem.lower() else 1),
                0 if p.suffix.lower() in {".jpg", ".jpeg"} else 1,
                p.name,
            ),
        )
        if cands:
            return cands[0]
    if not result.is_file():
        raise ValueError(f"Raster file does not exist: {result}")
    return result


def _json_number(value):
    """Spatial diagnostics must remain valid JSON even for broken metadata."""
    return float(value) if value is not None and math.isfinite(value) else None


def _effective_crs(src, path: Path):
    """Use a sibling .prj for JPEG/world-file rasters when GDAL leaves CRS empty."""
    if src.crs is not None:
        return src.crs
    candidates = [path.with_suffix(".prj"), path.with_suffix(".PRJ")]
    sidecar = next((item for item in candidates if item.is_file()), None)
    if sidecar is None:
        return None
    try:
        return CRS.from_wkt(sidecar.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, rasterio.errors.CRSError):
        return None


def _metadata(src, path: Path) -> dict:
    transform = src.transform
    values = list(transform)[:6]
    finite = all(math.isfinite(v) for v in values)
    north_up = finite and transform.b == 0 and transform.d == 0 and transform.a > 0 and transform.e < 0
    errors, warnings = [], []
    unit, factor = None, None
    crs = _effective_crs(src, path)
    if crs is None:
        errors.append("Missing CRS: a projected coordinate reference system is required for slicing.")
    elif not crs.is_projected:
        errors.append("A projected CRS is required; geographic/angular or other CRS cannot be sliced in this phase.")
    else:
        try:
            unit, factor = crs.linear_units_factor
            if not math.isfinite(factor) or factor <= 0:
                raise ValueError("Unknown linear unit")
        except (ValueError, rasterio.errors.CRSError):
            factor = None
            errors.append("Cannot convert the projected CRS linear unit to metres.")
    if not finite:
        errors.append("Affine transform contains non-finite coordinates.")
    elif transform.b != 0 or transform.d != 0:
        errors.append("Raster rotation or shear requires an explicit warp step, which is a later milestone.")
    elif not north_up:
        errors.append("A north-up affine with positive X scale and negative Y scale is required.")
    bounds = list(src.bounds)
    if not all(math.isfinite(v) for v in bounds):
        errors.append("Raster bounds contain non-finite coordinates.")
    gsd_x = math.hypot(transform.a, transform.d) * factor * 100 if finite and factor else None
    gsd_y = math.hypot(transform.b, transform.e) * factor * 100 if finite and factor else None
    if finite and factor and (not math.isfinite(gsd_x) or not math.isfinite(gsd_y) or gsd_x <= 0 or gsd_y <= 0):
        errors.append("The affine transform does not provide a finite, positive pixel size.")
    warnings.append("GSD is projected-grid distance; it does not certify survey accuracy.")
    warnings.append("Preview uses display scaling; exported GeoTIFF values are preserved.")
    if any(not flags for flags in src.mask_flag_enums):
        warnings.append("Explicit per-band masks are exported as .tif.msk companions; keep them with their GeoTIFFs.")
    max_block_bytes = max((h * w for h, w in src.block_shapes), default=0) * src.count * np.dtype(src.dtypes[0]).itemsize
    if max_block_bytes > 64 * 1024 * 1024:
        warnings.append("Source storage blocks are large; GDAL may read a whole block for a small window.")
    return {
        "path": str(path), "width": src.width, "height": src.height, "count": src.count,
        "dtype": src.dtypes[0], "crs": crs.to_string() if crs else None,
        "crs_wkt": crs.to_wkt() if crs else None,
        "linear_unit": unit, "unit_to_metre": factor,
        "transform": [_json_number(v) for v in values],
        "bounds": [_json_number(v) for v in bounds],
        "gsd_x_cm": _json_number(gsd_x), "gsd_y_cm": _json_number(gsd_y),
        "north_up": north_up, "eligible": not errors, "warnings": warnings, "errors": errors,
        "block_shapes": [list(shape) for shape in src.block_shapes],
        "nodata": _json_number(src.nodata),
        "georeference_source": "dataset CRS + raster transform" if src.crs is not None else "world file + .prj sidecars" if crs is not None else None,
    }


def inspect_raster(path: str) -> dict:
    source = _local_path(path)
    with rasterio.open(source) as src:
        meta = _metadata(src, source)
    try:
        from uav_app.infrastructure.dem import find_companion_dem
        comp_dem = find_companion_dem(source)
        meta["companion_dem"] = comp_dem.name if comp_dem is not None else None
    except Exception:
        meta["companion_dem"] = None
    if int(meta.get("count") or 0) == 1 and "dem" in source.stem.lower():
        meta["warnings"].insert(
            0,
            "CẢNH BÁO: Bạn đang mở tệp bản đồ độ cao DEM (1 kênh Z, không có màu RGB). "
            "Để nhận diện đúng màu sắc & vật liệu, hãy chọn tệp ảnh màu ORTHO (.jpg kèm .jgw + .prj) cùng thư mục — hệ thống sẽ tự động ghép kèm tệp DEM này!",
        )
    try:
        from uav_app.infrastructure.multispectral import find_companion_multispectral
        meta["multispectral"] = find_companion_multispectral(source)
    except Exception:
        meta["multispectral"] = {"available": False, "bands": {}, "band_names": [], "indices_supported": []}
    return meta


def plan_raster(path: str, config: dict, preview_limit: int = 2000) -> dict:
    return create_plan(inspect_raster(path), config).as_dict(preview_limit)


def _preview_window(src, window: dict | None) -> Window:
    if window is None:
        return Window(0, 0, src.width, src.height)
    if not isinstance(window, dict):
        raise ValueError("Preview window must be an object")
    values = [window.get(name) for name in ("col", "row", "width", "height")]
    if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        raise ValueError("Preview col, row, width and height must be integers")
    col, row, width, height = values
    if col < 0 or row < 0 or width <= 0 or height <= 0 or col + width > src.width or row + height > src.height:
        raise ValueError("Preview window must lie inside the source raster")
    return Window(col, row, width, height)


def preview_png(path: str, max_size: int = 32768, window: dict | None = None, _reader=None) -> bytes:
    """Return a full-resolution or bounded diagnostic RGBA preview preserving original image quality."""
    if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size <= 0:
        raise ValueError("max_size must be a positive integer")
    limit = min(max_size, MAX_PREVIEW_SIZE)
    source = _local_path(path)
    with (nullcontext(_reader) if _reader is not None else rasterio.open(source)) as src:
        selected = _preview_window(src, window)
        scale = min(1.0, limit / max(selected.width, selected.height))
        width, height = max(1, round(selected.width * scale)), max(1, round(selected.height * scale))
        rgb_interps = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
        if all(color in src.colorinterp for color in rgb_interps):
            bands = [src.colorinterp.index(color) + 1 for color in rgb_interps]
        else:
            bands = [1, 2, 3] if src.count >= 3 else [1]
        resample_mode = Resampling.nearest if scale == 1.0 else Resampling.bilinear
        data = src.read(bands, window=selected, out_shape=(len(bands), height, width),
                        resampling=resample_mode)
        validity = src.dataset_mask(window=selected, out_shape=(height, width), resampling=Resampling.nearest)
        valid = (validity > 0) & np.all(np.isfinite(data), axis=0)
        channels = []
        for band in data:
            if band.dtype == np.uint8:
                channels.append(band)
                continue
            display = np.abs(band).astype(np.float64) if np.iscomplexobj(band) else band.astype(np.float64)
            values = display[valid]
            channel = np.zeros((height, width), dtype=np.uint8)
            if values.size:
                lower, upper = np.percentile(values, [2, 98])
                if upper > lower:
                    channel[valid] = np.clip((display[valid] - lower) * 255 / (upper - lower), 0, 255).astype(np.uint8)
                else:
                    channel[valid] = 128
            channels.append(channel)
        if len(channels) == 1:
            channels *= 3
        rgba = np.stack([*channels, np.where(valid, validity, 0).astype(np.uint8)], axis=-1)
        buffer = io.BytesIO()
        Image.fromarray(rgba).save(buffer, format="PNG")
        return buffer.getvalue()


def _copy_tags(src, dst):
    # Storage structure and source geolocation arrays cannot be copied to a crop.
    excluded = {"IMAGE_STRUCTURE", "DERIVED_SUBDATASETS", "RPC", "GEOLOCATION"}
    for band in (0, *src.indexes):
        tags = src.tags(band)
        if tags:
            dst.update_tags(band, **tags)
        for namespace in src.tag_namespaces(band):
            if namespace not in excluded:
                tags = src.tags(band, ns=namespace)
                if tags:
                    dst.update_tags(band, ns=namespace, **tags)
    dst.colorinterp = src.colorinterp
    dst.scales = src.scales
    dst.offsets = src.offsets
    for band, description in enumerate(src.descriptions, 1):
        if description:
            dst.set_band_description(band, description)
    for band, unit in enumerate(src.units, 1):
        if unit:
            dst.set_band_unit(band, unit)
    for band, interpretation in enumerate(src.colorinterp, 1):
        if interpretation == ColorInterp.palette:
            dst.write_colormap(band, src.colormap(band))


def _write_json(path: Path, value: dict):
    import threading
    import time
    compact = path.name in {"detections.json", "checkpoint.json"}
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            if compact:
                json.dump(value, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            else:
                json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            if not compact:
                os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.015 * (attempt + 1))
    finally:
        if temporary.exists():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _copy_validity_masks(src, dst, window: Window, mask_path: Path) -> bool:
    """Return whether a GDAL RFC 15 external per-band mask was written."""
    explicit_bands = [band for band, flags in zip(src.indexes, src.mask_flag_enums) if not flags]
    shared_bands = [band for band, flags in zip(src.indexes, src.mask_flag_enums)
                    if MaskFlags.per_dataset in flags and MaskFlags.alpha not in flags]
    if explicit_bands:
        # RFC 15: flags=0 denotes an explicit band mask. A .msk with the same
        # band count and INTERNAL_MASK_FLAGS_n=0 overrides nodata for that band.
        # Shared masks use the companion's first band; omit tags for derived
        # masks so the original nodata/alpha fallback stays in effect.
        with rasterio.open(mask_path, "w", driver="GTiff", width=dst.width, height=dst.height,
                           count=src.count, dtype="uint8", crs=dst.crs, transform=dst.transform,
                           compress="deflate", tiled=True, BIGTIFF="IF_SAFER") as masks:
            if shared_bands:
                masks.write(src.read_masks(shared_bands[0], window=window), 1)
            for band in explicit_bands:
                masks.write(src.read_masks(band, window=window), band)
            flags = {f"INTERNAL_MASK_FLAGS_{band}": "0" for band in explicit_bands}
            flags.update({f"INTERNAL_MASK_FLAGS_{band}": "2" for band in shared_bands})
            masks.update_tags(**flags)
        return True
    # Shared explicit masks override nodata. Derived nodata/alpha masks are
    # recreated from unchanged band values and metadata, retaining band validity.
    if shared_bands:
        dst.write_mask(src.dataset_mask(window=window))
    return False


def export_tiles(path: str, output_dir: str, config: dict, progress=None, cancelled=None) -> dict:
    """Stream tiles into a new run directory; cancellation occurs between tiles."""
    source = _local_path(path)
    destination = Path(output_dir).expanduser().resolve()
    with rasterio.open(source) as src:
        metadata = _metadata(src, source)
        plan = create_plan(metadata, config)
        # Validate before claiming a directory. Never overwrite an existing run or source.
        destination.mkdir(parents=False, exist_ok=False)
        normalized = plan.config
        summary = {
            "source": str(source), "output_dir": str(destination), "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_tiles": 0, "tile_count": plan.tile_count,
            "base": {"x": normalized["base_x"], "y": normalized["base_y"]},
            "crs": metadata["crs"], "crs_wkt": metadata["crs_wkt"], "config": normalized,
            "coverage_guarantee_checked": plan.coverage_guarantee_checked,
            "warnings": list(plan.warnings), "manifest": "manifest.jsonl",
        }
        _write_json(destination / "summary.json", summary)
        pending = None
        pending_mask = None
        try:
            with (destination / "manifest.jsonl").open("x", encoding="utf-8") as manifest:
                with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
                    for tile in plan.iter_tiles():
                        if cancelled is not None and cancelled():
                            summary["status"] = "cancelled"
                            break
                        window = Window(tile["col"], tile["row"], tile["width"], tile["height"])
                        filename = tile["id"] + ".tif"
                        pending = destination / ("." + tile["id"] + ".partial.tif")
                        pending_mask = Path(str(pending) + ".msk")
                        source_crs = _effective_crs(src, source)
                        profile = dict(driver="GTiff", width=tile["width"], height=tile["height"],
                                       count=src.count, dtype=src.dtypes[0], crs=source_crs,
                                       transform=src.window_transform(window), nodata=src.nodata,
                                       compress="deflate", BIGTIFF="IF_SAFER")
                        with rasterio.open(pending, "w", **profile) as dst:
                            dst.write(src.read(window=window))
                            _copy_tags(src, dst)
                            external_mask = _copy_validity_masks(src, dst, window, pending_mask)
                        if external_mask:
                            # Publish the mask first so a visible tile never lacks its mask.
                            mask_target = destination / (filename + ".msk")
                            os.replace(pending_mask, mask_target)
                            pending_mask = mask_target
                        os.replace(pending, destination / filename)
                        pending = None
                        pending_mask = None
                        record = dict(tile, file=filename)
                        if external_mask:
                            record["mask_file"] = filename + ".msk"
                        manifest.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                        manifest.flush()
                        summary["completed_tiles"] += 1
                        if progress is not None:
                            progress(summary["completed_tiles"], plan.tile_count)
                    else:
                        summary["status"] = "completed"
        except Exception as error:
            summary["status"] = "failed"
            summary["error"] = str(error)
            raise
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
            if pending_mask is not None:
                pending_mask.unlink(missing_ok=True)
            summary["finished_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(destination / "summary.json", summary)
        return summary
