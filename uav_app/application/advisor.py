"""P04: local, explicit rules propose whitelisted settings; never patch code."""
import hashlib
import json
import uuid
from uav_app.domain.settings import validate_settings


def fingerprint(settings):
    return hashlib.sha256(json.dumps(settings,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def propose(request,current):
    if not isinstance(request,str) or not 1<=len(request.strip())<=2000:
        raise ValueError("Nhập yêu cầu từ 1 đến 2.000 ký tự.")
    text=request.casefold()
    patch={}
    if any(word in text for word in ("lúa","rice")):
        patch["categories"]=["newly transplanted rice","grass"]
    elif any(word in text for word in ("cỏ","weed","grass")):
        patch["categories"]=["grass"]
    if any(word in text for word in ("nhỏ","50m","50 m","mới cấy","non","small")):
        patch.update(micro_size=256,micro_overlap=.3,upscale=2)
    if any(word in text for word in ("bộ nhớ","vram","chậm","nhanh")):
        patch.update(max_image_size=768,max_new_tokens=256,upscale=2)
    if any(word in text for word in ("co","sát","tight")):
        patch.update(refinement=True,padding=0)
    if not patch:
        raise ValueError("Bộ gợi ý trên máy hiểu các yêu cầu như: tìm lúa mới cấy, tìm cỏ, giảm bộ nhớ, co khung sát hơn.")
    validated=validate_settings({**current,**patch})
    patch={k:v for k,v in patch.items() if current[k]!=validated[k]}
    if not patch:
        raise ValueError("Cấu hình hiện tại đã đáp ứng yêu cầu này.")
    return dict(id="CFG-"+uuid.uuid4().hex[:8],title="Gợi ý cấu hình theo yêu cầu của bạn",request=request,
                source="local_rules",before={k:current[k] for k in patch},patch=patch,
                base_fingerprint=fingerprint(current),approval_scope="configuration",
                note="Chỉ đổi cấu hình cho lần chạy sau. Đây là gợi ý theo quy tắc trên máy, chưa gọi dịch vụ chat AI.")
