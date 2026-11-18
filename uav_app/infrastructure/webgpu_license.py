"""WebGPU Portal License Key Manager, Device Fingerprint Binding, Quota Tracking & AES-256-GCM Model Encryption."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_LICENSE_LOCK = threading.Lock()
_ACTIVE_LEASES: dict[str, dict[str, Any]] = {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_licenses() -> dict[str, dict[str, Any]]:
    now = _utc_now()
    return {
        "UAV-WEBGPU-2026-PRO": {
            "key": "UAV-WEBGPU-2026-PRO",
            "plan": "Pro Survey WebGPU",
            "owner": "Tài khoản Kỹ sư Trắc địa (Mặc định)",
            "status": "active",
            "quota_ha_total": 500.0,
            "quota_ha_used": 0.0,
            "max_devices": 2,
            "devices": [],
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(days=365)),
        },
        "UAV-SURVEY-VN2000-VIP": {
            "key": "UAV-SURVEY-VN2000-VIP",
            "plan": "Enterprise Bình đồ VN2000",
            "owner": "Đội Bay Khảo sát Địa hình VIP",
            "status": "active",
            "quota_ha_total": 2500.0,
            "quota_ha_used": 0.0,
            "max_devices": 5,
            "devices": [],
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(days=730)),
        },
        "UAV-TRIAL-DEMO-50HA": {
            "key": "UAV-TRIAL-DEMO-50HA",
            "plan": "Gói Dùng thử Khách hàng mới",
            "owner": "Khách hàng Dùng thử",
            "status": "active",
            "quota_ha_total": 50.0,
            "quota_ha_used": 0.0,
            "max_devices": 1,
            "devices": [],
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(days=30)),
        },
    }


def _license_db_path(project_root: Path) -> Path:
    env_dir = (os.environ.get("UAV_DATA_DIR") or "").strip()
    base = Path(env_dir).expanduser().resolve() if env_dir else (Path(project_root) / "outputs" / "license_store")
    p = base / "webgpu_licenses.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_db(project_root: Path) -> dict[str, dict[str, Any]]:
    path = _license_db_path(project_root)
    if not path.is_file():
        db = _default_licenses()
        _write_json(path, db)
        return db
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass
    db = _default_licenses()
    _write_json(path, db)
    return db


def _save_db(project_root: Path, db: dict[str, dict[str, Any]]) -> None:
    _write_json(_license_db_path(project_root), db)


def _public_license_view(rec: dict[str, Any]) -> dict[str, Any]:
    total = float(rec.get("quota_ha_total") or 0.0)
    used = float(rec.get("quota_ha_used") or 0.0)
    return {
        "key": rec["key"],
        "plan": rec.get("plan", "Standard"),
        "owner": rec.get("owner", ""),
        "status": rec.get("status", "active"),
        "quota_ha_total": round(total, 2),
        "quota_ha_used": round(used, 3),
        "quota_ha_remaining": round(max(0.0, total - used), 3),
        "max_devices": int(rec.get("max_devices") or 1),
        "active_devices_count": len(rec.get("devices") or []),
        "devices": rec.get("devices") or [],
        "expires_at": rec.get("expires_at", ""),
    }


def list_licenses(project_root: Path) -> dict[str, Any]:
    with _LICENSE_LOCK:
        db = _load_db(project_root)
        items = [_public_license_view(v) for v in db.values()]
    return {"licenses": items, "available_models": list_available_onnx_models(project_root)}


def create_license(
    project_root: Path,
    owner: str,
    plan: str = "Pro Survey WebGPU",
    quota_ha: float = 200.0,
    max_devices: int = 2,
    days_valid: int = 365,
) -> dict[str, Any]:
    now = _utc_now()
    rand_part = secrets.token_hex(3).upper()
    new_key = f"UAV-{now.year}-{rand_part[:3]}-{rand_part[3:]}"
    rec = {
        "key": new_key,
        "plan": (plan or "Pro Survey WebGPU").strip(),
        "owner": (owner or "Khách hàng mới").strip(),
        "status": "active",
        "quota_ha_total": max(1.0, float(quota_ha)),
        "quota_ha_used": 0.0,
        "max_devices": max(1, int(max_devices)),
        "devices": [],
        "created_at": _iso(now),
        "expires_at": _iso(now + timedelta(days=max(1, int(days_valid)))),
    }
    with _LICENSE_LOCK:
        db = _load_db(project_root)
        db[new_key] = rec
        _save_db(project_root, db)
    return _public_license_view(rec)


def update_license_action(project_root: Path, key: str, action: str) -> dict[str, Any]:
    clean_key = (key or "").strip().upper()
    with _LICENSE_LOCK:
        db = _load_db(project_root)
        if clean_key not in db:
            raise ValueError(f"Không tìm thấy mã Key: {clean_key}")
        rec = db[clean_key]
        if action == "reset_devices":
            rec["devices"] = []
        elif action == "revoke":
            rec["status"] = "revoked"
        elif action == "activate":
            rec["status"] = "active"
        else:
            raise ValueError(f"Thao tác Key không hợp lệ: {action}")
        _save_db(project_root, db)
        return _public_license_view(rec)


def list_available_onnx_models(project_root: Path) -> list[dict[str, Any]]:
    models_root = Path(project_root) / "models" / "turbo_yolo"
    catalog = []

    terrain_onnx = models_root / "terrain_webgpu.onnx"
    catalog.append(
        {
            "id": "terrain_seg",
            "title": "🛣️ Phân vùng Địa hình & Đô thị 9 Lớp (Đường nhựa · Bê tông · Đất · Đi bộ · Sông/Ao · Mương · Nhà · Cây cảnh quan)",
            "task": "segmentation",
            "input_size": 512,
            "ready": terrain_onnx.is_file(),
            "size_mb": round(terrain_onnx.stat().st_size / (1024 * 1024), 2) if terrain_onnx.is_file() else 0.0,
            "classes": [
                "background",
                "asphalt_road",
                "concrete_road",
                "dirt_road",
                "footpath",
                "pond",
                "masonry_ditch",
                "house_building",
                "landscape_tree",
            ],
        }
    )

    for mode_id, label in (
        ("turbo_zone", "🌾 YOLO11 Turbo · Quét Vùng Lúa & Cỏ bờ (640×640)"),
        ("turbo_clump", "🌱 YOLO11 Turbo · Bắt Khóm Lúa Đơn Lẻ (~15cm · 512×512)"),
    ):
        p = models_root / mode_id / "weights" / "best.onnx"
        meta_p = models_root / mode_id / "train_summary.json"
        imgsz = 640 if mode_id == "turbo_zone" else 512
        cls_names = ["Newly transplanted rice", "Grass", "Newly transplanted rice + Partial Grass"]
        if meta_p.is_file():
            try:
                m_info = json.loads(meta_p.read_text(encoding="utf-8"))
                cls_names = m_info.get("classes") or cls_names
            except Exception:
                pass
        catalog.append(
            {
                "id": mode_id,
                "title": label,
                "task": "yolo_detection",
                "input_size": imgsz,
                "ready": p.is_file(),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2) if p.is_file() else 0.0,
                "classes": cls_names,
            }
        )
    return catalog


def _resolve_onnx_path(project_root: Path, model_id: str) -> tuple[Path, dict[str, Any]]:
    models = {m["id"]: m for m in list_available_onnx_models(project_root)}
    if model_id not in models:
        raise ValueError(f"Mô hình không tồn tại: {model_id}")
    info = models[model_id]
    models_root = Path(project_root) / "models" / "turbo_yolo"
    if model_id == "terrain_seg":
        path = models_root / "terrain_webgpu.onnx"
    else:
        path = models_root / model_id / "weights" / "best.onnx"
    if not path.is_file():
        raise ValueError(
            f"Mô hình '{info['title']}' chưa có tệp ONNX. Hãy huấn luyện ở Bước 05 hoặc chọn mô hình Phân vùng Địa hình."
        )
    return path, info


def authenticate_and_issue_webgpu_lease(
    project_root: Path,
    license_key: str,
    device_fingerprint: str,
    gpu_label: str = "",
    model_id: str = "terrain_seg",
) -> dict[str, Any]:
    """Validate license key, bind hardware fingerprint, and encrypt ONNX model with a 1-time AES-256-GCM key."""
    clean_key = (license_key or "").strip().upper()
    if not clean_key:
        raise ValueError("Vui lòng nhập mã License Key để đăng nhập.")

    dev_raw = (device_fingerprint or "browser-default-device").strip()
    dev_hash = hashlib.sha256(dev_raw.encode("utf-8")).hexdigest()[:16].upper()

    with _LICENSE_LOCK:
        db = _load_db(project_root)
        if clean_key not in db:
            raise ValueError("Mã License Key không hợp lệ hoặc không tồn tại trên hệ thống.")
        rec = db[clean_key]
        if rec.get("status") != "active":
            raise ValueError("Mã License Key này đã bị khóa hoặc thu hồi.")

        exp_str = rec.get("expires_at") or ""
        if exp_str:
            exp_dt = datetime.strptime(exp_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if _utc_now() > exp_dt:
                rec["status"] = "expired"
                _save_db(project_root, db)
                raise ValueError("Mã License Key đã hết hạn sử dụng.")

        rem_ha = float(rec.get("quota_ha_total") or 0.0) - float(rec.get("quota_ha_used") or 0.0)
        if rem_ha <= 0.0:
            raise ValueError("Tài khoản đã sử dụng hết hạn mức diện tích (Hecta). Vui lòng gia hạn thêm.")

        devices: list[dict[str, str]] = rec.setdefault("devices", [])
        known_ids = {d.get("device_id") for d in devices}
        max_dev = max(1, int(rec.get("max_devices") or 1))
        if dev_hash not in known_ids:
            if len(devices) >= max_dev:
                raise ValueError(
                    f"Key này đã kích hoạt tối đa {max_dev}/{max_dev} thiết bị. Hãy hủy kích hoạt máy cũ trước khi đăng nhập máy mới."
                )
            devices.append(
                {
                    "device_id": dev_hash,
                    "gpu": (gpu_label or "WebGPU Browser Adapter")[:80],
                    "activated_at": _iso(_utc_now()),
                }
            )
            _save_db(project_root, db)

        lic_view = _public_license_view(rec)

    onnx_path, model_info = _resolve_onnx_path(project_root, model_id)
    plain_onnx = onnx_path.read_bytes()

    aes_key = secrets.token_bytes(32)  # 256-bit AES key
    iv = secrets.token_bytes(12)       # 96-bit GCM IV
    ciphertext = AESGCM(aes_key).encrypt(iv, plain_onnx, None)

    lease_token = secrets.token_urlsafe(24)
    now_ts = time.time()
    with _LICENSE_LOCK:
        # Purge expired leases > 180s
        expired_tokens = [k for k, v in _ACTIVE_LEASES.items() if now_ts - v["created_ts"] > 180]
        for k in expired_tokens:
            _ACTIVE_LEASES.pop(k, None)
        _ACTIVE_LEASES[lease_token] = {
            "ciphertext": ciphertext,
            "created_ts": now_ts,
            "license_key": clean_key,
            "device_id": dev_hash,
            "model_id": model_id,
        }

    return {
        "authenticated": True,
        "device_id": dev_hash,
        "license": lic_view,
        "model": model_info,
        "crypto": {
            "algorithm": "AES-256-GCM",
            "lease_token": lease_token,
            "key_b64": base64.b64encode(aes_key).decode("ascii"),
            "iv_b64": base64.b64encode(iv).decode("ascii"),
            "encrypted_bytes": len(ciphertext),
            "expires_in_seconds": 180,
        },
    }


def consume_encrypted_model_lease(lease_token: str) -> bytes:
    """Return encrypted AES-256-GCM model bytes once and immediately wipe the lease from server RAM."""
    tok = (lease_token or "").strip()
    with _LICENSE_LOCK:
        entry = _ACTIVE_LEASES.pop(tok, None)
    if not entry or (time.time() - entry["created_ts"] > 180):
        raise ValueError("Phiên tải mô hình mã hóa đã hết hạn hoặc đã được sử dụng (Single-Use Lease).")
    return entry["ciphertext"]


def record_quota_usage(project_root: Path, license_key: str, area_ha: float) -> dict[str, Any]:
    clean_key = (license_key or "").strip().upper()
    delta = max(0.001, float(area_ha or 0.0))
    with _LICENSE_LOCK:
        db = _load_db(project_root)
        if clean_key not in db:
            raise ValueError("Mã License Key không hợp lệ.")
        rec = db[clean_key]
        rem = float(rec.get("quota_ha_total") or 0.0) - float(rec.get("quota_ha_used") or 0.0)
        if rem < delta:
            raise ValueError(f"Hạn mức còn lại ({rem:.3f} ha) không đủ để quét khu vực này ({delta:.3f} ha).")
        rec["quota_ha_used"] = round(float(rec.get("quota_ha_used") or 0.0) + delta, 4)
        _save_db(project_root, db)
        return _public_license_view(rec)


def build_demo_terrain_geotiff_bytes(project_root: Path | None = None) -> bytes:
    """Generate a realistic georeferenced EPSG:32648 UAV GeoTIFF (1024x1024, 5cm/px) with all 6 terrain classes."""
    if project_root is not None:
        cached = Path(project_root) / "models" / "turbo_yolo" / "demo_terrain_6_classes.tif"
        if cached.is_file():
            return cached.read_bytes()
    try:
        import cv2
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
    except ImportError as exc:
        raise ValueError(
            "Máy chủ Cloud siêu nhẹ không đính kèm trình sinh ảnh mẫu GDAL; hãy chọn trực tiếp bộ ảnh ORTHO (.JPG + .JGW + .PRJ) + DEM.TIF trên máy tính của bạn."
        ) from exc
    size = 1024
    rng = np.random.default_rng(2026)
    img = np.zeros((size, size, 3), dtype=np.float32)

    # Green paddy / grass background
    img[:, :, 0] = 88.0 + rng.normal(0, 9, size=(size, size))
    img[:, :, 1] = 136.0 + rng.normal(0, 10, size=(size, size))
    img[:, :, 2] = 66.0 + rng.normal(0, 8, size=(size, size))

    # 1. Pond (Ao / Hồ) in bottom-left quadrant
    pond_m = np.zeros((size, size), dtype=np.uint8)
    cv2.ellipse(pond_m, (260, 740), (145, 105), 18.0, 0, 360, 1, -1)
    p_idx = pond_m > 0
    img[p_idx, 0] = 46.0 + rng.normal(0, 3, size=int(p_idx.sum()))
    img[p_idx, 1] = 82.0 + rng.normal(0, 3, size=int(p_idx.sum()))
    img[p_idx, 2] = 79.0 + rng.normal(0, 3, size=int(p_idx.sum()))

    # 2. Dirt Road (Đường đất) curving across right-bottom
    dirt_m = np.zeros((size, size), dtype=np.uint8)
    cv2.polylines(
        dirt_m,
        [np.array([[520, 980], [670, 720], [990, 560]], dtype=np.int32)],
        False,
        1,
        thickness=56,
    )
    d_idx = dirt_m > 0
    img[d_idx, 0] = 166.0 + rng.normal(0, 6, size=int(d_idx.sum()))
    img[d_idx, 1] = 126.0 + rng.normal(0, 6, size=int(d_idx.sum()))
    img[d_idx, 2] = 86.0 + rng.normal(0, 5, size=int(d_idx.sum()))

    # 3. Footpath (Đường đi bộ ~1.1m = 22px) leading toward the pond
    fp_m = np.zeros((size, size), dtype=np.uint8)
    cv2.polylines(
        fp_m,
        [np.array([[385, 650], [455, 520], [500, 360]], dtype=np.int32)],
        False,
        1,
        thickness=20,
    )
    f_idx = fp_m > 0
    img[f_idx, 0] = 175.0 + rng.normal(0, 5, size=int(f_idx.sum()))
    img[f_idx, 1] = 162.0 + rng.normal(0, 5, size=int(f_idx.sum()))
    img[f_idx, 2] = 138.0 + rng.normal(0, 5, size=int(f_idx.sum()))

    # 4. Masonry Ditch (Mương xây ~1.1m = 22px) running top-right to middle-left with bright concrete walls
    ditch_outer = np.zeros((size, size), dtype=np.uint8)
    ditch_inner = np.zeros((size, size), dtype=np.uint8)
    d_pts = np.array([[40, 490], [520, 480], [985, 470]], dtype=np.int32)
    cv2.polylines(ditch_outer, [d_pts], False, 1, thickness=24)
    cv2.polylines(ditch_inner, [d_pts], False, 1, thickness=12)
    w_idx = (ditch_outer > 0) & (ditch_inner == 0)
    c_idx = ditch_inner > 0
    for ch in range(3):
        img[w_idx, ch] = 222.0 + rng.normal(0, 4, size=int(w_idx.sum()))
    img[c_idx, 0] = 44.0 + rng.normal(0, 4, size=int(c_idx.sum()))
    img[c_idx, 1] = 56.0 + rng.normal(0, 4, size=int(c_idx.sum()))
    img[c_idx, 2] = 60.0 + rng.normal(0, 4, size=int(c_idx.sum()))

    # 5. Concrete Road (Đường bê tông ~3.6m = 72px) branching northward
    conc_m = np.zeros((size, size), dtype=np.uint8)
    cv2.line(conc_m, (640, 260), (880, 30), 1, thickness=70)
    cc_idx = conc_m > 0
    for ch in range(3):
        img[cc_idx, ch] = 208.0 + rng.normal(0, 5, size=int(cc_idx.sum()))

    # 6. Asphalt Road (Đường nhựa ~5.0m = 100px) diagonal arterial highway across upper half
    asph_m = np.zeros((size, size), dtype=np.uint8)
    cv2.line(asph_m, (20, 310), (1004, 190), 1, thickness=98)
    a_idx = asph_m > 0
    img[a_idx, 0] = 98.0 + rng.normal(0, 4, size=int(a_idx.sum()))
    img[a_idx, 1] = 100.0 + rng.normal(0, 4, size=int(a_idx.sum()))
    img[a_idx, 2] = 105.0 + rng.normal(0, 4, size=int(a_idx.sum()))
    stripe_m = np.zeros((size, size), dtype=np.uint8)
    cv2.line(stripe_m, (20, 310), (1004, 190), 1, thickness=3)
    img[(stripe_m > 0) & a_idx] = 228.0

    # 7. House / Building (Nhà / Công trình ~7.5m x 4.25m terracotta tile roof in bottom-right)
    img[810:895, 750:900, 0] = 205.0 + rng.normal(0, 4, size=(85, 150))
    img[810:895, 750:900, 1] = 88.0 + rng.normal(0, 4, size=(85, 150))
    img[810:895, 750:900, 2] = 52.0 + rng.normal(0, 4, size=(85, 150))

    # 8. Landscape Tree (Cây cảnh quan ~4.4m crown in top-left with foliage contrast)
    tree_m = np.zeros((size, size), dtype=np.uint8)
    cv2.circle(tree_m, (160, 105), 44, 1, -1)
    t_idx = tree_m > 0
    foliage_var = rng.normal(0, 22, size=int(t_idx.sum()))
    img[t_idx, 0] = 36.0 + foliage_var * 0.7
    img[t_idx, 1] = 112.0 + foliage_var * 1.1
    img[t_idx, 2] = 32.0 + foliage_var * 0.6

    rgb_u8 = np.clip(img, 0, 255).astype(np.uint8)
    chw = np.transpose(rgb_u8, (2, 0, 1))
    transform = from_origin(584100.0, 1040200.0, 0.05, 0.05)

    buf = io.BytesIO()
    with rasterio.MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            width=size,
            height=size,
            count=3,
            dtype="uint8",
            crs="EPSG:32648",
            transform=transform,
        ) as dst:
            dst.write(chw)
        buf.write(memfile.read())
    return buf.getvalue()
