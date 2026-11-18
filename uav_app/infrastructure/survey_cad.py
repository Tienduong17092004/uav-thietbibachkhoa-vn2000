"""Topographic Survey Plan & CAD Symbol/Block Library Module (Bình đồ Khảo sát Địa hình & Thư viện Ký hiệu CAD).

Kept cleanly separated from the Tree/Rice counting workflow. Supports:
1. Inspecting user-supplied CAD libraries (.dxf) to extract Block definitions, Layers, and Linetypes,
   combined with a built-in VN2000 Topographic Survey Standard Library.
2. Configurable Survey Mapping Rules per feature category (`ornamental tree`, `ditch`, `road`, `bridge`,
   `building`, `fence`, `electric pole`):
   - `BLOCK`: Inserts a CAD Block (`INSERT`) at the feature center with custom block name, layer, color, and scale.
   - `DOUBLE_LINE`: Draws two parallel offset lines (`2 LINE song song`) along the feature axis/polyline with
     configurable corridor width, layer name, ACI color, and optional centerline (`CENTERLINE`).
   - `BRIDGE_SYMBOL`: Draws a standard topographic bridge symbol (deck + flared wingwalls) on the target layer.
   - `CLOSED_POLYLINE`: Draws a closed structural footprint polyline with optional hatch/layer.
3. Exporting the Topographic Survey Plan to `binh_do_khao_sat.dxf` (importing blocks from the user's CAD
   library if provided) and optionally sending directly to AutoCAD via COM.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import ezdxf

from uav_app.domain.detection import spatial_box
from uav_app.infrastructure.raster import _write_json

BUILTIN_SURVEY_BLOCKS = [
    {"name": "BLK_CAY_CANH", "label": "Block Cây cảnh / Cây bóng mát (Chuẩn Địa chính VN2000)", "category": "ornamental tree"},
    {"name": "BLK_CAY_CO_THU", "label": "Block Cây cổ thụ (Tán kép + Gốc)", "category": "tree"},
    {"name": "BLK_CAU_CONG", "label": "Block Cầu / Cống qua mương", "category": "bridge"},
    {"name": "BLK_COT_DIEN", "label": "Block Cột điện / Trụ đèn chiếu sáng", "category": "electric pole"},
    {"name": "BLK_HO_GA", "label": "Block Hố ga thoát nước", "category": "manhole"},
    {"name": "BLK_MOC_KHAO_SAT", "label": "Block Mốc trắc địa / Khống chế đo đạc", "category": "benchmark"},
]

BUILTIN_SURVEY_LAYERS = [
    {"name": "KS_CAY_CANH", "color": 3, "linetype": "CONTINUOUS", "description": "Cây cảnh, cây xanh đô thị (Xanh lá - ACI 3)"},
    {"name": "KS_MUONG_NUOC", "color": 4, "linetype": "CONTINUOUS", "description": "Mương thoát nước, kênh thủy lợi 2 nét (Xanh lơ - ACI 4)"},
    {"name": "KS_MUONG_XAY", "color": 4, "linetype": "CONTINUOUS", "description": "Mương xây bê tông 2 thành song song (Xanh lơ - ACI 4)"},
    {"name": "KS_AO_HO", "color": 5, "linetype": "CONTINUOUS", "description": "Bờ ao, hồ nước khép kín & taluy (Xanh dương - ACI 5)"},
    {"name": "KS_DUONG_GT", "color": 1, "linetype": "CONTINUOUS", "description": "Mép đường giao thông, bờ đường (Đỏ - ACI 1)"},
    {"name": "KS_DUONG_NHUA", "color": 1, "linetype": "CONTINUOUS", "description": "Đường nhựa 2 mép + tim tuyến (Đỏ - ACI 1)"},
    {"name": "KS_DUONG_BETONG", "color": 7, "linetype": "CONTINUOUS", "description": "Đường bê tông xi măng (Trắng/Đen - ACI 7)"},
    {"name": "KS_DUONG_DAT", "color": 30, "linetype": "DASHED", "description": "Đường đất, bờ bao đất nét đứt (Cam nâu - ACI 30)"},
    {"name": "KS_DUONG_DIBO", "color": 8, "linetype": "DASHED", "description": "Đường đi bộ, lối mòn, vỉa hè (Xám - ACI 8)"},
    {"name": "KS_TIM_DUONG", "color": 2, "linetype": "CENTER", "description": "Tim đường giao thông (Vàng - ACI 2)"},
    {"name": "KS_CAU_CONG", "color": 6, "linetype": "CONTINUOUS", "description": "Cầu, cống qua đường/mương (Tím - ACI 6)"},
    {"name": "KS_CONG_TRINH", "color": 7, "linetype": "CONTINUOUS", "description": "Nhà cửa, công trình xây dựng (Trắng - ACI 7)"},
    {"name": "KS_TUONG_RAO", "color": 8, "linetype": "DASHED", "description": "Tường rào, ranh giới thửa (Xám - ACI 8)"},
    {"name": "KS_HA_TANG", "color": 30, "linetype": "CONTINUOUS", "description": "Cột điện, hố ga, hạ tầng kỹ thuật (Cam - ACI 30)"},
]

DEFAULT_SURVEY_RULES: list[dict[str, Any]] = [
    {
        "category": "ornamental tree",
        "label_vi": "Cây cảnh / Cây bóng mát",
        "cad_type": "BLOCK",
        "block_name": "BLK_CAY_CANH",
        "layer": "KS_CAY_CANH",
        "color": 3,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 0.0,
        "centerline": False,
    },
    {
        "category": "ditch",
        "label_vi": "Mương nước / Kênh nội đồng (2 Line song song)",
        "cad_type": "DOUBLE_LINE",
        "block_name": "",
        "layer": "KS_MUONG_NUOC",
        "color": 4,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 1.2,
        "centerline": False,
    },
    {
        "category": "road",
        "label_vi": "Đường xá / Giao thông (2 Line mép + Tim đường)",
        "cad_type": "DOUBLE_LINE",
        "block_name": "",
        "layer": "KS_DUONG_GT",
        "color": 1,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 3.5,
        "centerline": True,
    },
    {
        "category": "bridge",
        "label_vi": "Cầu / Cống qua mương",
        "cad_type": "BRIDGE_SYMBOL",
        "block_name": "BLK_CAU_CONG",
        "layer": "KS_CAU_CONG",
        "color": 6,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 2.5,
        "centerline": False,
    },
    {
        "category": "building",
        "label_vi": "Nhà / Công trình xây dựng",
        "cad_type": "CLOSED_POLYLINE",
        "block_name": "",
        "layer": "KS_CONG_TRINH",
        "color": 7,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 0.0,
        "centerline": False,
    },
    {
        "category": "fence",
        "label_vi": "Tường rào / Bờ bao",
        "cad_type": "DOUBLE_LINE",
        "block_name": "",
        "layer": "KS_TUONG_RAO",
        "color": 8,
        "linetype": "DASHED",
        "scale": 1.0,
        "width_m": 0.25,
        "centerline": False,
    },
    {
        "category": "electric pole",
        "label_vi": "Cột điện / Trụ hạ tầng",
        "cad_type": "BLOCK",
        "block_name": "BLK_COT_DIEN",
        "layer": "KS_HA_TANG",
        "color": 30,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 0.0,
        "centerline": False,
    },
    {
        "category": "asphalt_road",
        "label_vi": "Đường nhựa (2 mép + Tim tuyến)",
        "cad_type": "DOUBLE_LINE",
        "block_name": "",
        "layer": "KS_DUONG_NHUA",
        "color": 1,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 5.0,
        "centerline": True,
    },
    {
        "category": "concrete_road",
        "label_vi": "Đường bê tông (2 mép + Tim tuyến)",
        "cad_type": "DOUBLE_LINE",
        "block_name": "",
        "layer": "KS_DUONG_BETONG",
        "color": 7,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 3.5,
        "centerline": True,
    },
    {
        "category": "dirt_road",
        "label_vi": "Đường đất (2 mép nét đứt)",
        "cad_type": "DOUBLE_LINE",
        "block_name": "",
        "layer": "KS_DUONG_DAT",
        "color": 30,
        "linetype": "DASHED",
        "scale": 1.0,
        "width_m": 3.0,
        "centerline": False,
    },
    {
        "category": "footpath",
        "label_vi": "Đường đi bộ / Lối mòn",
        "cad_type": "DOUBLE_LINE",
        "block_name": "",
        "layer": "KS_DUONG_DIBO",
        "color": 8,
        "linetype": "DASHED",
        "scale": 1.0,
        "width_m": 1.2,
        "centerline": False,
    },
    {
        "category": "pond",
        "label_vi": "Ao / Hồ nước (Bờ khép kín)",
        "cad_type": "CLOSED_POLYLINE",
        "block_name": "",
        "layer": "KS_AO_HO",
        "color": 5,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 0.0,
        "centerline": False,
    },
    {
        "category": "masonry_ditch",
        "label_vi": "Mương xây bê tông (2 thành song song)",
        "cad_type": "DOUBLE_LINE",
        "block_name": "",
        "layer": "KS_MUONG_XAY",
        "color": 4,
        "linetype": "CONTINUOUS",
        "scale": 1.0,
        "width_m": 1.0,
        "centerline": False,
    },
]


def inspect_cad_library(dxf_path: str | Path | None = None) -> dict[str, Any]:
    """Read user CAD library file (.dxf) and merge with built-in VN2000 Survey Standard Library."""
    blocks = copy.deepcopy(BUILTIN_SURVEY_BLOCKS)
    layers = copy.deepcopy(BUILTIN_SURVEY_LAYERS)
    linetypes = ["CONTINUOUS", "DASHED", "CENTER", "HIDDEN", "PHANTOM"]
    loaded_file = None

    if dxf_path and str(dxf_path).strip():
        candidate = Path(str(dxf_path).strip().strip('"')).expanduser()
        if not candidate.is_file():
            raise ValueError(f"Không tìm thấy tệp thư viện CAD: {candidate}")
        if candidate.suffix.lower() == ".dwg":
            from uav_app.infrastructure.dwg_io import convert_dwg_to_dxf

            resolved_dxf = convert_dwg_to_dxf(candidate)
        elif candidate.suffix.lower() == ".dxf":
            resolved_dxf = candidate
        else:
            raise ValueError("Hãy chọn tệp thư viện chuẩn định dạng .DWG hoặc .DXF.")
        doc = ezdxf.readfile(str(resolved_dxf))
        loaded_file = str(candidate.resolve())

        existing_block_names = {b["name"].upper() for b in blocks}
        for blk in doc.blocks:
            name = blk.name
            if name.startswith("*") or name.upper() in ("_ARCHTICK", "_OPEN", "_DOT", "_CLOSED"):
                continue
            if name.upper() not in existing_block_names:
                blocks.insert(0, {"name": name, "label": f"{name} (Từ thư viện CAD người dùng)", "category": "custom"})
                existing_block_names.add(name.upper())

        existing_layer_names = {l["name"].upper() for l in layers}
        for lyr in doc.layers:
            lname = lyr.dxf.name
            if lname.upper() in ("0", "DEFPOINTS") or lname.upper() in existing_layer_names:
                continue
            layers.insert(
                0,
                {
                    "name": lname,
                    "color": int(getattr(lyr.dxf, "color", 7) or 7),
                    "linetype": str(getattr(lyr.dxf, "linetype", "CONTINUOUS") or "CONTINUOUS"),
                    "description": "Layer từ tệp thư viện CAD người dùng",
                },
            )
            existing_layer_names.add(lname.upper())

        for lt in doc.linetypes:
            lt_name = lt.dxf.name.upper()
            if lt_name not in ("BYLAYER", "BYBLOCK") and lt_name not in linetypes:
                linetypes.append(lt_name)

    return {
        "library_path": loaded_file,
        "blocks": blocks,
        "layers": layers,
        "linetypes": linetypes,
        "default_rules": copy.deepcopy(DEFAULT_SURVEY_RULES),
    }


def _ensure_builtin_blocks(doc: Any) -> None:
    """Create standard VN2000 topographic survey blocks in the target DXF document if not already present."""
    # 1. BLK_CAY_CANH: Ornamental tree crown with trunk cross & foliage arcs
    if "BLK_CAY_CANH" not in doc.blocks:
        b = doc.blocks.new(name="BLK_CAY_CANH")
        b.add_circle((0, 0), radius=0.85, dxfattribs={"color": 3})
        b.add_circle((0, 0), radius=0.18, dxfattribs={"color": 3})
        b.add_line((-0.35, 0), (0.35, 0), dxfattribs={"color": 3})
        b.add_line((0, -0.35), (0, 0.35), dxfattribs={"color": 3})
        for angle_deg in (45, 135, 225, 315):
            rad = math.radians(angle_deg)
            cx, cy = 0.52 * math.cos(rad), 0.52 * math.sin(rad)
            b.add_circle((cx, cy), radius=0.38, dxfattribs={"color": 3})

    # 2. BLK_CAY_CO_THU: Ancient / large canopy tree
    if "BLK_CAY_CO_THU" not in doc.blocks:
        b = doc.blocks.new(name="BLK_CAY_CO_THU")
        b.add_circle((0, 0), radius=1.25, dxfattribs={"color": 3})
        b.add_circle((0, 0), radius=0.75, dxfattribs={"color": 3})
        b.add_circle((0, 0), radius=0.15, dxfattribs={"color": 3})
        b.add_line((-0.5, 0), (0.5, 0), dxfattribs={"color": 3})
        b.add_line((0, -0.5), (0, 0.5), dxfattribs={"color": 3})

    # 3. BLK_CAU_CONG: Bridge / culvert symbol with flared wingwalls
    if "BLK_CAU_CONG" not in doc.blocks:
        b = doc.blocks.new(name="BLK_CAU_CONG")
        b.add_lwpolyline([(-1.2, -0.6), (1.2, -0.6)], dxfattribs={"color": 6})
        b.add_lwpolyline([(-1.2, 0.6), (1.2, 0.6)], dxfattribs={"color": 6})
        # 4 flared wingwalls
        b.add_line((-1.2, -0.6), (-1.55, -0.95), dxfattribs={"color": 6})
        b.add_line((1.2, -0.6), (1.55, -0.95), dxfattribs={"color": 6})
        b.add_line((-1.2, 0.6), (-1.55, 0.95), dxfattribs={"color": 6})
        b.add_line((1.2, 0.6), (1.55, 0.95), dxfattribs={"color": 6})

    # 4. BLK_COT_DIEN: Electric pole with lightning/crossbar ticks
    if "BLK_COT_DIEN" not in doc.blocks:
        b = doc.blocks.new(name="BLK_COT_DIEN")
        b.add_circle((0, 0), radius=0.25, dxfattribs={"color": 30})
        b.add_line((-0.45, 0), (0.45, 0), dxfattribs={"color": 30})
        b.add_line((0, -0.45), (0, 0.45), dxfattribs={"color": 30})

    # 5. BLK_HO_GA: Manhole square + diagonal
    if "BLK_HO_GA" not in doc.blocks:
        b = doc.blocks.new(name="BLK_HO_GA")
        b.add_lwpolyline([(-0.3, -0.3), (0.3, -0.3), (0.3, 0.3), (-0.3, 0.3)], close=True, dxfattribs={"color": 30})
        b.add_line((-0.3, -0.3), (0.3, 0.3), dxfattribs={"color": 30})

    # 6. BLK_MOC_KHAO_SAT: Survey benchmark triangle + center dot
    if "BLK_MOC_KHAO_SAT" not in doc.blocks:
        b = doc.blocks.new(name="BLK_MOC_KHAO_SAT")
        b.add_lwpolyline([(0, 0.45), (-0.4, -0.3), (0.4, -0.3)], close=True, dxfattribs={"color": 1})
        b.add_circle((0, 0), radius=0.06, dxfattribs={"color": 1})


def _import_external_blocks(target_doc: Any, library_dxf_path: str | Path | None) -> list[str]:
    """Import custom block definitions from a user's external DWG/DXF library into target_doc."""
    imported: list[str] = []
    if not library_dxf_path or not str(library_dxf_path).strip():
        return imported
    lib_path = Path(str(library_dxf_path).strip().strip('"')).expanduser()
    if not lib_path.is_file() or lib_path.suffix.lower() not in {".dxf", ".dwg"}:
        return imported
    try:
        if lib_path.suffix.lower() == ".dwg":
            from uav_app.infrastructure.dwg_io import convert_dwg_to_dxf

            lib_path = convert_dwg_to_dxf(lib_path)
        from ezdxf.addons import Importer
        src_doc = ezdxf.readfile(str(lib_path))
        importer = Importer(src_doc, target_doc)
        names = [
            blk.name
            for blk in src_doc.blocks
            if not blk.name.startswith("*") and blk.name not in target_doc.blocks
        ]
        if names:
            importer.import_blocks(names)
            importer.finalize()
            imported.extend(names)
    except Exception:
        pass
    return imported


