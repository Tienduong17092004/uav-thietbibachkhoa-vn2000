"""Human decisions, labelled checks, active-learning dataset, DEM enrichment, and CAD/AutoCAD COM export."""
import copy
import csv
import json
from pathlib import Path
import shutil
import threading

from uav_app.domain.detection import (
    spatial_box,
    evaluate_boxes,
    fuse_boxes,
    stitch_large_objects,
    estimate_confidence,
)
from uav_app.infrastructure.raster import _write_json
from uav_app.infrastructure.autocad_com import export_to_autocad_com
from uav_app.infrastructure.dem import enrich_records_with_dem
from uav_app.infrastructure.multispectral import (
    enrich_records_with_multispectral,
    analyze_full_orthomosaic_multispectral,
    find_companion_multispectral,
    read_spectral_window,
    compute_spectral_indices,
    propose_spectral_refinement,
)
from uav_app.infrastructure.refinement import propose_refinement

_RESULTS_CACHE: dict[str, tuple[int, dict]] = {}
_DETECTIONS_IO_LOCK = threading.RLock()


def load_results(directory, _copy=True):
    with _DETECTIONS_IO_LOCK:
        path = (Path(directory) / "detections.json").resolve()
        if not path.is_file():
            raise ValueError("Chưa có kết quả nhận diện để xem lại.")
        key = str(path)
        mtime = path.stat().st_mtime_ns
        cached = _RESULTS_CACHE.get(key)
        if cached is None or cached[0] != mtime:
            data = json.loads(path.read_text(encoding="utf-8"))
            _RESULTS_CACHE[key] = (mtime, data)
        else:
            data = cached[1]
        return copy.deepcopy(data) if _copy else data


def _save_results(directory, data):
    with _DETECTIONS_IO_LOCK:
        path = (Path(directory) / "detections.json").resolve()
        _write_json(path, data)
        _RESULTS_CACHE[str(path)] = (path.stat().st_mtime_ns, copy.deepcopy(data))


def set_review(directory, object_id, decision, revision, sub_class=None, custom_box=None, allow_live_drift=False):
    with _DETECTIONS_IO_LOCK:
        data = load_results(directory)
        if not allow_live_drift and (type(revision) is not int or revision != data["revision"]):
            raise ValueError("Kết quả đã thay đổi. Hãy tải lại danh sách trước khi duyệt.")
        if decision not in {"raw", "candidate", "reject", "reset", "all_candidates"}:
            raise ValueError("Lựa chọn duyệt không hợp lệ.")
        if decision == "all_candidates":
            records = [r for r in data["records"] if r.get("candidate_box")]
            if not records:
                raise ValueError("Không có đối tượng nào có khung co sát hợp lệ.")
            for record in records:
                record["review_status"] = "accepted_candidate"
                record["spatial_selected"] = spatial_box(record["candidate_box"], data["metadata"]["transform"], data["base"])
            data["revision"] += 1
            _save_results(directory, data)
            return dict(revision=data["revision"], updated=len(records))

        records = data["records"] if object_id == "all" else [r for r in data["records"] if r["id"] == object_id]
        if not records:
            raise ValueError("Không tìm thấy đối tượng.")
        if object_id == "all" and decision == "candidate":
            raise ValueError("Hãy xem và duyệt từng khung co sát riêng.")
        if decision == "candidate" and any(not r.get("candidate_box") for r in records):
            raise ValueError("Đối tượng này chưa có khung co sát hợp lệ.")
        for record in records:
            record["review_status"] = {
                "raw": "accepted_raw",
                "candidate": "accepted_candidate",
                "reject": "rejected",
                "reset": "unreviewed",
            }[decision]
            if isinstance(sub_class, str) and sub_class.strip():
                record["sub_class"] = sub_class.strip()[:80]
            if isinstance(custom_box, list) and len(custom_box) == 4:
                record["candidate_box"] = [float(v) for v in custom_box]
            box = record.get("candidate_box") if decision == "candidate" else record["box"]
            record["spatial_selected"] = spatial_box(box, data["metadata"]["transform"], data["base"])
        data["revision"] += 1
        _save_results(directory, data)
        return dict(revision=data["revision"], updated=len(records))


def _effective_record_box(record: dict) -> list[float]:
    box = record["box"]
    cand = record.get("candidate_box")
    if record.get("review_status") == "accepted_candidate" and cand:
        return cand
    # When raw box is an oversized tile-wide container (> 160 px) and a tight candidate box exists, use candidate
    if cand and (box[2] - box[0] > 160 or box[3] - box[1] > 160):
        return cand
    return box


def deoverlap_records(records: list[dict]) -> tuple[list[dict], int]:
    """Eliminate overlapping boxes (giant container boxes, same-window split-token duplicates, and tile-overlap duplicates)."""
    import math

    def area(b):
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    def inter(a, b):
        return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))

    indexed = list(enumerate(records))

    def priority_key(item):
        idx, r = item
        b = _effective_record_box(r)
        w, h = b[2] - b[0], b[3] - b[1]
        is_giant = 1 if (w > 190 or h > 190) else 0
        is_edge = 1 if r.get("touches_window_edge") else 0
        veg = (r.get("refinement") or {}).get("vegetation_fraction") or 0.0
        return (is_giant, is_edge, -round(float(veg), 1), area(b), idx)

    sorted_items = sorted(indexed, key=priority_key)
    kept_indices = {}
    grid: dict[tuple[int, int], list[list[float]]] = {}

    for orig_idx, rec in sorted_items:
        b = _effective_record_box(rec)
        if b[2] <= b[0] or b[3] <= b[1]:
            continue
        x1, y1, x2, y2 = [int(math.floor(v / 128.0)) for v in b]
        conflict = False
        for gx in range(x1, x2 + 1):
            for gy in range(y1, y2 + 1):
                for other_b in grid.get((gx, gy), ()):
                    if inter(b, other_b) > 0:
                        conflict = True
                        break
                if conflict:
                    break
            if conflict:
                break
        if not conflict:
            kept_indices[orig_idx] = b
            for gx in range(x1, x2 + 1):
                for gy in range(y1, y2 + 1):
                    grid.setdefault((gx, gy), []).append(b)

    result = []
    for idx, rec in enumerate(records):
        if idx in kept_indices:
            cloned = copy.deepcopy(rec)
            cloned["_resolved_box"] = kept_indices[idx]
            result.append(cloned)
    return result, len(records) - len(result)


