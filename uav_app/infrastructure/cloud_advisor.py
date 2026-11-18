"""Optional text-only advisor. API keys never enter state, files or logs."""
import json
import urllib.error
import urllib.request
import uuid

from uav_app.domain.settings import DEFAULTS,validate_settings
from uav_app.application.advisor import fingerprint


def _schema():
    properties={}
    for key,value in DEFAULTS.items():
        if isinstance(value,list): item={"type":"array","items":{"type":"string"}}
        elif isinstance(value,bool): item={"type":"boolean"}
        elif isinstance(value,int): item={"type":"integer"}
        elif isinstance(value,float): item={"type":"number"}
        else: item={"type":"string"}
        properties[key]=item
    return dict(type="object",properties={"settings":dict(type="object",properties=properties,
        required=list(properties),additionalProperties=False),"reason":{"type":"string"}},
        required=["settings","reason"],additionalProperties=False)


DEFAULT_PROVIDER_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "google": "gemini-2.5-flash",
    "deepseek": "deepseek-chat",
    "openrouter": "openai/gpt-4o-mini",
}


def cloud_proposal(request,current,provider,api_key,model="",workspace=""):
    if provider not in set(DEFAULT_PROVIDER_MODELS):
        raise ValueError("Nhà cung cấp không hợp lệ.")
    model = (model or "").strip() or DEFAULT_PROVIDER_MODELS[provider]
    for name,value,limit in (("request",request,2000),("model",model,120),("api_key",api_key,500),("workspace",workspace,120)):
        if not isinstance(value,str) or len(value)>limit or "\x00" in value or (name!="request" and any(c in value for c in "\r\n")):
            raise ValueError("Thông tin yêu cầu, model hoặc khóa API không hợp lệ.")
    if not request.strip() or not model.strip() or not 16<=len(api_key)<=500:
        raise ValueError("Nhập yêu cầu và khóa API hợp lệ.")
    instructions=("You advise a UAV rice-field detector. Return JSON with full settings and reason in plain Vietnamese. "
        "Never output code or claim detection accuracy. Keep categories in English, 1-8 strings, max 100 characters without angle brackets. "
        "Allowed micro_size integer 128-1024; micro_overlap .1-.5; upscale 1,2,4; max_image_size 256-1024; "
        "max_new_tokens 64-2048; seed 0-2147483647; merge_mode none, equal_weight or smart_overlap; merge_iou .1-.95; "
        "refinement boolean; padding 0-30. Preserve unspecified settings. Fusion has no calibrated scores and needs human validation. "
        "Current settings: "+json.dumps(current,ensure_ascii=False))
    headers={"Content-Type":"application/json","Authorization":"Bearer "+api_key}
    if provider=="openai":
        url="https://api.openai.com/v1/responses"
        body=dict(model=model,instructions=instructions,input=request,max_output_tokens=1600,store=False,
                  text={"format":dict(type="json_schema",name="uav_settings",strict=True,schema=_schema())})
    elif provider=="anthropic":
        url="https://api.anthropic.com/v1/messages"
        headers["anthropic-version"]="2026-10-21"
        if workspace: headers["anthropic-workspace-id"]=workspace
        body=dict(model=model,system=instructions,max_tokens=1600,messages=[dict(role="user",content=request)])
    elif provider in {"deepseek","openrouter","google"}:
        endpoints={
            "deepseek":"https://api.deepseek.com/chat/completions",
            "openrouter":"https://openrouter.ai/api/v1/chat/completions",
            "google":"https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        }
        url=endpoints[provider]
        body=dict(model=model,max_tokens=1600,response_format={"type":"json_object"},
                  messages=[dict(role="system",content=instructions),dict(role="user",content=request)])
    http_request=urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode("utf-8"),headers=headers,method="POST")
    try:
        with urllib.request.urlopen(http_request,timeout=45) as response:
            raw=response.read(524289)
        if len(raw)>524288: raise ValueError("Phản hồi trợ lý quá lớn.")
        payload=json.loads(raw)
    except urllib.error.HTTPError as error:
        raise ValueError(f"Dịch vụ trả mã {error.code}. Kiểm tra khóa, tên model, quyền truy cập và hạn mức API.") from None
    except (urllib.error.URLError,TimeoutError):
        raise ValueError("Không kết nối được dịch vụ trong thời gian chờ.") from None
    if provider=="openai":
        if payload.get("status","completed")!="completed": raise ValueError("Trợ lý chưa trả xong cấu hình. Hãy thử lại.")
        text="".join(part.get("text","") for item in payload.get("output",[]) if item.get("type")=="message"
                     for part in item.get("content",[]) if part.get("type")=="output_text")
    elif provider=="anthropic":
        if payload.get("stop_reason")=="max_tokens": raise ValueError("Phản hồi trợ lý bị cắt ngắn. Hãy thử yêu cầu ngắn hơn.")
        text="".join(part.get("text","") for part in payload.get("content",[]) if part.get("type")=="text")
    else:
        choices=payload.get("choices") or []
        text=(choices[0].get("message",{}).get("content") or "") if choices else ""
    text=text.strip()
    if text.startswith("```json") and text.endswith("```"): text=text[7:-3].strip()
    try:
        result=json.loads(text)
        if not isinstance(result,dict) or set(result)!={"settings","reason"}:
            raise ValueError()
        settings=validate_settings(result["settings"])
        reason=result["reason"]
        if not isinstance(reason,str) or len(reason)>2000: raise ValueError()
    except (ValueError,TypeError,KeyError):
        raise ValueError("Trợ lý trả cấu hình không hợp lệ. Chưa có thay đổi nào được áp dụng.") from None
    patch={k:v for k,v in settings.items() if v!=current[k]}
    if not patch: raise ValueError("Trợ lý đề nghị giữ cấu hình hiện tại. "+reason)
    return dict(id="CFG-"+uuid.uuid4().hex[:8],title="Gợi ý từ "+provider,source=provider,model=model,
        request=request,before={k:current[k] for k in patch},patch=patch,base_fingerprint=fingerprint(current),
        approval_scope="configuration",note=reason+" Cần bạn duyệt; chỉ áp dụng cho lượt chạy sau.")
