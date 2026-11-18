"""Validated processing settings shared by UI jobs and stopped-job proposals."""
import math

DEFAULTS = dict(categories=["newly transplanted rice", "grass"], micro_size=384, micro_overlap=.3,
                upscale=2, max_image_size=768, max_new_tokens=512, seed=42,
                merge_mode="none", merge_iou=.55, refinement=True, padding=0,
                engine="locateanything")
VALID_ENGINES = {"locateanything", "turbo_zone", "turbo_clump"}


def validate_settings(values=None):
    from copy import deepcopy
    if values is None:
        values={}
    if not isinstance(values,dict) or set(values)-set(DEFAULTS):
        raise ValueError("Cấu hình nhận diện chứa trường không được hỗ trợ.")
    config=deepcopy(DEFAULTS); config.update(deepcopy(values))
    if config.get("engine") not in VALID_ENGINES:
        raise ValueError("Động cơ nhận diện không hợp lệ.")
    cats=config["categories"]
    if not isinstance(cats,list) or not 1<=len(cats)<=8 or any(not isinstance(v,str) or not v.strip() or len(v)>100 or any(c in v for c in "<>\r\n") for v in cats):
        raise ValueError("Nhập 1–8 đối tượng, mỗi đối tượng tối đa 100 ký tự; không dùng thẻ HTML.")
    config["categories"]=list(dict.fromkeys(v.strip() for v in cats))
    for key,lo,hi in (("micro_size",128,1024),("max_image_size",256,1024),("max_new_tokens",64,2048),("seed",0,2**31-1),("padding",0,30)):
        value=config[key]
        if isinstance(value,bool) or not isinstance(value,int) or not lo<=value<=hi:
            raise ValueError(f"{key} phải là số nguyên từ {lo} đến {hi}.")
    if type(config["upscale"]) is not int or config["upscale"] not in (1,2,4):
        raise ValueError("Mức phóng ảnh phải là 1, 2 hoặc 4.")
    for key,lo,hi in (("micro_overlap",.1,.5),("merge_iou",.1,.95)):
        value=config[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError(f"{key} phải từ {lo} đến {hi}.")
    if config["merge_mode"] not in {"none","equal_weight","smart_overlap"} or type(config["refinement"]) is not bool:
        raise ValueError("Chế độ gộp hoặc co khung không hợp lệ.")
    return config