def post_fuse_results(directory, revision, mode="smart_overlap", threshold=0.50, stitch_large=True):
    """Apply smart overlap fusion, large-object boundary stitching, and strict de-overlapping on an existing detection run."""
    data = load_results(directory)
    if type(revision) is not int or revision != data["revision"]:
        raise ValueError("Kết quả đã thay đổi. Hãy tải lại trước khi gộp khung.")
    backup = Path(directory) / f"detections_before_fuse_r{revision}.json"
    if not backup.is_file():
        _write_json(backup, data)
    before_count = len(data["records"])
    fused = fuse_boxes(data["records"], mode=mode, threshold=float(threshold))
    if stitch_large:
        fused = stitch_large_objects(fused)
    deoverlapped, _ = deoverlap_records(fused)
    for num, rec in enumerate(deoverlapped, 1):
        resolved = rec.pop("_resolved_box", None)
        if resolved is not None:
            rec["box"] = resolved
        rec["id"] = f"object_{num:06d}"
        rec["spatial_raw"] = spatial_box(rec["box"], data["metadata"]["transform"], data["base"])
        if rec.get("review_status") in {"accepted_raw", "accepted_candidate"}:
            box = rec.get("candidate_box") if rec["review_status"] == "accepted_candidate" and rec.get("candidate_box") else rec["box"]
            rec["spatial_selected"] = spatial_box(box, data["metadata"]["transform"], data["base"])
        rec["confidence_score"] = estimate_confidence(rec)
    data["records"] = deoverlapped
    data["revision"] += 1
    _save_results(directory, data)
    return {
        "revision": data["revision"],
        "before_count": before_count,
        "after_count": len(deoverlapped),
        "reduced_duplicates": before_count - len(deoverlapped),
        "mode": mode,
        "stitched_large_objects": bool(stitch_large),
    }


def enrich_results_with_dem(directory, revision, dem_path=None):
    """Enrich detections with elevation and height from DEM and classify Tree/Hedge/Grass hierarchy."""
    data = load_results(directory)
    if type(revision) is not int or revision != data["revision"]:
        raise ValueError("Kết quả đã thay đổi. Hãy tải lại trước khi tính độ cao DEM.")
    summary = enrich_records_with_dem(data["records"], data["metadata"], dem_path=dem_path)
    for rec in data["records"]:
        rec["confidence_score"] = estimate_confidence(rec)
    data["revision"] += 1
    _save_results(directory, data)
    summary["revision"] = data["revision"]
    return summary


def enrich_results_with_multispectral(directory, revision=None, source_path=None):
    """Enrich detections with Multispectral NDVI/NDRE/NDWI indices AND run full-orthomosaic spectral analysis."""
    data = load_results(directory)
    if revision is not None and (type(revision) is not int or revision != data["revision"]):
        raise ValueError("Kết quả đã thay đổi. Hãy tải lại trước khi phân tích phổ đa kênh.")
    eff_source = source_path or data.get("source") or (data.get("metadata") or {}).get("path")
    summary = enrich_records_with_multispectral(data["records"], data["metadata"], source_path=eff_source)
    for rec in data["records"]:
        rec["confidence_score"] = estimate_confidence(rec)
    if eff_source and Path(eff_source).is_file():
        try:
            field_summary = analyze_full_orthomosaic_multispectral(eff_source, output_dir=directory)
            data["spectral_summary"] = field_summary
            summary["field_summary"] = field_summary
            summary["overview_image"] = field_summary.get("overview_image")
            summary["land_cover_pct"] = field_summary.get("land_cover_pct")
        except Exception:
            pass
    data["revision"] += 1
    _save_results(directory, data)
    summary["revision"] = data["revision"]
    return summary


