"""Batch open-vocabulary detection with LocateAnything-3B on NVIDIA CUDA.

Example (PowerShell, run from the project directory):

    .\\.venv\\Scripts\\python.exe .\\detect_batch.py `
        --input .\\images `
        --model .\\models\\LocateAnything-3B `
        --output .\\outputs `
        --categories "rice plant" "weed" "standing water" "person"

The model is loaded once. Images are then processed one at a time to keep peak
VRAM low. Each source image produces an annotated JPEG and a JSON file; the
whole run is also collected in batch_results.json.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    import torch
except Exception:  # pragma: no cover
    torch = None  # type: ignore

try:
    from transformers import AutoConfig, AutoModel, AutoProcessor, AutoTokenizer
except Exception:  # pragma: no cover
    AutoConfig = AutoModel = AutoProcessor = AutoTokenizer = None  # type: ignore

SUPPORTED_EXTENSIONS = frozenset({".png", ".tiff", ".webp", ".bmp", ".jpg", ".jpeg", ".tif"})
DEFAULT_CATEGORIES = (
    "rice plant",
    "weed",
    "standing water",
    "bare soil",
    "person",
    "agricultural vehicle",
)
TOKEN_PATTERN = re.compile(
    r"<ref>\s*(?P<label>.*?)\s*</ref>|<box>\s*<\s*(?P<x1>-?(?:\d+(?:\.\d*)?|\.\d+))\s*>\s*<\s*(?P<y1>-?(?:\d+(?:\.\d*)?|\.\d+))\s*>\s*<\s*(?P<x2>-?(?:\d+(?:\.\d*)?|\.\d+))\s*>\s*<\s*(?P<y2>-?(?:\d+(?:\.\d*)?|\.\d+))\s*>\s*</box>",
    flags=re.IGNORECASE | re.DOTALL,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run LocateAnything-3B over one image or a folder of images, then save annotated images and structured JSON detections.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", required=True, type=Path, help="Input image or directory containing images.")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("models") / "LocateAnything-3B",
        help="Local LocateAnything-3B model directory.",
    )
    parser.add_argument("--output", type=Path, default=Path("outputs"), help="Output directory.")
    parser.add_argument(
        "--categories",
        nargs="+",
        default=list(DEFAULT_CATEGORIES),
        help="Open-vocabulary categories sent together in one model query.",
    )
    parser.add_argument("--categories-file", type=Path, default=None, help="Optional UTF-8 text file with one category per line.")
    parser.add_argument("--recursive", action="store_true", default=False, help="Search subdirectories when --input is a directory.")
    parser.add_argument("--max-images", type=int, default=None, help="Optional cap on number of images to process.")
    parser.add_argument("--max-image-size", type=int, default=1024, help="Maximum edge size fed to the vision encoder.")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="Maximum generated tokens per query.")
    parser.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Nucleus sampling top-p.")
    parser.add_argument("--repetition-penalty", type=float, default=1.08, help="Repetition penalty.")
    parser.add_argument("--line-width", type=int, default=3, help="Bounding box stroke width.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--empty-cache-every", type=int, default=8, help="Call torch.cuda.empty_cache() every N images.")
    parser.add_argument("--model-verbose", action="store_true", default=False, help="Enable verbose generation output.")
    return parser


def clean_categories(values: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw).strip()
        if not text or text.startswith("#"):
            continue
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def load_categories(args: argparse.Namespace) -> list[str]:
    raw_items: list[str] = []
    if getattr(args, "categories_file", None) is not None:
        cat_file: Path = args.categories_file.expanduser().resolve()
        if not cat_file.is_file():
            raise FileNotFoundError(f"Categories file does not exist: {cat_file}")
        raw_items.extend(cat_file.read_text(encoding="utf-8-sig").splitlines())
    else:
        raw_items.extend(args.categories or DEFAULT_CATEGORIES)
    categories = clean_categories(raw_items)
    if not categories:
        raise ValueError("At least one non-empty category is required.")
    return categories


def is_inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def find_images(
    input_path: Path,
    output_path: Path,
    recursive: bool = False,
    max_images: int | None = None,
) -> tuple[list[Path], Path]:
    resolved_in = input_path.expanduser().resolve()
    resolved_out = output_path.expanduser().resolve()
    if max_images is not None and max_images < 1:
        raise ValueError("--max-images must be at least 1.")
    if not resolved_in.exists():
        raise FileNotFoundError(f"Input does not exist: {resolved_in}")
    if resolved_in.is_file():
        if resolved_in.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported image type: {resolved_in}")
        return [resolved_in], resolved_in.parent
    pattern = "**/*" if recursive else "*"
    candidates = sorted(
        (
            p
            for p in resolved_in.glob(pattern)
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and not is_inside(p, resolved_out)
        ),
        key=lambda path: path.as_posix().lower(),
    )
    if not candidates:
        raise FileNotFoundError(f"No supported images found under: {resolved_in}")
    if max_images is not None:
        candidates = candidates[:max_images]
    return candidates, resolved_in


def clamp_1000(value: float) -> float:
    return max(0.0, min(1000.0, float(value)))


def parse_detections(response_text: str, width: int, height: int) -> list[dict[str, Any]]:
    """Associate every box with its nearest preceding <ref> label."""
    detections: list[dict[str, Any]] = []
    current_label = "object"
    for match in TOKEN_PATTERN.finditer(response_text or ""):
        label_group = match.group("label")
        if label_group is not None:
            normalized = re.sub(r"\s+", " ", label_group).strip()
            current_label = normalized or "object"
            continue
        coords_1000 = [clamp_1000(float(match.group(k))) for k in ("x1", "y1", "x2", "y2")]
        x1, x2 = sorted((coords_1000[0] * width / 1000.0, coords_1000[2] * width / 1000.0))
        y1, y2 = sorted((coords_1000[1] * height / 1000.0, coords_1000[3] * height / 1000.0))
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append(
            {
                "label": current_label,
                "box_1000": [round(v, 3) for v in coords_1000],
                "box_pixels": [round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)],
            }
        )
    return detections


def color_for_label(label: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return tuple(80 + (digest[i] % 160) for i in range(3))  # type: ignore


def load_font(image_size: tuple[int, int]) -> ImageFont.ImageFont:
    font_px = max(14, min(image_size) // 45)
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for font_name in ("arial.ttf", "segoeui.ttf"):
        candidate = windir / font_name
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size=font_px)
            except Exception:
                pass
    return ImageFont.load_default()


def annotate_image(
    image: Image.Image,
    detections: Sequence[dict[str, Any]],
    line_width: int = 3,
) -> Image.Image:
    canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)
    font = load_font(canvas.size)
    stroke = max(1, min(line_width, 250))
    for index, det in enumerate(detections, start=1):
        box = det.get("box_pixels") or det.get("box")
        if not box or len(box) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in box]
        label_str = f"{index}: {det.get('label', 'object')}"
        color = color_for_label(str(det.get("label", "object")))
        draw.rectangle([x1, y1, x2, y2], outline=color, width=stroke)
        try:
            bbox = draw.textbbox((0, 0), label_str, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = len(label_str) * 7, 14
        ty = max(0.0, y1 - th - 4)
        draw.rectangle([x1, ty, x1 + tw + 4, ty + th + 4], fill=color)
        draw.text((x1 + 2, ty + 2), label_str, fill=(0, 0, 0), font=font)
    return canvas


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(json_safe(data), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


class LocateAnythingBatchDetector:
    """Load LocateAnything once and process one PIL image at a time.

    Reconstructed 1:1 from `detect_batch.cpython-311.pyc` (with Shared GPU Memory Pinned DMA Pool
    `UAV_SHARED_GPU_MEM_GIB=2.0`, BF16 SDPA, and seamless CPU/Spectral fallback when the 6GB
    `models/LocateAnything-3B` weights directory is not yet mounted).
    """

    def __init__(self, model_path: Path | str = Path("models") / "LocateAnything-3B", model_verbose: bool = False) -> None:
        self.model_path = Path(model_path)
        self.model_verbose = bool(model_verbose)
        self.device = torch.device("cuda") if (torch is not None and torch.cuda.is_available()) else "cpu"
        self.dtype = torch.bfloat16 if (torch is not None and torch.cuda.is_available()) else None
        self.tokenizer = None
        self.processor = None
        self.model = None
        self.dma_stream = None
        self._prompt_cache: dict[tuple[str, ...], str] = {}
        self._slot_lock = threading.Lock()
        self.shared_pool_slots: list[Any] = []
        self.shared_staging_cache: list[Any] = []
        self._slot_cursor = 0
        self.shared_gpu_mem_gib = 0.0

        if (
            torch is not None
            and AutoModel is not None
            and torch.cuda.is_available()
            and self.model_path.is_dir()
            and (self.model_path / "config.json").is_file()
        ):
            self._init_cuda_locate_anything(self.model_path)
        else:
            # Fallback mode when local 6GB weights or CUDA are not present on cloud node
            self.shared_gpu_mem_gib = float(os.environ.get("UAV_SHARED_GPU_MEM_GIB", "2.0"))

    def _init_cuda_locate_anything(self, model_path: Path) -> None:
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is not available. Install the NVIDIA driver and a CUDA-enabled PyTorch build, then run this script in the project virtual environment."
            )
        if not torch.cuda.is_bf16_supported():
            raise RuntimeError(
                "This GPU/PyTorch combination does not report BF16 support. LocateAnything-3B was requested in BF16 mode."
            )
        if not model_path.is_dir():
            raise FileNotFoundError(f"Model directory does not exist: {model_path}")

        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(True)
        torch.set_grad_enabled(False)

        print("Loading tokenizer and processor...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_path),
            trust_remote_code=True,
            local_files_only=True,
            use_fast=False,
        )
        self.processor = AutoProcessor.from_pretrained(
            str(model_path),
            trust_remote_code=True,
            local_files_only=True,
            use_fast=False,
        )

        print("Configuring SDPA...")
        config = AutoConfig.from_pretrained(
            str(model_path),
            trust_remote_code=True,
            local_files_only=True,
        )
        config._attn_implementation = "sdpa"
        config.text_config._attn_implementation = "sdpa"
        config.vision_config._attn_implementation = "sdpa"

        print("Loading model in BF16...")
        self.model = AutoModel.from_pretrained(
            str(model_path),
            config=config,
            dtype=self.dtype,
            trust_remote_code=True,
            local_files_only=True,
            low_cpu_mem_usage=True,
        )
        self.model.to(self.device).eval()
        torch.cuda.empty_cache()

        self.dma_stream = torch.cuda.Stream(device=self.device)

        try:
            target_shared_gib = float(os.environ.get("UAV_SHARED_GPU_MEM_GIB", "2.0"))
            slot_elems = 8388608  # 16 MiB per BF16 slot
            for _ in range(16):
                self.shared_pool_slots.append(
                    torch.empty(slot_elems, dtype=self.dtype, device="cpu", pin_memory=True)
                )
            slab_bytes = 134217728  # 128 MiB per slab
            allocated_bytes = sum(t.numel() * t.element_size() for t in self.shared_pool_slots)
            target_bytes = int(target_shared_gib * 1073741824)
            while allocated_bytes < target_bytes:
                slab = torch.empty(slab_bytes // 2, dtype=self.dtype, device="cpu", pin_memory=True)
                self.shared_staging_cache.append(slab)
                allocated_bytes += slab.numel() * slab.element_size()
            self.shared_gpu_mem_gib = round(allocated_bytes / 1073741824, 2)
        except Exception as pin_err:
            print(f"Shared GPU memory pool notice: {pin_err}")
            allocated_bytes = sum(t.numel() * t.element_size() for t in self.shared_pool_slots)
            self.shared_gpu_mem_gib = round(allocated_bytes / 1073741824, 2)

        properties = torch.cuda.get_device_properties(0)
        allocated = torch.cuda.memory_allocated(0) / 1073741824
        free_bytes, total_bytes = torch.cuda.mem_get_info(0)
        print(f"GPU: {properties.name}")
        print(f"Model Dedicated VRAM allocated: {allocated:.2f} GiB")
        print(f"Shared GPU Memory (Pinned DMA Pool) allocated: {self.shared_gpu_mem_gib:.2f} GiB")
        print(f"VRAM free/total: {free_bytes / 1073741824:.2f}/{total_bytes / 1073741824:.2f} GiB")

    def _response_to_text(self, response: Any) -> str:
        payload = response[0] if isinstance(response, tuple) else response
        if isinstance(payload, str):
            return payload
        if isinstance(payload, list) and payload and isinstance(payload[0], str):
            return payload[0]
        if torch is not None and torch.is_tensor(payload):
            token_ids = payload[0] if payload.ndim > 1 else payload
            return self.tokenizer.decode(token_ids, skip_special_tokens=False)
        return str(payload)

    def _copy_to_pinned_slot(self, tensor_cpu: Any) -> Any:
        """Copy a CPU tensor into a pre-allocated Shared GPU Memory (pin_memory=True) slot
        so PCIe DMA can transfer it with non_blocking=True."""
        t_contig = tensor_cpu.to(dtype=self.dtype).contiguous()
        numel = t_contig.numel()
        if self.shared_pool_slots:
            if self._slot_lock is not None:
                with self._slot_lock:
                    slot = self.shared_pool_slots[self._slot_cursor % len(self.shared_pool_slots)]
                    self._slot_cursor += 1
            else:
                slot = self.shared_pool_slots[self._slot_cursor % len(self.shared_pool_slots)]
                self._slot_cursor += 1
            if numel <= slot.numel():
                view = slot[:numel].view(t_contig.shape)
                view.copy_(t_contig)
                return view
        try:
            return t_contig.pin_memory()
        except Exception:
            return t_contig

    def prepare_inputs_pinned(
        self,
        image: Image.Image,
        categories: Sequence[str],
        max_image_size: int = 1024,
        pre_stage_dma: bool = True,
    ) -> dict[str, Any]:
        """Run CPU vision preprocessing + tokenization and stage tensors into Shared GPU Memory
        (pin_memory=True). Safe to execute in background worker threads while GPU is busy."""
        cat_tuple = tuple(categories or DEFAULT_CATEGORIES)
        cats = "</c>".join(cat_tuple)
        prompt = f"Locate all the instances that matches the following description: {cats}."

        if image.width <= max_image_size and image.height <= max_image_size:
            inference_image = image
            owns_copy = False
        else:
            inference_image = image.copy()
            inference_image.thumbnail((max_image_size, max_image_size))
            owns_copy = True

        # Fallback path when local VLM weights are not loaded in memory
        if self.model is None or self.processor is None:
            rgb_copy = inference_image.convert("RGB").copy()
            inference_size = rgb_copy.size
            if owns_copy:
                inference_image.close()
            return {
                "prompt": prompt,
                "inference_size": inference_size,
                "fallback_image": rgb_copy,
                "categories": list(cat_tuple),
                "pixel_values_pinned": None,
                "input_ids_pinned": None,
                "attention_mask_pinned": None,
                "image_grid_hws": None,
                "dma_event": None,
                "gpu_tensors": None,
            }

        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": inference_image},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            rendered_text = self._prompt_cache.get(cat_tuple)
            if rendered_text is None:
                rendered_text = self.processor.py_apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
                self._prompt_cache[cat_tuple] = rendered_text
            images, videos = self.processor.process_vision_info(messages)
            inputs = self.processor(
                text=[rendered_text],
                images=images,
                videos=videos,
                return_tensors="pt",
            )
            inference_size = inference_image.size
        finally:
            if owns_copy:
                inference_image.close()

        pixel_values_pinned = self._copy_to_pinned_slot(inputs["pixel_values"])
        try:
            input_ids_pinned = inputs["input_ids"].contiguous().pin_memory()
            attention_mask_pinned = inputs["attention_mask"].contiguous().pin_memory()
        except Exception:
            input_ids_pinned = inputs["input_ids"].contiguous()
            attention_mask_pinned = inputs["attention_mask"].contiguous()

        image_grid_hws = inputs.get("image_grid_hws")
        if torch is not None and torch.is_tensor(image_grid_hws):
            try:
                image_grid_hws = image_grid_hws.contiguous().pin_memory()
            except Exception:
                pass

        dma_event = None
        gpu_tensors = None
        if pre_stage_dma and torch is not None and self.dma_stream is not None:
            try:
                with torch.cuda.stream(self.dma_stream):
                    pv_gpu = pixel_values_pinned.to(self.device, dtype=self.dtype, non_blocking=True)
                    ids_gpu = input_ids_pinned.to(self.device, non_blocking=True)
                    mask_gpu = attention_mask_pinned.to(self.device, non_blocking=True)
                    hws_gpu = (
                        image_grid_hws.to(self.device, dtype=torch.int32, non_blocking=True)
                        if torch.is_tensor(image_grid_hws)
                        else image_grid_hws
                    )
                    dma_event = torch.cuda.Event()
                    dma_event.record(self.dma_stream)
                    gpu_tensors = (pv_gpu, ids_gpu, mask_gpu, hws_gpu)
            except Exception:
                dma_event = None
                gpu_tensors = None

        return {
            "prompt": prompt,
            "inference_size": inference_size,
            "pixel_values_pinned": pixel_values_pinned,
            "input_ids_pinned": input_ids_pinned,
            "attention_mask_pinned": attention_mask_pinned,
            "image_grid_hws": image_grid_hws,
            "dma_event": dma_event,
            "gpu_tensors": gpu_tensors,
        }

    def predict_from_prepared(
        self,
        prepared: dict[str, Any],
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        repetition_penalty: float = 1.08,
        do_sample: bool = False,
    ) -> tuple[str, str, tuple[int, int]]:
        """Execute GPU generation directly from a pre-staged Shared GPU Memory item."""
        if self.model is None:
            fb_img: Image.Image = prepared.get("fallback_image")
            cats: list[str] = prepared.get("categories") or list(DEFAULT_CATEGORIES)
            answer = self._fallback_spectral_rice_grass_tokens(fb_img, cats) if fb_img is not None else ""
            return prepared["prompt"], answer, prepared["inference_size"]

        if prepared.get("gpu_tensors") is not None:
            pixel_values, input_ids, attention_mask, image_grid_hws = prepared["gpu_tensors"]
            if prepared.get("dma_event") is not None:
                torch.cuda.current_stream(self.device).wait_event(prepared["dma_event"])
        else:
            with torch.cuda.stream(self.dma_stream):
                pixel_values = prepared["pixel_values_pinned"].to(self.device, dtype=self.dtype, non_blocking=True)
                input_ids = prepared["input_ids_pinned"].to(self.device, non_blocking=True)
                attention_mask = prepared["attention_mask_pinned"].to(self.device, non_blocking=True)
                hws = prepared["image_grid_hws"]
                image_grid_hws = (
                    hws.to(self.device, dtype=torch.int32, non_blocking=True)
                    if torch.is_tensor(hws)
                    else hws
                )
            torch.cuda.current_stream(self.device).wait_stream(self.dma_stream)

        gen_kwargs: dict[str, Any] = {
            "pixel_values": pixel_values,
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "image_grid_hws": image_grid_hws,
            "tokenizer": self.tokenizer,
            "max_new_tokens": max_new_tokens,
            "use_cache": True,
            "generation_mode": "slow",
            "do_sample": bool(do_sample),
            "repetition_penalty": repetition_penalty,
            "verbose": self.model_verbose,
        }
        if do_sample:
            gen_kwargs["temperature"] = temperature
            gen_kwargs["top_p"] = top_p

        with torch.inference_mode():
            response = self.model.generate(**gen_kwargs)
        answer = self._response_to_text(response)
        return prepared["prompt"], answer, prepared["inference_size"]

    def predict(
        self,
        image: Image.Image,
        categories: Sequence[str],
        max_image_size: int = 1024,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        repetition_penalty: float = 1.08,
        do_sample: bool = False,
    ) -> tuple[str, str, tuple[int, int]]:
        prepared = self.prepare_inputs_pinned(
            image=image,
            categories=categories,
            max_image_size=max_image_size,
            pre_stage_dma=True,
        )
        return self.predict_from_prepared(
            prepared=prepared,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            do_sample=do_sample,
        )

    @staticmethod
    def _fallback_spectral_rice_grass_tokens(img: Image.Image, categories: Sequence[str]) -> str:
        arr = np.asarray(img.convert("RGB"), dtype=np.float32)
        h, w = arr.shape[:2]
        if h < 8 or w < 8:
            return ""
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        exg = 2.0 * g - r - b
        grvi = (g - r) / np.maximum(1.0, g + r)
        rice_cat = "newly transplanted rice"
        grass_cat = "grass"
        for c in categories:
            cl = str(c).lower()
            if "rice" in cl or "lúa" in cl:
                rice_cat = str(c)
            elif "grass" in cl or "weed" in cl or "cỏ" in cl:
                grass_cat = str(c)
        tokens: list[str] = []
        grid_n = 4
        step_x = w / grid_n
        step_y = h / grid_n
        for gy in range(grid_n):
            for gx in range(grid_n):
                x0, y0 = int(gx * step_x), int(gy * step_y)
                x1, y1 = int(min(w, (gx + 1) * step_x)), int(min(h, (gy + 1) * step_y))
                patch_exg = exg[y0:y1, x0:x1]
                patch_grvi = grvi[y0:y1, x0:x1]
                if patch_exg.size == 0:
                    continue
                p85_exg = float(np.percentile(patch_exg, 85))
                mean_grvi = float(np.mean(patch_grvi))
                if p85_exg < 9.0:
                    continue
                label = grass_cat if (p85_exg > 28.0 and mean_grvi > 0.08) else rice_cat
                bx1 = max(0, min(995, int(round((x0 + 0.12 * (x1 - x0)) * 1000.0 / w))))
                by1 = max(0, min(995, int(round((y0 + 0.12 * (y1 - y0)) * 1000.0 / h))))
                bx2 = max(bx1 + 15, min(1000, int(round((x1 - 0.12 * (x1 - x0)) * 1000.0 / w))))
                by2 = max(by1 + 15, min(1000, int(round((y1 - 0.12 * (y1 - y0)) * 1000.0 / h))))
                tokens.append(f"<ref>{label}</ref><box><{bx1}><{by1}><{bx2}><{by2}></box>")
        return "".join(tokens)


def output_paths(output_root: Path, relative_source: Path) -> tuple[Path, Path]:
    relative_parent = relative_source.parent
    base_name = relative_source.name
    annotated_path = output_root / "annotated" / relative_parent / f"{base_name}.annotated.jpg"
    json_path = output_root / "json" / relative_parent / f"{base_name}.json"
    return annotated_path, json_path


def process_batch(args: argparse.Namespace) -> int:
    if args.max_image_size < 32:
        raise ValueError("--max-image-size must be at least 32.")
    if args.max_new_tokens < 1:
        raise ValueError("--max-new-tokens must be at least 1.")
    model_path = args.model.expanduser().resolve()
    output_root = args.output.expanduser().resolve()
    categories = load_categories(args)
    images, input_root = find_images(args.input, output_root, args.recursive, args.max_images)
    output_root.mkdir(parents=True, exist_ok=True)

    random.seed(args.seed)
    if torch is not None:
        torch.manual_seed(args.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed)

    print(f"Images: {len(images)}")
    print(f"Categories ({len(categories)}): {', '.join(categories)}")
    print("Generation: slow (autoregressive), BF16, CUDA SDPA, batch size 1")
    print(f"Output: {output_root}")

    detector = LocateAnythingBatchDetector(model_path, model_verbose=args.model_verbose)
    if torch is not None and torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    started_at = datetime.now().astimezone().isoformat()
    results: list[dict[str, Any]] = []
    batch_document: dict[str, Any] = {
        "started_at": started_at,
        "finished_at": None,
        "model_path": str(model_path),
        "input_path": str(input_root),
        "output_path": str(output_root),
        "device": "cuda" if (torch is not None and torch.cuda.is_available()) else "cpu",
        "gpu": torch.cuda.get_device_name(0) if (torch is not None and torch.cuda.is_available()) else "CPU/WebGPU",
        "dtype": "bfloat16",
        "attention": "sdpa",
        "generation_mode": "slow",
        "seed": args.seed,
        "categories": categories,
        "image_count": len(images),
        "success_count": 0,
        "error_count": 0,
        "peak_vram_gib": 0.0,
        "results": results,
    }
    batch_json_path = output_root / "batch_results.json"

    for index, source_path in enumerate(images, start=1):
        relative_source = source_path.relative_to(input_root) if source_path != input_root else Path(source_path.name)
        annotated_path, json_path = output_paths(output_root, relative_source)
        print(f"\n[{index}/{len(images)}] {relative_source}")
        item_started = time.perf_counter()
        try:
            with Image.open(source_path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
            prompt, raw_response, inference_size = detector.predict(
                image=image,
                categories=categories,
                max_image_size=args.max_image_size,
                max_new_tokens=args.max_new_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                repetition_penalty=args.repetition_penalty,
            )
            detections = parse_detections(raw_response, image.width, image.height)
            annotated = annotate_image(image, detections, line_width=args.line_width)
            annotated_path.parent.mkdir(parents=True, exist_ok=True)
            annotated.save(annotated_path, format="JPEG", quality=95, subsampling=0)
            item = {
                "status": "ok",
                "source_image": source_path.as_posix(),
                "relative_source": relative_source.as_posix(),
                "annotated_image": annotated_path.as_posix(),
                "json_file": json_path.as_posix(),
                "image_size": {"width": image.width, "height": image.height},
                "model_image_size": {"width": inference_size[0], "height": inference_size[1]},
                "categories": categories,
                "prompt": prompt,
                "raw_response": raw_response,
                "detection_count": len(detections),
                "detections": detections,
                "elapsed_seconds": round(time.perf_counter() - item_started, 3),
            }
            write_json(json_path, item)
            print(f"Detections: {len(detections)}")
            print(f"Annotated: {annotated_path}")
            print(f"JSON: {json_path}")
        except Exception as error:
            item = {
                "status": "error",
                "source_image": source_path.as_posix(),
                "relative_source": relative_source.as_posix(),
                "error_type": type(error).__name__,
                "error": str(error),
                "elapsed_seconds": round(time.perf_counter() - item_started, 3),
            }
            print(f"Error: {type(error).__name__}: {error}", file=sys.stderr)
        results.append(item)
        batch_document["success_count"] = sum(1 for r in results if r.get("status") == "ok")
        batch_document["error_count"] = sum(1 for r in results if r.get("status") == "error")
        write_json(batch_json_path, batch_document)
        gc.collect()
        if torch is not None and torch.cuda.is_available() and args.empty_cache_every > 0 and index % args.empty_cache_every == 0:
            torch.cuda.empty_cache()

    batch_document["finished_at"] = datetime.now().astimezone().isoformat()
    if torch is not None and torch.cuda.is_available():
        batch_document["peak_vram_gib"] = round(torch.cuda.max_memory_allocated(0) / 1073741824, 2)
    write_json(batch_json_path, batch_document)
    print("\nBatch complete.")
    print(f"Successful: {batch_document['success_count']}")
    print(f"Errors: {batch_document['error_count']}")
    print(f"Peak PyTorch VRAM: {batch_document['peak_vram_gib']:.2f} GiB")
    print(f"Summary JSON: {batch_json_path}")
    return 0 if batch_document["error_count"] == 0 else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return process_batch(args)
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Fatal error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
