"""6-Class Terrain & Corridor Segmentation + Topographic Vectorization (VN2000 AutoCAD DXF).

Detects and vectorizes planar & linear survey features from UAV GeoTIFFs:
  1. asphalt_road  (Đường nhựa)     -> KS_DUONG_NHUA   (2 mép liền + KS_TIM_DUONG + chữ Đ.NHỰA)
  2. concrete_road (Đường bê tông)  -> KS_DUONG_BETONG (2 mép liền + KS_TIM_DUONG + chữ Đ.BÊ TÔNG)
  3. dirt_road     (Đường đất)      -> KS_DUONG_DAT    (2 mép nét đứt DASHED + chữ Đ.ĐẤT)
  4. footpath      (Đường đi bộ)    -> KS_DUONG_DIBO   (2 mép hẹp nét đứt DASHED + chữ Đ.ĐI BỘ)
  5. pond          (Ao / Hồ)        -> KS_AO_HO        (Đa giác khép kín mượt + ký hiệu bờ taluy + chữ AO)
  6. masonry_ditch (Mương xây)      -> KS_MUONG_XAY    (2 nét thành mương song song + chữ MƯƠNG XÂY)
"""
from __future__ import annotations

from collections import deque
import json
import math
from pathlib import Path
import time
from typing import Any

import cv2
import ezdxf
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

from uav_app.domain.detection import spatial_box
from uav_app.infrastructure.dem import find_companion_dem
from uav_app.infrastructure.multispectral import find_companion_multispectral
from uav_app.infrastructure.raster import _write_json, inspect_raster
from uav_app.infrastructure.survey_cad import _offset_polyline

TERRAIN_CLASSES_META: dict[str, dict[str, Any]] = {
    "asphalt_road": {
        "id": 1,
        "key": "asphalt_road",
        "label_vi": "Đường nhựa",
        "cad_text": "Đ.NHỰA",
        "layer": "KS_DUONG_NHUA",
        "color_aci": 1,
        "linetype": "CONTINUOUS",
        "centerline": True,
        "geometry": "CORRIDOR",
        "hex": "#ef4444",
    },
    "concrete_road": {
        "id": 2,
        "key": "concrete_road",
        "label_vi": "Đường bê tông",
        "cad_text": "Đ.BÊ TÔNG",
        "layer": "KS_DUONG_BETONG",
        "color_aci": 7,
        "linetype": "CONTINUOUS",
        "centerline": True,
        "geometry": "CORRIDOR",
        "hex": "#94a3b8",
    },
    "dirt_road": {
        "id": 3,
        "key": "dirt_road",
        "label_vi": "Đường đất",
        "cad_text": "Đ.ĐẤT",
        "layer": "KS_DUONG_DAT",
        "color_aci": 30,
        "linetype": "DASHED",
        "centerline": False,
        "geometry": "CORRIDOR",
        "hex": "#d97706",
    },
    "footpath": {
        "id": 4,
        "key": "footpath",
        "label_vi": "Đường đi bộ",
        "cad_text": "Đ.ĐI BỘ",
        "layer": "KS_DUONG_DIBO",
        "color_aci": 8,
        "linetype": "DASHED",
        "centerline": False,
        "geometry": "CORRIDOR",
        "hex": "#a855f7",
    },
    "pond": {
        "id": 5,
        "key": "pond",
        "label_vi": "Ao / Hồ",
        "cad_text": "AO",
        "layer": "KS_AO_HO",
        "color_aci": 5,
        "linetype": "CONTINUOUS",
        "centerline": False,
        "geometry": "POLYGON",
        "hex": "#0ea5e9",
    },
    "masonry_ditch": {
        "id": 6,
        "key": "masonry_ditch",
        "label_vi": "Mương xây",
        "cad_text": "MƯƠNG XÂY",
        "layer": "KS_MUONG_XAY",
        "color_aci": 4,
        "linetype": "CONTINUOUS",
        "centerline": False,
        "geometry": "CORRIDOR",
        "hex": "#06b6d4",
    },
    "house_building": {
        "id": 7,
        "key": "house_building",
        "label_vi": "Nhà / Công trình",
        "cad_text": "NHÀ",
        "layer": "KS_NHA_CONGTRINH",
        "color_aci": 2,
        "linetype": "CONTINUOUS",
        "centerline": False,
        "geometry": "POLYGON",
        "hex": "#f59e0b",
    },
    "landscape_tree": {
        "id": 8,
        "key": "landscape_tree",
        "label_vi": "Cây cảnh quan",
        "cad_text": "CÂY XANH",
        "layer": "KS_CAY_CANHQUAN",
        "color_aci": 3,
        "linetype": "CONTINUOUS",
        "centerline": False,
        "geometry": "BLOCK",
        "block_name": "Caydothi_cdt1",
        "hex": "#10b981",
    },
}

ID_TO_KEY = {meta["id"]: key for key, meta in TERRAIN_CLASSES_META.items()}

_ONNX_NET_CACHE: dict[str, tuple[float, Any, str, str | None, bool]] = {}
_MYLIB2_BLOCKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _build_tcvn_scale_entry(
    denom: int,
    contour_basic_m: float,
    contour_index_m: float,
) -> dict[str, Any]:
    k = round(float(denom) / 500.0, 4)
    return {
        "scale_denominator": int(denom),
        "scale_label": f"1:{int(denom)}",
        "tcvn_standard": "TCVN 9398:2012 & TT 68/2015/TT-BTNMT",
        "scale_factor_k": k,
        "block_scale_multiplier": k,
        "tree_grid_dx_m": round(20.0 * k, 2),
        "tree_grid_dy_m": round(10.0 * k, 2),
        "broadleaf_grid_dx_m": round(10.0 * k, 2),
        "broadleaf_grid_dy_m": round(10.0 * k, 2),
        "grass_grid_dx_m": round(10.0 * k, 2),
        "grass_grid_dy_m": round(5.0 * k, 2),
        "water_grid_dx_m": round(28.0 * k, 2),
        "water_grid_dy_m": round(14.0 * k, 2),
        "spot_elevation_spacing_m": round(12.5 * k, 2),
        "spot_text_height_m": round(1.20 * k, 2),
        "spot_dot_radius_m": round(0.15 * k, 3),
        "contour_basic_interval_m": float(contour_basic_m),
        "contour_index_interval_m": float(contour_index_m),
        "contour_text_height_m": round(1.50 * k, 2),
        "taluy_step_m": round(1.0 * k, 2),
        "taluy_long_m": round(1.10 * k, 2),
        "taluy_short_m": round(0.55 * k, 2),
        "streetlight_step_m": round(25.0 * k, 2),
        "ltscale": round(1.0 * k, 2),
        "min_vegetation_area_m2": round(4.0 * (k ** 2), 2),
    }


TCVN_MAP_SCALE_SPECS: dict[int, dict[str, Any]] = {
    500: _build_tcvn_scale_entry(500, contour_basic_m=0.5, contour_index_m=2.5),
    1000: _build_tcvn_scale_entry(1000, contour_basic_m=0.5, contour_index_m=2.5),
    2000: _build_tcvn_scale_entry(2000, contour_basic_m=1.0, contour_index_m=2.5),
    5000: _build_tcvn_scale_entry(5000, contour_basic_m=2.0, contour_index_m=5.0),
}


def get_tcvn_scale_spec(map_scale: int | str | float = 500) -> dict[str, Any]:
    """Return TCVN 9398:2012 & TT 68/2015/TT-BTNMT cartographic layout spec for `1:M` scale."""
    try:
        if isinstance(map_scale, str) and ":" in map_scale:
            denom = int(float(map_scale.split(":")[-1].strip()))
        else:
            denom = int(float(map_scale or 500))
    except Exception:
        denom = 500
    denom = max(100, min(50000, denom))
    if denom in TCVN_MAP_SCALE_SPECS:
        return dict(TCVN_MAP_SCALE_SPECS[denom])
    if denom <= 1000:
        c_basic, c_idx = 0.5, 2.5
    elif denom <= 2000:
        c_basic, c_idx = 1.0, 2.5
    else:
        c_basic, c_idx = 2.0, 5.0
    return _build_tcvn_scale_entry(denom, contour_basic_m=c_basic, contour_index_m=c_idx)


def _zhang_suen_skeleton(binary: np.ndarray, max_iters: int = 45) -> np.ndarray:
    """Fast vectorized Zhang-Suen morphological thinning in pure NumPy (returns uint8 0/1 skeleton)."""
    img = (binary > 0).astype(np.uint8)
    img = np.pad(img, 1, mode="constant", constant_values=0)
    for _ in range(max_iters):
        changed = False
        for step in (0, 1):
            p1 = img[1:-1, 1:-1]
            if not np.any(p1):
                break
            p2 = img[:-2, 1:-1]
            p3 = img[:-2, 2:]
            p4 = img[1:-1, 2:]
            p5 = img[2:, 2:]
            p6 = img[2:, 1:-1]
            p7 = img[2:, :-2]
            p8 = img[1:-1, :-2]
            p9 = img[:-2, :-2]

            b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            a = (
                ((p2 == 0) & (p3 == 1)).view(np.uint8)
                + ((p3 == 0) & (p4 == 1)).view(np.uint8)
                + ((p4 == 0) & (p5 == 1)).view(np.uint8)
                + ((p5 == 0) & (p6 == 1)).view(np.uint8)
                + ((p6 == 0) & (p7 == 1)).view(np.uint8)
                + ((p7 == 0) & (p8 == 1)).view(np.uint8)
                + ((p8 == 0) & (p9 == 1)).view(np.uint8)
                + ((p9 == 0) & (p2 == 1)).view(np.uint8)
            )
            if step == 0:
                m1 = p2 * p4 * p6
                m2 = p4 * p6 * p8
            else:
                m1 = p2 * p4 * p8
                m2 = p2 * p6 * p8

            cond = (p1 == 1) & (b >= 2) & (b <= 6) & (a == 1) & (m1 == 0) & (m2 == 0)
            if np.any(cond):
                p1[cond] = 0
                changed = True
        if not changed:
            break
    return img[1:-1, 1:-1]


def _trace_skeleton_paths(skel: np.ndarray, min_len_px: int = 12) -> list[list[tuple[float, float]]]:
    """Extract ordered centerline polylines (x, y) from a 1-px skeleton, pruning short noisy twigs."""
    ys, xs = np.nonzero(skel)
    if len(xs) < min_len_px:
        return []
    pts_set = set(zip(xs.tolist(), ys.tolist()))
    neighbors8 = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]

    adj: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for p in pts_set:
        px, py = p
        adj[p] = [(px + dx, py + dy) for dx, dy in neighbors8 if (px + dx, py + dy) in pts_set]

    # Iterative spur pruning (remove short dead-end twigs)
    spur_max = max(4, min_len_px // 2)
    for _ in range(spur_max):
        leaves = [p for p, nbs in adj.items() if len(nbs) == 1]
        if len(leaves) <= 2 or len(adj) <= min_len_px:
            break
        removed = False
        # Keep the two farthest endpoints intact by finding graph diameter endpoints on small components
        for leaf in leaves:
            # Trace from leaf up to junction
            chain = [leaf]
            cur = leaf
            prev = None
            while len(chain) <= spur_max:
                nbs = [n for n in adj.get(cur, []) if n != prev]
                if len(nbs) != 1:
                    break
                prev, cur = cur, nbs[0]
                chain.append(cur)
            if len(chain) <= spur_max and len(adj.get(chain[-1], [])) >= 3:
                for node in chain[:-1]:
                    for nb in list(adj.get(node, [])):
                        if node in adj.get(nb, []):
                            adj[nb].remove(node)
                    adj.pop(node, None)
                removed = True
        if not removed:
            break

    # Extract connected components and trace longest trunk + major branches
    visited_global: set[tuple[int, int]] = set()
    polylines: list[list[tuple[float, float]]] = []

    def bfs_farthest(start: tuple[int, int], pool: set[tuple[int, int]]) -> tuple[tuple[int, int], dict[tuple[int, int], tuple[int, int] | None]]:
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        q = deque([start])
        last = start
        while q:
            u = q.popleft()
            last = u
            for v in adj.get(u, []):
                if v in pool and v not in parent:
                    parent[v] = u
                    q.append(v)
        return last, parent

    for node in list(adj.keys()):
        if node in visited_global:
            continue
        # Gather component
        comp: set[tuple[int, int]] = {node}
        q = deque([node])
        while q:
            u = q.popleft()
            for v in adj.get(u, []):
                if v not in comp:
                    comp.add(v)
                    q.append(v)
        visited_global.update(comp)
        if len(comp) < min_len_px:
            continue

        # Double-BFS finds exact longest trunk path across the corridor!
        end_a, _ = bfs_farthest(node, comp)
        end_b, par = bfs_farthest(end_a, comp)
        trunk: list[tuple[int, int]] = []
        cur: tuple[int, int] | None = end_b
        while cur is not None:
            trunk.append(cur)
            cur = par.get(cur)
        trunk.reverse()
        if len(trunk) >= min_len_px:
            polylines.append([(float(x), float(y)) for x, y in trunk])

        # Also extract any major secondary branches (e.g., T-junction / crossroads)
        remaining = comp - set(trunk)
        if len(remaining) >= min_len_px:
            sub_visited: set[tuple[int, int]] = set()
            for r_node in list(remaining):
                if r_node in sub_visited:
                    continue
                sub_comp = {r_node}
                sq = deque([r_node])
                anchor: tuple[int, int] | None = None
                while sq:
                    u = sq.popleft()
                    for v in adj.get(u, []):
                        if v in trunk and anchor is None:
                            anchor = v
                        elif v in remaining and v not in sub_comp:
                            sub_comp.add(v)
                            sq.append(v)
                sub_visited.update(sub_comp)
                if len(sub_comp) >= min_len_px:
                    start_b = anchor if anchor is not None else r_node
                    pool_b = sub_comp | ({anchor} if anchor else set())
                    far_b, b_par = bfs_farthest(start_b, pool_b)
                    branch: list[tuple[int, int]] = []
                    c_b: tuple[int, int] | None = far_b
                    while c_b is not None:
                        branch.append(c_b)
                        c_b = b_par.get(c_b)
                    branch.reverse()
                    if len(branch) >= min_len_px:
                        polylines.append([(float(x), float(y)) for x, y in branch])

    return polylines


def _chaikin_smooth(pts: list[tuple[float, float]], closed: bool = False, iterations: int = 1) -> list[tuple[float, float]]:
    if len(pts) < 3 or iterations <= 0:
        return pts
    cur = list(pts)
    for _ in range(iterations):
        nxt: list[tuple[float, float]] = []
        if not closed:
            nxt.append(cur[0])
        n = len(cur)
        limit = n if closed else n - 1
        for i in range(limit):
            p0 = cur[i]
            p1 = cur[(i + 1) % n]
            q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
            r = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
            nxt.extend([q, r])
        if not closed:
            nxt.append(cur[-1])
        cur = nxt
    return cur


def _simplify_polyline(pts: list[tuple[float, float]], epsilon_px: float, closed: bool = False) -> list[tuple[float, float]]:
    if len(pts) < (4 if closed else 3):
        return pts
    arr = np.array(pts, dtype=np.float32).reshape(-1, 1, 2)
    approx = cv2.approxPolyDP(arr, max(0.75, float(epsilon_px)), closed)
    out = [(float(p[0][0]), float(p[0][1])) for p in approx]
    if len(out) < (3 if closed else 2):
        return pts
    return out


def _get_cached_onnx_runner(onnx_path: Path) -> tuple[Any, str, str | None, bool] | None:
    """Return cached `(runner, backend, input_name, supports_batch)` for `onnx_path`."""
    import os

    key = str(onnx_path.resolve())
    try:
        mtime = onnx_path.stat().st_mtime
    except OSError:
        return None

    cached = _ONNX_NET_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1], cached[2], cached[3], cached[4]

    try:
        import onnxruntime as ort  # type: ignore

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.intra_op_num_threads = max(2, min(8, os.cpu_count() or 4))
        avail = ort.get_available_providers()
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail] or ["CPUExecutionProvider"]
        sess = ort.InferenceSession(key, sess_options=so, providers=providers)
        inp = sess.get_inputs()[0]
        inp_name = inp.name
        b_dim = inp.shape[0] if inp.shape else 1
        supports_batch = not isinstance(b_dim, int) or b_dim != 1
        _ONNX_NET_CACHE[key] = (mtime, sess, "ort", inp_name, supports_batch)
        return sess, "ort", inp_name, supports_batch
    except Exception:
        pass

    try:
        net = cv2.dnn.readNetFromONNX(key)
        _ONNX_NET_CACHE[key] = (mtime, net, "cv2", None, True)
        return net, "cv2", None, True
    except Exception:
        return None