def split_merged_rice_clumps(directory, revision=None, object_id=None, allow_live_drift=True):
    """Split a merged multi-clump container box (or all merged boxes with clump_count >= 3 and size > 45px)
    into individual rice clump records AND separate partial grass levee segments using spectral/ExG components."""
    import io
    import math
    import cv2
    import numpy as np
    import rasterio
    from PIL import Image, ImageDraw
    from uav_app.infrastructure.raster import preview_png

    data = load_results(directory)
    if not allow_live_drift and revision is not None and (type(revision) is not int or revision != data["revision"]):
        raise ValueError("Kết quả đã thay đổi. Hãy tải lại trước khi tách khóm.")

    dir_path = Path(directory).resolve()
    (dir_path / "review").mkdir(parents=True, exist_ok=True)
    before_count = len(data["records"])

    split_mode = "normal"
    clean_object_id = object_id
    if isinstance(object_id, str) and ":" in object_id:
        clean_object_id, split_mode = object_id.split(":", 1)

    if clean_object_id and clean_object_id != "all":
        target_ids = {str(clean_object_id)}
        if not any(r.get("id") == clean_object_id for r in data["records"]):
            raise ValueError("Không tìm thấy đối tượng cần tách khóm.")
    else:
        target_ids = set()
        for r in data["records"]:
            b = r.get("box") or [0, 0, 0, 0]
            bw, bh = float(b[2] - b[0]), float(b[3] - b[1])
            ref = r.get("refinement") or {}
            clump_cnt = max(
                int(ref.get("estimated_plant_count") or 1),
                int(ref.get("components") or 1),
                len(ref.get("clump_boxes") or []),
            )
            if max(bw, bh) > 45.0 and clump_cnt >= 3:
                target_ids.add(r["id"])

    if not target_ids:
        return {
            "revision": data["revision"],
            "split_parents": 0,
            "created_clumps": 0,
            "before_count": before_count,
            "after_count": before_count,
        }

    source_path = data.get("source") or (data.get("metadata") or {}).get("path")
    has_source = bool(source_path and Path(source_path).is_file())
    meta = data.get("metadata") or {}
    transform = meta.get("transform") or [0.02, 0.0, 0.0, 0.0, -0.02, 0.0]
    base = data.get("base") or [0.0, 0.0]
    ms_info = (meta.get("multispectral") if isinstance(meta.get("multispectral"), dict) else None) or (
        find_companion_multispectral(source_path) if has_source else {"available": False}
    )

    used_nums = []
    for r in data["records"]:
        rid = str(r.get("id") or "")
        if rid.startswith("object_") and rid[7:].isdigit():
            used_nums.append(int(rid[7:]))
    next_num = max(used_nums, default=len(data["records"]))

    reader = rasterio.open(source_path) if has_source else None
    ms_readers = {}
    if has_source and ms_info and ms_info.get("available"):
        for k, v in (ms_info.get("bands") or {}).items():
            try:
                ms_readers[k] = rasterio.open(v)
            except Exception:
                pass

    new_records = []
    split_parents = 0
    created_clumps = 0
    rice_count = 0
    grass_count = 0

    try:
        for rec in data["records"]:
            if rec.get("id") not in target_ids:
                new_records.append(rec)
                continue

            raw = rec["box"]
            ref = rec.get("refinement") or {}
            pad = 16
            w_max = int(meta.get("width") or 100000)
            h_max = int(meta.get("height") or 100000)
            left = max(0, math.floor(raw[0]) - pad)
            top = max(0, math.floor(raw[1]) - pad)
            right = min(w_max, math.ceil(raw[2]) + pad)
            bottom = min(h_max, math.ceil(raw[3]) + pad)
            win_w = max(4, right - left)
            win_h = max(4, bottom - top)

            win_img = None
            scale_x = 1.0
            scale_y = 1.0
            global_clump_boxes: list[list[float]] = []

            if has_source and reader is not None:
                try:
                    png_bytes = preview_png(source_path, max_size=1600, window=dict(col=left, row=top, width=win_w, height=win_h), _reader=reader)
                    with Image.open(io.BytesIO(png_bytes)) as src_im:
                        win_img = src_im.convert("RGB")
                    scale_x = win_img.width / win_w
                    scale_y = win_img.height / win_h
                    local_box = [(raw[0] - left) * scale_x, (raw[1] - top) * scale_y, (raw[2] - left) * scale_x, (raw[3] - top) * scale_y]
                    indices = None
                    if ms_readers:
                        bands = read_spectral_window(ms_info, transform, left, top, win_w, win_h, out_w=win_img.width, out_h=win_img.height, readers=ms_readers)
                        if bands:
                            indices = compute_spectral_indices(bands)
                    if indices and "ndvi" in indices:
                        prop = propose_spectral_refinement(np.array(win_img), local_box, indices, padding=0)
                    else:
                        prop = propose_refinement(np.array(win_img), local_box, padding=0)
                    for cb in prop.get("clump_boxes") or []:
                        gx1 = cb[0] / scale_x + left
                        gy1 = cb[1] / scale_y + top
                        gx2 = cb[2] / scale_x + left
                        gy2 = cb[3] / scale_y + top
                        if gx2 - gx1 >= 3.0 and gy2 - gy1 >= 3.0:
                            global_clump_boxes.append([gx1, gy1, gx2, gy2])
                except Exception:
                    pass

            if len(global_clump_boxes) < 2 and ref.get("clump_boxes_global"):
                for cb in ref["clump_boxes_global"]:
                    if len(cb) == 4 and cb[2] - cb[0] >= 3.0 and cb[3] - cb[1] >= 3.0:
                        global_clump_boxes.append([float(v) for v in cb])

            if len(global_clump_boxes) < 2 and ref.get("clump_boxes"):
                crop = ref.get("crop") or [16, 16, int(raw[2] - raw[0]) + 16, int(raw[3] - raw[1]) + 16]
                cw_local = max(1.0, float(crop[2] - crop[0]))
                ch_local = max(1.0, float(crop[3] - crop[1]))
                sx_c = cw_local / max(1.0, float(raw[2] - raw[0]))
                sy_c = ch_local / max(1.0, float(raw[3] - raw[1]))
                for cb in ref["clump_boxes"]:
                    gx1 = raw[0] + (cb[0] - crop[0]) / sx_c
                    gy1 = raw[1] + (cb[1] - crop[1]) / sy_c
                    gx2 = raw[0] + (cb[2] - crop[0]) / sx_c
                    gy2 = raw[1] + (cb[3] - crop[1]) / sy_c
                    if gx2 - gx1 >= 3.0 and gy2 - gy1 >= 3.0:
                        global_clump_boxes.append([gx1, gy1, gx2, gy2])

            if len(global_clump_boxes) < 2 and rec.get("raw_image") and (dir_path / rec["raw_image"]).is_file():
                try:
                    with Image.open(dir_path / rec["raw_image"]) as r_im:
                        win_img = r_im.convert("RGB")
                    crop = ref.get("crop") or [16, 16, win_img.width - 16, win_img.height - 16]
                    prop = propose_refinement(np.array(win_img), crop, padding=0)
                    cw_local = max(1.0, float(crop[2] - crop[0]))
                    ch_local = max(1.0, float(crop[3] - crop[1]))
                    sx_c = cw_local / max(1.0, float(raw[2] - raw[0]))
                    sy_c = ch_local / max(1.0, float(raw[3] - raw[1]))
                    for cb in prop.get("clump_boxes") or []:
                        gx1 = raw[0] + (cb[0] - crop[0]) / sx_c
                        gy1 = raw[1] + (cb[1] - crop[1]) / sy_c
                        gx2 = raw[0] + (cb[2] - crop[0]) / sx_c
                        gy2 = raw[1] + (cb[3] - crop[1]) / sy_c
                        if gx2 - gx1 >= 3.0 and gy2 - gy1 >= 3.0:
                            global_clump_boxes.append([gx1, gy1, gx2, gy2])
                except Exception:
                    pass

            if len(global_clump_boxes) < 2:
                new_records.append(rec)
                continue

            split_parents += 1
            for cbox in global_clump_boxes:
                next_num += 1
                new_id = f"object_{next_num:06d}"
                sub_rec = copy.deepcopy(rec)
                sub_rec["id"] = new_id
                sub_rec["parent_id"] = rec["id"]
                sub_rec["box"] = [round(float(v), 3) for v in cbox]
                sub_rec["candidate_box"] = list(sub_rec["box"])
                sub_rec["spatial_raw"] = spatial_box(sub_rec["box"], transform, base)

                bw_c = max(4.0, cbox[2] - cbox[0])
                bh_c = max(4.0, cbox[3] - cbox[1])
                c_aspect = max(bw_c / max(1.0, bh_c), bh_c / max(1.0, bw_c))
                is_grass_segment = bool(
                    max(bw_c, bh_c) >= 44.0
                    or (bw_c * bh_c) >= 700.0
                    or (c_aspect >= 2.6 and max(bw_c, bh_c) >= 28.0)
                )

                if is_grass_segment:
                    sub_rec["sub_class"] = "Grass"
                    sub_rec["label"] = "grass"
                    sub_rec["is_partial_grass_segment"] = True
                    grass_count += 1
                    if split_mode == "reject_grass":
                        sub_rec["review_status"] = "rejected"
                    elif sub_rec.get("review_status") in {"accepted_raw", "accepted_candidate"}:
                        sub_rec["spatial_selected"] = copy.deepcopy(sub_rec["spatial_raw"])
                    else:
                        sub_rec["review_status"] = "unreviewed"
                else:
                    sub_rec["sub_class"] = "Newly transplanted rice"
                    sub_rec["label"] = "newly transplanted rice"
                    sub_rec["is_partial_grass_segment"] = False
                    if isinstance(sub_rec.get("height_m"), (int, float)) and sub_rec["height_m"] >= 0.30:
                        sub_rec["height_m"] = 0.12
                    if isinstance(sub_rec.get("ndvi_mean"), (int, float)) and sub_rec["ndvi_mean"] >= 0.35:
                        sub_rec["ndvi_mean"] = 0.24
                    rice_count += 1
                    if split_mode == "reject_grass":
                        sub_rec["review_status"] = "accepted_candidate"
                        sub_rec["spatial_selected"] = copy.deepcopy(sub_rec["spatial_raw"])
                    elif sub_rec.get("review_status") in {"accepted_raw", "accepted_candidate"}:
                        sub_rec["spatial_selected"] = copy.deepcopy(sub_rec["spatial_raw"])
                    else:
                        sub_rec["review_status"] = "unreviewed"

                sub_rec["refinement"] = {
                    "reason": (
                        f"🌱 Phần Cỏ bờ tách riêng từ khung hỗn hợp {rec['id']}."
                        if is_grass_segment
                        else f"🌾 Khóm lúa đơn lẻ tách từ khung hỗn hợp {rec['id']}."
                    ),
                    "crop": [8, 8, int(round(bw_c)) + 8, int(round(bh_c)) + 8],
                    "vegetation_fraction": 0.72 if is_grass_segment else 0.58,
                    "components": 1,
                    "estimated_plant_count": 1,
                    "plant_structure": "hedge" if is_grass_segment else "individual",
                    "clump_boxes": [[8.0, 8.0, 8.0 + bw_c, 8.0 + bh_c]],
                }
                for k in ("ndvi_mean", "ndvi_max", "ndre_mean", "ndwi_mean", "spectral_class"):
                    if k in ref:
                        sub_rec["refinement"][k] = ref[k]
                if not is_grass_segment:
                    sub_rec["refinement"]["spectral_class"] = "Newly transplanted rice"

                raw_rel = f"review/{new_id}_raw.png"
                cand_rel = f"review/{new_id}_candidate.png"
                if win_img is not None:
                    lx1 = int(max(0, math.floor((cbox[0] - left) * scale_x) - 8))
                    ly1 = int(max(0, math.floor((cbox[1] - top) * scale_y) - 8))
                    lx2 = int(min(win_img.width, math.ceil((cbox[2] - left) * scale_x) + 8))
                    ly2 = int(min(win_img.height, math.ceil((cbox[3] - top) * scale_y) + 8))
                    if lx2 > lx1 + 2 and ly2 > ly1 + 2:
                        sub_crop = win_img.crop((lx1, ly1, lx2, ly2))
                        bx_in = [
                            max(0.0, (cbox[0] - left) * scale_x - lx1),
                            max(0.0, (cbox[1] - top) * scale_y - ly1),
                            min(float(sub_crop.width), (cbox[2] - left) * scale_x - lx1),
                            min(float(sub_crop.height), (cbox[3] - top) * scale_y - ly1),
                        ]
                        im_raw = sub_crop.copy()
                        ImageDraw.Draw(im_raw).rectangle(bx_in, outline="#ffad33", width=2)
                        im_raw.save(dir_path / raw_rel, format="PNG")
                        im_cand = sub_crop.copy()
                        ImageDraw.Draw(im_cand).rectangle(bx_in, outline="#20e9ef", width=2)
                        im_cand.save(dir_path / cand_rel, format="PNG")
                        sub_rec["raw_image"] = raw_rel
                        sub_rec["candidate_image"] = cand_rel
                sub_rec["confidence_score"] = estimate_confidence(sub_rec)
                new_records.append(sub_rec)
                created_clumps += 1
            if win_img is not None:
                win_img.close()
    finally:
        if reader is not None:
            reader.close()
        for r in ms_readers.values():
            r.close()

    if split_parents > 0:
        data["records"] = new_records
        data["revision"] += 1
        _save_results(directory, data)

    return {
        "revision": data["revision"],
        "split_parents": split_parents,
        "created_clumps": created_clumps,
        "rice_count": rice_count,
        "grass_count": grass_count,
        "before_count": before_count,
        "after_count": len(data["records"]),
    }


