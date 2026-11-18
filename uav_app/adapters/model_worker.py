"""Runs only with the existing model Python, isolated from Rasterio/OpenCV.
Uses an asynchronous Shared GPU Memory (pin_memory=True) preprocessor pipeline
and dedicated CUDA DMA stream so CPU tokenization/vision patching and PCIe DMA
transfers overlap 100% with GPU 3D inference."""
import json
from pathlib import Path
import queue
import sys
import threading


def emit(value):
    print("@UAV@" + json.dumps(value, ensure_ascii=True, allow_nan=False), flush=True)


def _prepare_request(request, detector, project, Image):
    options = request["options"]
    raw_cats = request.get("categories") or request.get("category") or []
    if isinstance(raw_cats, str):
        cats = [raw_cats]
    else:
        cats = [str(c) for c in raw_cats if str(c).strip()]
    pre_resized = bool(request.get("pre_resized", False))
    with Image.open(request["image"]) as source:
        image = source.convert("RGB")
        if not pre_resized and options.get("upscale", 1) > 1:
            sr_mode = options.get("sr_mode", "")
            if sr_mode in ("ttst", "ttst_4x", "deep_sr", "realesrgan", "swinir", "hat"):
                try:
                    from uav_app.infrastructure.pytorch_sr_runner import super_resolve_pil
                    image, _ = super_resolve_pil(image, project, outscale=options["upscale"], preferred_arch=sr_mode)
                except Exception:
                    image = image.resize(
                        (image.width * options["upscale"], image.height * options["upscale"]),
                        Image.Resampling.BILINEAR,
                    )
            else:
                target_w = min(options["max_image_size"], image.width * options["upscale"])
                target_h = min(options["max_image_size"], image.height * options["upscale"])
                if (target_w, target_h) != image.size:
                    image = image.resize((target_w, target_h), Image.Resampling.BILINEAR)
        eff_max_tokens = int(options.get("max_new_tokens", 512))
        if int(options.get("micro_size", 384)) <= 512:
            eff_max_tokens = min(eff_max_tokens, 512)
        prepared = detector.prepare_inputs_pinned(
            image=image,
            categories=cats,
            max_image_size=options["max_image_size"],
            pre_stage_dma=True,
        )
        image.close()
    return prepared, eff_max_tokens, request.get("req_id")


def main():
    project = Path(sys.argv[1]).resolve()
    app_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project))
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from detect_batch import LocateAnythingBatchDetector
    from PIL import Image
    import torch

    detector = LocateAnythingBatchDetector(project / "models" / "LocateAnything-3B")
    emit({
        "status": "ready",
        "gpu": torch.cuda.get_device_name(0),
        "shared_gpu_mem_gib": getattr(detector, "shared_gpu_mem_gib", 0.0),
    })

    # Queue of pre-tokenized, Shared-GPU-Memory-pinned items ready for immediate GPU execution
    gpu_ready_q: queue.Queue = queue.Queue(maxsize=8)

    def _stdin_prefetch_stage():
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except Exception as err:
                gpu_ready_q.put(("error", None, str(err), None))
                continue
            if request.get("command") == "close":
                gpu_ready_q.put(("close", None, None, None))
                break
            try:
                prepared, eff_max_tokens, req_id = _prepare_request(request, detector, project, Image)
                gpu_ready_q.put(("ok", prepared, eff_max_tokens, req_id))
            except Exception as err:
                gpu_ready_q.put(("error", None, str(err), request.get("req_id")))
        gpu_ready_q.put(("close", None, None, None))

    stage_thread = threading.Thread(target=_stdin_prefetch_stage, daemon=True)
    stage_thread.start()

    step_count = 0
    vram_soft_cap_bytes = int(9.2 * (1024**3))

    while True:
        kind, payload, meta, req_id = gpu_ready_q.get()
        if kind == "close":
            break
        if kind == "error":
            emit({"status": "error", "message": str(meta), "req_id": req_id})
            continue
        try:
            step_count += 1
            prompt, text, size = detector.predict_from_prepared(
                prepared=payload,
                max_new_tokens=int(meta),
                temperature=0.7,
                top_p=0.9,
                repetition_penalty=1.08,
                do_sample=False,
            )
            del payload
            if step_count % 16 == 0 or torch.cuda.memory_reserved() > vram_soft_cap_bytes:
                torch.cuda.empty_cache()
            emit(dict(
                status="ok",
                req_id=req_id,
                text=text,
                prompt=prompt,
                inference_size=list(size),
                peak_vram_gib=round(torch.cuda.max_memory_allocated() / 1024**3, 2),
                shared_gpu_mem_gib=getattr(detector, "shared_gpu_mem_gib", 0.0),
            ))
        except Exception as error:
            torch.cuda.empty_cache()
            emit({"status": "error", "message": str(error), "req_id": req_id})


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit({"status": "error", "message": str(error)})
        raise