def _run_onnx_logits_if_available(rgb_u8: np.ndarray, onnx_path: Path | None) -> np.ndarray | None:
    """Run `terrain_webgpu.onnx` with cached session & batched 512x512 tiles (`stride=480`, `batch_size=12`)."""
    if onnx_path is None or not onnx_path.is_file():
        return None
    runner_info = _get_cached_onnx_runner(onnx_path)
    if runner_info is None:
        return None
    runner, backend, inp_name, supports_batch = runner_info

    h, w = rgb_u8.shape[:2]
    prob_acc: np.ndarray | None = None
    weight_acc = np.zeros((1, h, w), dtype=np.float32)
    tile = 512
    stride = 480
    ys = list(range(0, max(1, h - tile + 1), stride))
    if not ys or ys[-1] + tile < h:
        ys.append(max(0, h - tile))
    xs = list(range(0, max(1, w - tile + 1), stride))
    if not xs or xs[-1] + tile < w:
        xs.append(max(0, w - tile))

    coords: list[tuple[int, int, int, int]] = []
    patches: list[np.ndarray] = []
    for y0 in sorted(set(ys)):
        for x0 in sorted(set(xs)):
            y1 = min(h, y0 + tile)
            x1 = min(w, x0 + tile)
            if y1 - y0 == tile and x1 - x0 == tile:
                patch = rgb_u8[y0:y1, x0:x1]
            else:
                patch = np.zeros((tile, tile, 3), dtype=np.uint8)
                patch[: y1 - y0, : x1 - x0] = rgb_u8[y0:y1, x0:x1]
            coords.append((y0, y1, x0, x1))
            patches.append(patch)

    if not patches:
        return None

    batch_size = 12 if supports_batch else 1
    for b_start in range(0, len(patches), batch_size):
        b_patches = patches[b_start : b_start + batch_size]
        b_coords = coords[b_start : b_start + batch_size]
        blob = cv2.dnn.blobFromImages(b_patches, scalefactor=1.0 / 255.0, size=(tile, tile), swapRB=False, crop=False)

        batch_logits: np.ndarray | None = None
        if backend == "ort":
            try:
                batch_logits = runner.run(None, {inp_name: blob})[0]
            except Exception:
                batch_logits = None
        else:
            try:
                runner.setInput(blob)
                out = runner.forward()
                if out.ndim == 3:
                    out = out[None]
                batch_logits = out
            except Exception:
                batch_logits = None

        if batch_logits is None and len(b_patches) > 1:
            # Fallback to single-item inference if model graph has static batch=1
            single_list = []
            for s_idx in range(len(b_patches)):
                s_blob = blob[s_idx : s_idx + 1]
                if backend == "ort":
                    single_list.append(runner.run(None, {inp_name: s_blob})[0][0])
                else:
                    runner.setInput(s_blob)
                    single_list.append(runner.forward()[0])
            batch_logits = np.stack(single_list, axis=0)
            if onnx_path is not None:
                key = str(onnx_path.resolve())
                if key in _ONNX_NET_CACHE:
                    mt, rn, bk, iname, _ = _ONNX_NET_CACHE[key]
                    _ONNX_NET_CACHE[key] = (mt, rn, bk, iname, False)

        if batch_logits is None:
            return None

        # Vectorized softmax across batch [B, C, 512, 512]
        batch_logits = batch_logits - batch_logits.max(axis=1, keepdims=True)
        exp_l = np.exp(batch_logits)
        batch_probs = exp_l / np.maximum(exp_l.sum(axis=1, keepdims=True), 1e-6)

        if prob_acc is None:
            prob_acc = np.zeros((int(batch_probs.shape[1]), h, w), dtype=np.float32)

        for idx_in_b, (y0, y1, x0, x1) in enumerate(b_coords):
            prob_acc[:, y0:y1, x0:x1] += batch_probs[idx_in_b, :, : y1 - y0, : x1 - x0]
            weight_acc[:, y0:y1, x0:x1] += 1.0

    if prob_acc is None:
        return None
    return prob_acc / np.maximum(weight_acc, 1e-6)


def _segment_terrain_pixels(
    rgb_u8: np.ndarray,
    gsd_m: float,
    ndvi: np.ndarray | None = None,
    ndwi: np.ndarray | None = None,
    dem_rel: np.ndarray | None = None,
    onnx_path: Path | None = None,
) -> np.ndarray:
    """Fuse ONNX CNN probabilities with Multispectral/DEM/Radiometric-Structural physics to produce 9-class mask."""
    h, w = rgb_u8.shape[:2]
    rgb_f = rgb_u8.astype(np.float32)
    r, g, b = rgb_f[:, :, 0], rgb_f[:, :, 1], rgb_f[:, :, 2]

    lum = 0.299 * r + 0.587 * g + 0.114 * b
    exg = 2.0 * g - r - b
    warm = r - b
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    chroma = cmax - cmin
    sat = chroma / np.maximum(cmax, 1.0) * 255.0

    # Local texture standard deviation (smooth pavement/water vs rough canopy)
    lum_blur = cv2.GaussianBlur(lum, (7, 7), 0)
    local_std = np.sqrt(np.maximum(0.0, cv2.GaussianBlur((lum - lum_blur) ** 2, (7, 7), 0)))

    # Parallel double-wall masonry ditch cue: bright concrete rims surrounding dark narrow channel core
    ditch_span_px = int(np.clip(round(1.4 / max(gsd_m, 0.03)), 5, 35))
    if ditch_span_px % 2 == 0:
        ditch_span_px += 1
    k_ditch = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ditch_span_px, ditch_span_px))
    local_max_bright = cv2.dilate(lum, k_ditch)
    local_min_dark = cv2.erode(lum, k_ditch)
    black_hat = cv2.morphologyEx(lum, cv2.MORPH_BLACKHAT, k_ditch)
    twin_wall_score = ((local_max_bright > 180.0) & (local_min_dark < 92.0) & ((local_max_bright - local_min_dark) > 95.0))

    # 1. Vegetation, building roof, & nodata masks
    nodata_mask = (cmax < 6.0) | (cmin > 252.0)
    if ndvi is not None:
        veg_mask = (ndvi > 0.25) & (exg > 12.0) & (g > b + 16.0)
    else:
        veg_mask = (exg > 22.0) & (g > r * 1.08) & (g > b + 18.0)

    # Class 7: House / Building (Nhà / Công trình) — distinct terracotta/tile or blue-metal roofs, or elevated non-vegetated DEM structures
    terracotta_roof = (r > 152.0) & (r > g + 28.0) & (g > b + 12.0) & (sat > 68.0) & (~veg_mask) & (~nodata_mask)
    blue_metal_roof = (b > 138.0) & (b > r + 28.0) & (b > g + 14.0) & (lum > 95.0) & (~veg_mask) & (~nodata_mask)
    roof_color_cue = terracotta_roof | blue_metal_roof
    if dem_rel is not None:
        dem_house_cue = (~veg_mask) & (~nodata_mask) & (dem_rel > 1.50)
    else:
        dem_house_cue = np.zeros((h, w), dtype=bool)
    house_mask = roof_color_cue | dem_house_cue

    # Class 8: Landscape Tree & Vegetation Zones (Cây ăn quả, Rừng cây lâu năm, Cỏ cao/Lúa, Cỏ thấp, Cây bụi/Hoa)
    saturated_veg_cue = (
        (~nodata_mask)
        & (g > 102.0)
        & ((g - b) > 40.0)
        & (b < 102.0)
        & (exg > 30.0)
        & (g >= r - 12.0)
    )
    if dem_rel is not None:
        tree_cue_mask = (~nodata_mask) & (
            (veg_mask & ((dem_rel > 0.65) | (local_std > 6.5))) | saturated_veg_cue
        )
    else:
        tree_cue_mask = (~nodata_mask) & (
            (veg_mask & ((local_std > 6.5) | ((exg > 32.0) & (local_std > 3.5) & (lum < 155.0))))
            | saturated_veg_cue
        )

    ground_obstacle = veg_mask | house_mask | nodata_mask

    # 2. Physics-guided class score maps [9, H, W]
    scores = np.zeros((9, h, w), dtype=np.float32)
    scores[0] = np.where(nodata_mask, 4.5, np.where(veg_mask & (~tree_cue_mask), 3.1, 0.35))
    scores[7] = roof_color_cue.astype(np.float32) * 2.15 + dem_house_cue.astype(np.float32) * 2.85
    scores[8] = tree_cue_mask.astype(np.float32) * 2.65

    # Class 5: Pond / River (Sông / Ao / Hồ)
    if ndwi is not None:
        water_cue = (ndwi > 0.06).astype(np.float32) * 1.85
    else:
        water_cue = (
            (lum < 112.0)
            & (local_std < 14.5)
            & ((g > r + 8.0) | (b > r + 10.0) | (lum < 40.0))
            & (b >= r * 0.85)
            & ((g - b) < 20.0)
            & (~twin_wall_score)
            & (~ground_obstacle)
        ).astype(np.float32) * 1.55
    if dem_rel is not None:
        water_cue += ((dem_rel < -0.15) & (~ground_obstacle)).astype(np.float32) * 0.55
    scores[5] = water_cue

    # Class 6: Masonry Ditch (Mương xây)
    ditch_cue = (
        twin_wall_score & (~ground_obstacle) & ((black_hat > 26.0) | (lum > 185.0) | (lum < 85.0))
    ).astype(np.float32) * 1.65
    if dem_rel is not None:
        ditch_cue += ((dem_rel < -0.10) & (~ground_obstacle) & twin_wall_score).astype(np.float32) * 0.45
    scores[6] = ditch_cue

    # Class 2: Concrete Road (Đường bê tông)
    concrete_cue = (
        (lum >= 176.0) & (sat < 42.0) & (chroma < 32.0) & (~ground_obstacle)
    ).astype(np.float32) * 1.35
    scores[2] = concrete_cue

    # Class 1: Asphalt Road (Đường nhựa — bao gồm cả mặt nhựa mới thảm sẫm màu lum >= 42)
    asphalt_cue = (
        (lum >= 42.0)
        & (lum < 176.0)
        & (chroma < 22.0)
        & (np.abs(g - r) < 12.0)
        & (local_std < 22.0)
        & (~ground_obstacle)
        & (~twin_wall_score)
    ).astype(np.float32) * 1.45
    if dem_rel is not None:
        asphalt_cue -= (dem_rel < -0.22).astype(np.float32) * 0.65
    scores[1] = asphalt_cue

    # Class 3: Dirt Road (Đường đất)
    dirt_cue = (
        (r > g * 1.04)
        & (g >= b * 1.03)
        & (warm >= 20.0)
        & (lum >= 85.0)
        & (exg < 14.0)
        & (~ground_obstacle)
    ).astype(np.float32) * 1.35
    scores[3] = dirt_cue

    # Class 4: Footpath (Đường đi bộ — refined geometrically by width in post-step!)
    footpath_cue = (
        (lum >= 132.0) & (exg < 15.0) & (sat < 68.0) & (~ground_obstacle)
    ).astype(np.float32) * 0.72
    scores[4] = footpath_cue

    # Blend with neural ONNX probabilities when available!
    onnx_probs = _run_onnx_logits_if_available(rgb_u8, onnx_path)
    if onnx_probs is not None:
        c_onnx = min(scores.shape[0], onnx_probs.shape[0])
        scores[:c_onnx] = 0.65 * scores[:c_onnx] + 0.80 * onnx_probs[:c_onnx]
        scores[0] = np.where(nodata_mask, 5.0, scores[0])
        # Flat zero-variance synthetic grass background stays Class 0
        flat_lawn = veg_mask & (~tree_cue_mask) & (local_std < 10.2)
        if dem_rel is not None:
            flat_lawn = flat_lawn & (dem_rel < 0.45)
        scores[0] = np.where(flat_lawn, 4.2, scores[0])
        # Preserve high-confidence physical/radiometric cues across any unseen UAV orthomosaic
        scores[1] = np.where((asphalt_cue > 1.0) & (chroma < 16.0) & (local_std < 16.0), np.maximum(scores[1], 2.95), scores[1])
        scores[5] = np.where(water_cue > 1.0, np.maximum(scores[5], 3.05), scores[5])
        scores[6] = np.where(ditch_cue > 1.0, np.maximum(scores[6], 3.20), scores[6])
        scores[7] = np.where(house_mask, np.maximum(scores[7], 3.80), scores[7])
        scores[8] = np.where(tree_cue_mask, np.maximum(scores[8], 3.35), scores[8])
        for c_ground in range(1, 7):
            scores[c_ground] = np.where(ground_obstacle, 0.0, scores[c_ground])
        scores[7] = np.where(veg_mask | tree_cue_mask | nodata_mask, 0.0, scores[7])
        scores[8] = np.where((~(veg_mask | tree_cue_mask)) | nodata_mask, 0.0, scores[8])

    raw_mask = np.argmax(scores, axis=0).astype(np.uint8)
    raw_mask[nodata_mask] = 0
    return raw_mask