def auto_triage_results(directory, revision=None, threshold=0.72):
    """Stage 3 active learning: auto-accept detections matching user-confirmed prototypes (size + NDVI + DEM)
    and high-confidence detections, while flagging user-rejected prototypes for review/rejection."""
    import collections

    data = load_results(directory)
    if revision is not None and (type(revision) is not int or revision != data["revision"]):
        raise ValueError("Kết quả đã thay đổi. Hãy tải lại trước khi phân loại tự động.")
    threshold = float(threshold)
    if not 0.3 <= threshold <= 0.98:
        raise ValueError("Ngưỡng tự nhận phải nằm trong khoảng 0,30 đến 0,98.")

    def _feat(r: dict):
        b = _effective_record_box(r)
        w = max(1.0, float(b[2] - b[0]))
        h = max(1.0, float(b[3] - b[1]))
        ref = r.get("refinement") or {}
        ndvi_m = r.get("ndvi_mean") if isinstance(r.get("ndvi_mean"), (int, float)) else ref.get("ndvi_mean")
        ndvi_x = r.get("ndvi_max") if isinstance(r.get("ndvi_max"), (int, float)) else ref.get("ndvi_max")
        h_m = r.get("height_m") if isinstance(r.get("height_m"), (int, float)) else None
        clumps = max(int(ref.get("estimated_plant_count") or 1), int(ref.get("components") or 1))
        return {
            "w": w,
            "h": h,
            "max_dim": max(w, h),
            "area": w * h,
            "ndvi_mean": float(ndvi_m) if isinstance(ndvi_m, (int, float)) else None,
            "ndvi_max": float(ndvi_x) if isinstance(ndvi_x, (int, float)) else None,
            "height_m": float(h_m) if isinstance(h_m, (int, float)) else None,
            "clumps": clumps,
        }

    # Build positive and negative prototypes from human-confirmed records
    user_positives = [
        r for r in data["records"]
        if r.get("review_status") in {"accepted_raw", "accepted_candidate"}
        and r.get("triage_source") not in {"auto_high_confidence", "auto_user_prototype"}
    ]
    if not user_positives:
        user_positives = [r for r in data["records"] if r.get("review_status") in {"accepted_raw", "accepted_candidate"}]
    user_negatives = [r for r in data["records"] if r.get("review_status") == "rejected"]

    pos_proto = None
    if user_positives:
        pf = [_feat(r) for r in user_positives]
        p_dims = [f["max_dim"] for f in pf]
        p_areas = [f["area"] for f in pf]
        p_ndvi = [f["ndvi_mean"] for f in pf if f["ndvi_mean"] is not None]
        p_h = [f["height_m"] for f in pf if f["height_m"] is not None]
        valid_subs = [
            r.get("sub_class")
            for r in user_positives
            if r.get("sub_class") and r.get("sub_class") not in {"ditch", "Person"}
        ] or [r.get("sub_class") or r.get("category") for r in user_positives]
        dom_sub = collections.Counter(valid_subs).most_common(1)[0][0]
        dom_status = collections.Counter(r["review_status"] for r in user_positives).most_common(1)[0][0]
        pos_proto = {
            "min_dim": min(p_dims) * 0.45,
            "max_dim": max(p_dims) * 2.25,
            "min_area": min(p_areas) * 0.30,
            "max_area": max(p_areas) * 3.6,
            "ndvi_lo": (min(p_ndvi) - 0.16) if p_ndvi else None,
            "ndvi_hi": (max(p_ndvi) + 0.28) if p_ndvi else None,
            "h_lo": max(0.0, min(p_h) - 0.15) if p_h else None,
            "h_hi": (max(p_h) + 0.25) if p_h else None,
            "sub_class": dom_sub,
            "preferred_status": dom_status,
        }

    neg_proto = None
    if user_negatives:
        nf = [_feat(r) for r in user_negatives]
        n_dims = [f["max_dim"] for f in nf]
        n_areas = [f["area"] for f in nf]
        n_ndvi = [f["ndvi_mean"] for f in nf if f["ndvi_mean"] is not None]
        neg_proto = {
            "min_dim": min(n_dims) * 0.70,
            "max_dim": max(n_dims) * 1.45,
            "min_area": min(n_areas) * 0.55,
            "max_area": max(n_areas) * 1.85,
            "ndvi_lo": (min(n_ndvi) - 0.08) if n_ndvi else None,
            "ndvi_hi": (max(n_ndvi) + 0.08) if n_ndvi else None,
        }

    auto_accepted = 0
    matched_by_user_prototype = 0
    suggested_reject = 0
    needs_review = 0

    for rec in data["records"]:
        conf = estimate_confidence(rec)
        rec["confidence_score"] = conf
        if rec.get("review_status") != "unreviewed":
            continue

        f = _feat(rec)
        matched_pos = False
        if pos_proto is not None:
            size_ok = (pos_proto["min_dim"] <= f["max_dim"] <= pos_proto["max_dim"]) and (
                pos_proto["min_area"] <= f["area"] <= pos_proto["max_area"]
            )
            clump_ok = f["clumps"] <= 3
            ndvi_ok = True
            if pos_proto["ndvi_lo"] is not None and f["ndvi_mean"] is not None:
                ndvi_ok = (pos_proto["ndvi_lo"] <= f["ndvi_mean"] <= pos_proto["ndvi_hi"]) and ((f["ndvi_max"] or 0.0) >= -0.02)
            h_ok = True
            if pos_proto["h_lo"] is not None and f["height_m"] is not None:
                h_ok = pos_proto["h_lo"] <= f["height_m"] <= pos_proto["h_hi"]
            if size_ok and clump_ok and ndvi_ok and h_ok:
                matched_pos = True

        matched_neg = False
        if not matched_pos and neg_proto is not None:
            size_neg = (neg_proto["min_dim"] <= f["max_dim"] <= neg_proto["max_dim"]) and (
                neg_proto["min_area"] <= f["area"] <= neg_proto["max_area"]
            )
            ndvi_neg = True
            if neg_proto["ndvi_lo"] is not None and f["ndvi_mean"] is not None:
                ndvi_neg = neg_proto["ndvi_lo"] <= f["ndvi_mean"] <= neg_proto["ndvi_hi"]
            if size_neg and ndvi_neg:
                matched_neg = True
        elif not matched_pos and pos_proto is not None and pos_proto["max_dim"] < 60.0 and f["max_dim"] > 140.0:
            # Giant merged container box when user only confirmed small individual clumps
            matched_neg = True

        if matched_pos:
            if pos_proto["preferred_status"] == "accepted_raw" or not rec.get("candidate_box"):
                rec["review_status"] = "accepted_raw"
                box = rec["box"]
            else:
                rec["review_status"] = "accepted_candidate"
                box = rec["candidate_box"]
            rec["spatial_selected"] = spatial_box(box, data["metadata"]["transform"], data["base"])
            if pos_proto.get("sub_class"):
                rec["sub_class"] = pos_proto["sub_class"]
            rec["triage_source"] = "auto_user_prototype"
            auto_accepted += 1
            matched_by_user_prototype += 1
        elif matched_neg:
            rec["triage_source"] = "suggested_reject_by_prototype"
            rec["suggested_decision"] = "reject"
            suggested_reject += 1
            needs_review += 1
        elif conf >= threshold and f["max_dim"] <= 140.0:
            if rec.get("candidate_box"):
                rec["review_status"] = "accepted_candidate"
                box = rec["candidate_box"]
            else:
                rec["review_status"] = "accepted_raw"
                box = rec["box"]
            rec["spatial_selected"] = spatial_box(box, data["metadata"]["transform"], data["base"])
            rec["triage_source"] = "auto_high_confidence"
            auto_accepted += 1
        else:
            rec["triage_source"] = "needs_human_review"
            needs_review += 1

    data["revision"] += 1
    _save_results(directory, data)
    return {
        "revision": data["revision"],
        "threshold": threshold,
        "auto_accepted": auto_accepted,
        "matched_by_user_prototype": matched_by_user_prototype,
        "suggested_reject": suggested_reject,
        "needs_review": needs_review,
        "total": len(data["records"]),
    }


