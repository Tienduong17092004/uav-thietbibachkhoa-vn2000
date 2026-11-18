"""Isolated GPU worker for Stage 2 Turbo YOLO11 training & FP16 Batch=32 SharedMemory inference.
Runs inside the project's GPU .venv (PyTorch CUDA + Ultralytics + ONNX), isolated from Rasterio/GDAL."""
from __future__ import annotations

import json
from multiprocessing import shared_memory
from pathlib import Path
import shutil
import sys
import time


def emit(payload: dict) -> None:
    print("@UAV@" + json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)


def _run_train(job_json_path: Path) -> None:
    import torch
    from ultralytics import YOLO

    spec = json.loads(job_json_path.read_text(encoding="utf-8"))
    project_root = Path(spec["project_root"]).resolve()
    cancel_file = Path(spec["cancel_file"]) if spec.get("cancel_file") else None
    runs = spec.get("runs") or []
    device = 0 if torch.cuda.is_available() else "cpu"
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"

    models_cache_dir = project_root / "models" / "turbo_yolo"
    models_cache_dir.mkdir(parents=True, exist_ok=True)
    base_weights = models_cache_dir / str(spec.get("base_model") or "yolo11s.pt")

    emit({"event": "started", "gpu": gpu_name, "run_count": len(runs)})
    summary_results = {}

    for run_idx, run_cfg in enumerate(runs):
        if cancel_file and cancel_file.exists():
            emit({"event": "cancelled", "mode": run_cfg.get("mode")})
            return

        mode = str(run_cfg["mode"])
        data_yaml = Path(run_cfg["data_yaml"]).resolve()
        out_dir = Path(run_cfg["out_dir"]).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        epochs = int(run_cfg.get("epochs", 50))
        imgsz = int(run_cfg.get("imgsz", 640))
        batch = int(run_cfg.get("batch", 16))
        prev_best = out_dir / "best.pt"

        # Prefer continuing from local cached yolo11s.pt (or previous best if requested)
        init_weights = str(base_weights) if base_weights.is_file() else str(spec.get("base_model") or "yolo11s.pt")
        if run_cfg.get("resume_weights") and prev_best.is_file():
            init_weights = str(prev_best)

        model = YOLO(init_weights)
        # Cache downloaded base weights into models/turbo_yolo/yolo11s.pt if Ultralytics fetched it to cwd
        cwd_candidate = Path.cwd() / base_weights.name
        if not base_weights.is_file() and cwd_candidate.is_file():
            try:
                shutil.copy2(cwd_candidate, base_weights)
            except Exception:
                pass

        last_metrics: dict[str, float] = {}

        def _on_fit_epoch_end(trainer):
            nonlocal last_metrics
            if cancel_file and cancel_file.exists():
                trainer.stop = True
            ep = int(getattr(trainer, "epoch", 0)) + 1
            total_ep = int(getattr(trainer, "epochs", epochs))
            m_dict = getattr(trainer, "metrics", None) or {}
            map50 = float(m_dict.get("metrics/mAP50(B)", m_dict.get("metrics/mAP50", 0.0)) or 0.0)
            map50_95 = float(m_dict.get("metrics/mAP50-95(B)", m_dict.get("metrics/mAP50-95", 0.0)) or 0.0)
            prec = float(m_dict.get("metrics/precision(B)", m_dict.get("metrics/precision", 0.0)) or 0.0)
            rec = float(m_dict.get("metrics/recall(B)", m_dict.get("metrics/recall", 0.0)) or 0.0)
            tloss = getattr(trainer, "tloss", None)
            loss_val = 0.0
            if tloss is not None:
                try:
                    loss_val = float(tloss.sum().item() if hasattr(tloss, "sum") else float(tloss))
                except Exception:
                    loss_val = 0.0
            last_metrics = {
                "mAP50": round(map50, 4),
                "mAP50_95": round(map50_95, 4),
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "loss": round(loss_val, 4),
            }
            emit({
                "event": "epoch",
                "mode": mode,
                "run_index": run_idx,
                "run_count": len(runs),
                "epoch": ep,
                "epochs": total_ep,
                **last_metrics,
            })

        model.add_callback("on_fit_epoch_end", _on_fit_epoch_end)

        train_proj = out_dir / "train_runs"
        if train_proj.exists():
            shutil.rmtree(train_proj, ignore_errors=True)

        t0 = time.monotonic()
        model.train(
            data=str(data_yaml),
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            device=device,
            workers=0,  # Windows-safe deterministic fast DataLoader without multiprocessing spawn overhead
            amp=torch.cuda.is_available(),
            project=str(train_proj),
            name="exp",
            exist_ok=True,
            pretrained=True,
            mosaic=0.5 if mode == "clump" else 0.75,
            fliplr=0.5,
            flipud=0.5,
            degrees=15.0,
            patience=20,
            plots=False,
            verbose=False,
        )
        elapsed_s = round(time.monotonic() - t0, 1)

        if cancel_file and cancel_file.exists():
            emit({"event": "cancelled", "mode": mode})
            return

        weights_dir = train_proj / "exp" / "weights"
        produced_best = weights_dir / "best.pt"
        if not produced_best.is_file():
            produced_best = weights_dir / "last.pt"
        if not produced_best.is_file():
            raise RuntimeError(f"Không tìm thấy trọng số sau khi huấn luyện chế độ {mode}.")

        final_pt = out_dir / "best.pt"
        shutil.copy2(produced_best, final_pt)

        # Export ONNX (compatible with both ONNX Runtime and QGIS Deepness plugin)
        final_onnx = out_dir / "best.onnx"
        onnx_ok = False
        try:
            exp_model = YOLO(str(final_pt))
            exported_path = exp_model.export(
                format="onnx",
                imgsz=imgsz,
                opset=17,
                simplify=False,
                dynamic=False,
            )
            if exported_path and Path(exported_path).is_file():
                if Path(exported_path).resolve() != final_onnx.resolve():
                    shutil.copy2(exported_path, final_onnx)
                onnx_ok = True
        except Exception as onnx_err:
            sys.stderr.write(f"ONNX export warning ({mode}): {onnx_err}\n")

        meta = {
            "mode": mode,
            "engine_name": "YOLO11s-FP16",
            "gpu": gpu_name,
            "imgsz": imgsz,
            "epochs": epochs,
            "elapsed_seconds": elapsed_s,
            "pt_path": str(final_pt),
            "onnx_path": str(final_onnx) if onnx_ok and final_onnx.is_file() else None,
            "classes": run_cfg.get("classes") or [],
            "dataset_stats": run_cfg.get("dataset_stats") or {},
            "metrics": last_metrics,
            "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (out_dir / "metrics.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        summary_results[mode] = meta

    emit({"event": "completed", "results": summary_results})


def _run_infer(project_root: Path, mode: str, shm_name: str, max_batch: int, tile_size: int) -> None:
    import numpy as np
    from PIL import Image
    import torch
    from ultralytics import YOLO

    weights_path = project_root / "models" / "turbo_yolo" / f"turbo_{mode}" / "best.pt"
    if not weights_path.is_file():
        raise FileNotFoundError(f"Chưa có mô hình đã huấn luyện tại {weights_path}.")

    use_cuda = torch.cuda.is_available()
    device = 0 if use_cuda else "cpu"
    use_half = bool(use_cuda)
    gpu_name = torch.cuda.get_device_name(0) if use_cuda else "CPU"

    meta_path = weights_path.parent / "metrics.json"
    imgsz = 640
    if meta_path.is_file():
        try:
            imgsz = int(json.loads(meta_path.read_text(encoding="utf-8")).get("imgsz") or 640)
        except Exception:
            imgsz = 640

    model = YOLO(str(weights_path))
    # Warmup FP16 Tensor Cores
    dummy = Image.fromarray(np.zeros((tile_size, tile_size, 3), dtype=np.uint8))
    model.predict([dummy], imgsz=imgsz, half=use_half, device=device, verbose=False)

    shm = shared_memory.SharedMemory(name=shm_name, create=False)
    shm_arr = np.ndarray((max_batch, tile_size, tile_size, 3), dtype=np.uint8, buffer=shm.buf)

    names_map = getattr(model, "names", {}) or {}
    if isinstance(names_map, list):
        names_map = {i: n for i, n in enumerate(names_map)}
    else:
        names_map = {int(k): str(v) for k, v in names_map.items()}

    emit({
        "status": "ready",
        "gpu": gpu_name,
        "mode": mode,
        "imgsz": imgsz,
        "fp16": use_half,
        "names": names_map,
    })

    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            req = json.loads(line)
            if req.get("command") == "close":
                break
            count = int(req["count"])
            shapes = req["shapes"]
            conf = float(req.get("conf", 0.25))
            iou = float(req.get("iou", 0.50))
            max_det = int(req.get("max_det", 1500 if mode == "clump" else 300))

            pil_batch = [
                Image.fromarray(shm_arr[i, : int(shapes[i][0]), : int(shapes[i][1]), :])
                for i in range(count)
            ]
            preds = model.predict(
                pil_batch,
                imgsz=imgsz,
                half=use_half,
                device=device,
                batch=max(1, count),
                conf=conf,
                iou=iou,
                max_det=max_det,
                verbose=False,
            )
            batch_out = []
            for pred in preds:
                b_obj = pred.boxes
                if b_obj is None or len(b_obj) == 0:
                    batch_out.append([])
                    continue
                xyxy = b_obj.xyxy.detach().cpu().tolist()
                confs = b_obj.conf.detach().cpu().tolist()
                clss = b_obj.cls.detach().cpu().tolist()
                items = []
                for box, sc, cid in zip(xyxy, confs, clss):
                    c_int = int(cid)
                    items.append({
                        "box": [round(float(v), 2) for v in box],
                        "score": round(float(sc), 4),
                        "class_id": c_int,
                        "label": names_map.get(c_int, f"class_{c_int}"),
                    })
                batch_out.append(items)
            emit({"status": "ok", "results": batch_out})
    finally:
        shm.close()


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("Usage: turbo_worker.py <train|infer> ...")
    cmd = sys.argv[1]
    if cmd == "train":
        _run_train(Path(sys.argv[2]).resolve())
    elif cmd == "infer":
        _run_infer(
            Path(sys.argv[2]).resolve(),
            str(sys.argv[3]),
            str(sys.argv[4]),
            int(sys.argv[5]),
            int(sys.argv[6]),
        )
    else:
        raise SystemExit(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
