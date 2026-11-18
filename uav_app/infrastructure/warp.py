"""P01: reviewed north-up reprojection, streamed through a virtual raster."""
import hashlib
import io
import json
import math
from pathlib import Path
import numpy as np

import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling, ColorInterp
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform
from rasterio.windows import Window
from PIL import Image

from uav_app.infrastructure.raster import _effective_crs, _local_path, _metadata, _write_json


def plan_warp(path, target_crs, resolution_cm, resampling="bilinear"):
    source = _local_path(path)
    if isinstance(resolution_cm, bool) or not isinstance(resolution_cm, (int,float)) or not math.isfinite(resolution_cm) or not .1 <= resolution_cm <= 100000:
        raise ValueError("Kích thước pixel đích phải từ 0,1 đến 100.000 cm.")
    target = CRS.from_user_input(target_crs)
    if not target.is_projected:
        raise ValueError("Chọn hệ tọa độ phẳng cho ảnh chuẩn hóa.")
    factor = target.linear_units_factor[1]
    if resampling not in {"nearest", "bilinear", "cubic"}:
        raise ValueError("Phép nội suy không hợp lệ.")
    with rasterio.open(source) as src:
        crs = _effective_crs(src, source)
        if crs is None or src.transform.is_identity:
            raise ValueError("Nguồn phải có hệ tọa độ và vị trí pixel trước khi chuẩn hóa.")
        transform, width, height = calculate_default_transform(crs, target, src.width, src.height,
            *src.bounds, resolution=resolution_cm / 100 / factor)
        if width * height > 20_000_000_000:
            raise ValueError("Ảnh đích vượt 20 tỷ pixel. Chọn pixel lớn hơn hoặc xử lý một vùng nhỏ.")
        params = dict(path=str(source), target_crs=target.to_wkt(), resolution_cm=float(resolution_cm), resampling=resampling)
        signature = hashlib.sha256(json.dumps([params, source.stat().st_size, source.stat().st_mtime_ns,
            list(src.transform), crs.to_wkt()], sort_keys=True).encode()).hexdigest()
        return dict(signature=signature, params=params, source_crs=crs.to_string(), target_crs=target.to_string(),
                    transform=list(transform)[:6], width=width, height=height,
                    estimated_uncompressed_bytes=width*height*(src.count+1)*np.dtype(src.dtypes[0]).itemsize,
                    resolution_cm=float(resolution_cm), resampling=resampling,
                    notice="Chuẩn hóa có nội suy pixel. Nhập lại Base theo hệ tọa độ của ảnh đích.")


def _vrt(src, path, plan):
    from affine import Affine
    return WarpedVRT(src, src_crs=_effective_crs(src, Path(path)), crs=CRS.from_user_input(plan["params"]["target_crs"]),
        transform=Affine(*plan["transform"]), width=plan["width"], height=plan["height"],
        resampling=getattr(Resampling, plan["resampling"]), add_alpha=ColorInterp.alpha not in src.colorinterp, warp_mem_limit=128)


def warp_preview(plan):
    import numpy as np
    with rasterio.open(plan["params"]["path"]) as src, _vrt(src, plan["params"]["path"], plan) as vrt:
        scale = min(1, 1200/max(vrt.width,vrt.height))
        h,w = max(1,round(vrt.height*scale)),max(1,round(vrt.width*scale))
        bands = [1,2,3] if src.count >= 3 else [1,1,1]
        rgb = vrt.read(bands, out_shape=(3,h,w)).astype(float)
        if src.dtypes[0] != "uint8":
            for channel in rgb:
                lo,hi = np.percentile(channel[np.isfinite(channel)], [2,98]) if np.isfinite(channel).any() else (0,1)
                channel[:] = (channel-lo)*255/max(hi-lo,1)
        rgba = np.concatenate([np.clip(np.nan_to_num(rgb),0,255).astype('uint8'),
                               vrt.dataset_mask(out_shape=(h,w))[None]],axis=0).transpose(1,2,0)
        output=io.BytesIO(); Image.fromarray(rgba).save(output,format="PNG")
        return output.getvalue()


def execute_warp(plan, output_dir, progress=None, cancelled=None):
    checked = plan_warp(**plan["params"])
    if checked["signature"] != plan["signature"]:
        raise ValueError("Ảnh hoặc cấu hình đã đổi. Hãy xem trước lại.")
    destination = Path(output_dir)
    destination.mkdir(exist_ok=False)
    final, temporary = destination/"normalized.tif", destination/".normalized.partial.tif"
    summary = dict(kind="warp", status="running", plan=plan, output_path=None, done=0)
    _write_json(destination/"summary.json",summary)
    try:
        with rasterio.open(plan["params"]["path"]) as src, _vrt(src, plan["params"]["path"], plan) as vrt:
            profile = dict(driver="GTiff",width=vrt.width,height=vrt.height,count=vrt.count,dtype=vrt.dtypes[0],
                crs=vrt.crs,transform=vrt.transform,tiled=True,blockxsize=512,blockysize=512,
                compress="deflate",BIGTIFF="IF_SAFER")
            total=math.ceil(vrt.width/512)*math.ceil(vrt.height/512)
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(temporary,"w",**profile) as dst:
                dst.colorinterp=vrt.colorinterp
                extra=vrt.count-src.count
                dst.scales=tuple(src.scales)+(1,)*extra
                dst.offsets=tuple(src.offsets)+(0,)*extra
                for band in src.indexes:
                    dst.update_tags(band,**src.tags(band))
                    if src.descriptions[band-1]: dst.set_band_description(band,src.descriptions[band-1])
                    if src.units[band-1]: dst.set_band_unit(band,src.units[band-1])
                for row in range(0,vrt.height,512):
                    for col in range(0,vrt.width,512):
                        if cancelled and cancelled():
                            summary["status"]="cancelled"
                            return summary
                        window=Window(col,row,min(512,vrt.width-col),min(512,vrt.height-row))
                        dst.write(vrt.read(window=window),window=window)
                        dst.write_mask(vrt.dataset_mask(window=window),window=window)
                        summary["done"]+=1
                        if progress: progress(summary["done"],total)
            temporary.replace(final)
            summary.update(status="completed",output_path=str(final))
        return summary
    except Exception as error:
        summary.update(status="failed",error=str(error))
        raise
    finally:
        temporary.unlink(missing_ok=True)
        _write_json(destination/"summary.json",summary)