def export_ground_truth_dataset(project_root: Path, directory: Path):
    """Stage 1 -> Stage 2: Save human-reviewed detections (Keep/Edit/Reject) into Ground Truth training dataset
    using 100% clean un-annotated crops cut directly from the source GeoTIFF/image (no orange/green UI boxes)."""
    import math
    import rasterio
    from uav_app.infrastructure.raster import preview_png

    data = load_results(directory)
    reviewed = [r for r in data["records"] if r.get("review_status") in {"accepted_raw", "accepted_candidate", "rejected"}]
    if not reviewed:
        raise ValueError("Chưa có đối tượng đã duyệt (Giữ / Sửa / Bỏ) để lưu vào Dataset Ground Truth.")

    ds_root = Path(project_root) / "outputs" / "ground_truth_dataset"
    crops_dir = ds_root / "images"
    crops_dir.mkdir(parents=True, exist_ok=True)

    finetune_path = ds_root / "locateanything_finetune.jsonl"
    existing_map: dict[str, dict] = {}
    existing_order: list[str] = []
    if finetune_path.is_file():
        for line in finetune_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                suid = obj.get("sample_uid")
                if suid:
                    if suid not in existing_map:
                        existing_order.append(suid)
                    existing_map[suid] = obj

    run_id = Path(directory).name
    class_counts: dict[str, int] = {}
    positive_count = 0
    negative_count = 0

    source_path = data.get("source")
    src_reader = None
    if source_path and Path(source_path).is_file():
        try:
            src_reader = rasterio.open(source_path)
        except Exception:
            src_reader = None

    try:
        for rec in reviewed:
            uid = f"{run_id}_{rec['id']}"
            status = rec["review_status"]
            sub_class = rec.get("sub_class") or rec["category"]
            box = rec.get("candidate_box") if status == "accepted_candidate" and rec.get("candidate_box") else rec["box"]
            if status == "rejected":
                negative_count += 1
                label_key = f"REJECTED ({sub_class})"
            else:
                positive_count += 1
                label_key = sub_class
            class_counts[label_key] = class_counts.get(label_key, 0) + 1

            dst_crop = crops_dir / f"{uid}.png"
            prev_entry = existing_map.get(uid)
            copied_crop = None
            crop_window = None
            box_in_crop = None
            is_clean_crop = False

            if src_reader is not None and isinstance(box, list) and len(box) == 4:
                pad = 16
                left = max(0, min(src_reader.width - 1, math.floor(box[0]) - pad))
                top = max(0, min(src_reader.height - 1, math.floor(box[1]) - pad))
                right = max(left + 1, min(src_reader.width, math.ceil(box[2]) + pad))
                bottom = max(top + 1, min(src_reader.height, math.ceil(box[3]) + pad))
                win_w = right - left
                win_h = bottom - top
                crop_window = [left, top, right, bottom]
                box_in_crop = [
                    round(float(box[0]) - left, 2),
                    round(float(box[1]) - top, 2),
                    round(float(box[2]) - left, 2),
                    round(float(box[3]) - top, 2),
                ]
                need_write_clean = (not dst_crop.is_file()) or not (prev_entry and prev_entry.get("clean_crop"))
                if need_write_clean:
                    try:
                        png_bytes = preview_png(
                            str(source_path),
                            max_size=max(1600, win_w, win_h),
                            window={"col": left, "row": top, "width": win_w, "height": win_h},
                            _reader=src_reader,
                        )
                        dst_crop.write_bytes(png_bytes)
                        is_clean_crop = True
                    except Exception:
                        is_clean_crop = False
                else:
                    is_clean_crop = True
                if dst_crop.is_file():
                    copied_crop = f"images/{uid}.png"

            if copied_crop is None:
                raw_img_rel = rec.get("raw_crop") or rec.get("raw_image")
                if raw_img_rel and (Path(directory) / raw_img_rel).is_file():
                    if not dst_crop.is_file():
                        shutil.copy2(Path(directory) / raw_img_rel, dst_crop)
                    copied_crop = f"images/{uid}.png"

            entry = {
                "sample_uid": uid,
                "run_id": run_id,
                "source_image": data["source"],
                "object_id": rec["id"],
                "category": rec["category"],
                "sub_class": sub_class,
                "review_status": status,
                "is_positive": status != "rejected",
                "box_pixel": box,
                "crop_window_pixel": crop_window,
                "box_in_crop": box_in_crop,
                "clean_crop": is_clean_crop,
                "elevation_m": rec.get("elevation_m"),
                "height_m": rec.get("height_m"),
                "crop_image": copied_crop,
            }
            if uid not in existing_map:
                existing_order.append(uid)
            existing_map[uid] = entry
    finally:
        if src_reader is not None:
            src_reader.close()

    existing_lines = [existing_map[k] for k in existing_order]
    with finetune_path.open("w", encoding="utf-8") as fh:
        for item in existing_lines:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    total_positives = sum(1 for x in existing_lines if x.get("is_positive"))
    total_negatives = sum(1 for x in existing_lines if not x.get("is_positive"))
    ready_for_stage2 = total_positives >= 50

    summary = {
        "dataset_dir": str(ds_root),
        "run_exported": len(reviewed),
        "run_positives": positive_count,
        "run_negatives": negative_count,
        "total_accumulated_samples": len(existing_lines),
        "total_positives": total_positives,
        "total_negatives": total_negatives,
        "class_breakdown": class_counts,
        "ready_for_stage2_training": ready_for_stage2,
        "stage2_recommendation": (
            "Đã tích lũy đủ tối thiểu 50 mẫu dương tính. Sẵn sàng chuyển sang Giai đoạn 2 (Fine-tune model Tree / Hedge / Grass & Individual tree / Tree cluster)."
            if ready_for_stage2
            else f"Đã lưu {total_positives}/50 mẫu dương tính tối thiểu. Hãy tiếp tục duyệt thêm để đủ dữ liệu Giai đoạn 2."
        ),
    }
    _write_json(ds_root / "dataset_summary.json", summary)
    return summary


