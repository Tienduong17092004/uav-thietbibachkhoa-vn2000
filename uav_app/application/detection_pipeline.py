"""Windowed open-vocabulary inference and reviewable, georeferenced results."""
import copy
import io
import json
import math
from pathlib import Path
import queue
import threading
import time

import numpy as np
import rasterio
from PIL import Image, ImageDraw

from uav_app.domain.detection import fuse_boxes, parse_boxes, spatial_box, stitch_large_objects, estimate_confidence
from uav_app.domain.geometry import create_plan
from uav_app.domain.settings import validate_settings
from uav_app.infrastructure.raster import inspect_raster, preview_png, _write_json
from uav_app.infrastructure.refinement import propose_refinement
from uav_app.infrastructure.model_client import ModelClient, DetectionCancelled
from uav_app.infrastructure.super_resolution import uav_detail_upscale
from uav_app.infrastructure.dem import find_companion_dem, enrich_records_with_dem
from uav_app.infrastructure.multispectral import (
    find_companion_multispectral,
    read_spectral_window,
    compute_spectral_indices,
    render_spectral_composite,
    propose_spectral_refinement,
)
from uav_app.application.review import _DETECTIONS_IO_LOCK, _save_results


def _resolve_tile_region(metadata, grid, grid_config, tile_id):
    try:
        number = int(str(tile_id).removeprefix("tile_")) - 1
    except (ValueError, AttributeError):
        raise ValueError("Mã tile không hợp lệ.")
    if not 0 <= number < grid.tile_count or tile_id != f"tile_{number+1:06d}":
        raise ValueError("Tile không nằm trong lưới hiện tại.")
    col = (number % grid.columns) * grid.stride_x
    row = (number // grid.columns) * grid.stride_y
    return dict(
        col=col,
        row=row,
        width=min(grid_config["tile_width"], metadata["width"] - col),
        height=min(grid_config["tile_height"], metadata["height"] - row),
    )


def _point_in_poly(px: float, py: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _ccw(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> bool:
    return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)


def _segments_intersect(p1, p2, p3, p4) -> bool:
    return (_ccw(p1[0], p1[1], p3[0], p3[1], p4[0], p4[1]) != _ccw(p2[0], p2[1], p3[0], p3[1], p4[0], p4[1])) and (
        _ccw(p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]) != _ccw(p1[0], p1[1], p2[0], p2[1], p4[0], p4[1])
    )


def _polygon_intersects_rect(poly: list[list[float]], col: float, row: float, width: float, height: float) -> bool:
    right = col + width
    bottom = row + height
    # 1. Any polygon vertex inside rect
    for vx, vy in poly:
        if col <= vx <= right and row <= vy <= bottom:
            return True
    # 2. Any rect corner or center inside polygon
    rect_pts = [
        (col, row),
        (right, row),
        (right, bottom),
        (col, bottom),
        (col + width * 0.5, row + height * 0.5),
    ]
    for rx, ry in rect_pts:
        if _point_in_poly(rx, ry, poly):
            return True
    # 3. Any polygon edge intersects any rect edge
    rect_edges = [
        ((col, row), (right, row)),
        ((right, row), (right, bottom)),
        ((right, bottom), (col, bottom)),
        ((col, bottom), (col, row)),
    ]
    n = len(poly)
    for i in range(n):
        p1 = poly[i]
        p2 = poly[(i + 1) % n]
        for r1, r2 in rect_edges:
            if _segments_intersect(p1, p2, r1, r2):
                return True
    return False


def _sanitize_polygon(raw_poly, max_w: int, max_h: int) -> list[list[float]] | None:
    if not isinstance(raw_poly, list) or len(raw_poly) < 3:
        return None
    pts: list[list[float]] = []
    for pt in raw_poly:
        if isinstance(pt, dict):
            x, y = pt.get("col", pt.get("x")), pt.get("row", pt.get("y"))
        elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
            x, y = pt[0], pt[1]
        else:
            continue
        if x is None or y is None:
            continue
        fx, fy = float(x), float(y)
        if not (math.isfinite(fx) and math.isfinite(fy)):
            continue
        pts.append([max(0.0, min(float(max_w), fx)), max(0.0, min(float(max_h), fy))])
    return pts if len(pts) >= 3 else None


def plan_detection(path, grid_config, settings, scope="selected", tile_id="tile_000001", regions=None):
    settings=validate_settings(settings)
    metadata=inspect_raster(path)
    grid=create_plan(metadata,grid_config)
    if scope not in {"selected","all","multi"}:
        raise ValueError("Chọn nhận diện tile đang xem, nhiều vùng hoặc toàn bộ ảnh.")
    region_tasks = []
    if scope == "multi" and isinstance(regions, list) and regions:
        for idx, item in enumerate(regions):
            region_name = str(item.get("name") or f"Vùng {idx + 1}")
            region_color = str(item.get("color") or "#ff4d4f")
            tid = item.get("tile_id") or f"region_{idx + 1:02d}"
            cats = [c.strip() for c in (item.get("categories") or settings["categories"]) if isinstance(c, str) and c.strip()]
            if not cats:
                cats = list(settings["categories"])
            poly = _sanitize_polygon(item.get("polygon"), metadata["width"], metadata["height"])
            if poly:
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                left = max(0, min(metadata["width"] - 1, int(math.floor(min(xs)))))
                top = max(0, min(metadata["height"] - 1, int(math.floor(min(ys)))))
                right = max(left + 1, min(metadata["width"], int(math.ceil(max(xs)))))
                bottom = max(top + 1, min(metadata["height"], int(math.ceil(max(ys)))))
                reg = dict(col=left, row=top, width=right - left, height=bottom - top)
            else:
                reg = _resolve_tile_region(metadata, grid, grid_config, item.get("tile_id") or tile_id)
            loc = copy.deepcopy(metadata); loc.update(width=reg["width"], height=reg["height"])
            m = create_plan(loc, dict(base_x=0, base_y=0, tile_width=settings["micro_size"], tile_height=settings["micro_size"],
                                      overlap_x=settings["micro_overlap"], overlap_y=settings["micro_overlap"]))
            if poly:
                active_tiles = [
                    t for t in m.iter_tiles()
                    if _polygon_intersects_rect(poly, reg["col"] + t["col"], reg["row"] + t["row"], t["width"], t["height"])
                ]
                if not active_tiles:
                    active_tiles = list(m.iter_tiles())[:1]
            else:
                active_tiles = list(m.iter_tiles())
            region_tasks.append({
                "region_index": idx + 1,
                "name": region_name,
                "color": region_color,
                "tile_id": tid,
                "region": reg,
                "polygon": poly,
                "categories": cats,
                "micro": m,
                "active_tiles": active_tiles,
                "micro_count": len(active_tiles),
            })
        min_col = min(t["region"]["col"] for t in region_tasks)
        min_row = min(t["region"]["row"] for t in region_tasks)
        max_right = max(t["region"]["col"] + t["region"]["width"] for t in region_tasks)
        max_bottom = max(t["region"]["row"] + t["region"]["height"] for t in region_tasks)
        region = dict(col=min_col, row=min_row, width=max_right - min_col, height=max_bottom - min_row)
        micro = region_tasks[0]["micro"]
        micro_count = sum(t["micro_count"] for t in region_tasks)
        total = sum(t["micro_count"] * len(t["categories"]) for t in region_tasks)
    elif scope=="selected":
        region = _resolve_tile_region(metadata, grid, grid_config, tile_id)
        local=copy.deepcopy(metadata); local.update(width=region["width"],height=region["height"])
        micro=create_plan(local,dict(base_x=0,base_y=0,tile_width=settings["micro_size"],tile_height=settings["micro_size"],
            overlap_x=settings["micro_overlap"],overlap_y=settings["micro_overlap"]))
        micro_count = micro.tile_count
        total=micro.tile_count*len(settings["categories"])
    else:
        region=dict(col=0,row=0,width=metadata["width"],height=metadata["height"])
        local=copy.deepcopy(metadata); local.update(width=region["width"],height=region["height"])
        micro=create_plan(local,dict(base_x=0,base_y=0,tile_width=settings["micro_size"],tile_height=settings["micro_size"],
            overlap_x=settings["micro_overlap"],overlap_y=settings["micro_overlap"]))
        micro_count = micro.tile_count
        total=micro.tile_count*len(settings["categories"])
    if total>250000:
        raise ValueError("Lượt này vượt 250.000 truy vấn. Hãy chia nhỏ vùng hoặc giảm số đối tượng.")
    plan_dict = dict(metadata=metadata,region=region,scope=scope,tile_id=tile_id,settings=settings,
                     grid_config=grid.config,micro_count=micro_count,query_count=total)
    if region_tasks:
        plan_dict["regions"] = [
            {
                "region_index": t["region_index"],
                "name": t["name"],
                "color": t["color"],
                "tile_id": t["tile_id"],
                "region": t["region"],
                "polygon": t["polygon"],
                "categories": t["categories"],
                "micro_count": t["micro_count"],
            }
            for t in region_tasks
        ]
        micro = region_tasks
    return plan_dict,micro


def annotate_object(path, output, record, settings, metadata=None, reader=None, ms_info=None, ms_readers=None, spectral_mode=None):
    raw=record["box"]
    meta=metadata or inspect_raster(path)
    pad=16
    left,top=max(0,math.floor(raw[0])-pad),max(0,math.floor(raw[1])-pad)
    right,bottom=min(meta["width"],math.ceil(raw[2])+pad),min(meta["height"],math.ceil(raw[3])+pad)
    window=dict(col=left,row=top,width=right-left,height=bottom-top)
    # Keep inference/refinement in native pixels, bounded by microtile/fused size.
    with Image.open(io.BytesIO(preview_png(path,max_size=1600,window=window,_reader=reader))) as source:
        image=source.convert("RGB")
    scale_x=image.width/window["width"]; scale_y=image.height/window["height"]
    local=[(raw[0]-left)*scale_x,(raw[1]-top)*scale_y,(raw[2]-left)*scale_x,(raw[3]-top)*scale_y]

    use_spectral = bool(
        ms_info and ms_info.get("available") and spectral_mode not in ("off", "rgb_only", False)
    )
    spectral_indices = None
    if use_spectral:
        bands = read_spectral_window(
            ms_info, meta["transform"], left, top, window["width"], window["height"],
            out_w=image.width, out_h=image.height, readers=ms_readers
        )
        if bands:
            spectral_indices = compute_spectral_indices(bands)

    if settings["refinement"]:
        if spectral_indices and "ndvi" in spectral_indices:
            candidate = propose_spectral_refinement(np.array(image), local, spectral_indices, settings["padding"])
            if candidate.get("spectral_class") and not record.get("sub_class"):
                record["sub_class"] = candidate["spectral_class"]
            for k in ("ndvi_mean", "ndvi_max", "ndre_mean", "ndwi_mean"):
                if k in candidate:
                    record[k] = candidate[k]
        else:
            candidate = propose_refinement(np.array(image), local, settings["padding"])
    else:
        candidate = dict(candidate_box=None, mask=None, reason="Co khung đã tắt.")

    candidate_box=candidate.pop("candidate_box")
    mask=candidate.pop("mask")
    clump_boxes_local=candidate.get("clump_boxes") or []
    if clump_boxes_local:
        candidate["clump_boxes_global"]=[
            [cb[0]/scale_x+left,cb[1]/scale_y+top,cb[2]/scale_x+left,cb[3]/scale_y+top]
            for cb in clump_boxes_local
        ]
    record["candidate_box"]=[candidate_box[0]/scale_x+left,candidate_box[1]/scale_y+top,
                             candidate_box[2]/scale_x+left,candidate_box[3]/scale_y+top] if candidate_box else None
    record["refinement"]=candidate
    record["review_status"]="unreviewed"
    before=image.copy(); ImageDraw.Draw(before).rectangle(local,outline="#ffad33",width=3)
    before.save(output/"review"/(record["id"]+"_raw.png"))
    after=image.copy()
    if mask is not None:
        crop=candidate["crop"]
        tint=Image.new("RGB",(crop[2]-crop[0],crop[3]-crop[1]),"#38ff82")
        alpha=Image.fromarray((mask*.3).astype("uint8"))
        after.paste(tint,(crop[0],crop[1]),alpha)
        Image.fromarray(mask).save(output/"review"/(record["id"]+"_mask.png"))
    draw=ImageDraw.Draw(after); draw.rectangle(local,outline="#ffad33",width=2)
    if len(clump_boxes_local)>=2:
        for cb in clump_boxes_local:
            draw.rectangle(cb,outline="#38ff82",width=2)
    if candidate_box: draw.rectangle(candidate_box,outline="#20e9ef",width=3)
    after.save(output/"review"/(record["id"]+"_candidate.png"))
    record["raw_image"]=f"review/{record['id']}_raw.png"
    record["candidate_image"]=f"review/{record['id']}_candidate.png"
    image.close(); before.close(); after.close()


def _report_progress(progress, done: int, total: int, message: str, **extra):
    if not progress:
        return
    try:
        progress(done, total, message, **extra)
    except TypeError:
        progress(done, total, message)


def _is_homogeneous_empty_window(rgb_arr: np.ndarray, valid_mask: np.ndarray | None = None) -> bool:
    """Fast CPU/RAM filter: skip completely uniform/empty tiles (nodata, flat water, solid fill)."""
    if rgb_arr is None or rgb_arr.size == 0:
        return True
    if valid_mask is not None:
        valid_pixels = rgb_arr[valid_mask > 0]
        if valid_pixels.size == 0:
            return True
        return float(np.std(valid_pixels)) < 2.2
    return float(np.std(rgb_arr)) < 2.2


def _call_predict(client, tile_path, cat_or_cats, settings, pre_resized: bool = False):
    try:
        return client.predict(tile_path, cat_or_cats, settings, pre_resized=pre_resized)
    except TypeError:
        return client.predict(tile_path, cat_or_cats, settings)


def run_detection(project,path,output_dir,grid_config,settings,scope="selected",tile_id="tile_000001",
                  progress=None,cancelled=lambda:False,client_factory=ModelClient,regions=None,sr_mode=None,spectral_mode="auto",resume=False):
    plan,micro=plan_detection(path,grid_config,settings,scope,tile_id,regions=regions)
    settings=plan["settings"]
    if sr_mode:
        settings=dict(settings,sr_mode=sr_mode)
    if spectral_mode:
        settings=dict(settings,spectral_mode=spectral_mode)
    ms_info = plan["metadata"].get("multispectral") or find_companion_multispectral(path)
    use_spectral = bool(ms_info and ms_info.get("available") and spectral_mode not in ("off", "rgb_only"))
    output=Path(output_dir); output.mkdir(parents=True,exist_ok=True)
    (output/"review").mkdir(exist_ok=True)
    base=[grid_config["base_x"],grid_config["base_y"]]
    has_dem = find_companion_dem(path) is not None
    raw=[]; client=None; reader=None; ms_readers={}; completed=0
    scanned_windows=[]; completed_regions=[]
    completed_keys: set[str] = set()
    annotated_cache: dict[tuple, dict] = {}
    records: list[dict] = []

    if resume:
        raw_boxes_path = output / "raw_boxes.jsonl"
        if raw_boxes_path.is_file():
            for line in raw_boxes_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw.append(json.loads(line))
                except Exception:
                    pass
        resp_path = output / "raw_responses.jsonl"
        if resp_path.is_file():
            for line in resp_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    cats_in_item = item.get("categories") or ([item["category"]] if item.get("category") else [])
                    w_uid = item.get("window_id")
                    win = item.get("window") or {}
                    for cat in cats_in_item:
                        if w_uid and cat:
                            completed_keys.add(f"{w_uid}::{cat}")
                        if "col" in win and "row" in win and cat:
                            completed_keys.add(f"{win['col']}:{win['row']}::{cat}")
                except Exception:
                    pass
        ckpt_path = output / "checkpoint.json"
        if ckpt_path.is_file():
            try:
                ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
                for k in ckpt.get("completed_keys") or []:
                    completed_keys.add(str(k))
                for sw in ckpt.get("scanned_windows") or []:
                    if sw not in scanned_windows:
                        scanned_windows.append(sw)
                for cr in ckpt.get("completed_regions") or []:
                    if cr not in completed_regions:
                        completed_regions.append(cr)
                if isinstance(ckpt.get("completed_queries"), int):
                    completed = max(completed, ckpt["completed_queries"])
            except Exception:
                pass
        if completed == 0 and completed_keys:
            completed = len({k for k in completed_keys if "::" in k and not k.split("::", 1)[0][0].isdigit()})
        det_path = output / "detections.json"
        if det_path.is_file():
            try:
                old_det = json.loads(det_path.read_text(encoding="utf-8"))
                for rec in old_det.get("records") or []:
                    if isinstance(rec, dict) and "category" in rec and isinstance(rec.get("box"), list) and len(rec["box"]) == 4:
                        bkey = (rec["category"], tuple(round(float(x), 1) for x in rec["box"]))
                        annotated_cache[bkey] = copy.deepcopy(rec)
                records = list(old_det.get("records") or [])
            except Exception:
                pass
    initial_completed_floor = completed
    completed = 0

    summary=dict(kind="detection",status="running",plan=plan,completed_queries=max(completed, initial_completed_floor),raw_count=len(raw),count=len(annotated_cache),
                 multispectral_active=use_spectral,multispectral_bands=ms_info.get("band_names",[]) if use_spectral else [],
                 score_policy="No calibrated confidence. Equal geometry weights only when explicitly enabled.",
                 coverage_complete=False,peak_vram_gib=None)
    _write_json(output/"summary.json",summary)
    if not (output / "detections.json").is_file():
        _save_results(
            output,
            dict(
                revision=0,
                source=str(path),
                metadata=plan["metadata"],
                base=base,
                settings=settings,
                scope=scope,
                region=plan["region"],
                records=records,
            ),
        )
    region_tasks = micro if isinstance(micro, list) else [{"region_index": 1, "name": tile_id if scope=="selected" else "Toàn khu vực", "tile_id": tile_id, "region": plan["region"], "categories": settings["categories"], "micro": micro}]

    def _save_checkpoint():
        ckpt_data = dict(
            completed_keys=sorted(completed_keys),
            scanned_windows=scanned_windows,
            completed_regions=completed_regions,
            completed_queries=completed,
        )
        _write_json(output / "checkpoint.json", ckpt_data)
        summary.update(completed_queries=completed, raw_count=len(raw), count=len(records))
        _write_json(output / "summary.json", summary)

    def _flush_live_detections():
        nonlocal records
        current_revision = 0
        det_file = output / "detections.json"
        if det_file.is_file():
            try:
                with _DETECTIONS_IO_LOCK:
                    disk_data = json.loads(det_file.read_text(encoding="utf-8"))
                current_revision = int(disk_data.get("revision", 0))
                for d_rec in disk_data.get("records") or []:
                    if not isinstance(d_rec, dict) or "category" not in d_rec or not isinstance(d_rec.get("box"), list):
                        continue
                    bkey = (d_rec["category"], tuple(round(float(x), 1) for x in d_rec["box"]))
                    if bkey in annotated_cache:
                        cached_item = annotated_cache[bkey]
                        if d_rec.get("review_status") and d_rec.get("review_status") != "unreviewed":
                            cached_item["review_status"] = d_rec["review_status"]
                        if d_rec.get("sub_class"):
                            cached_item["sub_class"] = d_rec["sub_class"]
                        if d_rec.get("candidate_box"):
                            cached_item["candidate_box"] = d_rec["candidate_box"]
                        if d_rec.get("spatial_selected"):
                            cached_item["spatial_selected"] = d_rec["spatial_selected"]
                        if d_rec.get("triage_source"):
                            cached_item["triage_source"] = d_rec["triage_source"]
                    else:
                        annotated_cache[bkey] = copy.deepcopy(d_rec)
            except Exception:
                pass

        fused = fuse_boxes(raw, settings["merge_mode"], settings["merge_iou"])
        if settings["merge_mode"] in {"equal_weight", "smart_overlap"}:
            fused = stitch_large_objects(fused)

        used_ids: set[str] = set()
        for c_val in annotated_cache.values():
            if isinstance(c_val, dict) and c_val.get("id"):
                used_ids.add(str(c_val["id"]))
        next_id_num = len(used_ids)

        copy_fields = (
            "candidate_box", "refinement", "raw_image", "candidate_image",
            "spatial_raw", "spatial_selected", "confidence_score", "sub_class",
            "review_status", "triage_source", "ndvi_mean", "ndvi_max",
            "ndre_mean", "ndwi_mean", "elevation_m", "ground_elevation_m",
            "dem_z_ground", "height_m", "_dem_checked",
        )
        for record in fused:
            bkey = (record["category"], tuple(round(float(x), 1) for x in record["box"]))
            cached = annotated_cache.get(bkey)
            if cached and cached.get("raw_image") and (output / cached["raw_image"]).is_file():
                if cached.get("id"):
                    record["id"] = cached["id"]
                    used_ids.add(record["id"])
                for k in copy_fields:
                    if k in cached:
                        record[k] = copy.deepcopy(cached[k])
                record["confidence_score"] = estimate_confidence(record)
                annotated_cache[bkey] = copy.deepcopy(record)
            else:
                while record["id"] in used_ids:
                    next_id_num += 1
                    record["id"] = f"object_{next_id_num:06d}"
                used_ids.add(record["id"])
                annotate_object(path, output, record, settings, plan["metadata"], reader, ms_info=ms_info, ms_readers=ms_readers, spectral_mode=spectral_mode)
                record["spatial_raw"] = spatial_box(record["box"], plan["metadata"]["transform"], base)
                if not record.get("sub_class"):
                    record["sub_class"] = record.get("label") or record.get("category")
                record["confidence_score"] = estimate_confidence(record)
                annotated_cache[bkey] = copy.deepcopy(record)

        if has_dem:
            new_for_dem = [
                r for r in fused
                if not r.get("_dem_checked") and "dem_z_ground" not in r and "ground_elevation_m" not in r
            ]
            if new_for_dem:
                try:
                    enrich_records_with_dem(new_for_dem, plan["metadata"])
                    for r in new_for_dem:
                        r["_dem_checked"] = True
                        r["dem_z_ground"] = r.get("ground_elevation_m")
                        r["confidence_score"] = estimate_confidence(r)
                        rk = (r["category"], tuple(round(float(x), 1) for x in r["box"]))
                        annotated_cache[rk] = copy.deepcopy(r)
                except Exception:
                    pass

        with _DETECTIONS_IO_LOCK:
            extra_split_records: list[dict] = []
            if det_file.is_file():
                try:
                    latest_disk = json.loads(det_file.read_text(encoding="utf-8"))
                    current_revision = max(current_revision, int(latest_disk.get("revision", 0)))
                    disk_by_id: dict[str, dict] = {}
                    disk_by_bkey: dict[tuple, dict] = {}
                    for d_rec in latest_disk.get("records") or []:
                        if not isinstance(d_rec, dict):
                            continue
                        if d_rec.get("id"):
                            disk_by_id[str(d_rec["id"])] = d_rec
                        if "category" in d_rec and isinstance(d_rec.get("box"), list) and len(d_rec["box"]) == 4:
                            disk_by_bkey[(d_rec["category"], tuple(round(float(x), 1) for x in d_rec["box"]))] = d_rec
                        if d_rec.get("parent_id"):
                            extra_split_records.append(d_rec)
                    for rec in fused:
                        rk = (rec["category"], tuple(round(float(x), 1) for x in rec["box"]))
                        d_match = disk_by_id.get(str(rec.get("id"))) or disk_by_bkey.get(rk)
                        if d_match:
                            if d_match.get("review_status") and d_match.get("review_status") != "unreviewed":
                                rec["review_status"] = d_match["review_status"]
                            if d_match.get("sub_class"):
                                rec["sub_class"] = d_match["sub_class"]
                            if d_match.get("candidate_box"):
                                rec["candidate_box"] = d_match["candidate_box"]
                            if d_match.get("spatial_selected"):
                                rec["spatial_selected"] = d_match["spatial_selected"]
                            if d_match.get("triage_source"):
                                rec["triage_source"] = d_match["triage_source"]
                            annotated_cache[rk] = copy.deepcopy(rec)
                except Exception:
                    pass

            existing_ids = {str(r.get("id")) for r in fused if r.get("id")}
            for s_rec in extra_split_records:
                if str(s_rec.get("id")) not in existing_ids:
                    fused.append(s_rec)
                    existing_ids.add(str(s_rec.get("id")))

            records = fused
            results = dict(
                revision=current_revision,
                source=str(path),
                metadata=plan["metadata"],
                base=base,
                settings=settings,
                scope=scope,
                region=plan["region"],
                records=records,
            )
            _save_results(output, results)
        _save_checkpoint()

    stop_prefetch = threading.Event()
    prefetch_thread = None

    try:
        _report_progress(progress,max(completed, initial_completed_floor),plan["query_count"],"Đang nạp mô hình vào GPU & chuẩn bị bộ đệm RAM…",
                         scope=scope,tile_id=tile_id,scanned_windows=scanned_windows[-5000:],
                         completed_regions=list(completed_regions),active_window=None,live_count=len(annotated_cache))
        reader=rasterio.open(path)
        if use_spectral:
            for b_name, b_path in (ms_info.get("bands") or {}).items():
                try:
                    ms_readers[b_name] = rasterio.open(b_path)
                except Exception:
                    pass

        prefetch_q: queue.Queue = queue.Queue(maxsize=16)
        initial_done_snapshot = set(completed_keys)

        def _put_prefetch(item):
            while not stop_prefetch.is_set() and not cancelled():
                try:
                    prefetch_q.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def _prefetch_worker():
            p_reader = None
            p_ms_readers = {}
            buf_idx = 0
            skipped_done = 0
            skipped_wins = []

            def _emit_item(payload):
                nonlocal skipped_done, skipped_wins
                if skipped_done > 0:
                    payload = dict(payload, skipped_done=skipped_done, skipped_windows=skipped_wins)
                    skipped_done = 0
                    skipped_wins = []
                return _put_prefetch(payload)

            try:
                p_reader = rasterio.open(path)
                if use_spectral:
                    for b_name, b_path in (ms_info.get("bands") or {}).items():
                        try:
                            p_ms_readers[b_name] = rasterio.open(b_path)
                        except Exception:
                            pass
                for task_idx, task in enumerate(region_tasks):
                    if stop_prefetch.is_set() or cancelled():
                        return
                    t_region = task["region"]
                    t_cats = task["categories"]
                    t_poly = task.get("polygon")
                    r_idx = task.get("region_index", task_idx + 1)
                    r_name = task.get("name") or f"Vùng {r_idx}"
                    tiles_iter = task.get("active_tiles") if task.get("active_tiles") is not None else task["micro"].iter_tiles()
                    for tile in tiles_iter:
                        if stop_prefetch.is_set() or cancelled():
                            return
                        window = {key: tile[key] for key in ("col", "row", "width", "height")}
                        window["col"] += t_region["col"]
                        window["row"] += t_region["row"]
                        win_uid = f"{task['tile_id']}_{tile['id']}" if len(region_tasks) > 1 else tile["id"]
                        win_entry = [window["col"], window["row"], window["width"], window["height"], r_idx]
                        pending_cats = [
                            c for c in t_cats
                            if f"{win_uid}::{c}" not in initial_done_snapshot
                            and f"{window['col']}:{window['row']}::{c}" not in initial_done_snapshot
                        ]
                        base_item = dict(
                            kind="tile",
                            task=task,
                            r_idx=r_idx,
                            r_name=r_name,
                            window=window,
                            win_uid=win_uid,
                            win_entry=win_entry,
                            t_cats=t_cats,
                            pending_cats=pending_cats,
                        )
                        if not pending_cats:
                            skipped_done += len(t_cats)
                            skipped_wins.append(win_entry)
                            continue
                        png = preview_png(path, max_size=1024, window=window, _reader=p_reader)
                        with Image.open(io.BytesIO(png)) as rgba:
                            if rgba.getchannel("A").getbbox() is None:
                                if not _emit_item(dict(base_item, status="empty_alpha")):
                                    return
                                continue
                            valid_mask = np.array(rgba.getchannel("A"))
                            if t_poly:
                                poly_mask = Image.new("L", (window["width"], window["height"]), 0)
                                local_pts = [(p[0] - window["col"], p[1] - window["row"]) for p in t_poly]
                                ImageDraw.Draw(poly_mask).polygon(local_pts, fill=255)
                                valid_mask = np.minimum(valid_mask, np.array(poly_mask))
                                if not np.any(valid_mask):
                                    if not _emit_item(dict(base_item, status="empty_poly")):
                                        return
                                    continue
                            rgb_tile = rgba.convert("RGB")
                            rgb_arr = np.array(rgb_tile)
                            if _is_homogeneous_empty_window(rgb_arr, valid_mask):
                                rgb_tile.close()
                                if not _emit_item(dict(base_item, status="empty_homogeneous")):
                                    return
                                continue
                            if use_spectral and p_ms_readers and spectral_mode in ("spectral_fusion", "ndvi_color", "false_color_nir"):
                                bands_win = read_spectral_window(
                                    ms_info, plan["metadata"]["transform"],
                                    window["col"], window["row"], window["width"], window["height"],
                                    out_w=rgb_tile.width, out_h=rgb_tile.height, readers=p_ms_readers,
                                )
                                if bands_win:
                                    idxs_win = compute_spectral_indices(bands_win)
                                    rgb_tile = render_spectral_composite(rgb_tile, idxs_win, bands_win, mode=spectral_mode)
                            if sr_mode == "uav_detail":
                                rgb_tile = uav_detail_upscale(rgb_tile, scale=1)
                            pre_resized = False
                            upscale_factor = int(settings.get("upscale", 1))
                            max_img_sz = int(settings.get("max_image_size", 768))
                            if upscale_factor > 1 and sr_mode not in ("ttst", "ttst_4x", "deep_sr", "realesrgan", "swinir", "hat"):
                                target_w = min(max_img_sz, rgb_tile.width * upscale_factor)
                                target_h = min(max_img_sz, rgb_tile.height * upscale_factor)
                                if (target_w, target_h) != rgb_tile.size:
                                    rgb_tile = rgb_tile.resize((target_w, target_h), Image.Resampling.BILINEAR)
                                pre_resized = True
                            elif upscale_factor == 1 and rgb_tile.width <= max_img_sz and rgb_tile.height <= max_img_sz:
                                pre_resized = True
                            slot = buf_idx % 32
                            buf_idx += 1
                            tile_path = output / f".tile_buf_{slot:02d}.png"
                            rgb_tile.save(tile_path, format="PNG", compress_level=1)
                            rgb_tile.close()
                            if not _emit_item(dict(base_item, status="ready", tile_path=tile_path, pre_resized=pre_resized, valid_mask=valid_mask)):
                                return
                    if not _emit_item(dict(kind="region_done", r_idx=r_idx, r_name=r_name)):
                        return
                _emit_item(dict(kind="eof", error=None))
            except Exception as exc:
                _put_prefetch(dict(kind="eof", error=str(exc)))
            finally:
                if p_reader is not None:
                    try:
                        p_reader.close()
                    except Exception:
                        pass
                for pm in p_ms_readers.values():
                    try:
                        pm.close()
                    except Exception:
                        pass

        prefetch_thread = threading.Thread(target=_prefetch_worker, daemon=True, name="uav-tile-prefetch")
        prefetch_thread.start()

        client=client_factory(project,output,cancelled)
        supports_multi = bool(getattr(client, "supports_multi_category", False))
        supports_async = bool(getattr(client, "supports_async_pipeline", False) and hasattr(client, "submit") and hasattr(client, "receive"))
        max_gpu_inflight = 6 if supports_async else 0
        import collections
        inflight_events = collections.deque()
        gpu_inflight_count = 0
        eof_seen = False
        last_flush_time = 0.0
        last_ckpt_time = time.monotonic()
        steps_since_ckpt = 0
        unflushed_new_boxes = 0
        first_live_flushed = False

        def _enqueue_from_prefetch(block: bool):
            nonlocal gpu_inflight_count, eof_seen
            if eof_seen:
                return False
            try:
                raw_item = prefetch_q.get(timeout=0.1) if block else prefetch_q.get_nowait()
            except queue.Empty:
                return False
            if raw_item.get("kind") == "eof":
                eof_seen = True
                inflight_events.append(("eof", raw_item))
                return True
            if raw_item.get("kind") == "region_done" or raw_item.get("status") != "ready":
                inflight_events.append(("item", raw_item, None))
                return True
            # It is a "ready" tile: check if we can pre-submit to Shared GPU Memory pipeline
            win = raw_item["window"]
            w_uid = raw_item["win_uid"]
            p_cats = [
                c for c in raw_item["pending_cats"]
                if f"{w_uid}::{c}" not in completed_keys and f"{win['col']}:{win['row']}::{c}" not in completed_keys
            ]
            if supports_async and p_cats and (supports_multi or len(p_cats) == 1):
                q_arg = p_cats if (supports_multi and len(p_cats) > 1) else p_cats[0]
                client.submit(
                    raw_item["tile_path"],
                    q_arg,
                    settings,
                    pre_resized=raw_item["pre_resized"],
                    req_id=w_uid,
                )
                gpu_inflight_count += 1
                inflight_events.append(("submitted", raw_item, p_cats))
            else:
                inflight_events.append(("item", raw_item, p_cats))
            return True

        file_mode = "a" if resume else "w"
        with (output/"raw_responses.jsonl").open(file_mode,encoding="utf-8") as responses, (output/"raw_boxes.jsonl").open(file_mode,encoding="utf-8") as raw_file:
            while True:
                if cancelled():
                    raise DetectionCancelled()
                # Keep up to max_gpu_inflight windows pre-submitted into Shared GPU Memory
                while not eof_seen and gpu_inflight_count < max_gpu_inflight:
                    if not _enqueue_from_prefetch(block=False):
                        break
                if not inflight_events:
                    if eof_seen:
                        break
                    _enqueue_from_prefetch(block=True)
                    continue

                ev_entry = inflight_events.popleft()
                ev_type = ev_entry[0]
                item = ev_entry[1]
                pre_submitted_cats = ev_entry[2] if len(ev_entry) > 2 else None

                if item.get("skipped_done"):
                    completed += int(item["skipped_done"])
                    for sw in item.get("skipped_windows") or []:
                        if sw not in scanned_windows:
                            scanned_windows.append(sw)
                if ev_type == "eof" or item.get("kind") == "eof":
                    if item.get("error"):
                        raise RuntimeError(item["error"])
                    break
                kind = item.get("kind")
                if kind == "region_done":
                    r_idx = item["r_idx"]
                    r_name = item["r_name"]
                    if r_idx not in completed_regions:
                        completed_regions.append(r_idx)
                    if unflushed_new_boxes > 0:
                        _flush_live_detections()
                        unflushed_new_boxes = 0
                        last_flush_time = time.monotonic()
                        last_ckpt_time = last_flush_time
                        steps_since_ckpt = 0
                    else:
                        _save_checkpoint()
                        last_ckpt_time = time.monotonic()
                        steps_since_ckpt = 0
                    _report_progress(progress,completed,plan["query_count"],
                                     f"Đã hoàn tất {r_name} ({completed}/{plan['query_count']} truy vấn).",
                                     active_window=None,active_region_index=r_idx,
                                     scanned_windows=scanned_windows[-5000:],completed_regions=list(completed_regions),
                                     live_count=len(annotated_cache))
                    continue

                task = item["task"]
                r_idx = item["r_idx"]
                r_name = item["r_name"]
                window = item["window"]
                win_uid = item["win_uid"]
                win_entry = item["win_entry"]
                t_cats = item["t_cats"]
                status = item["status"]

                if status == "already_done":
                    completed += len(t_cats)
                    if win_entry not in scanned_windows:
                        scanned_windows.append(win_entry)
                    continue

                if cancelled():
                    raise DetectionCancelled()

                active_win_info = {
                    "col": window["col"], "row": window["row"],
                    "width": window["width"], "height": window["height"],
                    "tile_id": win_uid, "region_index": r_idx, "region_name": r_name,
                }

                if status in ("empty_alpha", "empty_poly", "empty_homogeneous"):
                    for c in t_cats:
                        completed_keys.add(f"{win_uid}::{c}")
                        completed_keys.add(f"{window['col']}:{window['row']}::{c}")
                    completed += len(t_cats)
                    if win_entry not in scanned_windows:
                        scanned_windows.append(win_entry)
                    steps_since_ckpt += 1
                    now_t = time.monotonic()
                    if steps_since_ckpt >= 8 or (now_t - last_ckpt_time) >= 2.0:
                        _save_checkpoint()
                        last_ckpt_time = now_t
                        steps_since_ckpt = 0
                    skip_msg = (
                        "Bỏ qua ảnh không có dữ liệu."
                        if status == "empty_alpha"
                        else "Bỏ qua ảnh nằm ngoài vùng Polyline."
                        if status == "empty_poly"
                        else "Bỏ qua nhanh ảnh đồng nhất không có chi tiết."
                    )
                    _report_progress(progress,completed,plan["query_count"],skip_msg,
                                     active_window=active_win_info,active_region_index=r_idx,
                                     scanned_windows=scanned_windows[-5000:],completed_regions=list(completed_regions),
                                     live_count=len(annotated_cache))
                    continue

                pending_cats = pre_submitted_cats if pre_submitted_cats is not None else [
                    c for c in item["pending_cats"]
                    if f"{win_uid}::{c}" not in completed_keys and f"{window['col']}:{window['row']}::{c}" not in completed_keys
                ]
                already_done_in_tile = len(t_cats) - len(pending_cats)
                if already_done_in_tile > 0:
                    completed += already_done_in_tile
                if not pending_cats:
                    if win_entry not in scanned_windows:
                        scanned_windows.append(win_entry)
                    continue

                _report_progress(progress,completed,plan["query_count"],
                                 f"Đang quét {r_name} · ảnh {win_uid} ({completed}/{plan['query_count']})…",
                                 active_window=active_win_info,active_region_index=r_idx,
                                 scanned_windows=scanned_windows[-5000:],completed_regions=list(completed_regions),
                                 live_count=len(annotated_cache))

                tile_path = item["tile_path"]
                pre_resized = item["pre_resized"]
                valid_mask = item["valid_mask"]
                window_new_boxes = 0

                if ev_type == "submitted" or (supports_multi and len(pending_cats) > 1):
                    if cancelled():
                        raise DetectionCancelled()
                    if ev_type == "submitted":
                        reply = client.receive()
                        gpu_inflight_count = max(0, gpu_inflight_count - 1)
                        # Immediately top up the Shared GPU Memory lookahead queue
                        while not eof_seen and gpu_inflight_count < max_gpu_inflight:
                            if not _enqueue_from_prefetch(block=False):
                                break
                    else:
                        reply = _call_predict(client, tile_path, pending_cats, settings, pre_resized=pre_resized)
                    responses.write(json.dumps(dict(window=window,window_id=win_uid,categories=pending_cats,category=pending_cats[0],**reply),ensure_ascii=False)+"\n")
                    responses.flush()
                    summary["peak_vram_gib"] = reply.get("peak_vram_gib")
                    if reply.get("shared_gpu_mem_gib") is not None:
                        summary["shared_gpu_mem_gib"] = reply.get("shared_gpu_mem_gib")
                    for record in parse_boxes(reply["text"], window["width"], window["height"], pending_cats):
                        local = record["box"]
                        center_x = min(window["width"] - 1, int((local[0] + local[2]) / 2))
                        center_y = min(window["height"] - 1, int((local[1] + local[3]) / 2))
                        if valid_mask[center_y, center_x] == 0:
                            continue
                        record.update(
                            id=f"raw_{len(raw)+1:07d}",
                            window_id=win_uid,
                            window=window.copy(),
                            region_name=task.get("name"),
                            touches_window_edge=local[0] <= 1 or local[1] <= 1 or local[2] >= window["width"] - 1 or local[3] >= window["height"] - 1,
                            box=[local[0] + window["col"], local[1] + window["row"], local[2] + window["col"], local[3] + window["row"]],
                        )
                        raw.append(record)
                        window_new_boxes += 1
                        raw_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                        if len(raw) >= 20000:
                            raise RuntimeError("Đã đạt giới hạn 20.000 khung cho một lượt. Giữ kết quả thô; hãy chọn vùng nhỏ hơn.")
                    raw_file.flush()
                    for category in pending_cats:
                        completed_keys.add(f"{win_uid}::{category}")
                        completed_keys.add(f"{window['col']}:{window['row']}::{category}")
                    completed += len(pending_cats)
                else:
                    for cat_idx, category in enumerate(pending_cats):
                        key_uid = f"{win_uid}::{category}"
                        key_pos = f"{window['col']}:{window['row']}::{category}"
                        if key_uid in completed_keys or key_pos in completed_keys:
                            completed += 1
                            if win_entry not in scanned_windows:
                                scanned_windows.append(win_entry)
                            continue
                        if cancelled():
                            raise DetectionCancelled()
                        reply = _call_predict(client, tile_path, category, settings, pre_resized=pre_resized)
                        responses.write(json.dumps(dict(window=window,window_id=win_uid,category=category,**reply),ensure_ascii=False)+"\n")
                        responses.flush()
                        summary["peak_vram_gib"] = reply.get("peak_vram_gib")
                        for record in parse_boxes(reply["text"], window["width"], window["height"], category):
                            local = record["box"]
                            center_x = min(window["width"] - 1, int((local[0] + local[2]) / 2))
                            center_y = min(window["height"] - 1, int((local[1] + local[3]) / 2))
                            if valid_mask[center_y, center_x] == 0:
                                continue
                            record.update(
                                id=f"raw_{len(raw)+1:07d}",
                                window_id=win_uid,
                                window=window.copy(),
                                region_name=task.get("name"),
                                touches_window_edge=local[0] <= 1 or local[1] <= 1 or local[2] >= window["width"] - 1 or local[3] >= window["height"] - 1,
                                box=[local[0] + window["col"], local[1] + window["row"], local[2] + window["col"], local[3] + window["row"]],
                            )
                            raw.append(record)
                            window_new_boxes += 1
                            raw_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                            if len(raw) >= 20000:
                                raise RuntimeError("Đã đạt giới hạn 20.000 khung cho một lượt. Giữ kết quả thô; hãy chọn vùng nhỏ hơn.")
                        raw_file.flush()
                        completed += 1
                        completed_keys.add(key_uid)
                        completed_keys.add(key_pos)
                        if cat_idx < len(pending_cats) - 1:
                            _report_progress(progress,completed,plan["query_count"],
                                             f"Đã xử lý {completed}/{plan['query_count']} truy vấn ({r_name}) · {len(raw)} khung thô.",
                                             active_window=active_win_info,active_region_index=r_idx,
                                             scanned_windows=scanned_windows[-5000:],completed_regions=list(completed_regions),
                                             live_count=len(annotated_cache))

                if win_entry not in scanned_windows:
                    scanned_windows.append(win_entry)
                unflushed_new_boxes += window_new_boxes
                steps_since_ckpt += 1
                now_t = time.monotonic()
                if unflushed_new_boxes > 0 and (not first_live_flushed or (now_t - last_flush_time) >= 2.0):
                    _flush_live_detections()
                    first_live_flushed = True
                    unflushed_new_boxes = 0
                    last_flush_time = time.monotonic()
                    last_ckpt_time = last_flush_time
                    steps_since_ckpt = 0
                elif steps_since_ckpt >= 8 or (now_t - last_ckpt_time) >= 2.0:
                    _save_checkpoint()
                    last_ckpt_time = now_t
                    steps_since_ckpt = 0
                _report_progress(progress,completed,plan["query_count"],
                                 f"Đã xử lý {completed}/{plan['query_count']} truy vấn ({r_name}) · {len(annotated_cache)} đối tượng.",
                                 active_window=active_win_info,active_region_index=r_idx,
                                 scanned_windows=scanned_windows[-5000:],completed_regions=list(completed_regions),
                                 live_count=len(annotated_cache))
        summary["status"]="completed"
        summary["coverage_complete"]=True
        _flush_live_detections()
    except DetectionCancelled:
        summary["status"]="cancelled"
        if reader is not None:
            try:
                _flush_live_detections()
            except Exception:
                pass
    except Exception as error:
        summary.update(status="failed",error=str(error))
    finally:
        stop_prefetch.set()
        if prefetch_thread is not None:
            prefetch_thread.join(timeout=2.0)
        if client: client.close()
        if reader: reader.close()
        for r_ms in ms_readers.values():
            try: r_ms.close()
            except Exception: pass
        ms_readers = {}
        (output/".current_tile.png").unlink(missing_ok=True)
        for buf_file in output.glob(".tile_buf_*.png"):
            buf_file.unlink(missing_ok=True)
        completed = max(completed, initial_completed_floor)
        summary.update(completed_queries=completed,raw_count=len(raw),count=len(records))
        _write_json(output/"summary.json",summary)
    # A failed load is a failed job, not an empty successful detection.
    if summary["status"]=="failed":
        raise RuntimeError(summary["error"])
    with Image.open(io.BytesIO(preview_png(path,window=plan["region"]))) as rgba:
        overview=rgba.convert("RGB")
    draw=ImageDraw.Draw(overview)
    r=plan["region"]
    for reg_info in plan.get("regions") or []:
        poly = reg_info.get("polygon")
        if poly and len(poly) >= 3:
            pts = [
                ((p[0] - r["col"]) * overview.width / r["width"], (p[1] - r["row"]) * overview.height / r["height"])
                for p in poly
            ]
            draw.line(pts + [pts[0]], fill=reg_info.get("color", "#ff4d4f"), width=3)
    for record in records:
        b=record["box"]
        coords=[(b[0]-r["col"])*overview.width/r["width"],(b[1]-r["row"])*overview.height/r["height"],
                (b[2]-r["col"])*overview.width/r["width"],(b[3]-r["row"])*overview.height/r["height"]]
        draw.rectangle(coords,outline="#ffbd33",width=2)
    overview.save(output/"overview.jpg",quality=93); overview.close()
    summary.update(count=len(records),coverage_complete=summary["status"]=="completed" and completed==plan["query_count"])
    _write_json(output/"summary.json",summary)
    return summary
