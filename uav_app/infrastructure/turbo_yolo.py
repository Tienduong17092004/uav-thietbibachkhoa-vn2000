"""Stage 2 Turbo YOLO11 dataset builder, training orchestrator, and FP16 Batch=32 SharedMemory inference.

Designed for dual-environment execution:
- Runs inside the App/Rasterio Python environment (no top-level torch/ultralytics imports).
- Spawns `uav_app/adapters/turbo_worker.py` inside the project's GPU `.venv` (PyTorch CUDA + Ultralytics + ONNX).
"""
from __future__ import annotations

import copy
import io
import json
import math
from multiprocessing import shared_memory
import os
from pathlib import Path
import random
import shutil
import subprocess
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageOps
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.windows import Window

from uav_app.application.detection_pipeline import (
    _is_homogeneous_empty_window,
    _point_in_poly,
    _report_progress,
    annotate_object,
    plan_detection,
)
from uav_app.application.review import _DETECTIONS_IO_LOCK, _save_results
from uav_app.domain.detection import spatial_box
from uav_app.infrastructure.dem import enrich_records_with_dem, find_companion_dem
from uav_app.infrastructure.model_client import DetectionCancelled
from uav_app.infrastructure.multispectral import (
    compute_spectral_indices,
    find_companion_multispectral,
    propose_spectral_refinement,
    read_spectral_window,
)
from uav_app.infrastructure.raster import _write_json, inspect_raster, preview_png
from uav_app.infrastructure.refinement import propose_refinement


ZONE_CLASSES = [
    "Newly transplanted rice",
    "Grass",
    "Newly transplanted rice + Partial Grass",
]
CLUMP_CLASSES = [
    "Newly transplanted rice",
    "Grass",
]


def _map_zone_class(label: str) -> int | None:
    low = str(label or "").strip().lower()
    if not low:
        return None
    if "partial" in low:
        return 2
    if any(k in low for k in ("grass", "weed", "hedge", "tree", "cỏ")):
        return 1
    if "rice" in low or "lúa" in low:
        return 0
    return None


def _map_clump_class(label: str) -> int | None:
    low = str(label or "").strip().lower()
    if not low:
        return None
    if any(k in low for k in ("grass", "weed", "hedge", "tree", "cỏ")) and "partial" not in low:
        return 1
    if "rice" in low or "lúa" in low:
        return 0
    return None


def _canonical_category(label: str, requested_categories: list[str] | None = None) -> str:
    low = str(label or "").lower()
    is_grass = ("grass" in low or "weed" in low) and "partial" not in low
    target = "grass" if is_grass else "newly transplanted rice"
    if requested_categories:
        for req in requested_categories:
            r_low = req.strip().lower()
            if is_grass and any(k in r_low for k in ("grass", "weed", "cỏ")):
                return req.strip()
            if not is_grass and any(k in r_low for k in ("rice", "lúa")):
                return req.strip()
    return target


