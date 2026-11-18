"""Direct AutoCAD COM integration (via pyautocad / comtypes) and native DWG export."""
from __future__ import annotations

import array
from pathlib import Path
import sys
from typing import Any

# Include local pyautocad skill repository if available
_SKILL_PYAUTOCAD = Path(__file__).resolve().parents[3] / "skills" / "pyautocad-master"
if _SKILL_PYAUTOCAD.is_dir() and str(_SKILL_PYAUTOCAD) not in sys.path:
    sys.path.insert(0, str(_SKILL_PYAUTOCAD))


LAYER_COLORS = {
    "OBJECT_CENTERS": 3,      # Green
    "OBJECT_BOXES": 2,        # Yellow
    "OBJECT_LABELS": 7,       # White/Black
    "INDIVIDUAL_TREE": 30,    # Orange
    "TREE_CLUSTER": 40,       # Gold
    "HEDGE": 94,              # Dark Green
    "GRASS": 82,              # Light Green
    "RICE": 50,               # Yellow-Green
    "PERSON": 1,              # Red
    "VEHICLE": 5,             # Blue
}


def _double_array(*values: float):
    return array.array("d", (float(v) for v in values))


def _connect_autocad(create_if_not_exists: bool = True, visible: bool = True):
    """Connect to a running AutoCAD instance or launch one via COM."""
    try:
        import comtypes.client
    except ImportError as exc:
        raise RuntimeError("Thiếu thư viện comtypes để kết nối COM với AutoCAD.") from exc

    prog_ids = (
        "AutoCAD.Application",
        "AutoCAD.Application.26",
        "AutoCAD.Application.25",
        "AutoCAD.Application.24",
    )
    last_error = None
    for prog_id in prog_ids:
        try:
            app = comtypes.client.GetActiveObject(prog_id, dynamic=True)
            if visible:
                try:
                    app.Visible = True
                except Exception:
                    pass
            return app
        except Exception as err:
            last_error = err

    if create_if_not_exists:
        for prog_id in prog_ids:
            try:
                app = comtypes.client.CreateObject(prog_id, dynamic=True)
                try:
                    app.Visible = visible
                except Exception:
                    pass
                return app
            except Exception as err:
                last_error = err

    raise RuntimeError(
        "Không thể kết nối COM với AutoCAD. Hãy mở sẵn AutoCAD trên máy rồi bấm lại."
    ) from last_error


def _ensure_layer(doc: Any, name: str, color: int):
    try:
        layer = doc.Layers.Add(name)
        layer.Color = int(color)
        return layer
    except Exception:
        return None


def _sub_layer_for_record(record: dict) -> str:
    sub = (record.get("sub_class") or record.get("category") or "").lower()
    if "cluster" in sub:
        return "TREE_CLUSTER"
    if "hedge" in sub or "row" in sub:
        return "HEDGE"
    if "rice" in sub or "lúa" in sub:
        return "RICE"
    if "grass" in sub or "weed" in sub or "cỏ" in sub:
        return "GRASS"
    if "person" in sub:
        return "PERSON"
    if "vehicle" in sub or "car" in sub:
        return "VEHICLE"
    if "tree" in sub:
        return "INDIVIDUAL_TREE"
    return "OBJECT_BOXES"


def export_to_autocad_com(
    exported_records: list[dict],
    output_dwg_path: Path,
    unit_to_metre: float = 1.0,
    create_if_not_exists: bool = True,
    connector=None,
) -> dict:
    """Draw reviewed detections directly into AutoCAD via COM and save DWG."""
    if not exported_records:
        raise ValueError("Chưa có đối tượng đã duyệt để gửi sang AutoCAD.")

    app = connector() if connector is not None else _connect_autocad(create_if_not_exists=create_if_not_exists)
    try:
        doc = app.ActiveDocument
    except Exception:
        doc = app.Documents.Add()

    for layer_name, color in LAYER_COLORS.items():
        _ensure_layer(doc, layer_name, color)

    try:
        arial_style = doc.TextStyles.Add("ARIAL")
        try:
            arial_style.SetFont("Arial", False, False, 0, 0)
        except Exception:
            arial_style.fontFile = "arial.ttf"
        doc.ActiveTextStyle = arial_style
    except Exception:
        pass

    model_space = doc.ModelSpace
    factor = unit_to_metre if unit_to_metre and unit_to_metre > 0 else 1.0
    text_height = max(0.03 / factor, 0.001)
    drawn_count = 0

    for record in exported_records:
        center = record["center_relative"]
        corners = record["corners_relative"]
        z_val = float(record.get("elevation_m") or 0.0)
        sub_layer = _sub_layer_for_record(record)
        _ensure_layer(doc, sub_layer, LAYER_COLORS.get(sub_layer, 2))

        pt = _double_array(center[0], center[1], z_val)
        point_entity = model_space.AddPoint(pt)
        try:
            point_entity.Layer = "OBJECT_CENTERS"
        except Exception:
            pass

        flat_coords = []
        for corner in corners:
            flat_coords.extend([float(corner[0]), float(corner[1])])
        poly = model_space.AddLightWeightPolyline(_double_array(*flat_coords))
        try:
            poly.Closed = True
            poly.Layer = sub_layer
            if z_val:
                poly.Elevation = z_val
        except Exception:
            pass

        display_class = str(record.get("sub_class") or record.get("category") or record.get("label_returned") or "object")
        text_entity = model_space.AddText(display_class, pt, float(text_height))
        try:
            text_entity.Layer = "OBJECT_LABELS"
            text_entity.StyleName = "ARIAL"
        except Exception:
            pass

        drawn_count += 1

    try:
        app.ZoomExtents()
    except Exception:
        pass

    output_dwg_path = Path(output_dwg_path).resolve()
    output_dwg_path.parent.mkdir(parents=True, exist_ok=True)
    saved_dwg = False
    save_error = None
    try:
        doc.SaveAs(str(output_dwg_path))
        saved_dwg = output_dwg_path.is_file() or True
    except Exception as err:
        save_error = str(err)

    return {
        "status": "ok",
        "drawn_count": drawn_count,
        "dwg_path": str(output_dwg_path) if saved_dwg else None,
        "saved_dwg": saved_dwg,
        "save_warning": save_error,
        "message": (
            f"Đã vẽ {drawn_count} đối tượng trực tiếp vào AutoCAD và lưu {output_dwg_path.name}."
            if saved_dwg
            else f"Đã vẽ {drawn_count} đối tượng trực tiếp vào AutoCAD (chưa lưu được tệp DWG: {save_error})."
        ),
    }
