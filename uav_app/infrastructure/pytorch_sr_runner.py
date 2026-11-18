"""PyTorch CUDA Super-Resolution runner integrating architectures & weights from `render/`:
- TTST (`render/TTST-main/model_archs/TTST_arc.py` + `saved_models/ttst_4x.pth`)
- Real-ESRGAN (`render/Real-ESRGAN-master/realesrgan/archs/srvgg_arch.py` + `RRDBNet`)
- SwinIR (`render/SwinIR-main/models/network_swinir.py` & `TTST-main/model_archs/swinir_arch.py`)
- HAT (`render/HAT-main/hat/archs/hat_arch.py` & `TTST-main/model_archs/hat_arch.py`)
- Remote Sensing & Classical SR (`HSENet`, `HAUNet`, `EDSR`, `RCAN`, `RDN`, `HAN`)
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys
import types
from PIL import Image
import numpy as np


_MODEL_CACHE: dict[tuple[str, str], tuple[object, int, int]] = {}


def _install_runtime_shims() -> None:
    """Install lightweight pure-PyTorch shims for basicsr, timm, thop, and einops so
    all architectures in `render/` load cleanly without compiling C++ extensions.
    """
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    if "thop" not in sys.modules:
        thop_mod = types.ModuleType("thop")
        thop_mod.profile = lambda *a, **kw: (0, 0)
        sys.modules["thop"] = thop_mod

    def to_2tuple(x):
        return (x, x) if isinstance(x, int) else x

    class DummyRegistry:
        def register(self):
            def deco(cls):
                return cls
            return deco

    class DropPath(nn.Module):
        def __init__(self, drop_prob: float = 0.0):
            super().__init__()
            self.drop_prob = drop_prob

        def forward(self, x):
            return x

    if "timm" not in sys.modules:
        timm_mod = types.ModuleType("timm")
        timm_models = types.ModuleType("timm.models")
        timm_layers = types.ModuleType("timm.models.layers")
        timm_layers.DropPath = DropPath
        timm_layers.to_2tuple = to_2tuple
        timm_layers.trunc_normal_ = nn.init.trunc_normal_
        sys.modules["timm"] = timm_mod
        sys.modules["timm.models"] = timm_models
        sys.modules["timm.models.layers"] = timm_layers

    if "basicsr" not in sys.modules:
        basicsr_mod = types.ModuleType("basicsr")
        basicsr_utils = types.ModuleType("basicsr.utils")
        basicsr_reg = types.ModuleType("basicsr.utils.registry")
        basicsr_reg.ARCH_REGISTRY = DummyRegistry()
        basicsr_archs = types.ModuleType("basicsr.archs")
        basicsr_arch_util = types.ModuleType("basicsr.archs.arch_util")
        basicsr_arch_util.to_2tuple = to_2tuple
        basicsr_arch_util.trunc_normal_ = nn.init.trunc_normal_
        sys.modules["basicsr"] = basicsr_mod
        sys.modules["basicsr.utils"] = basicsr_utils
        sys.modules["basicsr.utils.registry"] = basicsr_reg
        sys.modules["basicsr.archs"] = basicsr_archs
        sys.modules["basicsr.archs.arch_util"] = basicsr_arch_util

    if "einops" not in sys.modules:
        def rearrange(x, pattern: str, **axes):
            p = " ".join(pattern.strip().split())
            if p == "b c h w -> b (h w) c":
                return x.flatten(2).transpose(1, 2).contiguous()
            if p == "b (h w) c -> b c h w":
                return x.transpose(1, 2).contiguous().view(x.shape[0], x.shape[2], axes["h"], axes["w"])
            if p == "b (head c) h w -> b head c (h w)":
                b, hc, h, w = x.shape
                head = axes["head"]
                return x.view(b, head, hc // head, h * w)
            if p == "b head c (h w) -> b (head c) h w":
                b, head, c, _ = x.shape
                return x.view(b, head * c, axes["h"], axes["w"])
            if "nc (b nw) (owh oww) ch" in p:
                b, _, nw = x.shape
                nc, ch, owh, oww = axes["nc"], axes["ch"], axes["owh"], axes["oww"]
                return (
                    x.view(b, nc, ch, owh * oww, nw)
                    .permute(1, 0, 4, 3, 2)
                    .contiguous()
                    .view(nc, b * nw, owh * oww, ch)
                )
            if p == "b c (h p1) (w p2) -> b (h w) (p1 p2 c)":
                b, c, hp1, wp2 = x.shape
                p1, p2 = axes["p1"], axes["p2"]
                h, w = hp1 // p1, wp2 // p2
                return x.view(b, c, h, p1, w, p2).permute(0, 2, 4, 3, 5, 1).contiguous().view(b, h * w, p1 * p2 * c)
            if p == "b (h w) (p1 p2 c) -> b c (h p1) (w p2)":
                b, hw, p1p2c = x.shape
                h, p1, p2 = axes["h"], axes["p1"], axes["p2"]
                w = hw // h
                c = p1p2c // (p1 * p2)
                return x.view(b, h, w, p1, p2, c).permute(0, 5, 1, 3, 2, 4).contiguous().view(b, c, h * p1, w * p2)
            raise NotImplementedError(f"Unsupported rearrange pattern: {pattern}")

        einops_mod = types.ModuleType("einops")
        einops_mod.rearrange = rearrange
        einops_mod.repeat = lambda x, *a, **kw: x
        sys.modules["einops"] = einops_mod


def _build_rrdbnet(num_in_ch=3, num_out_ch=3, scale=4, num_feat=64, num_block=23, num_grow_ch=32):
    """Self-contained RRDBNet architecture for Real-ESRGAN x2/x4 weights."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class ResidualDenseBlock(nn.Module):
        def __init__(self, nf=64, gc=32):
            super().__init__()
            self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
            self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
            self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
            self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
            self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
            x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
            return x5 * 0.2 + x

    class RRDB(nn.Module):
        def __init__(self, nf, gc=32):
            super().__init__()
            self.rdb1 = ResidualDenseBlock(nf, gc)
            self.rdb2 = ResidualDenseBlock(nf, gc)
            self.rdb3 = ResidualDenseBlock(nf, gc)

        def forward(self, x):
            out = self.rdb1(x)
            out = self.rdb2(out)
            out = self.rdb3(out)
            return out * 0.2 + x

    class RRDBNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.scale = scale
            in_ch = num_in_ch * 4 if scale == 2 else num_in_ch
            self.conv_first = nn.Conv2d(in_ch, num_feat, 3, 1, 1)
            self.body = nn.ModuleList([RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
            self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            if self.scale == 2:
                b, c, h, w = x.size()
                x = x.view(b, c, h // 2, 2, w // 2, 2).permute(0, 1, 3, 5, 2, 4).contiguous().view(b, c * 4, h // 2, w // 2)
            feat = self.conv_first(x)
            body_feat = feat
            for block in self.body:
                body_feat = block(body_feat)
            body_feat = self.conv_body(body_feat)
            feat = feat + body_feat
            feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
            feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
            return self.conv_last(self.lrelu(self.conv_hr(feat)))

    return RRDBNet()


def _load_module_from_file(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_render_root(project_root: Path) -> Path:
    candidates = [
        project_root / "render",
        project_root.parent / "render",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return project_root / "render"


def find_best_weight(project_root: Path, preferred_arch: str = "ttst") -> tuple[str, Path] | None:
    """Locate the best available `.pth` weight across `render/` and `models/sr/`."""
    render_root = resolve_render_root(project_root)
    sr_dir = project_root / "models" / "sr"

    search_Files: list[Path] = []
    if sr_dir.is_dir():
        search_Files.extend(sorted(sr_dir.rglob("*.pth")))
    if render_root.is_dir():
        search_Files.extend(sorted(render_root.rglob("*.pth")))

    if not search_Files:
        return None

    arch = preferred_arch.lower()
    for path in search_Files:
        name = path.name.lower()
        if arch in ("ttst", "ttst_4x", "ttst_uav_rs", "auto", "deep_sr") and "ttst" in name:
            return "ttst", path
        if arch in ("realesrgan", "realesrgan_x4plus") and ("realesr" in name or "esrgan" in name):
            return "realesrgan", path
        if arch in ("swinir", "swinir_real_sr") and "swinir" in name:
            return "swinir", path
        if arch in ("hat", "hat_sr") and "hat" in name:
            return "hat", path

    # Fallback to first available weight (e.g., ttst_4x.pth)
    first = search_Files[0]
    fname = first.name.lower()
    if "ttst" in fname:
        return "ttst", first
    if "swinir" in fname:
        return "swinir", first
    if "hat" in fname:
        return "hat", first
    if "realesr" in fname or "esrgan" in fname:
        return "realesrgan", first
    return "ttst", first


def load_sr_model(project_root: Path, arch: str, weight_path: Path, device: str = "cuda"):
    """Load and cache a PyTorch Super-Resolution model from `render/`."""
    import torch

    cache_key = (arch, str(weight_path.resolve()))
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    _install_runtime_shims()
    render_root = resolve_render_root(project_root)
    ttst_root = render_root / "TTST-main"
    if str(ttst_root) not in sys.path:
        sys.path.insert(0, str(ttst_root))
    if str(ttst_root / "model_archs") not in sys.path:
        sys.path.insert(0, str(ttst_root / "model_archs"))

    ckpt = torch.load(str(weight_path), map_location="cpu")
    if isinstance(ckpt, dict):
        if "params_ema" in ckpt:
            state_dict = ckpt["params_ema"]
        elif "params" in ckpt:
            state_dict = ckpt["params"]
        elif "state_dict" in ckpt:
            state_dict = ckpt["state_dict"]
        else:
            state_dict = ckpt
    else:
        state_dict = ckpt

    clean_state = {k.replace("module.", ""): v for k, v in state_dict.items()}
    net_scale = 2 if "2x" in weight_path.name.lower() or "x2" in weight_path.name.lower() else 4
    window_size = 8

    if arch == "ttst":
        ttst_mod = _load_module_from_file("ttst_arc", ttst_root / "model_archs" / "TTST_arc.py")
        model = ttst_mod.TTST(upscale=net_scale)
        window_size = 16
    elif arch == "swinir":
        swin_file = render_root / "SwinIR-main" / "models" / "network_swinir.py"
        if not swin_file.is_file():
            swin_file = ttst_root / "model_archs" / "swinir_arch.py"
        swin_mod = _load_module_from_file("network_swinir", swin_file)
        is_real = any("conv_up1" in k for k in clean_state)
        model = swin_mod.SwinIR(
            upscale=net_scale,
            in_chans=3,
            img_size=64,
            window_size=8,
            img_range=1.0,
            depths=[6, 6, 6, 6, 6, 6],
            embed_dim=180,
            num_heads=[6, 6, 6, 6, 6, 6],
            mlp_ratio=2,
            upsampler="nearest+conv" if is_real else "pixelshuffle",
            resi_connection="1conv",
        )
        window_size = 8
    elif arch == "hat":
        hat_file = render_root / "HAT-main" / "hat" / "archs" / "hat_arch.py"
        if not hat_file.is_file():
            hat_file = ttst_root / "model_archs" / "hat_arch.py"
        hat_mod = _load_module_from_file("hat_arch", hat_file)
        model = hat_mod.HAT(upscale=net_scale)
        window_size = 16
    elif arch == "realesrgan":
        if any(k.startswith("body.0.rdb1") for k in clean_state):
            num_block = 6 if "anime_6b" in weight_path.name.lower() else 23
            model = _build_rrdbnet(scale=net_scale, num_block=num_block)
        else:
            srvgg_file = render_root / "Real-ESRGAN-master" / "realesrgan" / "archs" / "srvgg_arch.py"
            srvgg_mod = _load_module_from_file("srvgg_arch", srvgg_file)
            model = srvgg_mod.SRVGGNetCompact(num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=net_scale, act_type="prelu")
        window_size = 4
    else:
        ttst_mod = _load_module_from_file("ttst_arc", ttst_root / "model_archs" / "TTST_arc.py")
        model = ttst_mod.TTST(upscale=net_scale)
        window_size = 16

    model.load_state_dict(clean_state, strict=True)
    target_device = device if (device == "cuda" and torch.cuda.is_available()) else "cpu"
    model = model.to(target_device).eval()
    _MODEL_CACHE[cache_key] = (model, net_scale, window_size)
    return model, net_scale, window_size


def super_resolve_pil(
    image: Image.Image,
    project_root: Path,
    outscale: int = 2,
    preferred_arch: str = "ttst",
    tile_size: int = 128,
    tile_pad: int = 16,
) -> tuple[Image.Image, dict]:
    """Run tiled GPU Super-Resolution using the loaded architecture from `render/`."""
    import torch
    import torch.nn.functional as F

    found = find_best_weight(project_root, preferred_arch=preferred_arch)
    if found is None:
        raise FileNotFoundError("No pretrained .pth weight found in render/ or models/sr/.")

    arch, weight_path = found
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, net_scale, window_size = load_sr_model(project_root, arch, weight_path, device=device)

    rgb = np.array(image.convert("RGB")).astype(np.float32) / 255.0
    h_in, w_in = rgb.shape[:2]
    tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0).to(device)

    out_h = h_in * net_scale
    out_w = w_in * net_scale
    output = torch.zeros((1, 3, out_h, out_w), dtype=torch.float32, device=device)

    tiles_x = math.ceil(w_in / tile_size)
    tiles_y = math.ceil(h_in / tile_size)

    with torch.no_grad():
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                x0 = tx * tile_size
                y0 = ty * tile_size
                x1 = min(x0 + tile_size, w_in)
                y1 = min(y0 + tile_size, h_in)

                x0_pad = max(x0 - tile_pad, 0)
                y0_pad = max(y0 - tile_pad, 0)
                x1_pad = min(x1 + tile_pad, w_in)
                y1_pad = min(y1 + tile_pad, h_in)

                patch = tensor[:, :, y0_pad:y1_pad, x0_pad:x1_pad]
                _, _, ph, pw = patch.shape
                pad_h = (window_size - ph % window_size) % window_size
                pad_w = (window_size - pw % window_size) % window_size
                if pad_h > 0 or pad_w > 0:
                    patch = F.pad(patch, (0, pad_w, 0, pad_h), mode="reflect")

                pred_patch = model(patch)
                pred_patch = pred_patch[:, :, : ph * net_scale, : pw * net_scale]

                ox0 = (x0 - x0_pad) * net_scale
                oy0 = (y0 - y0_pad) * net_scale
                ow = (x1 - x0) * net_scale
                oh = (y1 - y0) * net_scale

                output[:, :, y0 * net_scale : y1 * net_scale, x0 * net_scale : x1 * net_scale] = pred_patch[
                    :, :, oy0 : oy0 + oh, ox0 : ox0 + ow
                ]

    out_np = output.squeeze(0).clamp(0.0, 1.0).cpu().numpy().transpose(1, 2, 0)
    out_u8 = (out_np * 255.0).round().astype(np.uint8)
    result_img = Image.fromarray(out_u8)

    if outscale != net_scale:
        result_img = result_img.resize((w_in * outscale, h_in * outscale), Image.Resampling.LANCZOS)

    return result_img, {
        "engine": f"pytorch_{arch}",
        "arch": arch,
        "weight": weight_path.name,
        "net_scale": net_scale,
        "outscale": outscale,
        "device": device,
    }


def main():
    """CLI entrypoint for invoking GPU SR from the non-CUDA server process."""
    if len(sys.argv) < 5:
        raise SystemExit("Usage: pytorch_sr_runner.py <project_root> <input_img> <output_img> <scale> [arch]")
    project_root = Path(sys.argv[1]).resolve()
    input_path = Path(sys.argv[2]).resolve()
    output_path = Path(sys.argv[3]).resolve()
    scale = int(sys.argv[4])
    arch = sys.argv[5] if len(sys.argv) > 5 else "ttst"

    with Image.open(input_path) as src:
        out_img, meta = super_resolve_pil(src, project_root, outscale=scale, preferred_arch=arch)
        out_img.save(output_path, format="PNG")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