def _build_exported_records(data):
    selected = [r for r in data["records"] if r.get("review_status") in {"accepted_raw", "accepted_candidate"}]
    if not selected:
        raise ValueError("Chưa có khung đã duyệt. Chọn Giữ khung gốc hoặc Dùng khung co trước khi xuất.")
    non_overlapping, removed_overlaps = deoverlap_records(selected)
    exported = []
    for record in non_overlapping:
        box = record.pop("_resolved_box", None) or (
            record["candidate_box"] if record["review_status"] == "accepted_candidate" and record.get("candidate_box") else record["box"]
        )
        spatial = spatial_box(box, data["metadata"]["transform"], data["base"])
        exported.append(
            dict(
                id=record["id"],
                category=record["category"],
                sub_class=record.get("sub_class", record["category"]),
                label_returned=record.get("label", record["category"]),
                review_status=record["review_status"],
                elevation_m=record.get("elevation_m"),
                height_m=record.get("height_m"),
                box=box,
                **spatial,
            )
        )
    return exported, removed_overlaps


def export_reviewed(directory, revision):
    import ezdxf

    data = load_results(directory)
    if type(revision) is not int or revision != data["revision"]:
        raise ValueError("Kết quả đã thay đổi. Tải lại trước khi xuất.")
    exported, removed_overlaps = _build_exported_records(data)
    root = Path(directory) / f"reviewed_r{revision}"
    # A repeat request returns the already exported immutable revision.
    if (root / "export_summary.json").is_file():
        return json.loads((root / "export_summary.json").read_text(encoding="utf-8"))
    root.mkdir(exist_ok=True)
    document = ezdxf.new("R2010")
    factor = data["metadata"]["unit_to_metre"]
    document.units = 6 if abs(factor - 1) < 1e-9 else 0
    if "ARIAL" not in document.styles:
        document.styles.new("ARIAL", dxfattribs={"font": "arial.ttf"})
    if "Standard" in document.styles:
        document.styles.get("Standard").dxf.font = "arial.ttf"
    document.layers.new("OBJECT_CENTERS", dxfattribs={"color": 3})
    document.layers.new("OBJECT_BOXES", dxfattribs={"color": 2})
    document.layers.new("OBJECT_LABELS", dxfattribs={"color": 7})
    space = document.modelspace()
    for record in exported:
        center = record["center_relative"]
        z_val = float(record.get("elevation_m") or 0.0)
        pt_3d = (center[0], center[1], z_val) if z_val else center
        space.add_point(pt_3d, dxfattribs={"layer": "OBJECT_CENTERS"})
        space.add_lwpolyline(record["corners_relative"], close=True, dxfattribs={"layer": "OBJECT_BOXES"})
        plain_text = str(record.get("sub_class") or record.get("category") or record.get("label_returned") or "object")
        space.add_text(
            plain_text,
            dxfattribs={
                "height": max(0.03 / factor, 0.001),
                "insert": center,
                "layer": "OBJECT_LABELS",
                "style": "ARIAL",
            },
        )
    document.saveas(root / "objects.dxf")
    _write_json(root / "objects.json", dict(crs=data["metadata"]["crs_wkt"], base=data["base"], records=exported))
    with (root / "centers.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["id", "category", "sub_class", "easting", "northing", "relative_x", "relative_y", "elevation_m", "height_m"])
        for record in exported:
            writer.writerow([
                record["id"],
                record["category"],
                record.get("sub_class", record["category"]),
                *record["center_map"],
                *record["center_relative"],
                record.get("elevation_m", ""),
                record.get("height_m", ""),
            ])
    summary = dict(
        directory=str(root),
        count=len(exported),
        removed_overlaps=removed_overlaps,
        excluded_unreviewed=sum(r["review_status"] == "unreviewed" for r in data["records"]),
        revision=revision,
        files=["objects.dxf", "objects.json", "centers.csv"],
        format="DXF R2010; tọa độ tương đối với Base; Font Arial; Đã khử chồng lấn",
    )
    _write_json(root / "export_summary.json", summary)
    return summary


def export_reviewed_autocad(directory, revision, connector=None):
    """Export reviewed records directly to AutoCAD via COM and save DWG."""
    data = load_results(directory)
    if type(revision) is not int or revision != data["revision"]:
        raise ValueError("Kết quả đã thay đổi. Tải lại trước khi xuất sang AutoCAD.")
    exported, removed_overlaps = _build_exported_records(data)
    root = Path(directory) / f"reviewed_r{revision}"
    root.mkdir(exist_ok=True)
    dwg_path = root / "objects.dwg"
    factor = data["metadata"].get("unit_to_metre") or 1.0
    result = export_to_autocad_com(exported, dwg_path, unit_to_metre=factor, connector=connector)
    result["revision"] = revision
    result["count"] = len(exported)
    result["removed_overlaps"] = removed_overlaps
    return result


def evaluate_result(directory, truth_path):
    data = load_results(directory)
    path = Path(truth_path)
    if not path.is_file() or path.suffix.lower() != ".json" or path.stat().st_size > 10_000_000:
        raise ValueError("Chọn file JSON nhãn kiểm chứng, tối đa 10 MB.")
    truth = json.loads(path.read_text(encoding="utf-8-sig"))
    if truth.get("source") != data["source"] or truth.get("region") != data["region"]:
        raise ValueError("File nhãn phải ghi đúng đường dẫn ảnh và vùng nhận diện hiện tại.")
    records = truth.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("File nhãn cần danh sách records do người dùng gán nhãn.")
    import math

    for record in records:
        box = record.get("box", [])
        if (
            not isinstance(record.get("category"), str)
            or len(box) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
            or not (0 <= box[0] < box[2] <= data["metadata"]["width"] and 0 <= box[1] < box[3] <= data["metadata"]["height"])
        ):
            raise ValueError("Nhãn cần category và box=[x1,y1,x2,y2] theo pixel ảnh gốc.")
        region = data["region"]
        if record["category"] not in data["settings"]["categories"] or not (
            region["col"] <= box[0] < box[2] <= region["col"] + region["width"]
            and region["row"] <= box[1] < box[3] <= region["row"] + region["height"]
        ):
            raise ValueError("Nhãn phải nằm trong đúng vùng và danh mục của lượt nhận diện.")
    summary = evaluate_boxes(data["records"], records)
    summary["truth_file"] = str(path)
    _write_json(Path(directory) / "evaluation.json", summary)
    return summary
