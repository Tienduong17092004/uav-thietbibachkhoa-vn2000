"""Single-window CLI entry point for LocateAnything-3B UAV detection (`detect.py`)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from PIL import Image

from detect_batch import LocateAnythingBatchDetector
from uav_app.domain.detection import parse_boxes


def run_single_detection(image_path: str | Path, categories: list[str], model_dir: str | Path = "models/LocateAnything-3B") -> dict:
    detector = LocateAnythingBatchDetector(model_dir)
    with Image.open(image_path) as src:
        img = src.convert("RGB")
        prepared = detector.prepare_inputs_pinned(img, categories=categories, max_image_size=1024)
        prompt, text, size = detector.predict_from_prepared(prepared)
        boxes = parse_boxes(text, img.width, img.height, categories)
    return {
        "image": str(image_path),
        "prompt": prompt,
        "raw_text": text,
        "count": len(boxes),
        "detections": boxes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LocateAnything-3B on a single UAV image/tile.")
    parser.add_argument("image", help="Path to UAV image or tile")
    parser.add_argument("--category", action="append", default=["newly transplanted rice", "grass"])
    args = parser.parse_args()
    print(json.dumps(run_single_detection(args.image, args.category), indent=2, ensure_ascii=False))