def _offset_segment(p1: tuple[float, float], p2: tuple[float, float], half_w: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return [p1, p2], [p1, p2]
    nx = -dy / length * half_w
    ny = dx / length * half_w
    left_line = [(p1[0] + nx, p1[1] + ny), (p2[0] + nx, p2[1] + ny)]
    right_line = [(p1[0] - nx, p1[1] - ny), (p2[0] - nx, p2[1] - ny)]
    return left_line, right_line


def _offset_polyline(pts: list[tuple[float, float]], half_w: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Compute left and right parallel offset polylines for a multi-vertex survey centerline."""
    if len(pts) < 2:
        return pts, pts
    if len(pts) == 2:
        return _offset_segment(pts[0], pts[1], half_w)

    left_pts: list[tuple[float, float]] = []
    right_pts: list[tuple[float, float]] = []
    n = len(pts)
    for i in range(n):
        if i == 0:
            dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        elif i == n - 1:
            dx, dy = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
        else:
            dx1, dy1 = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
            l1 = math.hypot(dx1, dy1) or 1.0
            dx2, dy2 = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
            l2 = math.hypot(dx2, dy2) or 1.0
            dx, dy = dx1 / l1 + dx2 / l2, dy1 / l1 + dy2 / l2
        length = math.hypot(dx, dy) or 1.0
        nx = -dy / length * half_w
        ny = dx / length * half_w
        left_pts.append((pts[i][0] + nx, pts[i][1] + ny))
        right_pts.append((pts[i][0] - nx, pts[i][1] - ny))
    return left_pts, right_pts


def _principal_axis_from_corners(corners: list[list[float]]) -> tuple[tuple[float, float], tuple[float, float], float]:
    """Extract the principal axis (start, end) and minor width from a 4-corner bounding box."""
    if len(corners) < 4:
        return (0.0, 0.0), (1.0, 0.0), 1.0
    p0, p1, p2, p3 = [tuple(map(float, c[:2])) for c in corners[:4]]
    d01 = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    d12 = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if d01 >= d12:
        start = ((p0[0] + p3[0]) * 0.5, (p0[1] + p3[1]) * 0.5)
        end = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
        minor_w = max(0.2, d12)
    else:
        start = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)
        end = ((p3[0] + p2[0]) * 0.5, (p3[1] + p2[1]) * 0.5)
        minor_w = max(0.2, d01)
    return start, end, minor_w


def _match_rule_for_category(category: str, rules_by_cat: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cat_low = (category or "").strip().lower()
    if cat_low in rules_by_cat:
        return rules_by_cat[cat_low]
    if any(k in cat_low for k in ("masonry_ditch", "masonry ditch", "mương xây")):
        return rules_by_cat.get("masonry_ditch", rules_by_cat.get("ditch", DEFAULT_SURVEY_RULES[1]))
    if any(k in cat_low for k in ("pond", "lake", "water", "ao", "hồ")):
        return rules_by_cat.get("pond", DEFAULT_SURVEY_RULES[4])
    if any(k in cat_low for k in ("asphalt", "đường nhựa")):
        return rules_by_cat.get("asphalt_road", rules_by_cat.get("road", DEFAULT_SURVEY_RULES[2]))
    if any(k in cat_low for k in ("concrete", "bê tông")):
        return rules_by_cat.get("concrete_road", rules_by_cat.get("road", DEFAULT_SURVEY_RULES[2]))
    if any(k in cat_low for k in ("dirt", "unpaved", "đường đất")):
        return rules_by_cat.get("dirt_road", rules_by_cat.get("road", DEFAULT_SURVEY_RULES[2]))
    if any(k in cat_low for k in ("footpath", "walkway", "sidewalk", "đi bộ", "lối mòn")):
        return rules_by_cat.get("footpath", rules_by_cat.get("road", DEFAULT_SURVEY_RULES[2]))
    if any(k in cat_low for k in ("ditch", "canal", "channel", "mương", "kênh", "rãnh")):
        return rules_by_cat.get("ditch", DEFAULT_SURVEY_RULES[1])
    if any(k in cat_low for k in ("road", "street", "path", "highway", "đường")):
        return rules_by_cat.get("road", DEFAULT_SURVEY_RULES[2])
    if any(k in cat_low for k in ("bridge", "culvert", "cầu", "cống")):
        return rules_by_cat.get("bridge", DEFAULT_SURVEY_RULES[3])
    if any(k in cat_low for k in ("building", "house", "roof", "nhà", "công trình")):
        return rules_by_cat.get("building", DEFAULT_SURVEY_RULES[4])
    if any(k in cat_low for k in ("fence", "wall", "tường", "rào")):
        return rules_by_cat.get("fence", DEFAULT_SURVEY_RULES[5])
    if any(k in cat_low for k in ("pole", "cột điện", "trụ")):
        return rules_by_cat.get("electric pole", DEFAULT_SURVEY_RULES[6])
    return rules_by_cat.get("ornamental tree", DEFAULT_SURVEY_RULES[0])


def export_survey_plan(
    output_dir: Path,
    metadata: dict[str, Any],
    base: list[float],
    records: list[dict[str, Any]],
    survey_polylines: list[dict[str, Any]] | None = None,
    rules: list[dict[str, Any]] | None = None,
    library_dxf_path: str | Path | None = None,
    include_unreviewed: bool = True,
) -> dict[str, Any]:
    """Export a Topographic Survey Plan (`binh_do_khao_sat.dxf`) using CAD Blocks & Double-Line Corridors."""
    active_rules = rules if isinstance(rules, list) and rules else DEFAULT_SURVEY_RULES
    rules_by_cat = {str(r.get("category") or "").strip().lower(): r for r in active_rules}

    doc = ezdxf.new("R2010")
    factor = float(metadata.get("unit_to_metre") or 1.0)
    doc.units = 6 if abs(factor - 1.0) < 1e-9 else 0

    if "ARIAL" not in doc.styles:
        doc.styles.new("ARIAL", dxfattribs={"font": "arial.ttf"})
    if "Standard" in doc.styles:
        doc.styles.get("Standard").dxf.font = "arial.ttf"

    for lt_name, pattern in (
        ("DASHED", [0.6, 0.4, -0.2]),
        ("CENTER", [1.0, 0.6, -0.15, 0.1, -0.15]),
    ):
        if lt_name not in doc.linetypes:
            try:
                doc.linetypes.new(lt_name, dxfattribs={"description": lt_name, "pattern": pattern})
            except Exception:
                pass

    _ensure_builtin_blocks(doc)
    imported_blocks = _import_external_blocks(doc, library_dxf_path)

    def ensure_layer(name: str, color: int, linetype: str = "CONTINUOUS"):
        clean_name = (name or "KS_DEFAULT").strip() or "KS_DEFAULT"
        lt = (linetype or "CONTINUOUS").strip().upper()
        if lt not in doc.linetypes:
            lt = "CONTINUOUS"
        if clean_name not in doc.layers:
            doc.layers.new(clean_name, dxfattribs={"color": int(color or 7), "linetype": lt})

    for lyr_def in BUILTIN_SURVEY_LAYERS:
        ensure_layer(lyr_def["name"], lyr_def["color"], lyr_def["linetype"])
    for r in active_rules:
        ensure_layer(str(r.get("layer") or "KS_DEFAULT"), int(r.get("color") or 7), str(r.get("linetype") or "CONTINUOUS"))

    msp = doc.modelspace()
    transform = metadata["transform"]
    counts_by_type = {"BLOCK": 0, "DOUBLE_LINE": 0, "BRIDGE_SYMBOL": 0, "CLOSED_POLYLINE": 0}
    drawn_features = 0

    # 1. Process detected/reviewed records
    for rec in records:
        status = rec.get("review_status", "unreviewed")
        if status == "rejected":
            continue
        if not include_unreviewed and status == "unreviewed":
            continue

        box = rec.get("candidate_box") if status == "accepted_candidate" and rec.get("candidate_box") else rec["box"]
        spatial = spatial_box(box, transform, base)
        center = spatial["center_relative"]
        corners = spatial["corners_relative"]
        cat = str(rec.get("sub_class") or rec.get("category") or "ornamental tree")
        rule = _match_rule_for_category(cat, rules_by_cat)

        cad_type = str(rule.get("cad_type") or "BLOCK").upper()
        layer_name = str(rule.get("layer") or "KS_CAY_CANH")
        color_aci = int(rule.get("color") or 3)
        linetype_name = str(rule.get("linetype") or "CONTINUOUS")
        ensure_layer(layer_name, color_aci, linetype_name)

        if cad_type == "BLOCK":
            blk_name = str(rule.get("block_name") or "BLK_CAY_CANH").strip()
            if blk_name not in doc.blocks:
                blk_name = "BLK_CAY_CANH"
            scale_val = float(rule.get("scale") or 1.0)
            msp.add_blockref(
                blk_name,
                (center[0], center[1]),
                dxfattribs={
                    "layer": layer_name,
                    "xscale": scale_val,
                    "yscale": scale_val,
                    "zscale": scale_val,
                },
            )
            counts_by_type["BLOCK"] += 1
        elif cad_type == "DOUBLE_LINE":
            p_start, p_end, detected_w = _principal_axis_from_corners(corners)
            cfg_w = float(rule.get("width_m") or 0.0)
            corridor_w = cfg_w if cfg_w > 0 else detected_w
            left_pts, right_pts = _offset_segment(p_start, p_end, corridor_w * 0.5)
            msp.add_line(left_pts[0], left_pts[1], dxfattribs={"layer": layer_name, "color": color_aci})
            msp.add_line(right_pts[0], right_pts[1], dxfattribs={"layer": layer_name, "color": color_aci})
            if rule.get("centerline"):
                ensure_layer("KS_TIM_DUONG", 2, "CENTER")
                msp.add_line(p_start, p_end, dxfattribs={"layer": "KS_TIM_DUONG", "color": 2})
            counts_by_type["DOUBLE_LINE"] += 1
        elif cad_type == "BRIDGE_SYMBOL":
            blk_name = str(rule.get("block_name") or "BLK_CAU_CONG").strip()
            if blk_name not in doc.blocks:
                blk_name = "BLK_CAU_CONG"
            p_start, p_end, _ = _principal_axis_from_corners(corners)
            angle_deg = math.degrees(math.atan2(p_end[1] - p_start[1], p_end[0] - p_start[0]))
            scale_val = float(rule.get("scale") or 1.0)
            msp.add_blockref(
                blk_name,
                (center[0], center[1]),
                dxfattribs={
                    "layer": layer_name,
                    "rotation": angle_deg,
                    "xscale": scale_val,
                    "yscale": scale_val,
                },
            )
            counts_by_type["BRIDGE_SYMBOL"] += 1
        else:
            msp.add_lwpolyline(corners, close=True, dxfattribs={"layer": layer_name, "color": color_aci})
            counts_by_type["CLOSED_POLYLINE"] += 1

        drawn_features += 1

    # 2. Process user-drawn survey polylines (e.g. digitized ditches, roads, fences on the map)
    for item in survey_polylines or []:
        poly = item.get("polygon") or item.get("points") or []
        if len(poly) < 2:
            continue
        cat = str((item.get("categories") or [item.get("category") or "ditch"])[0])
        rule = _match_rule_for_category(cat, rules_by_cat)
        cad_type = str(rule.get("cad_type") or "DOUBLE_LINE").upper()
        layer_name = str(rule.get("layer") or "KS_MUONG_NUOC")
        color_aci = int(rule.get("color") or 4)
        linetype_name = str(rule.get("linetype") or "CONTINUOUS")
        ensure_layer(layer_name, color_aci, linetype_name)

        rel_pts: list[tuple[float, float]] = []
        for pt in poly:
            px, py = (pt[0], pt[1]) if isinstance(pt, (list, tuple)) else (pt.get("col", 0), pt.get("row", 0))
            sp = spatial_box([px, py, px + 1, py + 1], transform, base)
            rel_pts.append(tuple(sp["center_relative"]))

        if cad_type == "DOUBLE_LINE" and len(rel_pts) >= 2:
            corridor_w = max(0.2, float(rule.get("width_m") or 1.2))
            left_pts, right_pts = _offset_polyline(rel_pts, corridor_w * 0.5)
            msp.add_lwpolyline(left_pts, close=False, dxfattribs={"layer": layer_name, "color": color_aci})
            msp.add_lwpolyline(right_pts, close=False, dxfattribs={"layer": layer_name, "color": color_aci})
            if rule.get("centerline"):
                ensure_layer("KS_TIM_DUONG", 2, "CENTER")
                msp.add_lwpolyline(rel_pts, close=False, dxfattribs={"layer": "KS_TIM_DUONG", "color": 2})
            counts_by_type["DOUBLE_LINE"] += 1
            drawn_features += 1
        elif cad_type == "CLOSED_POLYLINE" and len(rel_pts) >= 3:
            msp.add_lwpolyline(rel_pts, close=True, dxfattribs={"layer": layer_name, "color": color_aci})
            counts_by_type["CLOSED_POLYLINE"] += 1
            drawn_features += 1

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dxf_file = out_dir / "binh_do_khao_sat.dxf"
    doc.saveas(dxf_file)

    summary = {
        "dxf_file": "binh_do_khao_sat.dxf",
        "dxf_path": str(dxf_file),
        "drawn_features": drawn_features,
        "counts_by_type": counts_by_type,
        "imported_blocks": imported_blocks,
        "rules_applied": len(active_rules),
        "message": (
            f"Đã xuất Bình đồ Khảo sát Địa hình ({drawn_features} đối tượng: "
            f"{counts_by_type['BLOCK']} Block, {counts_by_type['DOUBLE_LINE']} tuyến 2-Line song song, "
            f"{counts_by_type['BRIDGE_SYMBOL']} Cầu/Cống, {counts_by_type['CLOSED_POLYLINE']} Công trình) ra binh_do_khao_sat.dxf."
        ),
    }
    _write_json(out_dir / "survey_export_summary.json", summary)
    return summary