def _gpu_python(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".venv" / "Scripts" / "python.exe"


def _worker_script() -> Path:
    return Path(__file__).resolve().parents[1] / "adapters" / "turbo_worker.py"


def get_turbo_status(project_root: Path) -> dict:
    """Fast (< 5 ms) status check of Ground Truth dataset counts and trained Turbo YOLO11 models."""
    root = Path(project_root).resolve()
    ds_dir = root / "outputs" / "ground_truth_dataset"
    manifest = ds_dir / "locateanything_finetune.jsonl"

    total_pos = 0
    total_neg = 0
    class_breakdown: dict[str, int] = {}
    run_ids: set[str] = set()

    if manifest.is_file():
        try:
            for line in manifest.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("run_id"):
                    run_ids.add(str(row["run_id"]))
                if row.get("is_positive", True) and row.get("review_status") != "rejected":
                    total_pos += 1
                    lbl = str(row.get("sub_class") or row.get("label") or row.get("category") or "Other")
                    class_breakdown[lbl] = class_breakdown.get(lbl, 0) + 1
                else:
                    total_neg += 1
        except Exception:
            pass

    models_root = root / "models" / "turbo_yolo"
    models_info: dict[str, dict] = {}
    for mode_key, engine_id, title in (
        ("zone", "turbo_zone", "Turbo YOLO11 · Quét Vùng (640px · FP16)"),
        ("clump", "turbo_clump", "Turbo YOLO11 · Khóm Lúa Lẻ (~15cm · FP16)"),
    ):
        m_dir = models_root / f"turbo_{mode_key}"
        pt_file = m_dir / "best.pt"
        onnx_file = m_dir / "best.onnx"
        meta_file = m_dir / "metrics.json"
        meta = {}
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        trained = pt_file.is_file()
        models_info[engine_id] = {
            "mode": mode_key,
            "engine": engine_id,
            "title": title,
            "trained": trained,
            "pt_path": str(pt_file) if trained else None,
            "onnx_path": str(onnx_file) if onnx_file.is_file() else meta.get("onnx_path"),
            "metrics": meta.get("metrics") or {},
            "trained_at": meta.get("trained_at"),
            "elapsed_seconds": meta.get("elapsed_seconds"),
            "epochs": meta.get("epochs"),
            "imgsz": meta.get("imgsz", 640),
            "classes": meta.get("classes") or (ZONE_CLASSES if mode_key == "zone" else CLUMP_CLASSES),
            "dataset_stats": meta.get("dataset_stats") or {},
        }

    return {
        "gpu_venv_ready": _gpu_python(root).is_file(),
        "base_weights_cached": (models_root / "yolo11s.pt").is_file(),
        "dataset": {
            "dataset_dir": str(ds_dir),
            "total_samples": total_pos + total_neg,
            "total_positives": total_pos,
            "total_negatives": total_neg,
            "saved_runs": len(run_ids),
            "class_breakdown": class_breakdown,
            "ready_to_train": total_pos >= 1,
        },
        "models": models_info,
    }


def _select_rgb_bands(src) -> list[int]:
    rgb_interps = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
    if all(color in src.colorinterp for color in rgb_interps):
        return [src.colorinterp.index(color) + 1 for color in rgb_interps]
    return [1, 2, 3] if src.count >= 3 else [1]


def _read_rgb_window(src, col: int, row: int, width: int, height: int, bands: list[int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Read an 8-bit RGB (H, W, 3) numpy array and validity mask (H, W) directly from an open rasterio dataset."""
    if bands is None:
        bands = _select_rgb_bands(src)
    win = Window(col, row, width, height)
    data = src.read(bands, window=win, out_shape=(len(bands), height, width), resampling=Resampling.nearest)
    validity = src.dataset_mask(window=win, out_shape=(height, width), resampling=Resampling.nearest)
    valid = (validity > 0) & np.all(np.isfinite(data), axis=0)

    if data.dtype == np.uint8:
        if data.shape[0] == 1:
            rgb = np.repeat(data[0][:, :, None], 3, axis=2)
        else:
            rgb = np.transpose(data[:3], (1, 2, 0)).copy()
        rgb[~valid] = 0
        return rgb, valid.astype(np.uint8)

    channels = []
    for band in data:
        display = np.abs(band).astype(np.float64) if np.iscomplexobj(band) else band.astype(np.float64)
        values = display[valid]
        ch = np.zeros((height, width), dtype=np.uint8)
        if values.size:
            lower, upper = np.percentile(values, [2, 98])
            if upper > lower:
                ch[valid] = np.clip((display[valid] - lower) * 255.0 / (upper - lower), 0, 255).astype(np.uint8)
            else:
                ch[valid] = 128
        channels.append(ch)
    if len(channels) == 1:
        channels = channels * 3
    rgb = np.stack(channels[:3], axis=-1)
    return rgb, valid.astype(np.uint8)


def _clip_yolo_labels(
    pos_boxes: list[tuple[int, float, float, float, float]],
    win_col: int,
    win_row: int,
    win_w: int,
    win_h: int,
    min_cover: float = 0.35,
    min_px: float = 3.0,
) -> list[tuple[int, float, float, float, float]]:
    """Return YOLO normalized `(cls_id, cx, cy, bw, bh)` for all positive boxes overlapping the window."""
    wx2 = win_col + win_w
    wy2 = win_row + win_h
    labels: list[tuple[int, float, float, float, float]] = []
    for cls_id, x1, y1, x2, y2 in pos_boxes:
        if x2 <= win_col or x1 >= wx2 or y2 <= win_row or y1 >= wy2:
            continue
        ix1 = max(float(win_col), x1)
        iy1 = max(float(win_row), y1)
        ix2 = min(float(wx2), x2)
        iy2 = min(float(wy2), y2)
        iw = ix2 - ix1
        ih = iy2 - iy1
        if iw < min_px or ih < min_px:
            continue
        orig_area = max(1e-6, (x2 - x1) * (y2 - y1))
        if (iw * ih) / orig_area < min_cover:
            continue
        cx = ((ix1 + ix2) * 0.5 - win_col) / win_w
        cy = ((iy1 + iy2) * 0.5 - win_row) / win_h
        bw = iw / win_w
        bh = ih / win_h
        cx = max(0.001, min(0.999, cx))
        cy = max(0.001, min(0.999, cy))
        bw = max(0.002, min(1.0, bw))
        bh = max(0.002, min(1.0, bh))
        labels.append((cls_id, cx, cy, bw, bh))
    return labels


def _format_yolo_txt(labels: list[tuple[int, float, float, float, float]]) -> str:
    if not labels:
        return ""
    return "\n".join(f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}" for cid, cx, cy, bw, bh in labels) + "\n"


def _flip_labels_h(labels: list[tuple[int, float, float, float, float]]) -> list[tuple[int, float, float, float, float]]:
    return [(cid, 1.0 - cx, cy, bw, bh) for cid, cx, cy, bw, bh in labels]


def _flip_labels_v(labels: list[tuple[int, float, float, float, float]]) -> list[tuple[int, float, float, float, float]]:
    return [(cid, cx, 1.0 - cy, bw, bh) for cid, cx, cy, bw, bh in labels]


def _clamp_window(cx: float, cy: float, tile_size: int, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    w = min(tile_size, img_w)
    h = min(tile_size, img_h)
    col = max(0, min(img_w - w, int(round(cx - w * 0.5))))
    row = max(0, min(img_h - h, int(round(cy - h * 0.5))))
    return col, row, w, h


def _write_data_yaml(out_dir: Path, class_names: list[str]) -> Path:
    yaml_path = out_dir / "data.yaml"
    posix_root = out_dir.resolve().as_posix()
    lines = [
        f"path: '{posix_root}'",
        "train: images/train",
        "val: images/val",
        f"nc: {len(class_names)}",
        "names:",
    ]
    for idx, name in enumerate(class_names):
        safe_name = name.replace("'", "''")
        lines.append(f"  {idx}: '{safe_name}'")
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path


def build_yolo_datasets(
    project_root: Path,
    modes: list[str],
    progress=None,
    cancelled=lambda: False,
) -> dict[str, dict]:
    """Build clean GeoTIFF-cut YOLO11 datasets for `zone` (640px) and/or `clump` (512px), including Hard Negatives."""
    root = Path(project_root).resolve()
    manifest = root / "outputs" / "ground_truth_dataset" / "locateanything_finetune.jsonl"
    if not manifest.is_file():
        raise ValueError("Chưa có bộ mẫu Ground Truth. Hãy bấm '💾 Lưu mẫu huấn luyện' trước khi huấn luyện.")

    entries = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            pass

    if not entries:
        raise ValueError("Tệp mẫu huấn luyện đang trống. Hãy duyệt đối tượng và bấm '💾 Lưu mẫu huấn luyện'.")

    # Group by source GeoTIFF
    by_source: dict[str, list[dict]] = {}
    run_ids_by_source: dict[str, set[str]] = {}
    for row in entries:
        src = str(row.get("source_image") or "").strip()
        if not src or not Path(src).is_file():
            continue
        src_norm = str(Path(src).resolve())
        by_source.setdefault(src_norm, []).append(row)
        if row.get("run_id"):
            run_ids_by_source.setdefault(src_norm, set()).add(str(row["run_id"]))

    if not by_source:
        raise ValueError("Không tìm thấy tệp ảnh GeoTIFF gốc của các mẫu đã lưu trên ổ đĩa.")

    pos_total_check = sum(
        1 for rows in by_source.values() for r in rows
        if r.get("is_positive", True) and r.get("review_status") != "rejected"
    )
    if pos_total_check == 0:
        raise ValueError("Cần ít nhất 1 mẫu dương (đã duyệt giữ lại) trong bộ mẫu trước khi huấn luyện.")

    # Load clump_boxes_global and scanned polygons from referenced detection runs
    clumps_by_run_obj: dict[tuple[str, str], list[list[float]]] = {}
    polygons_by_source: dict[str, list[list[list[float]]]] = {}
    runs_root = root / "outputs" / "detection_runs"
    for src_norm, r_ids in run_ids_by_source.items():
        for rid in r_ids:
            r_dir = runs_root / rid
            det_path = r_dir / "detections.json"
            if det_path.is_file():
                try:
                    det_data = json.loads(det_path.read_text(encoding="utf-8"))
                    for rec in det_data.get("records") or []:
                        oid = str(rec.get("id") or "")
                        c_global = (rec.get("refinement") or {}).get("clump_boxes_global")
                        if oid and isinstance(c_global, list) and c_global:
                            clumps_by_run_obj[(rid, oid)] = c_global
                except Exception:
                    pass
            sum_path = r_dir / "summary.json"
            if sum_path.is_file():
                try:
                    sum_data = json.loads(sum_path.read_text(encoding="utf-8"))
                    for reg in (sum_data.get("plan") or {}).get("regions") or []:
                        poly = reg.get("polygon")
                        if isinstance(poly, list) and len(poly) >= 3:
                            polygons_by_source.setdefault(src_norm, []).append(poly)
                except Exception:
                    pass

    rng = random.Random(42)
    built: dict[str, dict] = {}

    for mode_idx, mode in enumerate(modes):
        if cancelled():
            raise DetectionCancelled()
        if mode not in {"zone", "clump"}:
            raise ValueError(f"Chế độ huấn luyện không hợp lệ: {mode}")

        tile_size = 640 if mode == "zone" else 512
        stride = 480 if mode == "zone" else 512
        classes = ZONE_CLASSES if mode == "zone" else CLUMP_CLASSES
        out_dir = root / "outputs" / "turbo_datasets" / mode
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        for split in ("train", "val"):
            (out_dir / "images" / split).mkdir(parents=True, exist_ok=True)
            (out_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

        _report_progress(
            progress,
            2 + mode_idx * 6,
            100,
            f"Đang cắt bộ ô sạch {tile_size}×{tile_size} từ GeoTIFF cho chế độ {'Vùng' if mode == 'zone' else 'Khóm lẻ'}…",
        )

        # Collect tile samples: list of (rgb_uint8_array, yolo_labels, tag)
        samples: list[tuple[np.ndarray, list[tuple[int, float, float, float, float]], str]] = []
        total_box_instances = 0
        hard_neg_tiles = 0
        bg_empty_tiles = 0
        pos_tiles_count = 0

        for src_norm, rows in by_source.items():
            if cancelled():
                raise DetectionCancelled()
            with rasterio.open(src_norm) as src:
                bands = _select_rgb_bands(src)
                img_w, img_h = src.width, src.height

                pos_boxes: list[tuple[int, float, float, float, float]] = []
                neg_raw_boxes: list[tuple[float, float, float, float]] = []
                minority_centers: list[tuple[float, float]] = []

                for r in rows:
                    b = r.get("box_pixel") or r.get("box_px") or r.get("box")
                    if not isinstance(b, list) or len(b) != 4:
                        continue
                    x1, y1, x2, y2 = [float(v) for v in b]
                    if x2 - x1 < 2.0 or y2 - y1 < 2.0:
                        continue
                    is_pos = bool(r.get("is_positive", True)) and r.get("review_status") != "rejected"
                    if not is_pos:
                        neg_raw_boxes.append((x1, y1, x2, y2))
                        continue

                    lbl = str(r.get("sub_class") or r.get("label") or r.get("category") or "")
                    if mode == "zone":
                        cid = _map_zone_class(lbl)
                        if cid is not None:
                            pos_boxes.append((cid, x1, y1, x2, y2))
                            if cid in (1, 2):
                                minority_centers.append(((x1 + x2) * 0.5, (y1 + y2) * 0.5))
                    else:
                        cid = _map_clump_class(lbl)
                        if cid == 1:
                            pos_boxes.append((1, x1, y1, x2, y2))
                            minority_centers.append(((x1 + x2) * 0.5, (y1 + y2) * 0.5))
                        elif cid == 0:
                            rid = str(r.get("run_id") or "")
                            oid = str(r.get("object_id") or "")
                            c_list = clumps_by_run_obj.get((rid, oid))
                            if c_list:
                                for cb in c_list:
                                    if isinstance(cb, list) and len(cb) == 4 and (cb[2] - cb[0]) >= 3 and (cb[3] - cb[1]) >= 3:
                                        pos_boxes.append((0, float(cb[0]), float(cb[1]), float(cb[2]), float(cb[3])))
                            else:
                                pos_boxes.append((0, x1, y1, x2, y2))

                if not pos_boxes:
                    continue

                # 1. Positive grid windows across bounding envelope of positive annotations
                min_x = max(0, int(math.floor(min(b[1] for b in pos_boxes))) - 32)
                min_y = max(0, int(math.floor(min(b[2] for b in pos_boxes))) - 32)
                max_x = min(img_w, int(math.ceil(max(b[3] for b in pos_boxes))) + 32)
                max_y = min(img_h, int(math.ceil(max(b[4] for b in pos_boxes))) + 32)

                eff_w = min(tile_size, img_w)
                eff_h = min(tile_size, img_h)
                grid_windows: list[tuple[int, int, int, int]] = []
                seen_win: set[tuple[int, int]] = set()

                y_cursor = min_y
                while True:
                    row = max(0, min(img_h - eff_h, y_cursor))
                    x_cursor = min_x
                    while True:
                        col = max(0, min(img_w - eff_w, x_cursor))
                        if (col, row) not in seen_win:
                            seen_win.add((col, row))
                            grid_windows.append((col, row, eff_w, eff_h))
                        if col + eff_w >= max_x or eff_w >= img_w:
                            break
                        x_cursor += stride
                    if row + eff_h >= max_y or eff_h >= img_h:
                        break
                    y_cursor += stride

                pos_candidate_windows: list[tuple[tuple[int, int, int, int], list[tuple[int, float, float, float, float]], bool]] = []
                empty_grid_windows: list[tuple[int, int, int, int]] = []
                min_cov = 0.35 if mode == "zone" else 0.45

                for col, row, w, h in grid_windows:
                    lbls = _clip_yolo_labels(pos_boxes, col, row, w, h, min_cover=min_cov)
                    if lbls:
                        has_minority = any(c in (1, 2) for c, *_ in lbls)
                        pos_candidate_windows.append(((col, row, w, h), lbls, has_minority))
                    else:
                        empty_grid_windows.append((col, row, w, h))

                # Ensure every positive sample has at least 1 window if grid missed small datasets
                if not pos_candidate_windows:
                    for cid, x1, y1, x2, y2 in pos_boxes[:64]:
                        col, row, w, h = _clamp_window((x1 + x2) * 0.5, (y1 + y2) * 0.5, tile_size, img_w, img_h)
                        lbls = _clip_yolo_labels(pos_boxes, col, row, w, h, min_cover=0.25)
                        if lbls:
                            pos_candidate_windows.append(((col, row, w, h), lbls, cid in (1, 2)))

                # For clump mode with hundreds of dense tiles, keep 100% of minority-containing tiles + up to 340 evenly strided rice clump tiles
                if mode == "clump" and len(pos_candidate_windows) > 360:
                    min_wins = [item for item in pos_candidate_windows if item[2]]
                    maj_wins = [item for item in pos_candidate_windows if not item[2]]
                    keep_n = max(60, 360 - len(min_wins))
                    if len(maj_wins) > keep_n:
                        step_f = len(maj_wins) / float(keep_n)
                        maj_wins = [maj_wins[int(i * step_f)] for i in range(keep_n)]
                    pos_candidate_windows = min_wins + maj_wins

                for (col, row, w, h), lbls, has_minority in pos_candidate_windows:
                    rgb, valid = _read_rgb_window(src, col, row, w, h, bands=bands)
                    if float(np.mean(valid)) < 0.15:
                        continue
                    samples.append((rgb, lbls, "pos"))
                    pos_tiles_count += 1
                    total_box_instances += len(lbls)
                    # Oversample rare Grass / Partial Grass tiles via horizontal flip
                    if has_minority and len(minority_centers) < 120:
                        samples.append((np.fliplr(rgb).copy(), _flip_labels_h(lbls), "pos_min_flip"))
                        pos_tiles_count += 1
                        total_box_instances += len(lbls)

                # 2. Hard-Negative windows centered on user-rejected (`Loại bỏ`) boxes!
                seen_neg: set[tuple[int, int]] = set()
                neg_Repeat = 3 if (0 < len(neg_raw_boxes) < max(30, pos_tiles_count // 4)) else 1
                for nx1, ny1, nx2, ny2 in neg_raw_boxes:
                    col, row, w, h = _clamp_window((nx1 + nx2) * 0.5, (ny1 + ny2) * 0.5, tile_size, img_w, img_h)
                    key_q = (col // 32, row // 32)
                    if key_q in seen_neg:
                        continue
                    seen_neg.add(key_q)
                    rgb, valid = _read_rgb_window(src, col, row, w, h, bands=bands)
                    if float(np.mean(valid)) < 0.20:
                        continue
                    # Only positive boxes inside this window get labeled; the rejected object itself stays unlabeled (background)!
                    overlap_pos_lbls = _clip_yolo_labels(pos_boxes, col, row, w, h, min_cover=min_cov)
                    samples.append((rgb, overlap_pos_lbls, "hard_neg"))
                    hard_neg_tiles += 1
                    total_box_instances += len(overlap_pos_lbls)
                    if neg_Repeat >= 2:
                        samples.append((np.fliplr(rgb).copy(), _flip_labels_h(overlap_pos_lbls), "hard_neg_hflip"))
                        hard_neg_tiles += 1
                        total_box_instances += len(overlap_pos_lbls)
                    if neg_Repeat >= 3:
                        samples.append((np.flipud(rgb).copy(), _flip_labels_v(overlap_pos_lbls), "hard_neg_vflip"))
                        hard_neg_tiles += 1
                        total_box_instances += len(overlap_pos_lbls)

                # 3. Pure-background empty windows (from scanned polygon or empty grid cells with valid imagery)
                target_bg = max(4, min(40, pos_tiles_count // 8))
                polys = polygons_by_source.get(src_norm) or []
                rng.shuffle(empty_grid_windows)
                for col, row, w, h in empty_grid_windows:
                    if bg_empty_tiles >= target_bg:
                        break
                    if polys:
                        cx_g = col + w * 0.5
                        cy_g = row + h * 0.5
                        if not any(_point_in_poly(cx_g, cy_g, p) for p in polys):
                            continue
                    # Double-check 0 positive overlap at any threshold
                    if _clip_yolo_labels(pos_boxes, col, row, w, h, min_cover=0.05, min_px=1.0):
                        continue
                    rgb, valid = _read_rgb_window(src, col, row, w, h, bands=bands)
                    if float(np.mean(valid)) < 0.75 or _is_homogeneous_empty_window(rgb, valid):
                        continue
                    samples.append((rgb, [], "bg_empty"))
                    bg_empty_tiles += 1

        if not samples:
            raise ValueError(f"Không tạo được ô huấn luyện hợp lệ cho chế độ {mode}.")

        rng.shuffle(samples)
        n_total = len(samples)
        if n_total == 1:
            train_samples = samples
            val_samples = samples
        else:
            n_val = max(1, min(n_total - 1, int(round(n_total * 0.15))))
            val_samples = samples[:n_val]
            train_samples = samples[n_val:]

        for split_name, split_list in (("train", train_samples), ("val", val_samples)):
            img_dir = out_dir / "images" / split_name
            lbl_dir = out_dir / "labels" / split_name
            for idx, (rgb_arr, lbls, tag) in enumerate(split_list):
                stem = f"{mode}_{split_name}_{idx + 1:05d}_{tag}"
                Image.fromarray(rgb_arr).save(img_dir / f"{stem}.jpg", format="JPEG", quality=92)
                (lbl_dir / f"{stem}.txt").write_text(_format_yolo_txt(lbls), encoding="utf-8")

        yaml_path = _write_data_yaml(out_dir, classes)
        built[mode] = {
            "mode": mode,
            "data_yaml": str(yaml_path),
            "dataset_dir": str(out_dir),
            "tile_size": tile_size,
            "classes": classes,
            "train_tiles": len(train_samples),
            "val_tiles": len(val_samples),
            "positive_tiles": pos_tiles_count,
            "hard_negative_tiles": hard_neg_tiles,
            "background_empty_tiles": bg_empty_tiles,
            "total_box_instances": total_box_instances,
        }

    return built


def train_turbo_models(
    project_root: Path,
    output_dir: Path,
    mode: str = "both",
    epochs: int = 50,
    progress=None,
    cancelled=lambda: False,
) -> dict:
    """Build YOLO11 datasets from Ground Truth and train `turbo_zone` and/or `turbo_clump` on RTX GPU."""
    root = Path(project_root).resolve()
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if mode not in {"both", "zone", "clump"}:
        raise ValueError("Chế độ huấn luyện phải là 'both', 'zone' hoặc 'clump'.")
    epochs = max(1, min(300, int(epochs)))
    modes = ["zone", "clump"] if mode == "both" else [mode]

    gpu_py = _gpu_python(root)
    worker = _worker_script()
    if not gpu_py.is_file():
        raise ValueError(f"Không tìm thấy môi trường GPU Python tại {gpu_py}.")

    _report_progress(progress, 1, 100, "Đang kiểm tra mẫu dương & mẫu âm trong Ground Truth Dataset…")
    datasets = build_yolo_datasets(root, modes, progress=progress, cancelled=cancelled)

    cancel_file = out / ".cancel_train"
    cancel_file.unlink(missing_ok=True)
    runs_spec = []
    for m in modes:
        ds_info = datasets[m]
        runs_spec.append({
            "mode": m,
            "data_yaml": ds_info["data_yaml"],
            "out_dir": str(root / "models" / "turbo_yolo" / f"turbo_{m}"),
            "epochs": epochs,
            "imgsz": 640,
            "batch": 16,
            "classes": ds_info["classes"],
            "dataset_stats": {
                k: ds_info[k]
                for k in ("train_tiles", "val_tiles", "positive_tiles", "hard_negative_tiles", "background_empty_tiles", "total_box_instances")
            },
        })

    job_spec = {
        "project_root": str(root),
        "base_model": "yolo11s.pt",
        "cancel_file": str(cancel_file),
        "runs": runs_spec,
    }
    job_json = out / "train_job.json"
    _write_json(job_json, job_spec)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("HF_HUB_OFFLINE", None)
    env.pop("TRANSFORMERS_OFFLINE", None)

    _report_progress(
        progress,
        15,
        100,
        f"Đã chuẩn bị xong dữ liệu ({sum(d['train_tiles'] for d in datasets.values())} ô train, "
        f"{sum(d['hard_negative_tiles'] for d in datasets.values())} ô mẫu âm). Đang khởi động GPU RTX…",
    )

    proc = subprocess.Popen(
        [str(gpu_py), "-u", str(worker), "train", str(job_json)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(root),
    )

    stderr_lines: list[str] = []

    def _drain_stderr():
        if not proc.stderr:
            return
        for line in proc.stderr:
            stderr_lines.append(line.rstrip())
            if len(stderr_lines) > 80:
                stderr_lines.pop(0)

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()

    trained_results: dict = {}
    was_cancelled = False

    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            if cancelled() and not cancel_file.exists():
                cancel_file.write_text("cancel", encoding="utf-8")
            line = raw_line.strip()
            if not line.startswith("@UAV@"):
                continue
            event = json.loads(line[5:])
            ev_type = event.get("event")
            if ev_type == "started":
                _report_progress(progress, 16, 100, f"Đang huấn luyện YOLO11s-FP16 trên {event.get('gpu', 'GPU')}…")
            elif ev_type == "epoch":
                r_idx = int(event.get("run_index", 0))
                r_cnt = max(1, int(event.get("run_count", len(modes))))
                ep = int(event.get("epoch", 1))
                tot_ep = max(1, int(event.get("epochs", epochs)))
                frac = (r_idx + (ep / float(tot_ep))) / float(r_cnt)
                pct = min(98, max(16, int(round(16 + frac * 82))))
                m_label = "Chế độ Vùng (640px)" if event.get("mode") == "zone" else "Chế độ Khóm lẻ (~15cm)"
                map50_pct = round(float(event.get("mAP50", 0.0)) * 100.0, 1)
                loss_v = event.get("loss", 0.0)
                _report_progress(
                    progress,
                    pct,
                    100,
                    f"🚀 {m_label} · Epoch {ep}/{tot_ep} · mAP50: {map50_pct}% · Loss: {loss_v}",
                )
            elif ev_type == "cancelled":
                was_cancelled = True
                break
            elif ev_type == "completed":
                trained_results = event.get("results") or {}
    finally:
        if cancelled() and not cancel_file.exists():
            try:
                cancel_file.write_text("cancel", encoding="utf-8")
            except Exception:
                pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        err_thread.join(timeout=2)

    if was_cancelled or cancelled():
        summary = {"kind": "turbo_train", "status": "cancelled", "datasets": datasets, "models": trained_results}
        _write_json(out / "summary.json", summary)
        return summary

    if proc.returncode != 0 and not trained_results:
        tail = "\n".join(stderr_lines[-12:])
        raise RuntimeError(f"Huấn luyện Turbo YOLO11 thất bại (mã {proc.returncode}): {tail}")

    _report_progress(progress, 100, 100, "✅ Đã huấn luyện & xuất mô hình Turbo YOLO11 (.pt + .onnx) thành công!")
    summary = {
        "kind": "turbo_train",
        "status": "completed",
        "mode": mode,
        "epochs": epochs,
        "datasets": datasets,
        "models": trained_results,
    }
    _write_json(out / "summary.json", summary)
    return summary


def plan_turbo_detection(
    path: str,
    grid_config: dict,
    settings: dict,
    scope: str = "selected",
    tile_id: str = "tile_000001",
    regions=None,
):
    """Plan single-pass 640px (`turbo_zone`) or 512px (`turbo_clump`) windows — 1 GPU pass per tile."""
    engine = str((settings or {}).get("engine") or "turbo_zone")
    turbo_tile = 640 if engine == "turbo_zone" else 512
    eff_settings = copy.deepcopy(settings or {})
    eff_settings["engine"] = engine
    eff_settings["micro_size"] = turbo_tile
    eff_settings["micro_overlap"] = 0.20
    plan_dict, micro = plan_detection(path, grid_config, eff_settings, scope=scope, tile_id=tile_id, regions=regions)
    # YOLO predicts all classes simultaneously in 1 single pass per tile!
    plan_dict["query_count"] = int(plan_dict["micro_count"])
    plan_dict["engine"] = engine
    plan_dict["batch_size"] = 32
    return plan_dict, micro


def _sweep_nms_class_aware(raw_items: list[dict], iou_threshold: float = 0.45) -> list[dict]:
    """Fast O(N log N) sweep-line class-aware Non-Maximum Suppression capable of handling 250,000+ boxes in < 0.08s."""
    if len(raw_items) <= 1:
        return raw_items

    by_class: dict[str, list[dict]] = {}
    for item in raw_items:
        cls_key = str(item.get("sub_class") or item.get("label") or item.get("category") or "")
        by_class.setdefault(cls_key, []).append(item)

    kept_all: list[dict] = []
    for cls_key, items in by_class.items():
        n = len(items)
        if n <= 1:
            kept_all.extend(items)
            continue
        boxes = np.array([it["box"] for it in items], dtype=np.float32)
        scores = np.array([float(it.get("confidence_score") or 0.5) for it in items], dtype=np.float32)
        areas = np.maximum(1.0, (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))
        max_h = float(np.max(boxes[:, 3] - boxes[:, 1])) + 2.0

        # Bucket into horizontal spatial strips of height `max(256, 2 * max_h)` for fast local NMS
        strip_h = max(256.0, max_h * 2.0)
        order = np.argsort(-scores)
        suppressed = np.zeros(n, dtype=bool)
        strip_buckets: dict[int, list[int]] = {}

        for idx_i in order:
            i = int(idx_i)
            bx1, by1, bx2, by2 = boxes[i]
            s_min = int(by1 // strip_h)
            s_max = int(by2 // strip_h)
            is_dup = False
            for s_id in range(s_min, s_max + 1):
                cand_list = strip_buckets.get(s_id)
                if not cand_list:
                    continue
                for k in cand_list:
                    ix1 = max(bx1, boxes[k, 0])
                    iy1 = max(by1, boxes[k, 1])
                    ix2 = min(bx2, boxes[k, 2])
                    iy2 = min(by2, boxes[k, 3])
                    iw = ix2 - ix1
                    ih = iy2 - iy1
                    if iw > 0.0 and ih > 0.0:
                        inter = iw * ih
                        union = areas[i] + areas[k] - inter
                        if union > 0.0 and (inter / union) >= iou_threshold:
                            is_dup = True
                            break
                if is_dup:
                    break
            if not is_dup:
                kept_all.append(items[i])
                for s_id in range(s_min, s_max + 1):
                    strip_buckets.setdefault(s_id, []).append(i)

    kept_all.sort(key=lambda r: (round(r["box"][1] / 64.0), r["box"][0]))
    return kept_all


def render_lazy_review_image(directory: Path, requested_rel: str) -> Path | None:
    """Lazily render `review/object_XXXXXX_raw.png` or `_candidate.png` on demand if not pre-rendered during Turbo scan."""
    norm_rel = requested_rel.replace("\\", "/").lstrip("/")
    if not norm_rel.startswith("review/object_") or not norm_rel.endswith(("_raw.png", "_candidate.png")):
        return None
    obj_id = norm_rel.removeprefix("review/").removesuffix("_raw.png").removesuffix("_candidate.png")
    det_path = directory / "detections.json"
    if not det_path.is_file():
        return None
    data = json.loads(det_path.read_text(encoding="utf-8"))
    source_path = data.get("source")
    if not source_path or not Path(source_path).is_file():
        return None
    record = next((r for r in (data.get("records") or []) if r.get("id") == obj_id), None)
    if not record or not isinstance(record.get("box"), list) or len(record["box"]) != 4:
        return None

    (directory / "review").mkdir(parents=True, exist_ok=True)
    meta = data.get("metadata") or inspect_raster(source_path)
    raw = record["box"]
    pad = 16
    left = max(0, math.floor(raw[0]) - pad)
    top = max(0, math.floor(raw[1]) - pad)
    right = min(meta["width"], math.ceil(raw[2]) + pad)
    bottom = min(meta["height"], math.ceil(raw[3]) + pad)
    window = dict(col=left, row=top, width=max(4, right - left), height=max(4, bottom - top))
    with Image.open(io.BytesIO(preview_png(source_path, max_size=1600, window=window))) as src_img:
        image = src_img.convert("RGB")
    sx = image.width / window["width"]
    sy = image.height / window["height"]
    local = [(raw[0] - left) * sx, (raw[1] - top) * sy, (raw[2] - left) * sx, (raw[3] - top) * sy]

    before = image.copy()
    ImageDraw.Draw(before).rectangle(local, outline="#ffad33", width=3)
    raw_out = directory / "review" / f"{obj_id}_raw.png"
    before.save(raw_out, format="PNG")

    after = image.copy()
    draw = ImageDraw.Draw(after)
    draw.rectangle(local, outline="#ffad33", width=2)
    c_global = (record.get("refinement") or {}).get("clump_boxes_global") or []
    for cb in c_global:
        if isinstance(cb, list) and len(cb) == 4:
            cb_loc = [(cb[0] - left) * sx, (cb[1] - top) * sy, (cb[2] - left) * sx, (cb[3] - top) * sy]
            draw.rectangle(cb_loc, outline="#38ff82", width=2)
    cand = record.get("candidate_box")
    if isinstance(cand, list) and len(cand) == 4:
        cand_loc = [(cand[0] - left) * sx, (cand[1] - top) * sy, (cand[2] - left) * sx, (cand[3] - top) * sy]
        draw.rectangle(cand_loc, outline="#20e9ef", width=3)
    cand_out = directory / "review" / f"{obj_id}_candidate.png"
    after.save(cand_out, format="PNG")
    image.close()
    before.close()
    after.close()

    target = directory / norm_rel
    return target if target.is_file() else None


def run_turbo_detection(
    project: Path,
    path: str,
    output_dir: Path,
    grid_config: dict,
    settings: dict,
    scope: str = "selected",
    tile_id: str = "tile_000001",
    progress=None,
    cancelled=lambda: False,
    regions=None,
    sr_mode=None,
    spectral_mode: str = "auto",
    resume: bool = False,
) -> dict:
    """Zero-PNG SharedMemory FP16 Batch=32 YOLO11 inference across GeoTIFF windows."""
    root = Path(project).resolve()
    engine = str((settings or {}).get("engine") or "turbo_zone")
    mode = "zone" if engine == "turbo_zone" else "clump"
    weights_path = root / "models" / "turbo_yolo" / f"turbo_{mode}" / "best.pt"
    if not weights_path.is_file():
        raise ValueError(
            f"Mô hình {'Turbo Vùng' if mode == 'zone' else 'Turbo Khóm lẻ'} chưa được huấn luyện. "
            "Hãy chuyển sang Bước 04 → mục 02 bấm '🚀 Huấn luyện Mô hình Turbo' trước."
        )

    gpu_py = _gpu_python(root)
    worker = _worker_script()
    if not gpu_py.is_file():
        raise ValueError(f"Không tìm thấy môi trường GPU tại {gpu_py}.")

    plan, micro = plan_turbo_detection(path, grid_config, settings, scope=scope, tile_id=tile_id, regions=regions)
    eff_settings = plan["settings"]
    tile_size = int(eff_settings["micro_size"])
    batch_size = 32
    total_tiles = max(1, int(plan["query_count"]))

    ms_info = plan["metadata"].get("multispectral") or find_companion_multispectral(path)
    use_spectral = bool(ms_info and ms_info.get("available") and spectral_mode not in ("off", "rgb_only"))
    has_dem = find_companion_dem(path) is not None

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "review").mkdir(exist_ok=True)
    base = [grid_config["base_x"], grid_config["base_y"]]

    summary = dict(
        kind="detection",
        engine=engine,
        status="running",
        plan=plan,
        completed_queries=0,
        raw_count=0,
        count=0,
        multispectral_active=use_spectral,
        multispectral_bands=ms_info.get("band_names", []) if use_spectral else [],
        score_policy="YOLO11s-FP16 calibrated objectness * class confidence.",
        coverage_complete=False,
    )
    _write_json(output / "summary.json", summary)

    region_tasks = (
        micro
        if isinstance(micro, list)
        else [
            {
                "region_index": 1,
                "name": tile_id if scope == "selected" else "Toàn khu vực",
                "tile_id": tile_id,
                "region": plan["region"],
                "polygon": None,
                "categories": eff_settings["categories"],
                "micro": micro,
            }
        ]
    )

    shm = shared_memory.SharedMemory(create=True, size=batch_size * tile_size * tile_size * 3)
    shm_arr = np.ndarray((batch_size, tile_size, tile_size, 3), dtype=np.uint8, buffer=shm.buf)
    proc = None
    reader = None
    ms_readers: dict = {}
    scanned_windows: list[dict] = []
    completed_regions: list[int] = []
    raw_detections: list[dict] = []
    records: list[dict] = []
    done_tiles = 0
    t_start = time.monotonic()

    try:
        _report_progress(
            progress,
            0,
            total_tiles,
            f"⚡ Đang nạp YOLO11s-FP16 ({'Quét Vùng 640px' if mode == 'zone' else 'Khóm lẻ 512px'}) vào Tensor Cores RTX…",
            scope=scope,
            tile_id=tile_id,
        )
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [str(gpu_py), "-u", str(worker), "infer", str(root), mode, shm.name, str(batch_size), str(tile_size)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(root),
        )

        # Wait for ready handshake
        ready_msg = None
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.startswith("@UAV@"):
                ready_msg = json.loads(line[5:])
                break
        if not ready_msg or ready_msg.get("status") != "ready":
            err_out = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"Không khởi động được tiến trình GPU Turbo YOLO11: {err_out[-500:]}")

        reader = rasterio.open(path)
        rgb_bands = _select_rgb_bands(reader)
        if use_spectral:
            for b_name, b_path in (ms_info.get("bands") or {}).items():
                try:
                    ms_readers[b_name] = rasterio.open(b_path)
                except Exception:
                    pass

        batch_meta: list[dict] = []
        conf_thresh = 0.24 if mode == "zone" else 0.22

        def _flush_gpu_batch():
            nonlocal batch_meta
            if not batch_meta:
                return
            if cancelled():
                raise DetectionCancelled()
            req = {
                "count": len(batch_meta),
                "shapes": [[m["height"], m["width"]] for m in batch_meta],
                "conf": conf_thresh,
                "iou": 0.50 if mode == "zone" else 0.45,
                "max_det": 300 if mode == "zone" else 1500,
            }
            assert proc is not None and proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            reply = None
            for r_line in proc.stdout:
                if r_line.startswith("@UAV@"):
                    reply = json.loads(r_line[5:])
                    break
            if not reply or reply.get("status") != "ok":
                raise RuntimeError("Tiến trình GPU Turbo ngừng phản hồi khi quét Batch.")

            batch_preds = reply.get("results") or []
            for m_info, dets in zip(batch_meta, batch_preds):
                gx = m_info["col"]
                gy = m_info["row"]
                gw = m_info["width"]
                gh = m_info["height"]
                vmask = m_info["valid_mask"]
                poly = m_info["polygon"]
                req_cats = m_info["categories"]
                for det in dets:
                    lx1, ly1, lx2, ly2 = det["box"]
                    cx_l = min(gw - 1, max(0, int((lx1 + lx2) * 0.5)))
                    cy_l = min(gh - 1, max(0, int((ly1 + ly2) * 0.5)))
                    if vmask[cy_l, cx_l] == 0:
                        continue
                    cx_g = gx + (lx1 + lx2) * 0.5
                    cy_g = gy + (ly1 + ly2) * 0.5
                    if poly and not _point_in_poly(cx_g, cy_g, poly):
                        continue
                    lbl = str(det.get("label") or "Newly transplanted rice")
                    cat = _canonical_category(lbl, req_cats)
                    raw_detections.append({
                        "category": cat,
                        "label": lbl,
                        "sub_class": lbl,
                        "confidence_score": float(det.get("score") or 0.5),
                        "window_id": m_info["win_uid"],
                        "window": {"col": gx, "row": gy, "width": gw, "height": gh},
                        "region_name": m_info["region_name"],
                        "touches_window_edge": lx1 <= 1.5 or ly1 <= 1.5 or lx2 >= gw - 1.5 or ly2 >= gh - 1.5,
                        "box": [round(gx + lx1, 2), round(gy + ly1, 2), round(gx + lx2, 2), round(gy + ly2, 2)],
                    })
            batch_meta = []

        for task in region_tasks:
            if cancelled():
                raise DetectionCancelled()
            r_idx = int(task.get("region_index", 1))
            r_name = str(task.get("name") or f"Vùng {r_idx}")
            t_reg = task["region"]
            poly = task.get("polygon")
            req_cats = task.get("categories") or eff_settings["categories"]
            tiles_iter = task.get("active_tiles") if "active_tiles" in task else list(task["micro"].iter_tiles())

            for t in tiles_iter:
                if cancelled():
                    raise DetectionCancelled()
                gx = int(t_reg["col"] + t["col"])
                gy = int(t_reg["row"] + t["row"])
                gw = int(t["width"])
                gh = int(t["height"])
                win_uid = f"r{r_idx}_{t['id']}"
                win_entry = {"col": gx, "row": gy, "width": gw, "height": gh, "region_index": r_idx}
                scanned_windows.append(win_entry)

                rgb, valid_mask = _read_rgb_window(reader, gx, gy, gw, gh, bands=rgb_bands)
                done_tiles += 1
                if int(np.count_nonzero(valid_mask)) == 0 or _is_homogeneous_empty_window(rgb, valid_mask):
                    continue

                slot = len(batch_meta)
                shm_arr[slot].fill(0)
                shm_arr[slot, :gh, :gw, :] = rgb
                batch_meta.append({
                    "col": gx,
                    "row": gy,
                    "width": gw,
                    "height": gh,
                    "win_uid": win_uid,
                    "region_name": r_name,
                    "polygon": poly,
                    "categories": req_cats,
                    "valid_mask": valid_mask,
                })

                if len(batch_meta) >= batch_size:
                    _flush_gpu_batch()
                    elapsed = max(0.05, time.monotonic() - t_start)
                    speed = round(done_tiles / elapsed, 1)
                    _report_progress(
                        progress,
                        done_tiles,
                        total_tiles,
                        f"⚡ Đang quét Turbo Batch=32 ({done_tiles}/{total_tiles} ô · {speed} ô/giây) · {len(raw_detections)} phát hiện thô…",
                        active_window={
                            "col": gx, "row": gy, "width": gw, "height": gh,
                            "tile_id": win_uid, "region_index": r_idx, "region_name": r_name,
                        },
                        active_region_index=r_idx,
                        scanned_windows=scanned_windows[-5000:],
                        completed_regions=list(completed_regions),
                        live_count=len(raw_detections),
                    )

            _flush_gpu_batch()
            if r_idx not in completed_regions:
                completed_regions.append(r_idx)

        # Cross-tile NMS
        nms_iou = 0.45 if mode == "zone" else 0.40
        fused = _sweep_nms_class_aware(raw_detections, iou_threshold=nms_iou)

        _report_progress(
            progress,
            total_tiles,
            total_tiles,
            f"⚡ Đã quét GPU xong {total_tiles} ô trong {round(time.monotonic() - t_start, 1)}s! Đang đóng gói tọa độ RTK & chỉ số…",
            live_count=len(fused),
        )

        transform = plan["metadata"]["transform"]
        pre_render_limit = 60  # Page 1+ thumbnails ready immediately; remaining pages render lazily on view in < 10 ms!

        for idx, rec in enumerate(fused):
            if cancelled():
                raise DetectionCancelled()
            rec["id"] = f"object_{idx + 1:06d}"
            rec["review_status"] = "unreviewed"
            rec["spatial_raw"] = spatial_box(rec["box"], transform, base)
            rec["raw_image"] = f"review/{rec['id']}_raw.png"
            rec["candidate_image"] = f"review/{rec['id']}_candidate.png"

            if mode == "zone" and eff_settings.get("refinement", True) and len(fused) <= 2500:
                # Fast spectral/ExG clump counting & tight candidate box without saving thousands of PNGs
                b = rec["box"]
                pad = 12
                left = max(0, math.floor(b[0]) - pad)
                top = max(0, math.floor(b[1]) - pad)
                right = min(plan["metadata"]["width"], math.ceil(b[2]) + pad)
                bottom = min(plan["metadata"]["height"], math.ceil(b[3]) + pad)
                cw, ch = max(4, right - left), max(4, bottom - top)
                crop_rgb, _ = _read_rgb_window(reader, left, top, cw, ch, bands=rgb_bands)
                local_box = [b[0] - left, b[1] - top, b[2] - left, b[3] - top]

                spectral_indices = None
                if use_spectral:
                    bands_ms = read_spectral_window(
                        ms_info, transform, left, top, cw, ch, out_w=cw, out_h=ch, readers=ms_readers
                    )
                    if bands_ms:
                        spectral_indices = compute_spectral_indices(bands_ms)

                if spectral_indices and "ndvi" in spectral_indices:
                    cand = propose_spectral_refinement(crop_rgb, local_box, spectral_indices, eff_settings.get("padding", 0))
                    for k in ("ndvi_mean", "ndvi_max", "ndre_mean", "ndwi_mean"):
                        if k in cand:
                            rec[k] = cand[k]
                else:
                    cand = propose_refinement(crop_rgb, local_box, eff_settings.get("padding", 0))

                c_box = cand.pop("candidate_box", None)
                cand.pop("mask", None)
                c_local = cand.get("clump_boxes") or []
                if c_local:
                    cand["clump_boxes_global"] = [[cb[0] + left, cb[1] + top, cb[2] + left, cb[3] + top] for cb in c_local]
                rec["candidate_box"] = [c_box[0] + left, c_box[1] + top, c_box[2] + left, c_box[3] + top] if c_box else list(b)
                rec["refinement"] = cand
                if idx < pre_render_limit:
                    before = Image.fromarray(crop_rgb)
                    ImageDraw.Draw(before).rectangle(local_box, outline="#ffad33", width=3)
                    before.save(output / "review" / f"{rec['id']}_raw.png", format="PNG")
                    after = Image.fromarray(crop_rgb)
                    dr = ImageDraw.Draw(after)
                    dr.rectangle(local_box, outline="#ffad33", width=2)
                    for cb in c_local:
                        dr.rectangle(cb, outline="#38ff82", width=2)
                    if c_box:
                        dr.rectangle(c_box, outline="#20e9ef", width=3)
                    after.save(output / "review" / f"{rec['id']}_candidate.png", format="PNG")
                    before.close()
                    after.close()
            else:
                rec["candidate_box"] = list(rec["box"])
                rec["clump_count"] = 1
                rec["refinement"] = {"clump_count": 1, "estimated_plant_count": 1, "reason": "Turbo YOLO11 direct box."}
                if idx < pre_render_limit:
                    b = rec["box"]
                    pad = 16
                    left = max(0, math.floor(b[0]) - pad)
                    top = max(0, math.floor(b[1]) - pad)
                    right = min(plan["metadata"]["width"], math.ceil(b[2]) + pad)
                    bottom = min(plan["metadata"]["height"], math.ceil(b[3]) + pad)
                    cw, ch = max(4, right - left), max(4, bottom - top)
                    crop_rgb, _ = _read_rgb_window(reader, left, top, cw, ch, bands=rgb_bands)
                    local_box = [b[0] - left, b[1] - top, b[2] - left, b[3] - top]
                    im_raw = Image.fromarray(crop_rgb)
                    ImageDraw.Draw(im_raw).rectangle(local_box, outline="#ffad33", width=2)
                    im_raw.save(output / "review" / f"{rec['id']}_raw.png", format="PNG")
                    im_cand = Image.fromarray(crop_rgb)
                    ImageDraw.Draw(im_cand).rectangle(local_box, outline="#20e9ef", width=2)
                    im_cand.save(output / "review" / f"{rec['id']}_candidate.png", format="PNG")
                    im_raw.close()
                    im_cand.close()

        if has_dem and fused and len(fused) <= 5000:
            try:
                enrich_records_with_dem(fused, plan["metadata"])
                for r in fused:
                    r["_dem_checked"] = True
                    r["dem_z_ground"] = r.get("ground_elevation_m")
            except Exception:
                pass

        records = fused
        with _DETECTIONS_IO_LOCK:
            _save_results(
                output,
                dict(
                    revision=0,
                    source=str(path),
                    metadata=plan["metadata"],
                    base=base,
                    settings=eff_settings,
                    scope=scope,
                    region=plan["region"],
                    records=records,
                ),
            )

        elapsed_total = round(time.monotonic() - t_start, 2)
        summary.update(
            status="completed",
            coverage_complete=True,
            completed_queries=done_tiles,
            raw_count=len(raw_detections),
            count=len(records),
            elapsed_seconds=elapsed_total,
        )
    except DetectionCancelled:
        summary["status"] = "cancelled"
        summary["completed_queries"] = done_tiles
    except Exception as err:
        summary.update(status="failed", error=str(err))
    finally:
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.write(json.dumps({"command": "close"}) + "\n")
                    proc.stdin.flush()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
        if reader is not None:
            reader.close()
        for r_ms in ms_readers.values():
            try:
                r_ms.close()
            except Exception:
                pass
        try:
            shm.close()
            shm.unlink()
        except Exception:
            pass
        _write_json(output / "summary.json", summary)

    if summary["status"] == "failed":
        raise RuntimeError(summary["error"])

    # Render overview.jpg
    try:
        with Image.open(io.BytesIO(preview_png(path, window=plan["region"]))) as rgba:
            overview = rgba.convert("RGB")
        draw = ImageDraw.Draw(overview)
        r = plan["region"]
        for reg_info in plan.get("regions") or []:
            poly = reg_info.get("polygon")
            if poly and len(poly) >= 3:
                pts = [
                    ((p[0] - r["col"]) * overview.width / r["width"], (p[1] - r["row"]) * overview.height / r["height"])
                    for p in poly
                ]
                draw.line(pts + [pts[0]], fill=reg_info.get("color", "#ff4d4f"), width=3)
        for rec in records[:40000]:
            b = rec["box"]
            coords = [
                (b[0] - r["col"]) * overview.width / r["width"],
                (b[1] - r["row"]) * overview.height / r["height"],
                (b[2] - r["col"]) * overview.width / r["width"],
                (b[3] - r["row"]) * overview.height / r["height"],
            ]
            draw.rectangle(coords, outline="#38ff82" if mode == "clump" else "#ffbd33", width=1 if mode == "clump" else 2)
        overview.save(output / "overview.jpg", quality=92)
        overview.close()
    except Exception:
        pass

    _write_json(output / "summary.json", summary)
    return summary
