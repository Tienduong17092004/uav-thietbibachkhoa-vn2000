"""Utility to render LocateAnything-3B + DEM Rice/Grass bounding boxes onto UAV Orthomosaic images (`draw_boxes.py`)."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw


CLASS_COLORS = {
    "newly transplanted rice": "#fa3253",
    "newly_transplanted_rice": "#fa3253",
    "grass": "#0284c7",
    "rice_partial_grass": "#d97706",
}


def draw_detections_on_image(image_path: str | Path, records: list[dict], output_path: str | Path) -> str:
    with Image.open(image_path) as src:
        canvas = src.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    for rec in records:
        if rec.get("status") == "rejected":
            continue
        box = rec.get("candidate_box") or rec.get("box")
        if not box or len(box) != 4:
            continue
        sub_cls = (rec.get("sub_class") or rec.get("category") or "newly transplanted rice").lower()
        color = CLASS_COLORS.get(sub_cls, "#10b981")
        x1, y1, x2, y2 = [float(v) for v in box]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return str(out)