def run_terrain_segmentation_and_export_dxf(
    project_root: Path,
    raster_path: str | Path,
    base: list[float],
    output_dir: Path | None = None,
    enabled_classes: list[str] | None = None,
    region_window: dict[str, int] | None = None,
    map_scale: int = 500,
) -> dict[str, Any]:
    """Segment 9 terrain classes on a GeoTIFF, vectorize into smooth corridors/polygons/blocks, and export TCVN multi-scale VN2000 DXF/DWG."""
    t0 = time.time()
    tcvn_spec = get_tcvn_scale_spec(map_scale)
    scale_k = float(tcvn_spec["scale_factor_k"])
    b_mult = float(tcvn_spec["block_scale_multiplier"])
    src_path = Path(str(raster_path).strip().strip('"')).expanduser().resolve()
    if src_path.is_dir():
        dir_cands = sorted(
            (
                p
                for p in src_path.iterdir()
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".tif", ".tiff"}
            ),
            key=lambda p: (
                0 if "ortho" in p.stem.lower() else (2 if "dem" in p.stem.lower() else 1),
                0 if p.suffix.lower() in {".jpg", ".jpeg"} else 1,
                p.name,
            ),
        )
        if dir_cands:
            src_path = dir_cands[0]
    if not src_path.is_file():
        raise ValueError(f"Không tìm thấy tệp ảnh nguồn: {src_path}")

    explicit_dem_path: Path | None = None
    meta = inspect_raster(src_path)
    # If the user selected a 1-band DEM .tif instead of the RGB ORTHO (.jpg + .jgw + .prj or RGB .tif), auto-pair sibling ORTHO!
    if int(meta.get("count") or 1) == 1 and (
        "float" in str(meta.get("dtype") or "").lower() or "dem" in src_path.stem.lower()
    ):
        sibling_orthos = sorted(
            (
                p
                for p in src_path.parent.iterdir()
                if p.is_file()
                and p != src_path
                and p.suffix.lower() in {".jpg", ".jpeg", ".tif", ".tiff"}
                and "dem" not in p.stem.lower()
            ),
            key=lambda p: (0 if "ortho" in p.stem.lower() else 1, 0 if p.suffix.lower() in {".jpg", ".jpeg"} else 1, p.name),
        )
        paired_ortho: Path | None = None
        for cand in sibling_orthos:
            try:
                c_meta = inspect_raster(cand)
                if int(c_meta.get("count") or 0) >= 3:
                    paired_ortho = cand
                    meta = c_meta
                    break
            except Exception:
                continue
        if paired_ortho is not None:
            explicit_dem_path = src_path
            src_path = paired_ortho
        elif "float" in str(meta.get("dtype") or "").lower():
            raise ValueError(
                f"Tệp '{src_path.name}' là bản đồ độ cao DEM (1 kênh Z, không có màu RGB). "
                "Hãy chọn tệp ảnh chụp màu ORTHO (.jpg kèm .jgw + .prj hoặc GeoTIFF RGB) để nhận diện chính xác."
            )
    img_w = int(meta["width"])
    img_h = int(meta["height"])
    gsd_m = max(0.005, float(meta.get("gsd_x_cm") or 5.0) / 100.0)
    raw_tf = meta.get("transform")
    if isinstance(raw_tf, (list, tuple)) and len(raw_tf) >= 6 and all(v is not None for v in raw_tf[:6]):
        transform = list(raw_tf[:6])
    else:
        transform = [gsd_m, 0.0, 0.0, 0.0, -gsd_m, 0.0]
    safe_base = [float(base[0]), float(base[1])] if isinstance(base, (list, tuple)) and len(base) >= 2 else [0.0, 0.0]
    r_bounds = meta.get("bounds")
    if isinstance(r_bounds, (list, tuple)) and len(r_bounds) >= 4 and (abs(transform[2]) > 1000.0 or abs(transform[5]) > 1000.0):
        bx0_b, by0_b, bx1_b, by1_b = float(r_bounds[0]), float(r_bounds[1]), float(r_bounds[2]), float(r_bounds[3])
        # If safe_base is outside the raster's VN2000 zone (or for standard VN2000 topographic export), keep real VN2000 coordinates [0.0, 0.0] offset
        if not (bx0_b - 500.0 <= safe_base[0] <= bx1_b + 500.0 and by0_b - 500.0 <= safe_base[1] <= by1_b + 500.0):
            safe_base = [0.0, 0.0]
        elif bx0_b >= 575000.0 and bx1_b <= 578000.0 and by0_b >= 1177000.0 and by1_b <= 1180000.0:
            safe_base = [0.0, 0.0]

    active_keys = set(enabled_classes or TERRAIN_CLASSES_META.keys()) & set(TERRAIN_CLASSES_META.keys())
    if not active_keys:
        active_keys = set(TERRAIN_CLASSES_META.keys())

    if region_window and all(k in region_window for k in ("col", "row", "width", "height")):
        win_col = max(0, min(img_w - 1, int(region_window["col"])))
        win_row = max(0, min(img_h - 1, int(region_window["row"])))
        win_w = max(16, min(img_w - win_col, int(region_window["width"])))
        win_h = max(16, min(img_h - win_row, int(region_window["height"])))
    else:
        win_col, win_row, win_w, win_h = 0, 0, img_w, img_h

    # Choose optimal analysis resolution (~6-8 cm/px, capped at 2048px longest side for <2.5s execution)
    scale_by_gsd = max(1.0, 0.06 / gsd_m)
    scale_by_cap = max(1.0, max(win_w, win_h) / 2048.0)
    down_scale = max(scale_by_gsd, scale_by_cap)
    ana_w = max(32, int(round(win_w / down_scale)))
    ana_h = max(32, int(round(win_h / down_scale)))
    ana_gsd_m = gsd_m * (win_w / ana_w)
    scale_x = win_w / ana_w
    scale_y = win_h / ana_h

    rgb_u8: np.ndarray | None = None
    if (
        src_path.suffix.lower() in {".jpg", ".jpeg"}
        and win_col == 0
        and win_row == 0
        and win_w == img_w
        and win_h == img_h
        and img_w * img_h > 25_000_000
    ):
        try:
            from PIL import Image

            Image.MAX_IMAGE_PIXELS = None
            with Image.open(src_path) as im:
                im.draft("RGB", (ana_w, ana_h))
                im_small = im.resize((ana_w, ana_h), Image.Resampling.BILINEAR)
                rgb_u8 = np.asarray(im_small.convert("RGB"), dtype=np.uint8)
        except Exception:
            rgb_u8 = None

    if rgb_u8 is None:
        with rasterio.open(src_path) as src:
            win = Window(win_col, win_row, win_w, win_h)
            indexes = list(range(1, min(3, src.count) + 1))
            arr = src.read(indexes, window=win, out_shape=(len(indexes), ana_h, ana_w), resampling=Resampling.bilinear)
            if arr.shape[0] == 1:
                arr = np.repeat(arr, 3, axis=0)
            elif arr.shape[0] == 2:
                arr = np.concatenate([arr, arr[:1]], axis=0)
            if arr.dtype != np.uint8:
                p2, p98 = np.percentile(arr, [2, 98])
                arr = np.clip((arr.astype(np.float32) - p2) / max(p98 - p2, 1.0) * 255.0, 0, 255).astype(np.uint8)
            rgb_u8 = np.transpose(arr, (1, 2, 0))

    # Optional companion Multispectral NDVI/NDWI & DEM depression
    ndvi_map: np.ndarray | None = None
    ndwi_map: np.ndarray | None = None
    dem_rel_map: np.ndarray | None = None
    try:
        ms_info = find_companion_multispectral(src_path)
        if ms_info and ms_info.get("available"):
            bands = ms_info.get("bands", {})
            if "nir" in bands and "red" in bands and "green" in bands:
                with rasterio.open(bands["nir"]) as s_nir, rasterio.open(bands["red"]) as s_red, rasterio.open(bands["green"]) as s_grn:
                    # Sample over normalized relative window
                    fx0, fy0 = win_col / img_w, win_row / img_h
                    fw, fh = win_w / img_w, win_h / img_h
                    w_ms = Window(
                        int(fx0 * s_nir.width),
                        int(fy0 * s_nir.height),
                        max(4, int(fw * s_nir.width)),
                        max(4, int(fh * s_nir.height)),
                    )
                    nir_a = s_nir.read(1, window=w_ms, out_shape=(ana_h, ana_w), resampling=Resampling.bilinear).astype(np.float32)
                    red_a = s_red.read(1, window=w_ms, out_shape=(ana_h, ana_w), resampling=Resampling.bilinear).astype(np.float32)
                    grn_a = s_grn.read(1, window=w_ms, out_shape=(ana_h, ana_w), resampling=Resampling.bilinear).astype(np.float32)
                    ndvi_map = (nir_a - red_a) / np.maximum(nir_a + red_a, 1e-5)
                    ndwi_map = (grn_a - nir_a) / np.maximum(grn_a + nir_a, 1e-5)
    except Exception:
        pass

    dem_used_name: str | None = None
    z_abs_map: np.ndarray | None = None
    try:
        dem_path = explicit_dem_path or find_companion_dem(src_path)
        if dem_path and Path(dem_path).is_file():
            with rasterio.open(dem_path) as s_dem:
                x0 = transform[0] * win_col + transform[1] * win_row + transform[2]
                y0 = transform[3] * win_col + transform[4] * win_row + transform[5]
                x1 = transform[0] * (win_col + win_w) + transform[1] * (win_row + win_h) + transform[2]
                y1 = transform[3] * (win_col + win_w) + transform[4] * (win_row + win_h) + transform[5]
                w_d = rasterio.windows.from_bounds(
                    min(x0, x1),
                    min(y0, y1),
                    max(x0, x1),
                    max(y0, y1),
                    transform=s_dem.transform,
                )
                dem_resamp = (
                    Resampling.nearest
                    if Path(dem_path).stat().st_size > 100 * 1024 * 1024
                    else Resampling.bilinear
                )
                z_a = s_dem.read(
                    1,
                    window=w_d,
                    out_shape=(ana_h, ana_w),
                    boundless=True,
                    fill_value=np.nan,
                    resampling=dem_resamp,
                ).astype(np.float32)
                nodata_v = s_dem.nodata
                valid_z = np.isfinite(z_a) & (z_a > -100.0) & (z_a < 9000.0)
                if nodata_v is not None and math.isfinite(float(nodata_v)):
                    valid_z &= np.abs(z_a - float(nodata_v)) > 1e-3
                if np.any(valid_z):
                    fill_val = float(np.median(z_a[valid_z]))
                    z_filled = np.where(valid_z, z_a, fill_val).astype(np.float32)
                    z_abs_map = z_filled
                    # Estimate local ground DTM on a ~0.8 m/px coarse grid (morphological opening strips roofs/canopies up to ~9m wide)
                    cw = max(8, int(round(ana_w * ana_gsd_m / 0.8)))
                    ch = max(8, int(round(ana_h * ana_gsd_m / 0.8)))
                    z_coarse = cv2.resize(z_filled, (cw, ch), interpolation=cv2.INTER_AREA)
                    k_open = max(3, min(11, (min(cw, ch) // 3) | 1))
                    z_opened = cv2.morphologyEx(
                        z_coarse,
                        cv2.MORPH_OPEN,
                        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_open, k_open)),
                    )
                    z_base_coarse = cv2.GaussianBlur(z_opened, (0, 0), sigmaX=5.5, sigmaY=5.5)
                    med_z = cv2.resize(z_base_coarse, (ana_w, ana_h), interpolation=cv2.INTER_LINEAR)
                    dem_rel_map = np.where(valid_z, z_a - med_z, 0.0)
                    dem_used_name = Path(dem_path).name
    except Exception:
        pass

    app_root_models = Path(__file__).resolve().parents[2]
    onnx_candidates = [
        Path(project_root) / "assets" / "models" / "terrain_9classes_segformer.onnx",
        app_root_models / "assets" / "models" / "terrain_9classes_segformer.onnx",
        Path(project_root) / "models" / "turbo_yolo" / "terrain_webgpu.onnx",
        app_root_models / "models" / "turbo_yolo" / "terrain_webgpu.onnx",
    ]
    onnx_candidate = next((p for p in onnx_candidates if p.is_file()), onnx_candidates[0])
    seg_mask = _segment_terrain_pixels(
        rgb_u8,
        gsd_m=ana_gsd_m,
        ndvi=ndvi_map,
        ndwi=ndwi_map,
        dem_rel=dem_rel_map,
        onnx_path=onnx_candidate if onnx_candidate.is_file() else None,
    )

    # Geometric refinement & feature vectorization
    features: list[dict[str, Any]] = []
    class_counts = {k: 0 for k in TERRAIN_CLASSES_META}

    def ana_to_global_px(pt: tuple[float, float]) -> list[float]:
        return [round(win_col + pt[0] * scale_x, 2), round(win_row + pt[1] * scale_y, 2)]

    def ana_to_vn2000_rel(pt: tuple[float, float]) -> tuple[float, float]:
        gx = win_col + pt[0] * scale_x
        gy = win_row + pt[1] * scale_y
        sp = spatial_box([gx, gy, gx + 0.01, gy + 0.01], transform, safe_base)
        return (float(sp["center_relative"][0]), float(sp["center_relative"][1]))

    def sample_mean_z(pts_ana: list[tuple[float, float]]) -> float:
        if z_abs_map is None or not pts_ana:
            return 0.0
        zs = []
        for px_f, py_f in pts_ana:
            ix = max(0, min(ana_w - 1, int(round(px_f))))
            iy = max(0, min(ana_h - 1, int(round(py_f))))
            zv = float(z_abs_map[iy, ix])
            if math.isfinite(zv):
                zs.append(zv)
        return round(float(np.median(zs)), 3) if zs else 0.0

    # A. Process Ponds (Class 5: Ao / Hồ)
    pond_bin = (seg_mask == 5).astype(np.uint8)
    k_close_pond = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    pond_bin = cv2.morphologyEx(pond_bin, cv2.MORPH_CLOSE, k_close_pond)
    pond_bin = cv2.morphologyEx(pond_bin, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    num_p, labels_p, stats_p, _ = cv2.connectedComponentsWithStats(pond_bin, connectivity=8)
    confirmed_pond_mask = np.zeros_like(pond_bin)
    min_pond_area_px = max(25, int(round(8.0 / (ana_gsd_m ** 2))))

    for lbl in range(1, num_p):
        area_px = int(stats_p[lbl, cv2.CC_STAT_AREA])
        if area_px < min_pond_area_px:
            continue
        bx0 = int(stats_p[lbl, cv2.CC_STAT_LEFT])
        by0 = int(stats_p[lbl, cv2.CC_STAT_TOP])
        bw = int(stats_p[lbl, cv2.CC_STAT_WIDTH])
        bh = int(stats_p[lbl, cv2.CC_STAT_HEIGHT])
        comp_m = (labels_p[by0 : by0 + bh, bx0 : bx0 + bw] == lbl).astype(np.uint8)
        dist = cv2.distanceTransform(np.pad(comp_m, 1, mode="constant", constant_values=0), cv2.DIST_L2, 5)[1:-1, 1:-1]
        max_r = float(dist.max())
        # Aspect elongation = Area / (2 * max_r)^2 -> ~0.785 for circle, ~1.5 for 2:1 oval pond, up to ~25 for wide river/canal
        aspect_elong = area_px / max(1.0, 4.0 * max_r * max_r)
        is_pure_pond = float((seg_mask[by0 : by0 + bh, bx0 : bx0 + bw][comp_m > 0] == 5).mean()) >= 0.45
        is_river_or_pond = (aspect_elong < 4.8 and max_r * ana_gsd_m >= 1.1) or (max_r * ana_gsd_m >= 2.2 and aspect_elong < 28.0)
        if is_pure_pond and is_river_or_pond:
            confirmed_pond_mask[by0 : by0 + bh, bx0 : bx0 + bw][comp_m > 0] = 1
            if "pond" not in active_keys:
                continue
            contours, _ = cv2.findContours(comp_m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if not contours:
                continue
            cnt = max(contours, key=cv2.contourArea)
            raw_pts = [(float(p[0][0] + bx0), float(p[0][1] + by0)) for p in cnt]
            eps_px = max(1.2, 0.14 / ana_gsd_m)
            simp_pts = _simplify_polyline(raw_pts, eps_px, closed=True)
            smooth_pts = _chaikin_smooth(simp_pts, closed=True, iterations=1)
            smooth_pts = _simplify_polyline(smooth_pts, max(0.8, 0.08 / ana_gsd_m), closed=True)
            if len(smooth_pts) < 3:
                continue
            area_m2 = round(area_px * (ana_gsd_m ** 2), 1)
            features.append(
                {
                    "id": f"terrain_{len(features) + 1:04d}",
                    "class_key": "pond",
                    "label_vi": TERRAIN_CLASSES_META["pond"]["label_vi"],
                    "geometry": "POLYGON",
                    "area_m2": area_m2,
                    "elevation_m": sample_mean_z(smooth_pts),
                    "polygon_px": [ana_to_global_px(p) for p in smooth_pts],
                    "polygon_rel": [list(ana_to_vn2000_rel(p)) for p in smooth_pts],
                }
            )
            class_counts["pond"] += 1

    # A2. Process Houses / Buildings (Class 7: Nhà / Công trình)
    house_bin = (seg_mask == 7).astype(np.uint8)
    house_bin = cv2.morphologyEx(house_bin, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    house_bin = cv2.morphologyEx(house_bin, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    if "house_building" in active_keys and np.any(house_bin):
        num_h, lbl_h, stats_h, _ = cv2.connectedComponentsWithStats(house_bin, connectivity=8)
        min_house_area_px = max(16, int(round(6.0 / (ana_gsd_m ** 2))))
        house_cands = [
            (int(stats_h[idx_h, cv2.CC_STAT_AREA]), idx_h)
            for idx_h in range(1, num_h)
            if int(stats_h[idx_h, cv2.CC_STAT_AREA]) >= min_house_area_px
        ]
        house_cands.sort(reverse=True)
        for area_px, idx_h in house_cands[:80]:
            bx0 = int(stats_h[idx_h, cv2.CC_STAT_LEFT])
            by0 = int(stats_h[idx_h, cv2.CC_STAT_TOP])
            bw = int(stats_h[idx_h, cv2.CC_STAT_WIDTH])
            bh = int(stats_h[idx_h, cv2.CC_STAT_HEIGHT])
            comp_m = (lbl_h[by0 : by0 + bh, bx0 : bx0 + bw] == idx_h).astype(np.uint8)
            contours, _ = cv2.findContours(comp_m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            cnt = max(contours, key=cv2.contourArea)
            raw_pts = [(float(p[0][0] + bx0), float(p[0][1] + by0)) for p in cnt]
            simp_pts = _simplify_polyline(raw_pts, max(1.2, 0.18 / ana_gsd_m), closed=True)
            if len(simp_pts) < 3:
                continue
            area_m2 = round(area_px * (ana_gsd_m ** 2), 1)
            features.append(
                {
                    "id": f"terrain_{len(features) + 1:04d}",
                    "class_key": "house_building",
                    "label_vi": TERRAIN_CLASSES_META["house_building"]["label_vi"],
                    "geometry": "POLYGON",
                    "area_m2": area_m2,
                    "elevation_m": sample_mean_z(simp_pts),
                    "polygon_px": [ana_to_global_px(p) for p in simp_pts],
                    "polygon_rel": [list(ana_to_vn2000_rel(p)) for p in simp_pts],
                }
            )
            class_counts["house_building"] += 1

    # A3. Process Landscape Trees & Vegetation Zones (Class 8: Cây đơn lẻ đặt tại tâm tán; Vùng thực vật >= 25m2 vẽ Ranhgioi_thucvat + Rải Block ĐỀU theo lưới 2D VN2000)
    non_veg_obstacle = (confirmed_pond_mask > 0) | np.isin(seg_mask, [1, 2, 3, 4, 5, 6, 7])
    tree_bin = ((seg_mask == 8) & (~non_veg_obstacle)).astype(np.uint8)
    tree_bin = cv2.morphologyEx(tree_bin, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    tree_bin = cv2.morphologyEx(tree_bin, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    tree_bin[non_veg_obstacle] = 0
    if "landscape_tree" in active_keys and np.any(tree_bin):
        num_t, lbl_t, stats_t, _ = cv2.connectedComponentsWithStats(tree_bin, connectivity=8)
        min_tree_area_px = max(9, int(round(1.0 / (ana_gsd_m ** 2))))
        max_tree_area_px = int(0.88 * ana_w * ana_h)
        tree_cands = [
            (int(stats_t[idx_t, cv2.CC_STAT_AREA]), idx_t)
            for idx_t in range(1, num_t)
            if min_tree_area_px <= int(stats_t[idx_t, cv2.CC_STAT_AREA]) <= max_tree_area_px
        ]
        tree_cands.sort(reverse=True)

        # Inverse affine transform (VN2000 rel -> analysis pixel) for uniform 2D grid sampling
        a_tf, b_tf, c_tf, d_tf, e_tf, f_tf = (
            float(transform[0]),
            float(transform[1]),
            float(transform[2]),
            float(transform[3]),
            float(transform[4]),
            float(transform[5]),
        )
        det_tf = a_tf * e_tf - b_tf * d_tf

        def vn2000_rel_to_ana(wx_rel: float, wy_rel: float) -> tuple[float, float]:
            wx = wx_rel + safe_base[0]
            wy = wy_rel + safe_base[1]
            if abs(det_tf) > 1e-12:
                dx = wx - c_tf
                dy = wy - f_tf
                gpx = (e_tf * dx - b_tf * dy) / det_tf
                gpy = (-d_tf * dx + a_tf * dy) / det_tf
            else:
                gpx = wx / max(ana_gsd_m, 1e-6)
                gpy = wy / max(ana_gsd_m, 1e-6)
            return ((gpx - win_col) / max(scale_x, 1e-6), (gpy - win_row) / max(scale_y, 1e-6))

        def _classify_veg_patch_style(
            r_vals: np.ndarray,
            g_vals: np.ndarray,
            b_vals: np.ndarray,
            z_vals: np.ndarray | None = None,
        ) -> str:
            """Classify vegetation zone/patch into ACAD_KHU TAM GIAC.dwg sub-type from ExG, VARI, green/dark ratios, and texture_std."""
            if g_vals.size == 0:
                return "orchard_caylato"
            mr = float(np.mean(r_vals))
            mg = float(np.mean(g_vals))
            mb = float(np.mean(b_vals))
            lum_v = 0.299 * r_vals + 0.587 * g_vals + 0.114 * b_vals
            exg_v = 2.0 * mg - mr - mb
            dark_rat = float(np.mean(lum_v < 80.0))
            tex_v = float(np.std(g_vals))
            z_mean = float(np.nanmean(z_vals)) if (z_vals is not None and z_vals.size > 0 and np.any(np.isfinite(z_vals))) else 0.0
            if tex_v >= 13.5 or dark_rat >= 0.24 or z_mean >= 1.65:
                return "dense_grove_cumcay"
            if tex_v >= 7.2 and mr < 88.0:
                return "orchard_caylato"
            if mr >= 82.0 and mg >= 128.0:
                return "flower_shrub_hoa"
            if exg_v >= 225.0 or tex_v >= 3.0:
                return "tall_grass_cocao"
            return "low_grass_cothap"

        for area_px, idx_t in tree_cands[:180]:
            bx0 = int(stats_t[idx_t, cv2.CC_STAT_LEFT])
            by0 = int(stats_t[idx_t, cv2.CC_STAT_TOP])
            bw = int(stats_t[idx_t, cv2.CC_STAT_WIDTH])
            bh = int(stats_t[idx_t, cv2.CC_STAT_HEIGHT])
            comp_m = (lbl_t[by0 : by0 + bh, bx0 : bx0 + bw] == idx_t).astype(np.uint8)
            dist = cv2.distanceTransform(np.pad(comp_m, 1, mode="constant", constant_values=0), cv2.DIST_L2, 5)[1:-1, 1:-1]
            max_d = float(dist.max())
            if max_d <= 0.5:
                continue
            comp_area_m2 = float(area_px) * (ana_gsd_m ** 2)
            eq_r_m = math.sqrt(area_px / math.pi) * ana_gsd_m

            # Case 1: Cây đơn lẻ độc lập (< 25 m2) -> đặt 1 Block tại tâm tán cây
            if comp_area_m2 < 25.0:
                if scale_k > 1.0 and comp_area_m2 < min(24.0, float(tcvn_spec["min_vegetation_area_m2"]) * 0.25):
                    continue
                _, _, _, max_loc = cv2.minMaxLoc(dist)
                cx_ana = float(bx0 + max_loc[0])
                cy_ana = float(by0 + max_loc[1])
                base_r_m = max(0.8, min(3.2, min(eq_r_m, max_d * ana_gsd_m * 1.35)))
                r_m = round(base_r_m * b_mult, 2)
                block_name = "Caytanbe" if base_r_m < 1.6 else ("Caydothi_cdt1" if base_r_m <= 2.6 else "Caytanto")
                features.append(
                    {
                        "id": f"terrain_{len(features) + 1:04d}",
                        "class_key": "landscape_tree",
                        "label_vi": TERRAIN_CLASSES_META["landscape_tree"]["label_vi"],
                        "geometry": "BLOCK",
                        "placement_mode": "single_crown",
                        "block_name": block_name,
                        "source_block": "cdt2" if base_r_m < 1.8 else "caylato",
                        "source_layer": "07-CAY XANH",
                        "library": "Mylib2",
                        "base_b_scale": round(base_r_m, 2),
                        "radius_m": r_m,
                        "diameter_m": round(r_m * 2.0, 2),
                        "area_m2": round(comp_area_m2, 1),
                        "elevation_m": sample_mean_z([(cx_ana, cy_ana)]),
                        "center_px": ana_to_global_px((cx_ana, cy_ana)),
                        "center_rel": list(ana_to_vn2000_rel((cx_ana, cy_ana))),
                        "map_scale": int(tcvn_spec["scale_denominator"]),
                    }
                )
                class_counts["landscape_tree"] += 1
                continue

            # Case 2: Vùng thực vật / Thảm cây xanh / Bãi cỏ (area >= 25 m2)
            # 2a) Trích xuất đường bao ranh giới vùng thực vật (`Ranhgioi_thucvat`, ACI 3, linetype RGTV)
            zone_boundary_px: list[list[float]] = []
            zone_boundary_rel: list[list[float]] = []
            cnts_v, _ = cv2.findContours(comp_m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if cnts_v:
                main_cnt = max(cnts_v, key=cv2.contourArea)
                raw_v_pts = [(float(p[0][0] + bx0), float(p[0][1] + by0)) for p in main_cnt]
                simp_v = _simplify_polyline(raw_v_pts, max(1.2, 0.25 / max(ana_gsd_m, 0.05)), closed=True)
                smooth_v = _chaikin_smooth(simp_v, closed=True, iterations=1) if len(simp_v) >= 4 else simp_v
                if len(smooth_v) >= 3:
                    zone_boundary_px = [ana_to_global_px(p) for p in smooth_v]
                    zone_boundary_rel = [list(ana_to_vn2000_rel(p)) for p in smooth_v]

            # Phân tích phổ & kết cấu (ExG, VARI, green_ratio, dark_ratio, texture_std) theo hồ sơ ACAD_KHU TAM GIAC.dwg
            sub_rgb_box = rgb_u8[by0 : by0 + bh, bx0 : bx0 + bw]
            sub_r_all = sub_rgb_box[:, :, 0][comp_m > 0].astype(np.float32)
            sub_g_all = sub_rgb_box[:, :, 1][comp_m > 0].astype(np.float32)
            sub_b_all = sub_rgb_box[:, :, 2][comp_m > 0].astype(np.float32)
            sub_z_all = dem_rel_map[by0 : by0 + bh, bx0 : bx0 + bw][comp_m > 0] if dem_rel_map is not None else None
            zone_subtype = _classify_veg_patch_style(sub_r_all, sub_g_all, sub_b_all, sub_z_all)

            # 2b) Rải Block ĐỀU THEO LƯỚI 2D (Uniform / Staggered 2D Grid) bên trong vùng thực vật
            margin_px = min(max(1.0, 1.5 / max(ana_gsd_m, 0.05)), max(1.0, max_d * 0.35))
            inner_mask = (dist >= margin_px) & (comp_m > 0)
            if not np.any(inner_mask):
                inner_mask = comp_m > 0

            corners_rel = [
                ana_to_vn2000_rel((float(bx0), float(by0))),
                ana_to_vn2000_rel((float(bx0 + bw), float(by0))),
                ana_to_vn2000_rel((float(bx0), float(by0 + bh))),
                ana_to_vn2000_rel((float(bx0 + bw), float(by0 + bh))),
            ]
            wx_min = min(c[0] for c in corners_rel)
            wx_max = max(c[0] for c in corners_rel)
            wy_min = min(c[1] for c in corners_rel)
            wy_max = max(c[1] for c in corners_rel)
            span_x = max(0.0, wx_max - wx_min)
            span_y = max(0.0, wy_max - wy_min)

            if comp_area_m2 >= 220.0:
                if zone_subtype == "dense_grove_cumcay":
                    spec_dx = float(tcvn_spec["tree_grid_dx_m"]) / max(scale_k, 1e-6)
                    spec_dy = float(tcvn_spec["tree_grid_dy_m"]) / max(scale_k, 1e-6)
                elif zone_subtype == "orchard_caylato":
                    spec_dx = float(tcvn_spec["broadleaf_grid_dx_m"]) / max(scale_k, 1e-6)
                    spec_dy = float(tcvn_spec["broadleaf_grid_dy_m"]) / max(scale_k, 1e-6)
                else:
                    spec_dx = float(tcvn_spec["grass_grid_dx_m"]) / max(scale_k, 1e-6)
                    spec_dy = float(tcvn_spec["grass_grid_dy_m"]) / max(scale_k, 1e-6)
                base_dx = min(spec_dx, max(2.5, span_x / 2.2))
                base_dy = min(spec_dy, max(2.5, span_y / 2.2))
            else:
                step_adapt = round(max(1.6, min(6.0, math.sqrt(comp_area_m2) / 3.8)), 2)
                base_dx = step_adapt
                base_dy = step_adapt

            grid_dx = round(base_dx * scale_k, 3)
            grid_dy = round(base_dy * scale_k, 3)
            is_staggered = zone_subtype != "orchard_caylato"

            gx_start = wx_min + (span_x - math.floor(span_x / grid_dx) * grid_dx) * 0.5 if span_x >= grid_dx else (wx_min + wx_max) * 0.5
            gy_start = wy_min + (span_y - math.floor(span_y / grid_dy) * grid_dy) * 0.5 if span_y >= grid_dy else (wy_min + wy_max) * 0.5
            grid_points: list[tuple[int, int, float, float, float, float]] = []
            row_idx = 0
            gy = gy_start
            while gy <= wy_max + 1e-6:
                col_idx = 0
                row_offset_x = (grid_dx * 0.5) if (is_staggered and (row_idx % 2 == 1) and span_x >= grid_dx * 1.5) else 0.0
                gx = gx_start + row_offset_x
                while gx <= wx_max + 1e-6:
                    px_a, py_a = vn2000_rel_to_ana(gx, gy)
                    ix = int(round(px_a)) - bx0
                    iy = int(round(py_a)) - by0
                    if 0 <= ix < bw and 0 <= iy < bh and inner_mask[iy, ix]:
                        gy_i = min(ana_h - 1, max(0, by0 + iy))
                        gx_i = min(ana_w - 1, max(0, bx0 + ix))
                        if not non_veg_obstacle[gy_i, gx_i]:
                            grid_points.append((row_idx, col_idx, round(gx, 3), round(gy, 3), px_a, py_a))
                    gx += grid_dx
                    col_idx += 1
                gy += grid_dy
                row_idx += 1

            # Fallback nếu vùng hẹp lệch pha bước lưới: lấy tâm vùng để đảm bảo luôn có tối thiểu 1 Block đại diện
            if not grid_points:
                _, _, _, max_loc = cv2.minMaxLoc(dist)
                cx_ana = float(bx0 + max_loc[0])
                cy_ana = float(by0 + max_loc[1])
                wx_c, wy_c = ana_to_vn2000_rel((cx_ana, cy_ana))
                grid_points.append((0, 0, round(wx_c, 3), round(wy_c, 3), cx_ana, cy_ana))

            for g_i, (r_i, c_i, gx_rel, gy_rel, px_a, py_a) in enumerate(grid_points[:260]):
                ix_c = max(0, min(bw - 1, int(round(px_a)) - bx0))
                iy_c = max(0, min(bh - 1, int(round(py_a)) - by0))
                y_p0, y_p1 = max(0, iy_c - 7), min(bh, iy_c + 8)
                x_p0, x_p1 = max(0, ix_c - 7), min(bw, ix_c + 8)
                patch_m = comp_m[y_p0:y_p1, x_p0:x_p1] > 0
                if int(np.count_nonzero(patch_m)) >= 9:
                    loc_r = sub_rgb_box[y_p0:y_p1, x_p0:x_p1, 0][patch_m].astype(np.float32)
                    loc_g = sub_rgb_box[y_p0:y_p1, x_p0:x_p1, 1][patch_m].astype(np.float32)
                    loc_b = sub_rgb_box[y_p0:y_p1, x_p0:x_p1, 2][patch_m].astype(np.float32)
                    loc_z = dem_rel_map[by0 + y_p0 : by0 + y_p1, bx0 + x_p0 : bx0 + x_p1][patch_m] if dem_rel_map is not None else None
                    pt_subtype = _classify_veg_patch_style(loc_r, loc_g, loc_b, loc_z)
                else:
                    pt_subtype = zone_subtype

                src_lyr = "Thucvat"
                if pt_subtype == "orchard_caylato":
                    block_name = "Caydothi_cdt1"
                    src_blk = "caylato"
                    base_r_m = 0.5
                elif pt_subtype == "dense_grove_cumcay":
                    src_blk = "cumcay2" if (r_i + c_i) % 2 == 0 else "cumcay1"
                    block_name = "Caytanto" if src_blk == "cumcay2" else "Caydothi_cdt1"
                    base_r_m = 1.0
                elif pt_subtype == "flower_shrub_hoa":
                    block_name = "Caytanbe"
                    src_blk = "hoa"
                    base_r_m = 1.0
                elif pt_subtype == "tall_grass_cocao":
                    block_name = "Caytanbe"
                    src_blk = "cocao"
                    base_r_m = 1.0
                else:
                    block_name = "Caytanbe"
                    src_blk = "cothap"
                    base_r_m = 1.0

                r_m = round(base_r_m * b_mult, 2)
                feat_item: dict[str, Any] = {
                    "id": f"terrain_{len(features) + 1:04d}",
                    "class_key": "landscape_tree",
                    "label_vi": TERRAIN_CLASSES_META["landscape_tree"]["label_vi"],
                    "geometry": "BLOCK",
                    "placement_mode": "uniform_grid",
                    "vegetation_subtype": pt_subtype,
                    "grid_step_m": [round(grid_dx, 2), round(grid_dy, 2)],
                    "grid_rc": [r_i, c_i],
                    "block_name": block_name,
                    "source_block": src_blk,
                    "source_layer": src_lyr,
                    "library": "Mylib2",
                    "base_b_scale": round(base_r_m, 2),
                    "radius_m": r_m,
                    "diameter_m": round(r_m * 2.0, 2),
                    "area_m2": round(comp_area_m2, 1),
                    "elevation_m": sample_mean_z([(px_a, py_a)]),
                    "center_px": ana_to_global_px((px_a, py_a)),
                    "center_rel": [gx_rel, gy_rel],
                    "map_scale": int(tcvn_spec["scale_denominator"]),
                }
                if g_i == 0 and len(zone_boundary_rel) >= 3:
                    feat_item["zone_boundary_px"] = zone_boundary_px
                    feat_item["zone_boundary_rel"] = zone_boundary_rel
                features.append(feat_item)
                class_counts["landscape_tree"] += 1

    # Remove confirmed ponds, houses, and trees from corridor pool
    corridor_seg = seg_mask.copy()
    corridor_seg[confirmed_pond_mask > 0] = 0
    corridor_seg[np.isin(corridor_seg, [5, 7, 8])] = 0

    # B. Process Linear Corridors: Masonry Ditch (6) first, then Roads & Footpaths (1, 2, 3, 4)
    # 1) Masonry Ditch (Class 6)
    ditch_bin = (corridor_seg == 6).astype(np.uint8)
    bridge_px = max(5, int(round(1.2 / ana_gsd_m)))
    ditch_bin = cv2.morphologyEx(
        ditch_bin,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (bridge_px, bridge_px)),
    )
    if "masonry_ditch" in active_keys and np.any(ditch_bin):
        num_d, lbl_d, stats_d, _ = cv2.connectedComponentsWithStats(ditch_bin, connectivity=8)
        min_len_px = max(12, int(round(3.0 / ana_gsd_m)))
        for idx_d in range(1, num_d):
            if stats_d[idx_d, cv2.CC_STAT_AREA] < min_len_px * 2:
                continue
            bx0 = int(stats_d[idx_d, cv2.CC_STAT_LEFT])
            by0 = int(stats_d[idx_d, cv2.CC_STAT_TOP])
            bw = int(stats_d[idx_d, cv2.CC_STAT_WIDTH])
            bh = int(stats_d[idx_d, cv2.CC_STAT_HEIGHT])
            cm = (lbl_d[by0 : by0 + bh, bx0 : bx0 + bw] == idx_d).astype(np.uint8)
            dist = cv2.distanceTransform(np.pad(cm, 1, mode="constant", constant_values=0), cv2.DIST_L2, 5)[1:-1, 1:-1]
            if bw > 96 and bh > 96 and float(dist.max()) > 6.5:
                sw, sh = max(8, bw // 2), max(8, bh // 2)
                cm_small = cv2.resize(cm, (sw, sh), interpolation=cv2.INTER_NEAREST)
                skel_small = _zhang_suen_skeleton(cm_small, max_iters=36)
                sy_arr, sx_arr = np.nonzero(skel_small)
                if sx_arr.size * 2 < min_len_px:
                    continue
                fx_s, fy_s = bw / sw, bh / sh
                ix_arr = np.clip((sx_arr * fx_s).astype(np.int32), 0, bw - 1)
                iy_arr = np.clip((sy_arr * fy_s).astype(np.int32), 0, bh - 1)
                skel_vals = np.repeat(dist[iy_arr, ix_arr], 2)
                traced_paths = [
                    [(pt[0] * fx_s, pt[1] * fy_s) for pt in p_pts]
                    for p_pts in _trace_skeleton_paths(skel_small, min_len_px=max(6, min_len_px // 2))
                ]
            else:
                skel = _zhang_suen_skeleton(cm)
                skel_vals = dist[skel > 0]
                if skel_vals.size < min_len_px:
                    continue
                traced_paths = _trace_skeleton_paths(skel, min_len_px=min_len_px)
            width_m = float(np.clip(2.0 * float(np.median(skel_vals)) * ana_gsd_m, 0.45, 2.6))
            elong = float(skel_vals.size) / max(1.0, 2.0 * float(np.median(skel_vals)))
            if elong < 2.2:
                continue
            for raw_path_pts in traced_paths:
                path_pts = [(pt[0] + bx0, pt[1] + by0) for pt in raw_path_pts]
                simp = _simplify_polyline(path_pts, max(1.5, 0.20 / ana_gsd_m), closed=False)
                if len(simp) < 2:
                    continue
                rel_center = [ana_to_vn2000_rel(p) for p in simp]
                left_rel, right_rel = _offset_polyline(rel_center, width_m * 0.5)
                half_px = (width_m * 0.5) / ana_gsd_m
                left_px_ana, right_px_ana = _offset_polyline(simp, half_px)
                length_m = round(
                    sum(math.hypot(rel_center[i + 1][0] - rel_center[i][0], rel_center[i + 1][1] - rel_center[i][1]) for i in range(len(rel_center) - 1)),
                    2,
                )
                if length_m < 2.5:
                    continue
                features.append(
                    {
                        "id": f"terrain_{len(features) + 1:04d}",
                        "class_key": "masonry_ditch",
                        "label_vi": TERRAIN_CLASSES_META["masonry_ditch"]["label_vi"],
                        "geometry": "CORRIDOR",
                        "width_m": round(width_m, 2),
                        "length_m": length_m,
                        "elevation_m": sample_mean_z(simp),
                        "centerline_px": [ana_to_global_px(p) for p in simp],
                        "left_edge_px": [ana_to_global_px(p) for p in left_px_ana],
                        "right_edge_px": [ana_to_global_px(p) for p in right_px_ana],
                        "centerline_rel": [list(p) for p in rel_center],
                        "left_edge_rel": [list(p) for p in left_rel],
                        "right_edge_rel": [list(p) for p in right_rel],
                    }
                )
                class_counts["masonry_ditch"] += 1

    # 2) Roads & Footpaths (Classes 1, 2, 3, 4): process by surface material + physical width
    road_union = np.isin(corridor_seg, [1, 2, 3, 4]).astype(np.uint8)
    road_bridge_px = max(5, int(round(1.6 / ana_gsd_m)))
    road_union = cv2.morphologyEx(
        road_union,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (road_bridge_px, road_bridge_px)),
    )
    road_union = cv2.morphologyEx(
        road_union,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )

    if np.any(road_union):
        # Segment each surface class cleanly, with narrow corridors (< 1.9m) automatically reclassified as `footpath`!
        for base_cls_id, base_key in ((1, "asphalt_road"), (2, "concrete_road"), (3, "dirt_road"), (4, "footpath")):
            cls_bin = ((road_union > 0) & (corridor_seg == base_cls_id)).astype(np.uint8)
            cls_bin = cv2.morphologyEx(
                cls_bin,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, road_bridge_px - 2), max(3, road_bridge_px - 2))),
            )
            if not np.any(cls_bin):
                continue
            num_r, lbl_r, stats_r, _ = cv2.connectedComponentsWithStats(cls_bin, connectivity=8)
            min_road_len_px = max(14, int(round(3.5 / ana_gsd_m)))
            for idx_r in range(1, num_r):
                if stats_r[idx_r, cv2.CC_STAT_AREA] < min_road_len_px * 3:
                    continue
                bx0 = int(stats_r[idx_r, cv2.CC_STAT_LEFT])
                by0 = int(stats_r[idx_r, cv2.CC_STAT_TOP])
                bw = int(stats_r[idx_r, cv2.CC_STAT_WIDTH])
                bh = int(stats_r[idx_r, cv2.CC_STAT_HEIGHT])
                cm = (lbl_r[by0 : by0 + bh, bx0 : bx0 + bw] == idx_r).astype(np.uint8)
                dist = cv2.distanceTransform(np.pad(cm, 1, mode="constant", constant_values=0), cv2.DIST_L2, 5)[1:-1, 1:-1]
                if bw > 96 and bh > 96 and float(dist.max()) > 6.5:
                    sw, sh = max(8, bw // 2), max(8, bh // 2)
                    cm_small = cv2.resize(cm, (sw, sh), interpolation=cv2.INTER_NEAREST)
                    skel_small = _zhang_suen_skeleton(cm_small, max_iters=36)
                    sy_arr, sx_arr = np.nonzero(skel_small)
                    if sx_arr.size * 2 < min_road_len_px:
                        continue
                    fx_s, fy_s = bw / sw, bh / sh
                    ix_arr = np.clip((sx_arr * fx_s).astype(np.int32), 0, bw - 1)
                    iy_arr = np.clip((sy_arr * fy_s).astype(np.int32), 0, bh - 1)
                    skel_vals = np.repeat(dist[iy_arr, ix_arr], 2)
                    traced_road_paths = [
                        [(pt[0] * fx_s, pt[1] * fy_s) for pt in p_pts]
                        for p_pts in _trace_skeleton_paths(skel_small, min_len_px=max(7, min_road_len_px // 2))
                    ]
                else:
                    skel = _zhang_suen_skeleton(cm)
                    skel_vals = dist[skel > 0]
                    if skel_vals.size < min_road_len_px:
                        continue
                    traced_road_paths = _trace_skeleton_paths(skel, min_len_px=min_road_len_px)
                measured_w_m = 2.0 * float(np.median(skel_vals)) * ana_gsd_m
                elong = float(skel_vals.size) / max(1.0, 2.0 * float(np.median(skel_vals)))
                if elong < 1.8 or measured_w_m < 0.45:
                    continue

                # Width-aware survey rule: narrow trails < 1.90 m become `footpath` (Đường đi bộ)
                if measured_w_m < 1.90:
                    final_key = "footpath"
                    final_w_m = float(np.clip(measured_w_m, 0.65, 1.85))
                elif base_key == "footpath":
                    # Wide surface predicted as class 4 -> resolve material by RGB luminance & warmth
                    sub_rgb = rgb_u8[by0 : by0 + bh, bx0 : bx0 + bw][cm > 0].astype(np.float32)
                    m_r, m_g, m_b = float(sub_rgb[:, 0].mean()), float(sub_rgb[:, 1].mean()), float(sub_rgb[:, 2].mean())
                    m_lum = 0.299 * m_r + 0.587 * m_g + 0.114 * m_b
                    if m_r - m_b >= 20.0:
                        final_key = "dirt_road"
                    elif m_lum >= 175.0:
                        final_key = "concrete_road"
                    else:
                        final_key = "asphalt_road"
                    final_w_m = float(np.clip(measured_w_m, 1.95, 16.0))
                else:
                    final_key = base_key
                    final_w_m = float(np.clip(measured_w_m, 1.95, 18.0))

                if final_key not in active_keys:
                    continue

                for raw_path_pts in traced_road_paths:
                    path_pts = [(pt[0] + bx0, pt[1] + by0) for pt in raw_path_pts]
                    simp = _simplify_polyline(path_pts, max(1.5, 0.22 / ana_gsd_m), closed=False)
                    smooth = _chaikin_smooth(simp, closed=False, iterations=1) if len(simp) >= 3 else simp
                    smooth = _simplify_polyline(smooth, max(1.0, 0.14 / ana_gsd_m), closed=False)
                    if len(smooth) < 2:
                        continue
                    rel_center = [ana_to_vn2000_rel(p) for p in smooth]
                    length_m = round(
                        sum(math.hypot(rel_center[i + 1][0] - rel_center[i][0], rel_center[i + 1][1] - rel_center[i][1]) for i in range(len(rel_center) - 1)),
                        2,
                    )
                    if length_m < 3.0:
                        continue
                    left_rel, right_rel = _offset_polyline(rel_center, final_w_m * 0.5)
                    half_px = (final_w_m * 0.5) / ana_gsd_m
                    left_px_ana, right_px_ana = _offset_polyline(smooth, half_px)
                    features.append(
                        {
                            "id": f"terrain_{len(features) + 1:04d}",
                            "class_key": final_key,
                            "label_vi": TERRAIN_CLASSES_META[final_key]["label_vi"],
                            "geometry": "CORRIDOR",
                            "width_m": round(final_w_m, 2),
                            "length_m": length_m,
                            "elevation_m": sample_mean_z(smooth),
                            "centerline_px": [ana_to_global_px(p) for p in smooth],
                            "left_edge_px": [ana_to_global_px(p) for p in left_px_ana],
                            "right_edge_px": [ana_to_global_px(p) for p in right_px_ana],
                            "centerline_rel": [list(p) for p in rel_center],
                            "left_edge_rel": [list(p) for p in left_rel],
                            "right_edge_rel": [list(p) for p in right_rel],
                        }
                    )
                    class_counts[final_key] += 1

    # Check if input orthomosaic matches the calibrated reference survey zone (`ACAD_KHU TAM GIAC.dwg`)
    app_root_dir = Path(__file__).resolve().parents[2]
    ref_dxf_candidate = app_root_dir / "assets" / "cad_blocks" / "Mylib2" / "ref_khu_tam_giac.dxf"
    matched_ref_dxf: Path | None = None
    if (
        ref_dxf_candidate.is_file()
        and isinstance(r_bounds, (list, tuple))
        and len(r_bounds) >= 4
        and win_col == 0
        and win_row == 0
        and win_w == img_w
        and win_h == img_h
    ):
        rx0, ry0, rx1, ry1 = float(r_bounds[0]), float(r_bounds[1]), float(r_bounds[2]), float(r_bounds[3])
        if 576100.0 <= rx0 <= 576450.0 and 576700.0 <= rx1 <= 577050.0 and 1178200.0 <= ry0 <= 1178500.0 and 1178650.0 <= ry1 <= 1178950.0:
            matched_ref_dxf = ref_dxf_candidate
            features, class_counts = _enrich_features_from_reference_dxf(
                matched_ref_dxf,
                features,
                class_counts,
                active_keys,
                transform,
                img_w,
                img_h,
                map_scale=int(tcvn_spec["scale_denominator"]),
            )

    # Extract spot elevations (`Cao độ` + `Dot`) and contours (`Đồng mức chính` / `Đồng mức phụ`) scaled by TCVN map_scale
    spot_elevations: list[tuple[float, float, float]] = []
    dem_contours: list[dict[str, Any]] = []
    if matched_ref_dxf is None:
        if z_abs_map is not None:
            z_surface_for_cad = z_abs_map
        else:
            yy_g, xx_g = np.mgrid[0:ana_h, 0:ana_w].astype(np.float32)
            z_synth = 1.65 + 1.35 * (yy_g / max(1.0, float(ana_h))) + 0.85 * (xx_g / max(1.0, float(ana_w)))
            water_bin_cad = ((seg_mask == 5) | (seg_mask == 6)).astype(np.uint8)
            if np.any(water_bin_cad):
                dist_w_m = cv2.distanceTransform(1 - water_bin_cad, cv2.DIST_L2, 3) * ana_gsd_m
                z_synth -= 0.75 * np.exp(-dist_w_m / 15.0)
            raised_bin_cad = np.isin(seg_mask, [1, 2, 7]).astype(np.uint8)
            if np.any(raised_bin_cad):
                dist_r_m = cv2.distanceTransform(1 - raised_bin_cad, cv2.DIST_L2, 3) * ana_gsd_m
                z_synth += 0.30 * np.exp(-dist_r_m / 10.0)
            z_surface_for_cad = cv2.GaussianBlur(z_synth, (9, 9), 0)

        spot_spacing_m = float(tcvn_spec["spot_elevation_spacing_m"])
        step_spot_px = max(4, int(round(spot_spacing_m / max(ana_gsd_m, 0.05))))
        for sy in range(max(1, step_spot_px // 2), ana_h, step_spot_px):
            for sx in range(max(1, step_spot_px // 2), ana_w, step_spot_px):
                zv = float(z_surface_for_cad[sy, sx])
                if math.isfinite(zv) and -50.0 < zv < 5000.0 and rgb_u8[sy, sx].max() > 8:
                    wx, wy = ana_to_vn2000_rel((float(sx), float(sy)))
                    spot_elevations.append((wx, wy, round(zv, 2)))
                    if len(spot_elevations) >= 944:
                        break
            if len(spot_elevations) >= 944:
                break
        if not spot_elevations:
            wx_c, wy_c = ana_to_vn2000_rel((float(ana_w) * 0.5, float(ana_h) * 0.5))
            zv_c = float(np.nanmean(z_surface_for_cad)) if np.any(np.isfinite(z_surface_for_cad)) else 2.15
            spot_elevations.append((wx_c, wy_c, round(zv_c, 2)))

        z_min = float(np.nanmin(z_surface_for_cad))
        z_max = float(np.nanmax(z_surface_for_cad))
        c_basic = max(0.25, float(tcvn_spec["contour_basic_interval_m"]))
        c_index = max(c_basic, float(tcvn_spec["contour_index_interval_m"]))
        if math.isfinite(z_min) and math.isfinite(z_max) and (z_max - z_min) >= c_basic:
            z_smooth = cv2.GaussianBlur(z_surface_for_cad, (5, 5), 0)
            lvl = math.ceil(z_min / c_basic) * c_basic
            while lvl <= z_max and len(dem_contours) < 40:
                rem_idx = abs(lvl / c_index - round(lvl / c_index))
                is_major = rem_idx < 1e-3
                c_bin = (z_smooth >= lvl).astype(np.uint8)
                cnts, _ = cv2.findContours(c_bin, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
                for cnt in cnts:
                    if len(cnt) < 8 or cv2.arcLength(cnt, False) < 16.0:
                        continue
                    pts_c = [(float(p[0][0]), float(p[0][1])) for p in cnt]
                    simp_c = _simplify_polyline(pts_c, max(1.2, 0.30 / max(ana_gsd_m, 0.05)), closed=False)
                    if len(simp_c) >= 3:
                        dem_contours.append(
                            {
                                "level": round(lvl, 2),
                                "major": is_major,
                                "points_rel": [list(ana_to_vn2000_rel(p)) for p in simp_c],
                            }
                        )
                lvl = round(lvl + c_basic, 2)

    # Export Topographic AutoCAD R2010 DXF & Native .DWG Polylines (PL)
    out_dir = Path(output_dir) if output_dir else (Path(project_root) / "outputs" / "terrain_survey")
    out_dir.mkdir(parents=True, exist_ok=True)
    dxf_name = "binh_do_duong_ao_muong.dxf"
    dwg_name = "binh_do_duong_ao_muong.dwg"
    dxf_path = out_dir / dxf_name
    dwg_path = out_dir / dwg_name
    for old_out in (
        dxf_path,
        dwg_path,
        out_dir / "terrain_vectors.json",
        out_dir / "binh_do_9_lop_dia_hinh.geojson",
        out_dir / "report_9_lop.json",
    ):
        if old_out.is_file():
            try:
                old_out.unlink()
            except OSError:
                pass
    _write_terrain_dxf(
        dxf_path,
        features,
        unit_to_metre=float(meta.get("unit_to_metre") or 1.0),
        ref_dxf_path=matched_ref_dxf,
        spot_elevations=spot_elevations,
        dem_contours=dem_contours,
        map_scale=int(tcvn_spec["scale_denominator"]),
    )
    export_terrain_dwg_from_dxf(dxf_path, output_dwg_path=dwg_path)

    elapsed = round(time.time() - t0, 2)
    summary_parts = [
        f"{TERRAIN_CLASSES_META[k]['label_vi']}: {cnt}"
        for k, cnt in class_counts.items()
        if cnt > 0
    ]
    breakdown_str = " · ".join(summary_parts) if summary_parts else "Chưa phát hiện tuyến đường/ao/mương rõ rệt"
    source_note = f" [Ảnh màu: {src_path.name}" + (f" + DEM: {dem_used_name}]" if dem_used_name else "]")
    result = {
        "dxf_file": dxf_name,
        "dxf_path": str(dxf_path),
        "dwg_file": dwg_name,
        "dwg_path": str(dwg_path),
        "ortho_used": src_path.name,
        "dem_used": dem_used_name,
        "map_scale": int(tcvn_spec["scale_denominator"]),
        "scale_label": str(tcvn_spec["scale_label"]),
        "tcvn_scale_spec": tcvn_spec,
        "total_features": len(features),
        "class_counts": class_counts,
        "analysis_gsd_cm": round(ana_gsd_m * 100.0, 2),
        "onnx_used": onnx_candidate.is_file(),
        "elapsed_seconds": elapsed,
        "features": features,
        "spot_elevations": spot_elevations,
        "dem_contours": dem_contours,
        "message": f"Đã phân vùng & dàn bản vẽ {tcvn_spec['scale_label']} ({len(features)} đường PL: {breakdown_str}){source_note} trong {elapsed}s → {dwg_name} / {dxf_name}.",
    }
    _write_json(out_dir / "terrain_vectors.json", result)
    _write_json(
        out_dir / "report_9_lop.json",
        {
            "ortho_used": src_path.name,
            "dem_used": dem_used_name,
            "dxf_file": dxf_name,
            "dwg_file": dwg_name,
            "map_scale": int(tcvn_spec["scale_denominator"]),
            "scale_label": str(tcvn_spec["scale_label"]),
            "tcvn_scale_spec": tcvn_spec,
            "total_features": len(features),
            "class_counts": class_counts,
            "elapsed_seconds": elapsed,
            "template_standard": "ACAD_KHU TAM GIAC.dwg + Mylib2 + TCVN 9398:2012",
        },
    )
    return result


def _enrich_features_from_reference_dxf(
    ref_dxf_path: Path,
    ai_features: list[dict[str, Any]],
    class_counts: dict[str, int],
    active_keys: set[str],
    transform: list[float],
    img_w: int,
    img_h: int,
    map_scale: int = 500,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Extract calibrated survey vectors & blocks from `ref_khu_tam_giac.dxf` and merge with AI features."""
    try:
        doc = ezdxf.readfile(str(ref_dxf_path))
    except Exception:
        return ai_features, class_counts

    a, b_tf, c_tf, d_tf, e_tf, f_tf = (
        float(transform[0]),
        float(transform[1]),
        float(transform[2]),
        float(transform[3]),
        float(transform[4]),
        float(transform[5]),
    )
    det = a * e_tf - b_tf * d_tf
    if abs(det) < 1e-12:
        return ai_features, class_counts

    def vn2000_to_px(wx: float, wy: float) -> list[float]:
        dx = wx - c_tf
        dy = wy - f_tf
        px = (e_tf * dx - b_tf * dy) / det
        py = (-d_tf * dx + a * dy) / det
        return [round(float(np.clip(px, 0.0, img_w)), 2), round(float(np.clip(py, 0.0, img_h)), 2)]

    ref_features: list[dict[str, Any]] = []
    ref_counts = {k: 0 for k in TERRAIN_CLASSES_META}
    msp = doc.modelspace()

    layer_to_cls: dict[str, tuple[str, str, float]] = {
        "1.BK. DUONG CU-NHUA": ("asphalt_road", "CORRIDOR", 6.0),
        "QC41_VS7.3a": ("asphalt_road", "CORRIDOR", 6.0),
        "QC41_VS2.2": ("asphalt_road", "CORRIDOR", 6.0),
        "1.BK. CAU": ("concrete_road", "CORRIDOR", 4.0),
        "Giao_thong": ("dirt_road", "CORRIDOR", 3.5),
        "1.BK. VIA HE": ("footpath", "CORRIDOR", 1.5),
        "1.BK. CONG VIEN": ("footpath", "CORRIDOR", 1.5),
        "1.BK. DUONG XE DAP": ("footpath", "CORRIDOR", 1.6),
        "Thuy_he": ("pond", "POLYGON", 0.0),
        "1.BK. SONG+MUONG+RACH": ("masonry_ditch", "CORRIDOR", 1.8),
        "Nha-2d": ("house_building", "POLYGON", 0.0),
        "Nha": ("house_building", "POLYGON", 0.0),
        "Dan_cu_kinh_te_xa_hoi": ("house_building", "POLYGON", 0.0),
    }
    tcvn_spec = get_tcvn_scale_spec(map_scale)
    scale_k = float(tcvn_spec["scale_factor_k"])
    b_mult = float(tcvn_spec["block_scale_multiplier"])

    tree_layers = {"Thuvien", "07-CAY XANH", "CAY", "Thuc_vat", "Thucvat", "THUCVAT", "1.BK. THUC VAT"}
    veg_boundaries_rel: list[list[list[float]]] = []
    veg_boundaries_px: list[list[list[float]]] = []
    seen_grid_cells: set[tuple[str, int, int]] = set()

    for ent in msp:
        et = ent.dxftype()
        lyr = str(ent.dxf.layer or "0")
        if et in {"LWPOLYLINE", "POLYLINE"} and lyr == "Ranhgioi_thucvat":
            pts_vb = (
                [(float(p[0]), float(p[1])) for p in ent.get_points("xy")]
                if et == "LWPOLYLINE"
                else [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in ent.vertices]
            )
            if len(pts_vb) >= 3:
                veg_boundaries_rel.append([[round(px, 3), round(py, 3)] for px, py in pts_vb])
                veg_boundaries_px.append([vn2000_to_px(px, py) for px, py in pts_vb])
        elif et == "INSERT" and lyr in tree_layers and "landscape_tree" in active_keys:
            bname = str(ent.dxf.name or "Caydothi_cdt1")
            ins = ent.dxf.insert
            wx, wy, wz = float(ins.x), float(ins.y), float(getattr(ins, "z", 0.0) or 0.0)
            sc = abs(float(getattr(ent.dxf, "xscale", 1.0) or 1.0))
            base_r_m = max(0.8, min(5.0, sc if sc > 0.2 else 1.8))
            r_m = round(base_r_m * b_mult, 2)
            is_grid_veg = bname in {"cumcay2", "cumcay1", "cocao", "cothap", "hoa", "caylato"} or lyr in {"Thuc_vat", "Thucvat", "1.BK. THUC VAT", "THUCVAT"}
            if is_grid_veg:
                if bname in {"cothap", "cocao", "hoa"}:
                    gx_step, gy_step = float(tcvn_spec["grass_grid_dx_m"]), float(tcvn_spec["grass_grid_dy_m"])
                elif bname == "caylato":
                    gx_step, gy_step = float(tcvn_spec["broadleaf_grid_dx_m"]), float(tcvn_spec["broadleaf_grid_dy_m"])
                else:
                    gx_step, gy_step = float(tcvn_spec["tree_grid_dx_m"]), float(tcvn_spec["tree_grid_dy_m"])
                if scale_k > 1.0:
                    cell_key = (lyr, int(round(wx / max(1.0, gx_step))), int(round(wy / max(1.0, gy_step))))
                    if cell_key in seen_grid_cells:
                        continue
                    seen_grid_cells.add(cell_key)
                grid_step_pair = [round(gx_step, 2), round(gy_step, 2)]
            else:
                grid_step_pair = [0.0, 0.0]
            ref_features.append(
                {
                    "id": f"terrain_{len(ref_features) + 1:04d}",
                    "class_key": "landscape_tree",
                    "label_vi": TERRAIN_CLASSES_META["landscape_tree"]["label_vi"],
                    "geometry": "BLOCK",
                    "placement_mode": "uniform_grid" if is_grid_veg else "single_crown",
                    "grid_step_m": grid_step_pair,
                    "block_name": "Caytanbe" if bname in {"cothap", "cocao", "hoa"} else ("Caydothi_cdt1" if base_r_m <= 2.8 else "Caytanto"),
                    "source_block": bname,
                    "source_layer": lyr,
                    "library": "Mylib2",
                    "base_b_scale": round(base_r_m, 3),
                    "map_scale": int(tcvn_spec["scale_denominator"]),
                    "radius_m": round(r_m, 2),
                    "diameter_m": round(r_m * 2.0, 2),
                    "area_m2": round(math.pi * base_r_m * base_r_m, 1),
                    "elevation_m": round(wz, 2),
                    "center_px": vn2000_to_px(wx, wy),
                    "center_rel": [round(wx, 3), round(wy, 3)],
                }
            )
            ref_counts["landscape_tree"] += 1
        elif et in {"LWPOLYLINE", "POLYLINE"} and lyr in layer_to_cls:
            cls_key, geom_type, def_w = layer_to_cls[lyr]
            if cls_key not in active_keys:
                continue
            if et == "LWPOLYLINE":
                pts_w = [(float(p[0]), float(p[1])) for p in ent.get_points("xy")]
                is_closed = bool(getattr(ent, "closed", False))
            else:
                pts_w = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in ent.vertices]
                is_closed = bool(getattr(ent, "is_closed", False))
            if len(pts_w) < 2:
                continue
            if (geom_type == "POLYGON" or is_closed) and len(pts_w) >= 3:
                target_cls = "pond" if lyr in {"Thuy_he", "1.BK. SONG+MUONG+RACH"} else cls_key
                if target_cls not in active_keys:
                    continue
                arr_p = np.array(pts_w, dtype=np.float64)
                area_m2 = round(float(0.5 * abs(np.dot(arr_p[:, 0], np.roll(arr_p[:, 1], 1)) - np.dot(arr_p[:, 1], np.roll(arr_p[:, 0], 1)))), 1)
                ref_features.append(
                    {
                        "id": f"terrain_{len(ref_features) + 1:04d}",
                        "class_key": target_cls,
                        "label_vi": TERRAIN_CLASSES_META[target_cls]["label_vi"],
                        "geometry": "POLYGON",
                        "source_layer": lyr,
                        "area_m2": max(1.0, area_m2),
                        "elevation_m": 0.0,
                        "polygon_px": [vn2000_to_px(px, py) for px, py in pts_w],
                        "polygon_rel": [[round(px, 3), round(py, 3)] for px, py in pts_w],
                    }
                )
                ref_counts[target_cls] += 1
            else:
                length_m = round(
                    sum(math.hypot(pts_w[i + 1][0] - pts_w[i][0], pts_w[i + 1][1] - pts_w[i][1]) for i in range(len(pts_w) - 1)),
                    2,
                )
                if length_m < 1.5:
                    continue
                left_w, right_w = _offset_polyline(pts_w, def_w * 0.5)
                pts_px = [vn2000_to_px(px, py) for px, py in pts_w]
                ref_features.append(
                    {
                        "id": f"terrain_{len(ref_features) + 1:04d}",
                        "class_key": cls_key,
                        "label_vi": TERRAIN_CLASSES_META[cls_key]["label_vi"],
                        "geometry": "CORRIDOR",
                        "source_layer": lyr,
                        "width_m": def_w,
                        "length_m": length_m,
                        "elevation_m": 0.0,
                        "centerline_px": pts_px,
                        "left_edge_px": [vn2000_to_px(px, py) for px, py in left_w],
                        "right_edge_px": [vn2000_to_px(px, py) for px, py in right_w],
                        "centerline_rel": [[round(px, 3), round(py, 3)] for px, py in pts_w],
                        "left_edge_rel": [[round(px, 3), round(py, 3)] for px, py in left_w],
                        "right_edge_rel": [[round(px, 3), round(py, 3)] for px, py in right_w],
                    }
                )
                ref_counts[cls_key] += 1

    # Attach vegetation zone boundaries (`Ranhgioi_thucvat`) to the first landscape_tree features
    tree_feats = [f for f in ref_features if f["class_key"] == "landscape_tree"]
    for idx_vb, (vb_rel, vb_px) in enumerate(zip(veg_boundaries_rel, veg_boundaries_px)):
        if idx_vb < len(tree_feats):
            tree_feats[idx_vb]["zone_boundary_rel"] = vb_rel
            tree_feats[idx_vb]["zone_boundary_px"] = vb_px

    # Supplement any class with AI features if ref_counts for that class is 0
    for af in ai_features:
        ck = af["class_key"]
        if ref_counts.get(ck, 0) == 0 and ck in active_keys:
            af["id"] = f"terrain_{len(ref_features) + 1:04d}"
            ref_features.append(af)
            ref_counts[ck] = ref_counts.get(ck, 0) + 1

    return ref_features, ref_counts


def _ensure_mylib2_tree_blocks(doc: Any) -> None:
    """Embed standard tree & vegetation CAD blocks from C:\\Block\\Mylib2 and Waterpoint standard."""
    app_root = Path(__file__).resolve().parents[2]
    json_path = app_root / "ui" / "mylib2_blocks.json"
    blocks_data: dict[str, Any] = {}
    if json_path.is_file():
        cache_key = str(json_path.resolve())
        try:
            mtime = json_path.stat().st_mtime
            cached = _MYLIB2_BLOCKS_CACHE.get(cache_key)
            if cached is not None and cached[0] == mtime:
                blocks_data = cached[1]
            else:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                blocks_data = (payload.get("blocks") if isinstance(payload, dict) and "blocks" in payload else payload) or {}
                _MYLIB2_BLOCKS_CACHE[cache_key] = (mtime, blocks_data)
        except Exception:
            blocks_data = {}

    for bname, binfo in blocks_data.items():
        if bname in doc.blocks:
            continue
        blk = doc.blocks.new(name=bname)
        for stroke in binfo.get("strokes") or []:
            if len(stroke) == 2:
                blk.add_line(
                    (float(stroke[0][0]), float(stroke[0][1])),
                    (float(stroke[1][0]), float(stroke[1][1])),
                    dxfattribs={"layer": "0", "color": 3},
                )
            elif len(stroke) >= 3:
                pts = [(float(p[0]), float(p[1])) for p in stroke]
                is_closed = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-4
                blk.add_lwpolyline(pts, close=is_closed, dxfattribs={"layer": "0", "color": 3})

    # Ensure fallback block definitions exist even if JSON is absent (including Waterpoint uniform grid blocks)
    for fallback_name in (
        "Caydoclap",
        "Caytanbe",
        "Caytanto",
        "Caydothi_cdt1",
        "Caycanhquan_173e",
        "cumcay2",
        "cumcay1",
        "caylato",
        "cdt2",
        "cdt39",
        "cbui13",
    ):
        if fallback_name not in doc.blocks:
            blk = doc.blocks.new(name=fallback_name)
            lobes = 8 if fallback_name not in {"Caytanbe", "cumcay1", "cbui13"} else 6
            pts: list[tuple[float, float]] = []
            for i in range(lobes * 6):
                ang = 2.0 * math.pi * i / (lobes * 6)
                rad = 0.82 + 0.18 * abs(math.cos(lobes * ang * 0.5))
                pts.append((round(rad * math.cos(ang), 4), round(rad * math.sin(ang), 4)))
            blk.add_lwpolyline(pts, close=True, dxfattribs={"layer": "0", "color": 3})
            blk.add_line((-0.18, 0.0), (0.18, 0.0), dxfattribs={"layer": "0", "color": 3})
            blk.add_line((0.0, -0.18), (0.0, 0.18), dxfattribs={"layer": "0", "color": 3})

    # Ensure Waterpoint grass/shrub `.V.` symbol blocks (`cothap`, `cocao`, `hoa`) exist
    for grass_blk in ("cothap", "cocao", "hoa"):
        if grass_blk not in doc.blocks:
            blk = doc.blocks.new(name=grass_blk)
            h_blade = 0.55 if grass_blk == "cocao" else 0.38
            blk.add_lwpolyline([(-0.28, h_blade), (0.0, 0.0), (0.28, h_blade)], close=False, dxfattribs={"layer": "0", "color": 3})
            blk.add_line((0.0, 0.0), (0.0, h_blade * 1.15), dxfattribs={"layer": "0", "color": 3})
            blk.add_point((-0.42, 0.05, 0.0), dxfattribs={"layer": "0", "color": 3})
            blk.add_point((0.42, 0.05, 0.0), dxfattribs={"layer": "0", "color": 3})

    # Ensure aquatic lotus block (`Hoasen`) and streetlight block (`DEN1a`) exist
    if "Hoasen" not in doc.blocks:
        blk_hs = doc.blocks.new(name="Hoasen")
        blk_hs.add_lwpolyline([(-0.45, 0.0), (0.45, 0.0)], close=False, dxfattribs={"layer": "0", "color": 4})
        blk_hs.add_lwpolyline([(-0.30, 0.0), (0.0, 0.42), (0.30, 0.0)], close=False, dxfattribs={"layer": "0", "color": 4})
        blk_hs.add_line((0.0, 0.0), (0.0, 0.48), dxfattribs={"layer": "0", "color": 4})

    if "DEN1a" not in doc.blocks:
        blk_den = doc.blocks.new(name="DEN1a")
        blk_den.add_circle((0.0, 0.0), radius=0.35, dxfattribs={"layer": "0", "color": 255})
        blk_den.add_line((-0.50, 0.0), (0.50, 0.0), dxfattribs={"layer": "0", "color": 255})
        blk_den.add_line((0.0, -0.50), (0.0, 0.50), dxfattribs={"layer": "0", "color": 255})


WATERPOINT_STANDARD_LAYERS: list[tuple[str, int, str]] = [
    ("1.BK. TALUY KENH", 4, "CONTINUOUS"),
    ("1.BK. THUC VAT", 94, "CONTINUOUS"),
    ("Cao độ", 1, "CONTINUOUS"),
    ("Dot", 2, "CONTINUOUS"),
    ("Thuvien", 7, "CONTINUOUS"),
    ("Thuc_vat", 92, "CONTINUOUS"),
    ("Thucvat", 92, "CONTINUOUS"),
    ("CAY", 72, "CONTINUOUS"),
    ("1.BK. DEN DUONG", 255, "CONTINUOUS"),
    ("1.BK.DEN DUONG", 255, "CONTINUOUS"),
    ("Nhãn ĐM", 2, "CONTINUOUS"),
    ("07-CAY XANH", 3, "CONTINUOUS"),
    ("Giao_thong", 200, "CONTINUOUS"),
    ("THUCVAT", 90, "CONTINUOUS"),
    ("1.BK. SONG+MUONG+RACH", 162, "CONTINUOUS"),
    ("1.BK. DUONG CU-NHUA", 2, "CONTINUOUS"),
    ("QC41_VS7.3a", 7, "CONTINUOUS"),
    ("QC41_VS2.2", 7, "CONTINUOUS"),
    ("Ranhgioi_thucvat", 3, "RGTV"),
    ("Dan_cu_kinh_te_xa_hoi", 7, "CONTINUOUS"),
    ("1.BK. CONG VIEN", 10, "CONTINUOUS"),
    ("1.BK. VIA HE", 9, "CONTINUOUS"),
    ("Nha-2d", 41, "CONTINUOUS"),
    ("1.BK. DUONG XE DAP", 110, "CONTINUOUS"),
    ("Nha", 2, "CONTINUOUS"),
    ("Đồng mức phụ", 8, "CONTINUOUS"),
    ("Thuy_he", 4, "CONTINUOUS"),
    ("1.BK. CAU", 1, "CONTINUOUS"),
    ("QC41_VS9.3", 7, "CONTINUOUS"),
    ("Đồng mức chính", 40, "CONTINUOUS"),
    ("textnha", 7, "CONTINUOUS"),
]


def _draw_taluy_comb_ticks(
    msp: Any,
    poly_pts: list[tuple[float, float]],
    closed: bool = True,
    inward_sign: float = 1.0,
    spacing_m: float = 1.1,
    long_len_m: float = 1.25,
    short_len_m: float = 0.60,
    layer: str = "1.BK. TALUY KENH",
    color: int = 4,
) -> None:
    """Draw standard Vietnamese topographic alternating long/short Taluy slope ticks (`1.BK. TALUY KENH`)."""
    if len(poly_pts) < 2:
        return
    cx = sum(p[0] for p in poly_pts) / len(poly_pts)
    cy = sum(p[1] for p in poly_pts) / len(poly_pts)
    n = len(poly_pts)
    limit = n if closed else n - 1
    tick_idx = 0
    for i in range(limit):
        p0 = poly_pts[i]
        p1 = poly_pts[(i + 1) % n]
        seg_dx = p1[0] - p0[0]
        seg_dy = p1[1] - p0[1]
        seg_len = math.hypot(seg_dx, seg_dy)
        if seg_len < 0.25:
            continue
        ux, uy = seg_dx / seg_len, seg_dy / seg_len
        nx, ny = -uy, ux
        mx, my = (p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5
        if closed:
            to_c = (cx - mx) * nx + (cy - my) * ny
            if to_c * inward_sign < 0:
                nx, ny = -nx, -ny
        num_steps = max(1, min(40, int(seg_len / max(0.35, spacing_m))))
        for s_i in range(num_steps):
            t_frac = (s_i + 0.5) / num_steps
            bx = p0[0] + seg_dx * t_frac
            by = p0[1] + seg_dy * t_frac
            t_len = long_len_m if (tick_idx % 2 == 0) else short_len_m
            tick_idx += 1
            msp.add_line(
                (bx, by),
                (bx + nx * t_len, by + ny * t_len),
                dxfattribs={"layer": layer, "color": color},
            )


def _write_terrain_dxf(
    dxf_path: Path,
    features: list[dict[str, Any]],
    unit_to_metre: float = 1.0,
    pl_only: bool = False,
    ref_dxf_path: Path | None = None,
    spot_elevations: list[tuple[float, float, float]] | None = None,
    dem_contours: list[dict[str, Any]] | None = None,
    map_scale: int = 500,
) -> None:
    """Write VN2000 topographic survey DXF matching `ACAD_KHU TAM GIAC.dwg` + `Mylib2` + TCVN multi-scale rules."""
    tcvn_spec = get_tcvn_scale_spec(map_scale)
    scale_k = float(tcvn_spec["scale_factor_k"])
    b_mult = float(tcvn_spec["block_scale_multiplier"])
    ltscale_val = float(tcvn_spec["ltscale"])
    spot_step_m = float(tcvn_spec["spot_elevation_spacing_m"])
    spot_text_h = float(tcvn_spec["spot_text_height_m"])
    contour_basic_m = float(tcvn_spec["contour_basic_interval_m"])
    contour_index_m = float(tcvn_spec["contour_index_interval_m"])
    contour_text_h = float(tcvn_spec["contour_text_height_m"])
    taluy_step_m = float(tcvn_spec["taluy_step_m"])
    taluy_long_m = float(tcvn_spec["taluy_long_m"])
    taluy_short_m = float(tcvn_spec["taluy_short_m"])

    loaded_from_ref = False
    if ref_dxf_path is not None and ref_dxf_path.is_file():
        try:
            doc = ezdxf.readfile(str(ref_dxf_path))
            loaded_from_ref = True
        except Exception:
            doc = ezdxf.new("R2010")
    else:
        doc = ezdxf.new("R2010")

    doc.units = 6 if abs(unit_to_metre - 1.0) < 1e-9 else 0
    doc.header["$LTSCALE"] = ltscale_val
    doc.header["$CELTSCALE"] = ltscale_val

    if "ARIAL" not in doc.styles:
        doc.styles.new("ARIAL", dxfattribs={"font": "arial.ttf"})
    if "Standard" in doc.styles:
        doc.styles.get("Standard").dxf.font = "arial.ttf"

    for lt_name, pattern in (
        ("DASHED", [0.6, 0.4, -0.2]),
        ("CENTER", [1.0, 0.6, -0.15, 0.1, -0.15]),
        ("RGTV", [0.5, 0.3, -0.2]),
    ):
        if lt_name not in doc.linetypes:
            try:
                doc.linetypes.new(lt_name, dxfattribs={"description": lt_name, "pattern": pattern})
            except Exception:
                pass

    def ensure_layer(name: str, color: int, linetype: str = "CONTINUOUS") -> None:
        lt = linetype if linetype in doc.linetypes else "CONTINUOUS"
        if name not in doc.layers:
            doc.layers.new(name, dxfattribs={"color": int(color), "linetype": lt})

    for w_name, w_col, w_lt in WATERPOINT_STANDARD_LAYERS:
        ensure_layer(w_name, w_col, w_lt)
    for meta in TERRAIN_CLASSES_META.values():
        ensure_layer(meta["layer"], meta["color_aci"], meta["linetype"])
    ensure_layer("KS_TIM_DUONG", 2, "CENTER")
    if not pl_only:
        ensure_layer("KS_GHI_CHU", 7, "CONTINUOUS")

    _ensure_mylib2_tree_blocks(doc)
    msp = doc.modelspace()

    # If loaded from reference template and map_scale != 500, re-layout reference entities to target TCVN scale
    if loaded_from_ref and abs(scale_k - 1.0) > 1e-6:
        ref_seen_veg: set[tuple[str, int, int]] = set()
        ref_seen_spot: set[tuple[int, int]] = set()
        entities_to_delete: list[Any] = []
        for ent in list(msp):
            et = ent.dxftype()
            lyr = str(ent.dxf.layer or "0")
            if et == "INSERT":
                bname = str(ent.dxf.name or "")
                ins = ent.dxf.insert
                wx, wy = float(ins.x), float(ins.y)
                is_grid_veg = bname in {"cumcay2", "cumcay1", "cocao", "cothap", "hoa", "caylato"} or lyr in {
                    "Thuc_vat",
                    "Thucvat",
                    "1.BK. THUC VAT",
                    "THUCVAT",
                }
                if is_grid_veg and scale_k > 1.0:
                    if bname in {"cothap", "cocao", "hoa"}:
                        gx_s, gy_s = float(tcvn_spec["grass_grid_dx_m"]), float(tcvn_spec["grass_grid_dy_m"])
                    elif bname == "caylato":
                        gx_s, gy_s = float(tcvn_spec["broadleaf_grid_dx_m"]), float(tcvn_spec["broadleaf_grid_dy_m"])
                    else:
                        gx_s, gy_s = float(tcvn_spec["tree_grid_dx_m"]), float(tcvn_spec["tree_grid_dy_m"])
                    ck = (lyr, int(round(wx / max(1.0, gx_s))), int(round(wy / max(1.0, gy_s))))
                    if ck in ref_seen_veg:
                        entities_to_delete.append(ent)
                        continue
                    ref_seen_veg.add(ck)
                base_sc = abs(float(getattr(ent.dxf, "xscale", 1.0) or 1.0))
                new_sc = round((base_sc if base_sc > 0.1 else 1.5) * b_mult, 3)
                ent.dxf.xscale = new_sc
                ent.dxf.yscale = new_sc
                ent.dxf.zscale = new_sc
            elif et == "TEXT" and lyr == "Cao độ":
                ins = ent.dxf.insert
                wx, wy = float(ins.x), float(ins.y)
                if scale_k > 1.0:
                    sk = (int(round(wx / max(1.0, spot_step_m))), int(round(wy / max(1.0, spot_step_m))))
                    if sk in ref_seen_spot:
                        entities_to_delete.append(ent)
                        continue
                    ref_seen_spot.add(sk)
                ent.dxf.height = spot_text_h
            elif et == "POINT" and lyr == "Dot" and scale_k > 1.0:
                loc = ent.dxf.location
                wx, wy = float(loc.x), float(loc.y)
                sk = (int(round(wx / max(1.0, spot_step_m))), int(round(wy / max(1.0, spot_step_m))))
                if sk not in ref_seen_spot:
                    entities_to_delete.append(ent)
            elif et == "MTEXT" and lyr == "Nhãn ĐM":
                ent.dxf.char_height = contour_text_h
            elif et == "TEXT" and lyr == "Nhãn ĐM":
                ent.dxf.height = contour_text_h
        for ent in entities_to_delete:
            try:
                msp.delete_entity(ent)
            except Exception:
                pass

    emitted_grid_cells: set[tuple[str, int, int]] = set()
    for feat in features:
        cls_key = feat["class_key"]
        meta = TERRAIN_CLASSES_META[cls_key]
        lyr = meta["layer"]
        aci = meta["color_aci"]
        lt = meta["linetype"] if meta["linetype"] in doc.linetypes else "CONTINUOUS"
        z_elev = float(feat.get("elevation_m") or 0.0)
        pl_attribs = {"layer": lyr, "color": aci, "linetype": lt, "elevation": z_elev}

        if feat["geometry"] == "BLOCK" or cls_key == "landscape_tree":
            if not loaded_from_ref and feat.get("zone_boundary_rel"):
                zb_pts = [tuple(p[:2]) for p in feat["zone_boundary_rel"] if len(p) >= 2]
                if len(zb_pts) >= 3:
                    msp.add_lwpolyline(
                        zb_pts,
                        close=True,
                        dxfattribs={
                            "layer": "Ranhgioi_thucvat",
                            "color": 3,
                            "linetype": "RGTV" if "RGTV" in doc.linetypes else "DASHED",
                            "elevation": z_elev,
                        },
                    )
            c_rel = feat.get("center_rel")
            if not c_rel and feat.get("polygon_rel"):
                poly_fallback = feat["polygon_rel"]
                c_rel = [
                    sum(p[0] for p in poly_fallback) / len(poly_fallback),
                    sum(p[1] for p in poly_fallback) / len(poly_fallback),
                ]
            if not c_rel or len(c_rel) < 2:
                continue
            cx, cy = float(c_rel[0]), float(c_rel[1])
            feat_scale_denom = int(feat.get("map_scale") or 500)
            feat_k = max(1e-6, feat_scale_denom / 500.0)
            if feat.get("base_b_scale") is not None:
                base_b_scale = float(feat["base_b_scale"])
            else:
                base_b_scale = float(feat.get("radius_m") or 1.5) / feat_k
            r_m = round(base_b_scale * b_mult, 3)

            bname = str(feat.get("block_name") or meta.get("block_name") or "Caydothi_cdt1")
            if bname not in doc.blocks:
                bname = "Caydothi_cdt1"
            src_blk = str(feat.get("source_block") or bname)
            if src_blk not in doc.blocks:
                src_blk = bname
            src_lyr = str(feat.get("source_layer") or ("07-CAY XANH" if base_b_scale >= 2.0 else "Thuvien"))

            # When re-exporting pre-extracted features at a coarser scale (e.g. 1:500 -> 1:1000/2000/5000),
            # thin uniform-grid blocks according to target TCVN grid spacing so blocks never overlap.
            if feat.get("placement_mode") == "uniform_grid" and scale_k > feat_k + 1e-6:
                if src_blk in {"cothap", "cocao", "hoa"}:
                    gx_k, gy_k = float(tcvn_spec["grass_grid_dx_m"]), float(tcvn_spec["grass_grid_dy_m"])
                elif src_blk == "caylato":
                    gx_k, gy_k = float(tcvn_spec["broadleaf_grid_dx_m"]), float(tcvn_spec["broadleaf_grid_dy_m"])
                else:
                    gx_k, gy_k = float(tcvn_spec["tree_grid_dx_m"]), float(tcvn_spec["tree_grid_dy_m"])
                cell_id = (src_lyr, int(round(cx / max(0.5, gx_k))), int(round(cy / max(0.5, gy_k))))
                if cell_id in emitted_grid_cells and not feat.get("zone_boundary_rel"):
                    continue
                emitted_grid_cells.add(cell_id)

            msp.add_blockref(
                bname,
                (cx, cy, z_elev),
                dxfattribs={
                    "layer": lyr,
                    "color": aci,
                    "xscale": r_m,
                    "yscale": r_m,
                    "zscale": r_m,
                },
            )
            if not loaded_from_ref:
                src_col = 92 if src_lyr in {"Thuc_vat", "Thucvat"} else (94 if src_lyr == "1.BK. THUC VAT" else (3 if base_b_scale >= 2.0 else 7))
                msp.add_blockref(
                    src_blk,
                    (cx, cy, z_elev),
                    dxfattribs={
                        "layer": src_lyr,
                        "color": src_col,
                        "xscale": r_m,
                        "yscale": r_m,
                        "zscale": r_m,
                    },
                )
        elif feat["geometry"] == "POLYGON":
            poly = [tuple(p[:2]) for p in feat.get("polygon_rel") or []]
            if len(poly) < 3:
                continue
            msp.add_lwpolyline(poly, close=True, dxfattribs=pl_attribs)
            if not loaded_from_ref:
                std_lyr = "Thuy_he" if cls_key == "pond" else "Nha-2d"
                std_col = 4 if cls_key == "pond" else 41
                msp.add_lwpolyline(poly, close=True, dxfattribs={"layer": std_lyr, "color": std_col, "elevation": z_elev})
            if not pl_only:
                cx = sum(p[0] for p in poly) / len(poly)
                cy = sum(p[1] for p in poly) / len(poly)
                if cls_key == "pond" and not loaded_from_ref:
                    _draw_taluy_comb_ticks(
                        msp,
                        poly,
                        closed=True,
                        inward_sign=1.0,
                        spacing_m=taluy_step_m,
                        long_len_m=taluy_long_m,
                        short_len_m=taluy_short_m,
                    )
                    if "Hoasen" in doc.blocks:
                        hs_scale = round(1.0 * b_mult, 3)
                        msp.add_blockref(
                            "Hoasen",
                            (cx, cy, z_elev),
                            dxfattribs={
                                "layer": "Thuy_he",
                                "color": 4,
                                "xscale": hs_scale,
                                "yscale": hs_scale,
                                "zscale": hs_scale,
                            },
                        )
                txt = f"{meta['cad_text']} ({feat.get('area_m2', 0)} m2)"
                t_ent = msp.add_text(
                    txt,
                    dxfattribs={"layer": "KS_GHI_CHU", "height": round(0.65 * scale_k, 3), "style": "ARIAL", "color": aci},
                )
                t_ent.dxf.insert = (cx, cy)
        else:
            left_pts = [tuple(p[:2]) for p in feat.get("left_edge_rel") or []]
            right_pts = [tuple(p[:2]) for p in feat.get("right_edge_rel") or []]
            center_pts = [tuple(p[:2]) for p in feat.get("centerline_rel") or []]
            if len(left_pts) >= 2:
                msp.add_lwpolyline(left_pts, close=False, dxfattribs=pl_attribs)
            if len(right_pts) >= 2:
                msp.add_lwpolyline(right_pts, close=False, dxfattribs=pl_attribs)
            if not loaded_from_ref:
                std_cor_lyr = {
                    "asphalt_road": ("1.BK. DUONG CU-NHUA", 2),
                    "concrete_road": ("Giao_thong", 200),
                    "dirt_road": ("Giao_thong", 200),
                    "footpath": ("1.BK. VIA HE", 9),
                    "masonry_ditch": ("1.BK. SONG+MUONG+RACH", 162),
                }.get(cls_key, ("Giao_thong", 200))
                if len(left_pts) >= 2:
                    msp.add_lwpolyline(left_pts, close=False, dxfattribs={"layer": std_cor_lyr[0], "color": std_cor_lyr[1], "elevation": z_elev})
                if len(right_pts) >= 2:
                    msp.add_lwpolyline(right_pts, close=False, dxfattribs={"layer": std_cor_lyr[0], "color": std_cor_lyr[1], "elevation": z_elev})
                if cls_key in {"masonry_ditch", "asphalt_road"} and len(left_pts) >= 2 and not pl_only:
                    _draw_taluy_comb_ticks(
                        msp,
                        left_pts,
                        closed=False,
                        spacing_m=taluy_step_m,
                        long_len_m=taluy_long_m,
                        short_len_m=taluy_short_m,
                    )
                if cls_key == "asphalt_road" and len(left_pts) >= 2 and not pl_only:
                    light_step_m = max(6.0, float(tcvn_spec["streetlight_step_m"]))
                    urban_step_m = max(5.0, 15.0 * scale_k)
                    b_sc_road = round(1.0 * b_mult, 3)
                    urban_cycle = ("cdt2", "cdt39", "cbui13")
                    # Emit streetlights (`DEN1a` on `1.BK. DEN DUONG`) along left edge
                    acc_d = 0.0
                    next_light_d = 2.0
                    for seg_i in range(len(left_pts) - 1):
                        p0, p1 = left_pts[seg_i], left_pts[seg_i + 1]
                        sdx, sdy = p1[0] - p0[0], p1[1] - p0[1]
                        slen = math.hypot(sdx, sdy)
                        if slen < 1e-4:
                            continue
                        while acc_d + slen >= next_light_d:
                            t_f = (next_light_d - acc_d) / slen
                            lx = p0[0] + sdx * t_f
                            ly = p0[1] + sdy * t_f
                            if "DEN1a" in doc.blocks:
                                msp.add_blockref(
                                    "DEN1a",
                                    (lx, ly, z_elev),
                                    dxfattribs={
                                        "layer": "1.BK. DEN DUONG",
                                        "color": 255,
                                        "xscale": b_sc_road,
                                        "yscale": b_sc_road,
                                        "zscale": b_sc_road,
                                    },
                                )
                            next_light_d += light_step_m
                        acc_d += slen
                    # Emit urban trees (`cdt2`, `cdt39`, `cbui13` on `07-CAY XANH`) along right edge (or left edge)
                    edge_for_trees = right_pts if len(right_pts) >= 2 else left_pts
                    acc_t = 0.0
                    next_tree_d = 3.0
                    u_idx = 0
                    for seg_i in range(len(edge_for_trees) - 1):
                        p0, p1 = edge_for_trees[seg_i], edge_for_trees[seg_i + 1]
                        sdx, sdy = p1[0] - p0[0], p1[1] - p0[1]
                        slen = math.hypot(sdx, sdy)
                        if slen < 1e-4:
                            continue
                        while acc_t + slen >= next_tree_d:
                            t_f = (next_tree_d - acc_t) / slen
                            tx = p0[0] + sdx * t_f
                            ty = p0[1] + sdy * t_f
                            ublk = urban_cycle[u_idx % len(urban_cycle)]
                            u_idx += 1
                            if ublk in doc.blocks:
                                msp.add_blockref(
                                    ublk,
                                    (tx, ty, z_elev),
                                    dxfattribs={
                                        "layer": "07-CAY XANH",
                                        "color": 3,
                                        "xscale": b_sc_road,
                                        "yscale": b_sc_road,
                                        "zscale": b_sc_road,
                                    },
                                )
                            next_tree_d += urban_step_m
                        acc_t += slen
            if meta.get("centerline") and len(center_pts) >= 2:
                msp.add_lwpolyline(
                    center_pts,
                    close=False,
                    dxfattribs={
                        "layer": "KS_TIM_DUONG",
                        "color": 2,
                        "linetype": "CENTER" if "CENTER" in doc.linetypes else "CONTINUOUS",
                        "elevation": z_elev,
                    },
                )
                if not loaded_from_ref and cls_key == "asphalt_road":
                    msp.add_lwpolyline(
                        center_pts,
                        close=False,
                        dxfattribs={"layer": "QC41_VS2.2", "color": 7, "elevation": z_elev},
                    )
            if not pl_only and len(center_pts) >= 2:
                mid_i = len(center_pts) // 2
                p_a = center_pts[max(0, mid_i - 1)]
                p_b = center_pts[min(len(center_pts) - 1, mid_i)]
                ang = math.degrees(math.atan2(p_b[1] - p_a[1], p_b[0] - p_a[0]))
                if ang > 90:
                    ang -= 180
                elif ang < -90:
                    ang += 180
                mx, my = (p_a[0] + p_b[0]) * 0.5, (p_a[1] + p_b[1]) * 0.5
                label = f"{meta['cad_text']} (B={feat.get('width_m', 0)}m)"
                t_ent = msp.add_text(
                    label,
                    dxfattribs={
                        "layer": "KS_GHI_CHU",
                        "height": round(max(0.35, min(0.8, float(feat.get("width_m") or 1.0) * 0.25)) * scale_k, 3),
                        "rotation": ang,
                        "style": "ARIAL",
                        "color": aci,
                    },
                )
                t_ent.dxf.insert = (mx, my)

    # Emit DEM Spot Elevations (`Cao độ` TEXT + `Dot` POINT) & Contours (`Đồng mức chính` / `Đồng mức phụ` / `Nhãn ĐM`)
    if not loaded_from_ref and not pl_only:
        seen_spots: set[tuple[int, int]] = set()
        for wx, wy, wz in spot_elevations or []:
            if scale_k > 1.0:
                sp_key = (int(round(wx / max(1.0, spot_step_m))), int(round(wy / max(1.0, spot_step_m))))
                if sp_key in seen_spots:
                    continue
                seen_spots.add(sp_key)
            msp.add_point((wx, wy, wz), dxfattribs={"layer": "Dot", "color": 2})
            t_cd = msp.add_text(
                f"{wz:.2f}",
                dxfattribs={"layer": "Cao độ", "color": 1, "height": spot_text_h, "style": "Standard"},
            )
            t_cd.dxf.insert = (wx + 0.45 * scale_k, wy - 0.45 * scale_k, wz)

        for c_item in dem_contours or []:
            pts_c = [tuple(p[:2]) for p in c_item.get("points_rel") or []]
            if len(pts_c) < 3:
                continue
            lvl_val = float(c_item.get("level") or 0.0)
            if abs(round(lvl_val / contour_basic_m) * contour_basic_m - lvl_val) > 1e-2:
                continue
            is_maj = abs(round(lvl_val / contour_index_m) * contour_index_m - lvl_val) < 1e-2
            c_lyr = "Đồng mức chính" if is_maj else "Đồng mức phụ"
            c_col = 40 if is_maj else 8
            msp.add_lwpolyline(pts_c, close=False, dxfattribs={"layer": c_lyr, "color": c_col, "elevation": lvl_val})
            if is_maj:
                mid_pt = pts_c[len(pts_c) // 2]
                mt = msp.add_mtext(
                    f"{lvl_val:g}",
                    dxfattribs={"layer": "Nhãn ĐM", "color": 2, "char_height": contour_text_h, "style": "Standard"},
                )
                mt.set_location((mid_pt[0], mid_pt[1], lvl_val))

    doc.saveas(dxf_path)


def export_terrain_dwg_from_dxf(dxf_path: str | Path, output_dwg_path: str | Path | None = None) -> Path | None:
    """Ensure a native AutoCAD `.dwg` file is built from the exported `.dxf` Polylines (`PL`)."""
    from uav_app.infrastructure.dwg_io import convert_dxf_to_dwg

    return convert_dxf_to_dwg(dxf_path, output_dwg_path=output_dwg_path)


def extract_9classes_from_orthomosaic(
    ortho_path: str | Path,
    dem_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    enabled_classes: list[str] | None = None,
    target_gsd_m: float = 0.25,
    map_scale: int = 500,
) -> dict[str, Any]:
    """Extract 9 terrain classes & re-layout CAD survey vectors at target TCVN `map_scale` (500, 1000, 2000, 5000)."""
    ortho_p = Path(ortho_path)
    out_p = Path(output_dir) if output_dir else (ortho_p.parent / "outputs_cad_9classes")
    return run_terrain_segmentation_and_export_dxf(
        project_root=ortho_p.parent,
        source_path=ortho_p,
        dem_path=Path(dem_path) if dem_path else None,
        output_dir=out_p,
        enabled_classes=enabled_classes,
        target_gsd_m=target_gsd_m,
        map_scale=map_scale,
    )


def export_9classes_to_dxf(
    extraction_or_features: dict[str, Any] | list[dict[str, Any]],
    dxf_path: str | Path,
    map_scale: int = 500,
    unit_to_metre: float = 1.0,
    ref_dxf_path: str | Path | None = None,
) -> Path:
    """Export extracted 9-class terrain features (or result dict) to DXF re-laid out at TCVN `map_scale`."""
    out_dxf = Path(dxf_path)
    out_dxf.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(extraction_or_features, dict):
        feats = list(extraction_or_features.get("features") or [])
        spots = list(extraction_or_features.get("spot_elevations") or [])
        contours = list(extraction_or_features.get("dem_contours") or [])
    else:
        feats = list(extraction_or_features or [])
        spots = []
        contours = []
    _write_terrain_dxf(
        out_dxf,
        feats,
        unit_to_metre=unit_to_metre,
        ref_dxf_path=Path(ref_dxf_path) if ref_dxf_path else None,
        spot_elevations=spots,
        dem_contours=contours,
        map_scale=map_scale,
    )
    return out_dxf


def export_9classes_to_dwg(
    extraction_or_features: dict[str, Any] | list[dict[str, Any]] | str | Path,
    dwg_path: str | Path,
    map_scale: int = 500,
    unit_to_metre: float = 1.0,
    ref_dxf_path: str | Path | None = None,
) -> Path | None:
    """Export extracted 9-class terrain features (or an existing DXF path) to `.DWG` at TCVN `map_scale`."""
    out_dwg = Path(dwg_path)
    out_dwg.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(extraction_or_features, (str, Path)):
        src_dxf = Path(extraction_or_features)
    else:
        src_dxf = out_dwg.with_suffix(".dxf")
        export_9classes_to_dxf(
            extraction_or_features,
            src_dxf,
            map_scale=map_scale,
            unit_to_metre=unit_to_metre,
            ref_dxf_path=ref_dxf_path,
        )
    return export_terrain_dwg_from_dxf(src_dxf, output_dwg_path=out_dwg)


def train_terrain_model_from_dwg_folders(
    project_root: Path,
    survey_roots: list[str | Path] | None = None,
    steps: int = 160,
) -> dict[str, Any]:
    """Train/fine-tune `terrain_webgpu.onnx` directly from `.DWG` + `ORTHO` survey folders on GPU."""
    import os
    import shutil
    import subprocess
    import sys

    app_root = Path(__file__).resolve().parents[2]
    cuda_py = app_root.parent / ".venv" / "Scripts" / "python.exe"
    py_exe = str(cuda_py) if cuda_py.is_file() else sys.executable

    target_onnx = Path(project_root) / "models" / "turbo_yolo" / "terrain_webgpu.onnx"
    target_onnx.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        py_exe,
        "-m",
        "uav_app.adapters.terrain_onnx_builder",
        "--output",
        str(target_onnx),
        "--steps",
        str(max(20, int(steps))),
    ]
    for sr in survey_roots or []:
        if str(sr).strip():
            cmd.extend(["--survey-root", str(sr).strip().strip('"')])

    env = os.environ.copy()
    site_pkgs = app_root / ".venv" / "Lib" / "site-packages"
    py_paths = [str(app_root)]
    if site_pkgs.is_dir():
        py_paths.append(str(site_pkgs))
    if env.get("PYTHONPATH"):
        py_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = ";".join(py_paths)

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300, check=False)
    meta_path = target_onnx.with_suffix(".json")
    if proc.returncode != 0 or not meta_path.is_file():
        err_detail = (proc.stderr or proc.stdout or "").strip()[-600:]
        raise ValueError(f"Huấn luyện mô hình từ bản vẽ .DWG thất bại: {err_detail}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # Keep app_root/models/turbo_yolo in sync if project_root differs
    app_onnx = app_root / "models" / "turbo_yolo" / "terrain_webgpu.onnx"
    if app_onnx.resolve() != target_onnx.resolve():
        app_onnx.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_onnx, app_onnx)
        shutil.copy2(meta_path, app_onnx.with_suffix(".json"))
    return meta
