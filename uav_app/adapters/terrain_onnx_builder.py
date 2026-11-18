"""Build and train the 9-class UAV Terrain, Urban & Landscape Segmentation ONNX model from real `sample/RGB` + `.DWG` + `ORTHO` + `DEM` survey folders.

Classes (output tensor shape [1, 9, 512, 512]):
  0: background (Bare earth / Nodata / Other)
  1: asphalt_road (Đường ô tô / Đường nhựa)
  2: concrete_road (Đường ô tô / Đường bê tông)
  3: dirt_road (Đường đi / Đường đất)
  4: footpath (Đường đi bộ / Vỉa hè)
  5: pond (Sông / Ao / Hồ / Kênh nước)
  6: masonry_ditch (Mương xây / Bờ kè kênh)
  7: house_building (Nhà / Công trình xây dựng)
  8: landscape_tree (Cây cảnh quan / Cây xanh đô thị)
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from typing import Any

import cv2
import ezdxf
import numpy as np
from PIL import Image
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]

from uav_app.infrastructure.dwg_io import convert_dwg_to_dxf

Image.MAX_IMAGE_PIXELS = None

TERRAIN_CLASS_NAMES = [
    "background",
    "asphalt_road",
    "concrete_road",
    "dirt_road",
    "footpath",
    "pond",
    "masonry_ditch",
    "house_building",
    "landscape_tree",
]

DEFAULT_SURVEY_SEARCH_ROOTS = [
    Path(r"C:\Users\HL\OneDrive\09 1.KCPD DOAN 67-71\ACAD\Waterpoint_10.3.26\ACAD-KHU TAM GIAC (06-10-2026)"),
    Path(r"C:\Users\HL\Desktop\DETECTION RICE_FIELD\sample\RGB"),
    Path(r"D:\LUUTRU VIEC N\ACAD\Waterpoint_10.3.26"),
    Path(r"C:\Users\HL\OneDrive\09 1.KCPD DOAN 67-71\ACAD\Waterpoint_10.3.26"),
]


if nn is not None:
    class ConvBNAct(nn.Module):
        def __init__(self, in_ch: int, out_ch: int, k: int = 3, s: int = 1, d: int = 1):
            super().__init__()
            p = (k // 2) * d
            self.net = nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size=k, stride=s, padding=p, dilation=d, bias=False),
                nn.BatchNorm2d(out_ch),
                nn.SiLU(inplace=True),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.net(x)

    class TerrainSegUNetLite(nn.Module):
        """Compact multi-scale encoder-decoder with built-in radiometric & Sobel edge feature stem.

        Static [1, 3, 512, 512] -> [1, 9, 512, 512] graph (opset 17) for 100% WebGPU WGSL compatibility.
        """

        def __init__(self, num_classes: int = 9):
            super().__init__()
            gx = torch.tensor([[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]]).view(1, 1, 3, 3)
            gy = torch.tensor([[-1.0, -2.0, -1.0], [0.0, 0.0, 0.0], [1.0, 2.0, 1.0]]).view(1, 1, 3, 3)
            self.register_buffer("sobel_x", gx)
            self.register_buffer("sobel_y", gy)

            # Input stem receives 8 channels: R, G, B, Luminance, ExG, EarthWarmth(R-B), ChromaSpread, EdgeMag
            self.stem = ConvBNAct(8, 24, k=3, s=2)       # 256x256
            self.enc1 = nn.Sequential(ConvBNAct(24, 32, k=3, s=1), ConvBNAct(32, 32, k=3, s=2))  # 128x128
            self.enc2 = nn.Sequential(ConvBNAct(32, 48, k=3, s=1), ConvBNAct(48, 48, k=3, s=2))  # 64x64
            self.enc3 = nn.Sequential(
                ConvBNAct(48, 64, k=3, s=2),             # 32x32
                ConvBNAct(64, 64, k=3, d=2),
                ConvBNAct(64, 64, k=3, d=4),
            )

            self.dec2 = ConvBNAct(64 + 48, 48, k=3)
            self.dec1 = ConvBNAct(48 + 32, 32, k=3)
            self.dec0 = ConvBNAct(32 + 24, 24, k=3)
            self.head = nn.Sequential(
                ConvBNAct(24, 24, k=3),
                nn.Conv2d(24, num_classes, kernel_size=1),
            )

        def _extract_features(self, rgb: torch.Tensor) -> torch.Tensor:
            r = rgb[:, 0:1]
            g = rgb[:, 1:2]
            b = rgb[:, 2:3]
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            exg = torch.clamp(2.0 * g - r - b, -1.0, 1.0)
            warm = torch.clamp(r - b, -1.0, 1.0)
            cmax = torch.maximum(torch.maximum(r, g), b)
            cmin = torch.minimum(torch.minimum(r, g), b)
            chroma = cmax - cmin
            ex = F.conv2d(lum, self.sobel_x, padding=1)
            ey = F.conv2d(lum, self.sobel_y, padding=1)
            edge = torch.sqrt(ex * ex + ey * ey + 1e-6)
            return torch.cat([r, g, b, lum, exg, warm, chroma, edge], dim=1)

        def forward(self, rgb: torch.Tensor) -> torch.Tensor:
            feat = self._extract_features(rgb)
            s0 = self.stem(feat)
            s1 = self.enc1(s0)
            s2 = self.enc2(s1)
            s3 = self.enc3(s2)

            u2 = F.interpolate(s3, size=(64, 64), mode="bilinear", align_corners=False)
            d2 = self.dec2(torch.cat([u2, s2], dim=1))
            u1 = F.interpolate(d2, size=(128, 128), mode="bilinear", align_corners=False)
            d1 = self.dec1(torch.cat([u1, s1], dim=1))
            u0 = F.interpolate(d1, size=(256, 256), mode="bilinear", align_corners=False)
            d0 = self.dec0(torch.cat([u0, s0], dim=1))
            out = self.head(d0)
            return F.interpolate(out, size=(512, 512), mode="bilinear", align_corners=False)


def discover_dwg_ortho_bundles(search_roots: list[str | Path] | None = None) -> list[dict[str, Any]]:
    """Find survey folders containing paired `.dwg`/`.dxf` + `ORTHO_*.jpg` + `.jgw` (+ optional `DEM_*.tif`)."""
    roots: list[Path] = []
    for r in search_roots or DEFAULT_SURVEY_SEARCH_ROOTS:
        p = Path(str(r).strip().strip('"')).expanduser()
        if p.exists():
            roots.append(p.resolve())
    for r_def in DEFAULT_SURVEY_SEARCH_ROOTS:
        if r_def.exists() and r_def.resolve() not in roots:
            roots.append(r_def.resolve())

    visited_dirs: set[Path] = set()
    bundles: list[dict[str, Any]] = []
    known_cads_by_ortho: dict[str, Path] = {}

    # Pre-scan CAD files across roots so `sample/RGB` (which has ORTHO + JGW + DEM) can pair with its `.dwg`
    for root in roots:
        dirs_to_scan = [root.parent] if root.is_file() else [root, *[s for s in sorted(root.rglob("*")) if s.is_dir()]]
        for d in dirs_to_scan:
            if not d.is_dir():
                continue
            files = [f for f in d.iterdir() if f.is_file()]
            jpgs = [f for f in files if f.suffix.lower() in {".jpg", ".jpeg"} and f.with_suffix(".jgw").is_file()]
            cad_files = [
                f
                for f in files
                if f.suffix.lower() in {".dwg", ".dxf"}
                and "points+contour" not in f.name.lower()
                and "khung" not in f.name.lower()
            ]
            if jpgs and cad_files:
                cad_sorted = sorted(
                    cad_files,
                    key=lambda f: (
                        0
                        if "acad_khu tam giac" in f.name.lower()
                        else 1
                        if "acad_" in f.name.lower()
                        else 2
                        if "topographic" in f.name.lower()
                        else 3,
                        -f.stat().st_size,
                    ),
                )
                ortho_jpg = sorted(jpgs, key=lambda f: -f.stat().st_size)[0]
                known_cads_by_ortho[ortho_jpg.name.lower()] = cad_sorted[0]

    def check_dir(d: Path) -> None:
        if d in visited_dirs or not d.is_dir():
            return
        visited_dirs.add(d)
        files = [f for f in d.iterdir() if f.is_file()]
        jpgs = [f for f in files if f.suffix.lower() in {".jpg", ".jpeg"} and f.with_suffix(".jgw").is_file()]
        if not jpgs:
            return
        ortho_jpg = sorted(jpgs, key=lambda f: -f.stat().st_size)[0]
        cad_files = [
            f
            for f in files
            if f.suffix.lower() in {".dwg", ".dxf"}
            and "points+contour" not in f.name.lower()
            and "khung" not in f.name.lower()
        ]
        cad_chosen: Path | None = None
        if cad_files:
            cad_sorted = sorted(
                cad_files,
                key=lambda f: (
                    0
                    if "acad_khu tam giac" in f.name.lower()
                    else 1
                    if "acad_" in f.name.lower()
                    else 2
                    if "topographic" in f.name.lower()
                    else 3,
                    -f.stat().st_size,
                ),
            )
            cad_chosen = cad_sorted[0]
        else:
            cad_chosen = known_cads_by_ortho.get(ortho_jpg.name.lower())

        dem_files = [f for f in files if f.suffix.lower() in {".tif", ".tiff"} and "dem" in f.name.lower()]
        if cad_chosen is None and not dem_files:
            return
        bundles.append(
            {
                "folder": str(d),
                "cad_path": cad_chosen,
                "ortho_path": ortho_jpg,
                "jgw_path": ortho_jpg.with_suffix(".jgw"),
                "dem_path": dem_files[0] if dem_files else None,
            }
        )

    for root in roots:
        if root.is_file():
            check_dir(root.parent)
        elif root.is_dir():
            check_dir(root)
            for sub in sorted(root.rglob("*")):
                if sub.is_dir():
                    check_dir(sub)

    # Deduplicate by ortho_path.name, preferring the bundle that has `dem_path` (e.g. `sample/RGB`)
    by_name: dict[str, dict[str, Any]] = {}
    for b in bundles:
        key = b["ortho_path"].name.lower()
        if key not in by_name or (b.get("dem_path") is not None and by_name[key].get("dem_path") is None):
            by_name[key] = b
    return list(by_name.values())


def build_gt_mask_from_dwg_bundle(
    cad_path: Path | None,
    jpg_path: Path,
    jgw_path: Path,
    dem_path: Path | None = None,
    target_gsd_m: float = 0.15,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """Convert `sample/RGB` (`ORTHO.jpg` + `.jgw` + `DEM.tif` + `.dwg` polylines & `INSERT` blocks) into a 9-class mask."""
    lines = [float(x.strip()) for x in jgw_path.read_text(encoding="utf-8", errors="ignore").splitlines() if x.strip()]
    a_gsd, _d, _b, e_gsd, c_x, f_y = lines[:6]
    orig_gsd = max(0.005, abs(a_gsd))
    scale = min(1.0, orig_gsd / target_gsd_m)

    with Image.open(jpg_path) as im:
        orig_w, orig_h = im.size
        ds_w = max(64, int(round(orig_w * scale)))
        ds_h = max(64, int(round(orig_h * scale)))
        rgb = np.asarray(im.resize((ds_w, ds_h), Image.Resampling.BILINEAR), dtype=np.uint8)

    gsd_m = orig_gsd / scale
    rgb_f = rgb.astype(np.float32)
    r, g, b = rgb_f[:, :, 0], rgb_f[:, :, 1], rgb_f[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    exg = 2.0 * g - r - b
    warm = r - b
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    chroma = cmax - cmin

    nodata = (cmax < 8.0) | ((cmin > 248.0) & (chroma < 5.0))
    veg = (exg > 20.0) & (g > r * 1.06) & (g > b + 14.0)

    # Read optional DEM relative height `dem_rel` (for separating tall roofs +1.8m, landscape trees +0.8m, and depressed rivers -0.25m)
    dem_rel: np.ndarray | None = None
    if dem_path is not None and Path(dem_path).is_file():
        try:
            import rasterio
            from rasterio.enums import Resampling as RioResampling

            with rasterio.open(dem_path) as s_dem:
                z_arr = s_dem.read(1, out_shape=(ds_h, ds_w), resampling=RioResampling.nearest).astype(np.float32)
                valid_z = np.isfinite(z_arr) & (z_arr > -100.0) & (z_arr < 9000.0)
                if np.any(valid_z):
                    med_v = float(np.median(z_arr[valid_z]))
                    z_fill = np.where(valid_z, z_arr, med_v).astype(np.float32)
                    cw = max(8, ds_w // 8)
                    ch = max(8, ds_h // 8)
                    z_small = cv2.resize(z_fill, (cw, ch), interpolation=cv2.INTER_AREA)
                    z_open = cv2.morphologyEx(
                        z_small,
                        cv2.MORPH_OPEN,
                        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
                    )
                    z_ground = cv2.resize(
                        cv2.GaussianBlur(z_open, (0, 0), sigmaX=4.5, sigmaY=4.5),
                        (ds_w, ds_h),
                        interpolation=cv2.INTER_LINEAR,
                    )
                    dem_rel = np.where(valid_z, z_arr - z_ground, 0.0)
        except Exception:
            dem_rel = None

    def w2p(wx: float, wy: float) -> tuple[int, int]:
        return int(round((wx - c_x) / a_gsd * scale)), int(round((wy - f_y) / e_gsd * scale))

    msp = None
    if cad_path is not None and Path(cad_path).is_file():
        try:
            dxf_path = convert_dwg_to_dxf(cad_path)
            doc = ezdxf.readfile(str(dxf_path))
            msp = doc.modelspace()
        except Exception:
            msp = None

    def draw_layers(
        layer_names: list[str],
        line_thick_m: float = 0.8,
        fill_closed: bool = False,
        max_fill_area_m2: float = 25000.0,
        close_gap_m: float = 0.0,
        point_radius_m: float = 0.0,
    ) -> np.ndarray:
        m = np.zeros((ds_h, ds_w), dtype=np.uint8)
        if msp is None:
            return m
        thick_px = max(2, int(round(line_thick_m / gsd_m)))
        pt_rad_px = max(3, int(round(point_radius_m / gsd_m))) if point_radius_m > 0 else 0
        max_area_px = max_fill_area_m2 / (gsd_m * gsd_m)
        target_set = {n.upper() for n in layer_names}
        for ent in msp:
            lyr_u = str(ent.dxf.layer or "").upper()
            if lyr_u not in target_set:
                continue
            et = ent.dxftype()
            if et == "LWPOLYLINE":
                pts_w = list(ent.get_points("xy"))
                if len(pts_w) < 2:
                    continue
                pts = [w2p(p[0], p[1]) for p in pts_w]
                arr = np.array(pts, dtype=np.int32)
                dist_m = math.hypot(pts_w[0][0] - pts_w[-1][0], pts_w[0][1] - pts_w[-1][1])
                if fill_closed and (ent.closed or (len(pts) >= 4 and dist_m < 6.0)):
                    if abs(cv2.contourArea(arr)) <= max_area_px:
                        cv2.fillPoly(m, [arr], 1)
                    else:
                        cv2.polylines(m, [arr], bool(ent.closed), 1, thickness=thick_px)
                else:
                    cv2.polylines(m, [arr], bool(ent.closed), 1, thickness=thick_px)
            elif et == "POLYLINE":
                pts_w = [(v.dxf.location.x, v.dxf.location.y) for v in ent.vertices]
                if len(pts_w) < 2:
                    continue
                pts = [w2p(p[0], p[1]) for p in pts_w]
                arr = np.array(pts, dtype=np.int32)
                if fill_closed and ent.is_closed and abs(cv2.contourArea(arr)) <= max_area_px:
                    cv2.fillPoly(m, [arr], 1)
                else:
                    cv2.polylines(m, [arr], bool(ent.is_closed), 1, thickness=thick_px)
            elif et == "LINE":
                s, end = ent.dxf.start, ent.dxf.end
                cv2.line(m, w2p(s.x, s.y), w2p(end.x, end.y), 1, thickness=thick_px)
            elif et == "INSERT" and pt_rad_px > 0:
                ins = ent.dxf.insert
                cv2.circle(m, w2p(ins.x, ins.y), pt_rad_px, 1, -1)
            elif et == "CIRCLE":
                cen = ent.dxf.center
                rad_px = max(2, int(round(float(ent.dxf.radius or 1.0) / gsd_m)))
                cv2.circle(m, w2p(cen.x, cen.y), rad_px, 1, -1 if fill_closed else thick_px)
        if close_gap_m > 0:
            k_px = max(3, int(round(close_gap_m / gsd_m)) | 1)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_px, k_px))
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        return m

    house_cad = (
        draw_layers(
            ["Nha", "Nha-2d", "textnha", "KS_NHA_CONGTRINH"],
            line_thick_m=0.8,
            fill_closed=True,
            max_fill_area_m2=6500.0,
            close_gap_m=3.5,
            point_radius_m=2.5,
        )
        > 0
    )
    tree_cad = (
        draw_layers(
            [
                "07-CAY XANH",
                "1.BK. CAY DO THI",
                "1.BK. THUC VAT",
                "Thuc_vat",
                "THUCVAT",
                "CAY",
                "Thuvien",
                "Ranhgioi_thucvat",
                "KS_CAY_CANHQUAN",
            ],
            line_thick_m=1.2,
            fill_closed=True,
            max_fill_area_m2=180000.0,
            close_gap_m=3.5,
            point_radius_m=2.8,
        )
        > 0
    )

    # Solid continuous Vegetation Zone (`Vùng thực vật`) from `Ranhgioi_thucvat` polygons + uniform grid-distributed blocks
    # (`cumcay2`, `caylato`, `cothap`, `cocao`, `cumcay1`, `hoa`) so deep learning learns the full contiguous region
    veg_zone_solid = np.zeros((ds_h, ds_w), dtype=np.uint8)
    if msp is not None:
        veg_bound_layers = {"RANHGIOI_THUCVAT", "THUC_VAT", "1.BK. THUC VAT", "THUCVAT", "KS_CAY_CANHQUAN"}
        veg_block_layers = {"1.BK. THUC VAT", "THUC_VAT", "THUCVAT", "THUVIEN", "CAY", "07-CAY XANH"}
        veg_block_prefixes = ("CUMCAY1", "CUMCAY2", "CAYLATO", "COTHAP", "COCAO", "HOA", "CUMCAY", "THUCVAT", "CAY", "CO")
        grid_pts_mask = np.zeros((ds_h, ds_w), dtype=np.uint8)
        bound_line_mask = np.zeros((ds_h, ds_w), dtype=np.uint8)
        grid_rad_px = max(4, int(round(4.8 / gsd_m)))
        b_thick_px = max(2, int(round(1.5 / gsd_m)))
        max_zone_px = 220000.0 / (gsd_m * gsd_m)

        for ent in msp:
            lyr_u = str(ent.dxf.layer or "").upper()
            et = ent.dxftype()
            if lyr_u in veg_bound_layers and et in {"LWPOLYLINE", "POLYLINE"}:
                pts_w = (
                    list(ent.get_points("xy"))
                    if et == "LWPOLYLINE"
                    else [(v.dxf.location.x, v.dxf.location.y) for v in ent.vertices]
                )
                if len(pts_w) >= 3:
                    pts = [w2p(p[0], p[1]) for p in pts_w]
                    arr = np.array(pts, dtype=np.int32)
                    is_cl = bool(ent.closed) if et == "LWPOLYLINE" else bool(ent.is_closed)
                    dist_m = math.hypot(pts_w[0][0] - pts_w[-1][0], pts_w[0][1] - pts_w[-1][1])
                    if (is_cl or dist_m < 28.0) and abs(cv2.contourArea(arr)) <= max_zone_px:
                        cv2.fillPoly(veg_zone_solid, [arr], 1)
                    cv2.polylines(bound_line_mask, [arr], is_cl, 1, thickness=b_thick_px)
            elif et == "INSERT":
                blk_name = str(getattr(ent.dxf, "name", "") or "").upper()
                if lyr_u in veg_block_layers or any(blk_name.startswith(pref) for pref in veg_block_prefixes):
                    ins = ent.dxf.insert
                    cv2.circle(grid_pts_mask, w2p(ins.x, ins.y), grid_rad_px, 1, -1)

        # Bridge regular grid-spaced vegetation blocks (`cumcay2`, `caylato`, `cothap`, `cocao`, `cumcay1`, `hoa`) into continuous polygons
        if np.any(grid_pts_mask):
            k_bridge = max(5, int(round(9.5 / gsd_m)) | 1)
            bridged = cv2.morphologyEx(
                grid_pts_mask,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_bridge, k_bridge)),
            )
            cnts_v, _ = cv2.findContours(bridged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            min_cluster_px = max(25.0, 36.0 / (gsd_m * gsd_m))
            for cnt in cnts_v:
                area_c = cv2.contourArea(cnt)
                if min_cluster_px <= area_c <= max_zone_px:
                    cv2.fillPoly(veg_zone_solid, [cnt], 1)
        if np.any(bound_line_mask):
            k_b = max(3, int(round(4.0 / gsd_m)) | 1)
            b_closed = cv2.morphologyEx(
                bound_line_mask,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_b, k_b)),
            )
            cnts_b, _ = cv2.findContours(b_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in cnts_b:
                area_b = cv2.contourArea(cnt)
                if 20.0 / (gsd_m * gsd_m) <= area_b <= max_zone_px:
                    cv2.fillPoly(veg_zone_solid, [cnt], 1)

    veg_zone_bool = (veg_zone_solid > 0) & (~nodata)

    # Combine CAD house footprints with DEM elevated roof structures (> +1.85m above local ground and non-vegetation)
    roof_color_cue = (
        ((r > 150.0) & (r > g + 28.0) & (g > b + 10.0))  # Terracotta / red-orange tile roof
        | ((b > 140.0) & (b > r + 30.0) & (b > g + 12.0))  # Blue corrugated metal roof
    )
    if dem_rel is not None:
        house_mask = (~nodata) & (~veg) & (house_cad | ((dem_rel > 1.85) & ((lum > 90.0) | roof_color_cue)))
        tree_mask = (~nodata) & (~house_mask) & (veg_zone_bool | (veg & (tree_cad | (dem_rel > 0.75) | (exg > 32.0))))
    else:
        house_mask = (~nodata) & (~veg) & (house_cad | (house_cad & roof_color_cue))
        tree_mask = (~nodata) & (~house_mask) & (veg_zone_bool | (veg & (tree_cad | (exg > 30.0))))

    pond_poly = (
        draw_layers(
            ["1.BK. AO NUOC", "Thuy_he", "KS_AO_HO"],
            line_thick_m=1.2,
            fill_closed=True,
            max_fill_area_m2=28000.0,
            close_gap_m=3.5,
        )
        > 0
    )
    canal_corridor = (
        draw_layers(
            ["1.BK. SONG+MUONG+RACH"],
            line_thick_m=1.8,
            fill_closed=False,
            close_gap_m=16.5,
        )
        > 0
    )
    water_like = (~nodata) & (~house_mask) & (~veg) & (lum < 142.0) & ((g >= r * 0.92) | (b >= r * 0.85))
    if dem_rel is not None:
        water_like = water_like | ((~nodata) & (~house_mask) & (~veg) & (dem_rel < -0.35) & (lum < 155.0))

    ditch_corridor = (
        draw_layers(
            ["1.BK. TALUY KENH", "KS_MUONG_XAY"],
            line_thick_m=1.2,
            fill_closed=False,
            close_gap_m=2.8,
        )
        > 0
    )
    footpath_corridor = (
        draw_layers(
            ["1.BK. DUONG XE DAP", "1.BK. VIA HE", "1.BK. CONG VIEN", "KS_DUONG_DIBO"],
            line_thick_m=1.2,
            fill_closed=False,
            close_gap_m=3.2,
        )
        > 0
    )
    asphalt_markings = (
        draw_layers(
            [
                "1.BK. DUONG CU-NHUA",
                "Đường nhựa",
                "QC41_VS2.1",
                "QC41_VS2.2",
                "QC41_VS2.3a",
                "QC41_VS7.3a",
                "QC41_VS9.3",
                "1.BK. DEN DUONG",
                "KS_DUONG_NHUA",
            ],
            line_thick_m=3.5,
            fill_closed=False,
            close_gap_m=14.0,
            point_radius_m=2.8,
        )
        > 0
    )
    bridge_corridor = (
        draw_layers(
            ["1.BK. CAU", "KS_DUONG_BETONG"],
            line_thick_m=1.8,
            fill_closed=True,
            max_fill_area_m2=3000.0,
            close_gap_m=6.0,
        )
        > 0
    )
    traffic_narrow = (
        draw_layers(
            ["Giao_thong", "Dan_cu_kinh_te_xa_hoi", "KS_DUONG_DAT"],
            line_thick_m=1.1,
            fill_closed=False,
            close_gap_m=3.8,
        )
        > 0
    )
    traffic_wide = (
        draw_layers(
            ["Giao_thong", "Dan_cu_kinh_te_xa_hoi", "KS_DUONG_DAT"],
            line_thick_m=1.5,
            fill_closed=False,
            close_gap_m=11.0,
        )
        > 0
    )

    gt = np.zeros((ds_h, ds_w), dtype=np.int64)
    valid_surface = (~nodata) & (~veg) & (~house_mask)
    road_cand = (traffic_wide | asphalt_markings | bridge_corridor) & valid_surface
    dist_road = cv2.distanceTransform(road_cand.astype(np.uint8), cv2.DIST_L2, 5) * gsd_m
    k_prop = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (max(3, int(round(8.0 / gsd_m)) | 1), max(3, int(round(8.0 / gsd_m)) | 1)),
    )
    local_width_m = cv2.dilate(dist_road, k_prop) * 2.0

    is_fp = (traffic_narrow & valid_surface & (local_width_m < 3.5) & (~asphalt_markings)) | (
        footpath_corridor & valid_surface
    )
    is_dirt = road_cand & (~is_fp) & (~asphalt_markings) & (warm >= 22.0) & (r > g * 1.03) & (lum >= 75.0)
    is_conc = (
        road_cand & (~is_fp) & (~is_dirt) & (~asphalt_markings) & (lum >= 166.0) & (chroma < 30.0)
    ) | (bridge_corridor & valid_surface)
    is_asph = (
        (road_cand | (asphalt_markings & valid_surface))
        & (~is_fp)
        & (~is_dirt)
        & (~is_conc)
        & (chroma < 34.0)
        & (lum >= 38.0)
    )

    gt[is_asph] = 1
    gt[is_conc] = 2
    gt[is_dirt] = 3
    gt[is_fp] = 4

    is_pond = ((pond_poly | canal_corridor) & water_like) & (gt == 0)
    gt[is_pond] = 5

    is_ditch = (ditch_corridor & valid_surface) & (gt == 0)
    gt[is_ditch] = 6

    # Class 7: House / Building (Nhà / Công trình xây dựng)
    gt[house_mask & (gt == 0)] = 7

    # Class 8: Landscape Tree / Urban Greenery (Cây cảnh quan / Cây xanh đô thị)
    gt[tree_mask & (gt == 0)] = 8

    gt[nodata] = 0
    counts = {TERRAIN_CLASS_NAMES[i]: int((gt == i).sum()) for i in range(len(TERRAIN_CLASS_NAMES))}
    return rgb, gt, counts


def _sample_real_dwg_patch(
    rng: np.random.Generator,
    scenes: list[dict[str, Any]],
    size: int = 512,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample a 512x512 training patch centered on foreground survey polylines or hard-negative roofs/trees."""
    scene = scenes[int(rng.integers(0, len(scenes)))]
    rgb: np.ndarray = scene["rgb"]
    gt: np.ndarray = scene["gt"]
    h, w = gt.shape

    # Pick a target class present in this scene to guarantee balanced multi-class training
    avail_classes = [cls_id for cls_id, pts in scene["class_centers"].items() if len(pts) > 0]
    if avail_classes and rng.random() < 0.88:
        target_cls = avail_classes[int(rng.integers(0, len(avail_classes)))]
        pts = scene["class_centers"][target_cls]
        cy, cx = pts[int(rng.integers(0, len(pts)))]
        cy += int(rng.integers(-96, 97))
        cx += int(rng.integers(-96, 97))
    else:
        cy = int(rng.integers(size // 2, max(size // 2 + 1, h - size // 2)))
        cx = int(rng.integers(size // 2, max(size // 2 + 1, w - size // 2)))

    y0 = max(0, min(max(0, h - size), cy - size // 2))
    x0 = max(0, min(max(0, w - size), cx - size // 2))
    patch_rgb = np.zeros((size, size, 3), dtype=np.uint8)
    patch_gt = np.zeros((size, size), dtype=np.int64)
    ph = min(size, h - y0)
    pw = min(size, w - x0)
    patch_rgb[:ph, :pw] = rgb[y0 : y0 + ph, x0 : x0 + pw]
    patch_gt[:ph, :pw] = gt[y0 : y0 + ph, x0 : x0 + pw]

    # Geometric augmentations (flips + 90-deg rotations)
    k_rot = int(rng.integers(0, 4))
    if k_rot > 0:
        patch_rgb = np.rot90(patch_rgb, k_rot)
        patch_gt = np.rot90(patch_gt, k_rot)
    if rng.random() < 0.5:
        patch_rgb = np.fliplr(patch_rgb)
        patch_gt = np.fliplr(patch_gt)

    # Mild radiometric jitter
    gain = float(rng.uniform(0.92, 1.08))
    bias = float(rng.uniform(-8.0, 8.0))
    img_f = np.clip(patch_rgb.astype(np.float32) * gain + bias, 0.0, 255.0) / 255.0
    chw = np.transpose(img_f, (2, 0, 1)).copy()
    return chw, patch_gt.copy()


def _synthesize_uav_terrain_sample(rng: np.random.Generator, size: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """Generate a realistic UAV orthomosaic patch (512x512 RGB) and exact 7-class ground-truth mask."""
    img = np.zeros((size, size, 3), dtype=np.float32)
    mask = np.zeros((size, size), dtype=np.int64)

    bg_g = rng.uniform(95, 165)
    bg_r = bg_g * rng.uniform(0.55, 0.82)
    bg_b = bg_g * rng.uniform(0.38, 0.65)
    noise_bg = rng.normal(0, 14, size=(size, size, 3)).astype(np.float32)
    img[:, :, 0] = bg_r
    img[:, :, 1] = bg_g
    img[:, :, 2] = bg_b
    img += noise_bg

    for _ in range(int(rng.integers(3, 9))):
        cx, cy = int(rng.integers(20, size - 20)), int(rng.integers(20, size - 20))
        rad = int(rng.integers(14, 38))
        tree_layer = np.zeros((size, size), dtype=np.uint8)
        cv2.circle(tree_layer, (cx, cy), rad, 1, -1)
        idx = tree_layer > 0
        img[idx, 0] = rng.uniform(35, 65) + rng.normal(0, 8, size=int(idx.sum()))
        img[idx, 1] = rng.uniform(85, 138) + rng.normal(0, 10, size=int(idx.sum()))
        img[idx, 2] = rng.uniform(28, 52) + rng.normal(0, 7, size=int(idx.sum()))
        mask[idx] = 8  # Class 8: landscape_tree (Cây cảnh quan)

    # Class 7: house_building (Nhà / Công trình xây dựng with terracotta or corrugated metal roofs)
    for _ in range(int(rng.integers(1, 4))):
        hx = int(rng.integers(40, size - 110))
        hy = int(rng.integers(40, size - 110))
        hw = int(rng.integers(44, 92))
        hh = int(rng.integers(36, 80))
        house_layer = np.zeros((size, size), dtype=np.uint8)
        cv2.rectangle(house_layer, (hx, hy), (hx + hw, hy + hh), 1, -1)
        idx = house_layer > 0
        if rng.random() < 0.6:
            # Terracotta / red-orange tile roof
            hr, hg, hb = rng.uniform(175, 222), rng.uniform(85, 128), rng.uniform(55, 88)
        else:
            # Blue / cyan corrugated metal roof
            hr, hg, hb = rng.uniform(65, 105), rng.uniform(125, 165), rng.uniform(175, 225)
        img[idx, 0] = hr + rng.normal(0, 6, size=int(idx.sum()))
        img[idx, 1] = hg + rng.normal(0, 6, size=int(idx.sum()))
        img[idx, 2] = hb + rng.normal(0, 6, size=int(idx.sum()))
        mask[idx] = 7

    def rand_edge_pts() -> tuple[tuple[int, int], tuple[int, int]]:
        side1 = int(rng.integers(0, 4))
        side2 = (side1 + int(rng.integers(1, 4))) % 4
        pts = []
        for s in (side1, side2):
            v = int(rng.integers(30, size - 30))
            if s == 0:
                pts.append((v, 0))
            elif s == 1:
                pts.append((size - 1, v))
            elif s == 2:
                pts.append((v, size - 1))
            else:
                pts.append((0, v))
        return pts[0], pts[1]

    if rng.random() < 0.85:
        cx, cy = int(rng.integers(90, size - 90)), int(rng.integers(90, size - 90))
        rx, ry = int(rng.integers(48, 105)), int(rng.integers(40, 95))
        angle = float(rng.uniform(0, 180))
        pond_m = np.zeros((size, size), dtype=np.uint8)
        cv2.ellipse(pond_m, (cx, cy), (rx, ry), angle, 0, 360, 1, -1)
        idx = pond_m > 0
        if rng.random() < 0.5:
            wr, wg, wb = rng.uniform(32, 68), rng.uniform(62, 96), rng.uniform(58, 92)
        else:
            wr, wg, wb = rng.uniform(55, 88), rng.uniform(72, 102), rng.uniform(68, 98)
        smooth_n = cv2.GaussianBlur(rng.normal(0, 4, size=(size, size, 3)).astype(np.float32), (7, 7), 0)
        img[idx, 0] = wr + smooth_n[idx, 0]
        img[idx, 1] = wg + smooth_n[idx, 1]
        img[idx, 2] = wb + smooth_n[idx, 2]
        mask[idx] = 5

    if rng.random() < 0.80:
        p1, p2 = rand_edge_pts()
        w_px = int(rng.integers(34, 62))
        layer = np.zeros((size, size), dtype=np.uint8)
        cv2.line(layer, p1, p2, 1, thickness=w_px)
        idx = layer > 0
        dr = rng.uniform(138, 188)
        dg = dr * rng.uniform(0.72, 0.84)
        db = dr * rng.uniform(0.46, 0.62)
        img[idx, 0] = dr + rng.normal(0, 9, size=int(idx.sum()))
        img[idx, 1] = dg + rng.normal(0, 8, size=int(idx.sum()))
        img[idx, 2] = db + rng.normal(0, 8, size=int(idx.sum()))
        mask[idx] = 3

    if rng.random() < 0.80:
        p1, p2 = rand_edge_pts()
        mid = (
            int(np.clip((p1[0] + p2[0]) // 2 + rng.integers(-60, 60), 20, size - 20)),
            int(np.clip((p1[1] + p2[1]) // 2 + rng.integers(-60, 60), 20, size - 20)),
        )
        w_px = int(rng.integers(10, 20))
        layer = np.zeros((size, size), dtype=np.uint8)
        cv2.polylines(layer, [np.array([p1, mid, p2], dtype=np.int32)], False, 1, thickness=w_px)
        idx = layer > 0
        fp_base = rng.uniform(148, 195)
        img[idx, 0] = fp_base + rng.uniform(5, 18) + rng.normal(0, 7, size=int(idx.sum()))
        img[idx, 1] = fp_base + rng.normal(0, 7, size=int(idx.sum()))
        img[idx, 2] = fp_base - rng.uniform(8, 22) + rng.normal(0, 7, size=int(idx.sum()))
        mask[idx] = 4

    if rng.random() < 0.85:
        p1, p2 = rand_edge_pts()
        outer_w = int(rng.integers(16, 30))
        inner_w = max(6, outer_w - int(rng.integers(6, 11)))
        outer_m = np.zeros((size, size), dtype=np.uint8)
        inner_m = np.zeros((size, size), dtype=np.uint8)
        cv2.line(outer_m, p1, p2, 1, thickness=outer_w)
        cv2.line(inner_m, p1, p2, 1, thickness=inner_w)
        wall_idx = (outer_m > 0) & (inner_m == 0)
        core_idx = inner_m > 0
        wall_v = rng.uniform(195, 238)
        core_v = rng.uniform(35, 72)
        for c in range(3):
            img[wall_idx, c] = wall_v + rng.normal(0, 6, size=int(wall_idx.sum()))
        img[core_idx, 0] = core_v * 0.85 + rng.normal(0, 5, size=int(core_idx.sum()))
        img[core_idx, 1] = core_v * 1.05 + rng.normal(0, 5, size=int(core_idx.sum()))
        img[core_idx, 2] = core_v * 1.10 + rng.normal(0, 5, size=int(core_idx.sum()))
        mask[outer_m > 0] = 6

    if rng.random() < 0.80:
        p1, p2 = rand_edge_pts()
        w_px = int(rng.integers(40, 76))
        layer = np.zeros((size, size), dtype=np.uint8)
        cv2.line(layer, p1, p2, 1, thickness=w_px)
        idx = layer > 0
        cv_base = rng.uniform(186, 232)
        img[idx, 0] = cv_base + rng.normal(0, 6, size=int(idx.sum()))
        img[idx, 1] = cv_base + rng.normal(0, 6, size=int(idx.sum()))
        img[idx, 2] = cv_base - rng.uniform(0, 6) + rng.normal(0, 6, size=int(idx.sum()))
        mask[idx] = 2

    if rng.random() < 0.85:
        p1, p2 = rand_edge_pts()
        w_px = int(rng.integers(48, 92))
        layer = np.zeros((size, size), dtype=np.uint8)
        cv2.line(layer, p1, p2, 1, thickness=w_px)
        idx = layer > 0
        as_base = rng.uniform(52, 134)
        img[idx, 0] = as_base + rng.normal(0, 5, size=int(idx.sum()))
        img[idx, 1] = as_base + rng.uniform(-2, 3) + rng.normal(0, 5, size=int(idx.sum()))
        img[idx, 2] = as_base + rng.uniform(2, 8) + rng.normal(0, 5, size=int(idx.sum()))
        mask[idx] = 1
        if rng.random() < 0.6:
            stripe = np.zeros((size, size), dtype=np.uint8)
            cv2.line(stripe, p1, p2, 1, thickness=2)
            s_idx = (stripe > 0) & idx
            img[s_idx] = 225.0

    img = np.clip(img, 0, 255).astype(np.float32) / 255.0
    chw = np.transpose(img, (2, 0, 1))
    return chw, mask


def extract_khu_tam_giac_style_profile(
    cad_path: Path | None = None,
    ortho_path: Path | None = None,
    jgw_path: Path | None = None,
    dem_path: Path | None = None,
    output_profile_path: Path | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Extract multi-channel spectral, texture & elevation prototypes and CAD drawing rules from `ACAD_KHU TAM GIAC.dwg`.

    Computes per-block and per-class prototypes over 9 features:
      `[r_norm, g_norm, b_norm, exg, vari, ngrdi, canopy_darkness, local_std, dz_m]`
    for all 10 vegetation/landscape blocks (`caylato`, `cumcay2`, `cumcay1`, `cocao`, `cothap`, `hoa`,
    `Hoasen`, `cdt2`, `cdt39`, `cbui13`) + grid density and `Ranhgioi_thucvat` boundary rules.
    Saves:
      - `.cache/ref_khu_tam_giac.dxf`
      - `.cache/ref_khu_tam_giac_analysis.json`
      - `assets/models/khu_tam_giac_style_profile.json`
    """
    import shutil

    app_root = Path(__file__).resolve().parents[2]
    ws_root = app_root.parent if (app_root.parent / "sample").is_dir() else app_root

    ref_dwg = cad_path or Path(
        r"c:\Users\HL\OneDrive\09 1.KCPD DOAN 67-71\ACAD\Waterpoint_10.3.26\ACAD-KHU TAM GIAC (06-10-2026)\ACAD_KHU TAM GIAC.dwg"
    )
    if not ref_dwg.is_file():
        bundles = discover_dwg_ortho_bundles()
        if bundles and bundles[0].get("cad_path"):
            ref_dwg = Path(bundles[0]["cad_path"])

    ortho_candidates = [
        ortho_path,
        ws_root / "sample" / "RGB" / "22585258_Khu_Tam_Giac_5cm.tif",
        ws_root / "sample" / "RGB" / "ORTHO_KHU TAM GIAC (03-10-2026).jpg",
        ref_dwg.parent / "ORTHO_KHU TAM GIAC (03-10-2026).jpg",
    ]
    eff_ortho = next((Path(p) for p in ortho_candidates if p and Path(p).is_file()), None)

    dem_candidates = [
        dem_path,
        ws_root / "sample" / "22585258_Khu_Tam_Giac_DEM.tif",
        ws_root / "sample" / "RGB" / "DEM_TAM GIAC (03-10-2026).tif",
        ref_dwg.parent / "DEM_TAM GIAC (03-10-2026).tif",
    ]
    eff_dem = next((Path(p) for p in dem_candidates if p and Path(p).is_file()), None)

    eff_jgw = jgw_path or (eff_ortho.with_suffix(".jgw") if eff_ortho is not None else None)

    eff_cache_dirs = [
        cache_dir or (app_root / ".cache"),
        ws_root / ".cache",
    ]
    for cd in eff_cache_dirs:
        cd.mkdir(parents=True, exist_ok=True)

    dxf_path = convert_dwg_to_dxf(ref_dwg)
    for cd in eff_cache_dirs:
        dst_dxf = cd / "ref_khu_tam_giac.dxf"
        if dxf_path.resolve() != dst_dxf.resolve():
            try:
                shutil.copy2(dxf_path, dst_dxf)
            except Exception:
                pass

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    # Load orthomosaic + DEM at 0.20m/px to sample spectral/texture/elevation around every INSERT & polyline
    target_gsd_m = 0.20
    a_gsd, e_gsd, c_x, f_y = 0.05, -0.05, 581000.0, 1170000.0
    scale = 0.25
    ds_w, ds_h = 2048, 1600
    rgb = np.zeros((ds_h, ds_w, 3), dtype=np.uint8)

    if eff_ortho is not None and eff_ortho.is_file():
        if eff_jgw is not None and eff_jgw.is_file():
            jlines = [
                float(x.strip())
                for x in eff_jgw.read_text(encoding="utf-8", errors="ignore").splitlines()
                if x.strip()
            ]
            a_gsd, _d, _b, e_gsd, c_x, f_y = jlines[:6]
        orig_gsd = max(0.005, abs(a_gsd))
        scale = min(1.0, orig_gsd / target_gsd_m)
        with Image.open(eff_ortho) as im:
            orig_w, orig_h = im.size
            ds_w = max(64, int(round(orig_w * scale)))
            ds_h = max(64, int(round(orig_h * scale)))
            rgb = np.asarray(im.resize((ds_w, ds_h), Image.Resampling.BILINEAR), dtype=np.uint8)

    rgb_f = rgb.astype(np.float32)
    r, g, b = rgb_f[:, :, 0], rgb_f[:, :, 1], rgb_f[:, :, 2]
    rgb_sum = np.maximum(r + g + b, 1.0)
    r_norm = r / rgb_sum
    g_norm = g / rgb_sum
    b_norm = b / rgb_sum
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    exg = (2.0 * g - r - b) / 255.0
    vari = np.clip((g - r) / np.maximum(g + r - b, 1.0), -1.0, 1.0)
    ngrdi = np.clip((g - r) / np.maximum(g + r, 1.0), -1.0, 1.0)
    canopy_dark = 1.0 - np.clip(lum / 255.0, 0.0, 1.0)
    lum_blur = cv2.GaussianBlur(lum, (5, 5), 0)
    local_std = np.sqrt(np.maximum(0.0, cv2.GaussianBlur((lum - lum_blur) ** 2, (5, 5), 0))) / 255.0

    dz_map = np.zeros((ds_h, ds_w), dtype=np.float32)
    if eff_dem is not None and eff_dem.is_file():
        try:
            import rasterio
            from rasterio.enums import Resampling as RioResampling

            with rasterio.open(eff_dem) as s_dem:
                z_arr = s_dem.read(1, out_shape=(ds_h, ds_w), resampling=RioResampling.nearest).astype(np.float32)
                valid_z = np.isfinite(z_arr) & (z_arr > -100.0) & (z_arr < 9000.0)
                if np.any(valid_z):
                    med_v = float(np.median(z_arr[valid_z]))
                    z_fill = np.where(valid_z, z_arr, med_v).astype(np.float32)
                    cw, ch = max(8, ds_w // 8), max(8, ds_h // 8)
                    z_small = cv2.resize(z_fill, (cw, ch), interpolation=cv2.INTER_AREA)
                    z_open = cv2.morphologyEx(
                        z_small,
                        cv2.MORPH_OPEN,
                        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
                    )
                    z_ground = cv2.resize(
                        cv2.GaussianBlur(z_open, (0, 0), sigmaX=4.5, sigmaY=4.5),
                        (ds_w, ds_h),
                        interpolation=cv2.INTER_LINEAR,
                    )
                    dz_map = np.where(valid_z, z_arr - z_ground, 0.0)
        except Exception:
            pass

    feature_stack = np.stack(
        [r_norm, g_norm, b_norm, exg, vari, ngrdi, canopy_dark, local_std, dz_map],
        axis=-1,
    )  # [H, W, 9]
    feature_names = [
        "r_norm",
        "g_norm",
        "b_norm",
        "exg",
        "vari",
        "ngrdi",
        "canopy_darkness",
        "local_std",
        "dz_m",
    ]

    def w2p(wx: float, wy: float) -> tuple[int, int]:
        return int(round((wx - c_x) / a_gsd * scale)), int(round((wy - f_y) / e_gsd * scale))

    target_blocks = [
        "caylato",
        "cumcay2",
        "cumcay1",
        "cocao",
        "cothap",
        "hoa",
        "Hoasen",
        "cdt2",
        "cdt39",
        "cbui13",
    ]
    block_descriptions = {
        "caylato": "Cây lá to / Cây bóng mát tán rộng trong vùng thực vật",
        "cumcay2": "Cụm cây bụi nhỡ rải lưới đều trong Ranhgioi_thucvat (layer Thuc_vat)",
        "cumcay1": "Cụm cây bụi lớn / Cây bụi cảnh quan (layer THUCVAT)",
        "cocao": "Cỏ cao / Lau sậy vùng thực vật ẩm hoặc ven kênh (layer 1.BK. THUC VAT)",
        "cothap": "Cỏ thấp / Thảm cỏ nền rải lưới đều (layer 1.BK. THUC VAT)",
        "hoa": "Thảm hoa / Cây hoa trang trí công viên & ven đường (layer 1.BK. THUC VAT)",
        "Hoasen": "Hoa sen / Thực vật thủy sinh mặt nước ao hồ (layer 1.BK. THUC VAT)",
        "cdt2": "Cây đô thị loại 2 trồng dọc vỉa hè & công viên (layer Thuvien)",
        "cdt39": "Cây đô thị tán tròn lớn dọc trục đường chính (layer Thuvien)",
        "cbui13": "Cây xanh cảnh quan / Cây bụi công viên (layer 07-CAY XANH)",
    }

    block_samples: dict[str, list[np.ndarray]] = {b: [] for b in target_blocks}
    block_coords_w: dict[str, list[tuple[float, float]]] = {b: [] for b in target_blocks}
    block_layers_seen: dict[str, str] = {}
    block_scales_seen: dict[str, list[float]] = {b: [] for b in target_blocks}
    layer_entity_counts: dict[str, int] = {}

    for ent in msp:
        lyr = str(ent.dxf.layer or "")
        layer_entity_counts[lyr] = layer_entity_counts.get(lyr, 0) + 1
        if ent.dxftype() == "INSERT":
            bname = str(getattr(ent.dxf, "name", "") or "")
            matched = next((tb for tb in target_blocks if tb.lower() == bname.lower()), None)
            if matched is None:
                continue
            block_layers_seen.setdefault(matched, lyr)
            ins = ent.dxf.insert
            wx, wy = float(ins.x), float(ins.y)
            block_coords_w[matched].append((wx, wy))
            sx = float(getattr(ent.dxf, "xscale", 1.0) or 1.0)
            block_scales_seen[matched].append(abs(sx))
            px, py = w2p(wx, wy)
            if 3 <= px < ds_w - 3 and 3 <= py < ds_h - 3:
                patch_feat = feature_stack[py - 2 : py + 3, px - 2 : px + 3].reshape(-1, len(feature_names))
                block_samples[matched].append(patch_feat.mean(axis=0))

    block_prototypes: dict[str, Any] = {}
    for bname in target_blocks:
        pts_w = block_coords_w[bname]
        nn_dists: list[float] = []
        if len(pts_w) >= 2:
            arr_w = np.array(pts_w, dtype=np.float64)
            for idx_p in range(min(len(arr_w), 250)):
                diffs = arr_w - arr_w[idx_p]
                d2 = np.hypot(diffs[:, 0], diffs[:, 1])
                d2_pos = d2[(d2 > 0.4) & (d2 < 25.0)]
                if len(d2_pos) > 0:
                    nn_dists.append(float(np.min(d2_pos)))
        spacing_m = round(float(np.median(nn_dists)), 2) if nn_dists else 6.5

        feats_list = block_samples[bname]
        if feats_list:
            f_arr = np.stack(feats_list, axis=0)
            p_mean = [round(float(v), 4) for v in f_arr.mean(axis=0)]
            p_std = [round(max(0.015, float(v)), 4) for v in f_arr.std(axis=0)]
        else:
            p_mean = [0.28, 0.44, 0.28, 0.16, 0.18, 0.14, 0.58, 0.08, 0.45]
            p_std = [0.05, 0.06, 0.05, 0.06, 0.06, 0.05, 0.10, 0.04, 0.35]

        scales = block_scales_seen[bname]
        med_scale = round(float(np.median(scales)), 3) if scales else 1.0
        block_prototypes[bname] = {
            "block_name": bname,
            "cad_layer": block_layers_seen.get(bname, "1.BK. THUC VAT"),
            "count_in_reference_dwg": len(pts_w),
            "grid_spacing_m": spacing_m,
            "default_scale": med_scale,
            "description_vi": block_descriptions.get(bname, ""),
            "feature_names": feature_names,
            "prototype_mean": dict(zip(feature_names, p_mean)),
            "prototype_vector": p_mean,
            "prototype_std": p_std,
        }

    profile_payload = {
        "profile_name": "KhuTamGiac-Waterpoint-Reference-Style-Profile",
        "reference_dwg": str(ref_dwg),
        "reference_dxf_cache": str(eff_cache_dirs[0] / "ref_khu_tam_giac.dxf"),
        "reference_ortho": str(eff_ortho) if eff_ortho else None,
        "reference_dem": str(eff_dem) if eff_dem else None,
        "feature_names": feature_names,
        "classes_9": TERRAIN_CLASS_NAMES,
        "vegetation_boundary_rule": {
            "boundary_layer": "Ranhgioi_thucvat",
            "secondary_layer": "Thuc_vat",
            "closed_lwpolyline": True,
            "fill_mode": "uniform_staggered_grid_blocks",
            "default_grid_spacing_x_m": 6.5,
            "default_grid_spacing_y_m": 6.0,
            "stagger_alternate_rows": True,
            "boundary_margin_m": 1.8,
            "mix_blocks_in_large_zones": ["cumcay2", "caylato", "cothap", "cocao", "cumcay1", "hoa"],
            "water_vegetation_block": "Hoasen",
            "street_tree_blocks": ["cdt2", "cdt39", "cbui13"],
        },
        "block_prototypes": block_prototypes,
        "total_block_instances_sampled": sum(int(v.get("count_in_reference_dwg", 0)) for v in block_prototypes.values()),
        "layer_entity_counts": layer_entity_counts,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    for cd in eff_cache_dirs:
        analysis_file = cd / "ref_khu_tam_giac_analysis.json"
        analysis_file.write_text(json.dumps(profile_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    profile_targets = [
        app_root / "assets" / "models" / "khu_tam_giac_style_profile.json",
        ws_root / "assets" / "models" / "khu_tam_giac_style_profile.json",
    ]
    if output_profile_path is not None:
        profile_targets.insert(0, Path(output_profile_path))
    for pt in profile_targets:
        pt.parent.mkdir(parents=True, exist_ok=True)
        pt.write_text(json.dumps(profile_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return profile_payload


def train_and_export_terrain_onnx(
    output_onnx: Path,
    steps: int = 200,
    batch_size: int = 8,
    survey_roots: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Train TerrainSegUNetLite on real `sample/RGB` + `.DWG` + `ORTHO` + `DEM` bundles and export 9-class ONNX."""
    import shutil

    t0 = time.time()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(42)
    rng = np.random.default_rng(42)

    style_profile = extract_khu_tam_giac_style_profile()

    bundles = discover_dwg_ortho_bundles(survey_roots)
    real_scenes: list[dict[str, Any]] = []
    zone_summaries: list[dict[str, Any]] = []
    total_class_pixels = {k: 0 for k in TERRAIN_CLASS_NAMES}

    for b in bundles:
        try:
            rgb, gt, counts = build_gt_mask_from_dwg_bundle(
                b.get("cad_path"),
                b["ortho_path"],
                b["jgw_path"],
                dem_path=b.get("dem_path"),
                target_gsd_m=0.15,
            )
            class_centers: dict[int, np.ndarray] = {}
            for cls_id in range(1, len(TERRAIN_CLASS_NAMES)):
                ys, xs = np.nonzero(gt == cls_id)
                if len(ys) > 0:
                    step_sub = max(1, len(ys) // 1500)
                    class_centers[cls_id] = np.stack([ys[::step_sub], xs[::step_sub]], axis=1)
            cad_name = b["cad_path"].name if b.get("cad_path") else b["ortho_path"].name
            real_scenes.append(
                {
                    "name": cad_name,
                    "ortho": b["ortho_path"].name,
                    "rgb": rgb,
                    "gt": gt,
                    "class_centers": class_centers,
                }
            )
            for k, v in counts.items():
                total_class_pixels[k] = total_class_pixels.get(k, 0) + int(v)
            zone_summaries.append(
                {
                    "folder": b.get("folder"),
                    "dwg_file": cad_name,
                    "ortho_file": b["ortho_path"].name,
                    "dem_file": b["dem_path"].name if b.get("dem_path") else None,
                    "resolution": f"{rgb.shape[1]}x{rgb.shape[0]}",
                    "class_pixels": counts,
                }
            )
        except Exception:
            continue

    model = TerrainSegUNetLite(num_classes=len(TERRAIN_CLASS_NAMES)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(10, steps))
    weights = torch.tensor(
        [0.55, 1.35, 1.45, 1.40, 1.65, 1.20, 1.75, 1.45, 1.15],
        dtype=torch.float32,
        device=device,
    )
    criterion = nn.CrossEntropyLoss(weight=weights)

    model.train()
    last_loss = 0.0
    real_patches_used = 0
    for _ in range(steps):
        xs, ys = [], []
        for _b in range(batch_size):
            if real_scenes and rng.random() < 0.78:
                x, y = _sample_real_dwg_patch(rng, real_scenes, 512)
                real_patches_used += 1
            else:
                x, y = _synthesize_uav_terrain_sample(rng, 512)
            xs.append(x)
            ys.append(y)
        bx = torch.from_numpy(np.stack(xs, axis=0)).to(device)
        by = torch.from_numpy(np.stack(ys, axis=0)).to(device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(bx)
        loss = criterion(logits, by)
        loss.backward()
        optimizer.step()
        scheduler.step()
        last_loss = float(loss.item())

    model.eval()
    correct_px = 0
    total_px = 0
    with torch.no_grad():
        for i in range(8):
            if real_scenes and i < 5:
                x, y = _sample_real_dwg_patch(rng, real_scenes, 512)
            else:
                x, y = _synthesize_uav_terrain_sample(rng, 512)
            bx = torch.from_numpy(x[None]).to(device)
            pred = model(bx).argmax(dim=1).squeeze(0).cpu().numpy()
            correct_px += int((pred == y).sum())
            total_px += int(y.size)
    val_acc = round(correct_px / max(1, total_px), 4)

    output_onnx = Path(output_onnx)
    output_onnx.parent.mkdir(parents=True, exist_ok=True)
    cpu_model = model.to("cpu").eval()
    dummy = torch.zeros((1, 3, 512, 512), dtype=torch.float32)
    torch.onnx.export(
        cpu_model,
        dummy,
        str(output_onnx),
        input_names=["images"],
        output_names=["logits"],
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )

    app_root = Path(__file__).resolve().parents[2]
    ws_root = app_root.parent if (app_root.parent / "sample").is_dir() else app_root
    segformer_targets = [
        app_root / "assets" / "models" / "terrain_9classes_segformer.onnx",
        ws_root / "assets" / "models" / "terrain_9classes_segformer.onnx",
    ]
    for st in segformer_targets:
        st.parent.mkdir(parents=True, exist_ok=True)
        if output_onnx.resolve() != st.resolve():
            shutil.copy2(output_onnx, st)

    meta = {
        "model_name": "TerrainSegUNetLite-WebGPU-9Class",
        "classes": TERRAIN_CLASS_NAMES,
        "input_shape": [1, 3, 512, 512],
        "output_shape": [1, len(TERRAIN_CLASS_NAMES), 512, 512],
        "opset": 17,
        "device_trained": str(device),
        "steps": steps,
        "batch_size": batch_size,
        "segformer_onnx_path": str(segformer_targets[0]),
        "style_profile_path": str(app_root / "assets" / "models" / "khu_tam_giac_style_profile.json"),
        "block_prototypes_count": len(style_profile.get("block_prototypes", {})),
        "real_dwg_zones_count": len(zone_summaries),
        "real_dwg_zones_trained": zone_summaries,
        "real_patches_sampled": real_patches_used,
        "total_class_pixels": total_class_pixels,
        "final_loss": round(last_loss, 4),
        "val_pixel_accuracy": val_acc,
        "size_bytes": output_onnx.stat().st_size,
        "elapsed_seconds": round(time.time() - t0, 2),
    }
    meta_path = output_onnx.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--survey-root", type=Path, action="append", default=None)
    args = parser.parse_args()
    meta = train_and_export_terrain_onnx(args.output, steps=args.steps, survey_roots=args.survey_root)
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
