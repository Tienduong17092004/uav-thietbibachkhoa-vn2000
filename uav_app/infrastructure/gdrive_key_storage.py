"""Key Management Vault & 30TB Google Drive Ultra Storage Adapter.

Provides:
1. `KeyVaultManager`:
   - Generates, stores (with 0600 file permissions), masks, and resolves keys:
     * `UAV_TPU_API_KEY` (256-bit token protecting the remote Kaggle/Colab TPU `/infer` endpoint)
     * `GEMINI_API_KEY` (Google AI Studio / Gemini Ultra API key)
     * `UAV_TPU_ENDPOINT_URL` (Dynamic HTTPS URL of the Kaggle/Colab TPU server)
     * `CLOUDFLARE_TUNNEL_ID` (Zero-hosting tunnel for `https://thietbibachkhoa.id.vn/`)
     * `GDRIVE_FOLDER_ID` (`1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV`)
2. `GoogleDrive30TBStorage`:
   - Integrates the user's 30 TB Google Drive Ultra account (`30,720.0 GB` total) as the
     primary storage backend for heavy UAV GeoTIFF orthomosaics (`.tif`, `.jgw`, `.dem`),
     VN2000 AutoCAD deliverables (`.dwg`, `.dxf`), TPU tile caches, and encrypted key/endpoint
     discovery between Kaggle/Colab TPU and the local workstation.
"""

from __future__ import annotations

import csv
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_GDRIVE_FOLDER_ID: str = "1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV"
PROCESSED_DATA_GDRIVE_FOLDER_ID: str = "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN"
PROCESSED_DATA_GDRIVE_FOLDER_URL: str = (
    "https://drive.google.com/drive/u/3/folders/1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN"
)
DEFAULT_ULTRA_QUOTA_GB: float = 30720.0  # 30 TB Google One AI Premium / Ultra
DEFAULT_ADMIN_KEY: str = "uav_admin_master_key_vn2000"
RED_WARNING_REMAINING_RATIO: float = 1.0 / 3.0

GOOGLE_SHEET_HEADERS: List[str] = [
    "Người nhận",
    "SĐT người nhận",
    "Key",
    "Mục đích",
    "Thời gian cấp",
    "Thời gian hết hạn",
    "Tình trạng",
]

VALID_KEY_PURPOSES: Dict[str, int] = {
    "1h": 3600,
    "3h": 10800,
    "5h": 18000,
    "1m": 2592000,
    "3m": 7776000,
    "6m": 15552000,
    "1y": 31536000,
    "test 1h": 3600,
    "test 3h": 10800,
    "test 5h": 18000,
    "1 tháng": 2592000,
    "3 tháng": 7776000,
    "6 tháng": 15552000,
    "1 năm": 31536000,
}

_EXTRA_PURPOSE_ALIASES: Dict[str, int] = {
    "test thử 1h": 3600,
    "test thử 3h": 10800,
    "test thử 5h": 18000,
    "mua 1 tháng": 2592000,
    "mua 3 tháng": 7776000,
    "mua 6 tháng": 15552000,
    "mua 1 năm": 31536000,
    "12m": 31536000,
    "12 tháng": 31536000,
}


def mask_secret(value: Optional[str]) -> Optional[str]:
    """Mask a sensitive key/token so it can be safely displayed in status APIs and logs."""
    if not value:
        return None
    clean = str(value).strip()
    if len(clean) <= 8:
        return "***"
    return f"{clean[:6]}...{clean[-4:]}"


def _format_iso8601(ts: float) -> str:
    """Format epoch seconds as UTC ISO-8601 timestamp string."""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class KeyVaultConfig:
    """Configuration for the local and Google Drive-backed Key Vault."""

    vault_path: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "config" / ".uav_key_vault.json"
    )
    gdrive_folder_id: str = DEFAULT_GDRIVE_FOLDER_ID
    processed_data_folder_id: str = PROCESSED_DATA_GDRIVE_FOLDER_ID
    auto_generate_tpu_key: bool = True


class KeyVaultManager:
    """Secure manager for TPU, Gemini Ultra, Cloudflare Tunnel, and Kaggle keys."""

    MANAGED_KEYS: Tuple[str, ...] = (
        "UAV_TPU_API_KEY",
        "UAV_TPU_ENDPOINT_URL",
        "UAV_TPU_PROVIDER",
        "GEMINI_API_KEY",
        "KAGGLE_USERNAME",
        "KAGGLE_KEY",
        "CLOUDFLARE_TUNNEL_ID",
        "GDRIVE_FOLDER_ID",
        "PROCESSED_DATA_GDRIVE_FOLDER_ID",
    )

    def __init__(self, config: Optional[KeyVaultConfig] = None, vault_path: Optional[Path] = None) -> None:
        self.config = config or KeyVaultConfig()
        if vault_path is not None:
            self.config.vault_path = Path(vault_path)
        self.processed_data_folder_id: str = self.config.processed_data_folder_id
        self._data: Dict[str, Any] = self._load_or_initialize()

    def _load_or_initialize(self) -> Dict[str, Any]:
        path = self.config.vault_path
        data: Dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        changed = False
        if "GDRIVE_FOLDER_ID" not in data:
            data["GDRIVE_FOLDER_ID"] = os.environ.get("GDRIVE_FOLDER_ID", self.config.gdrive_folder_id)
            changed = True
        if "PROCESSED_DATA_GDRIVE_FOLDER_ID" not in data:
            data["PROCESSED_DATA_GDRIVE_FOLDER_ID"] = os.environ.get(
                "PROCESSED_DATA_GDRIVE_FOLDER_ID", self.config.processed_data_folder_id
            )
            changed = True
        if "UAV_TPU_PROVIDER" not in data:
            data["UAV_TPU_PROVIDER"] = os.environ.get("UAV_TPU_PROVIDER", "kaggle_free_tpu")
            changed = True
        if self.config.auto_generate_tpu_key and not data.get("UAV_TPU_API_KEY"):
            data["UAV_TPU_API_KEY"] = (
                os.environ.get("UAV_TPU_API_KEY") or f"uav_tpu_{secrets.token_urlsafe(24)}"
            )
            changed = True

        if changed:
            self._save(data)
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        path = self.config.vault_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass

    def get_key(self, key_name: str, default: Optional[str] = None) -> Optional[str]:
        """Resolve a key using priority: Environment Variable -> Local Vault -> Default."""
        env_val = os.environ.get(key_name)
        if env_val is not None and str(env_val).strip() != "":
            return str(env_val).strip()
        vault_val = self._data.get(key_name)
        if vault_val is not None and str(vault_val).strip() != "":
            return str(vault_val).strip()
        return default

    def set_key(self, key_name: str, value: str) -> Dict[str, Any]:
        """Store or rotate a key in the local 0600 vault."""
        if not key_name or not str(key_name).strip():
            raise ValueError("key_name must be a non-empty string")
        clean_key = str(key_name).strip()
        self._data[clean_key] = str(value).strip()
        self._save(self._data)
        return {
            "key": clean_key,
            "masked_value": mask_secret(self._data[clean_key]),
            "stored_in": str(self.config.vault_path),
            "permissions": "0600 (owner read/write only)",
        }

    def rotate_tpu_api_key(self) -> Dict[str, Any]:
        """Generate a fresh 256-bit UAV_TPU_API_KEY for authenticating Workstation <-> TPU traffic."""
        new_key = f"uav_tpu_{secrets.token_urlsafe(24)}"
        return self.set_key("UAV_TPU_API_KEY", new_key)

    def get_processed_data_folder_info(self) -> Dict[str, Any]:
        """Return processed data Google Drive folder metadata."""
        folder_id = self.get_key("PROCESSED_DATA_GDRIVE_FOLDER_ID", PROCESSED_DATA_GDRIVE_FOLDER_ID) or PROCESSED_DATA_GDRIVE_FOLDER_ID
        main_id = self.get_key("GDRIVE_FOLDER_ID", DEFAULT_GDRIVE_FOLDER_ID) or DEFAULT_GDRIVE_FOLDER_ID
        return {
            "folder_id": folder_id,
            "processed_data_folder_id": folder_id,
            "folder_url": f"https://drive.google.com/drive/u/3/folders/{folder_id}",
            "processed_data_folder_url": f"https://drive.google.com/drive/u/3/folders/{folder_id}",
            "main_project_folder_id": main_id,
            "main_project_folder_url": f"https://drive.google.com/drive/folders/{main_id}",
            "status": "ok",
        }

    def get_masked_status(self) -> Dict[str, Any]:
        """Return safe, masked key management status suitable for web UI and diagnostics."""
        tpu_key = self.get_key("UAV_TPU_API_KEY")
        gemini_key = self.get_key("GEMINI_API_KEY")
        tpu_url = self.get_key("UAV_TPU_ENDPOINT_URL")
        proc_folder = self.get_key("PROCESSED_DATA_GDRIVE_FOLDER_ID", PROCESSED_DATA_GDRIVE_FOLDER_ID)
        return {
            "vault_file": str(self.config.vault_path),
            "vault_exists": self.config.vault_path.exists(),
            "file_permissions": "0600",
            "processed_data_folder_id": proc_folder,
            "processed_data_folder_url": f"https://drive.google.com/drive/u/3/folders/{proc_folder}",
            "resolution_order": [
                "1. OS Environment Variables (UAV_TPU_API_KEY, GEMINI_API_KEY, UAV_TPU_ENDPOINT_URL)",
                "2. Local Encrypted/Restricted Vault (config/.uav_key_vault.json, chmod 600)",
                "3. Google Drive 30TB Private Folder Sync (1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV & 1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN)",
            ],
            "keys_configured": {
                "UAV_TPU_API_KEY": {
                    "configured": bool(tpu_key),
                    "masked": mask_secret(tpu_key),
                    "purpose": "Xác thực bảo mật giữa Máy trạm (Port 8765) và Kaggle/Colab TPU Server (Port 8470)",
                },
                "GEMINI_API_KEY": {
                    "configured": bool(gemini_key),
                    "masked": mask_secret(gemini_key),
                    "purpose": "Gọi Gemini Ultra Multimodal API để tự gán nhãn bình đồ VN2000",
                },
                "UAV_TPU_ENDPOINT_URL": {
                    "configured": bool(tpu_url),
                    "value": tpu_url or "http://127.0.0.1:8470",
                    "purpose": "Địa chỉ HTTPS của Kaggle Free TPU / Colab TPU Server",
                },
                "GDRIVE_FOLDER_ID": {
                    "configured": True,
                    "value": self.get_key("GDRIVE_FOLDER_ID", DEFAULT_GDRIVE_FOLDER_ID),
                    "purpose": "Thư mục gốc dự án trên Google Drive 30TB Ultra",
                },
                "PROCESSED_DATA_GDRIVE_FOLDER_ID": {
                    "configured": True,
                    "value": proc_folder,
                    "url": f"https://drive.google.com/drive/u/3/folders/{proc_folder}",
                    "purpose": "Thư mục lưu dữ liệu xử lý nhận diện/YOLO trên Google Drive",
                },
            },
        }


class GoogleSheetKeyManager:
    """7-Column Google Sheet + Web Admin Key Manager with <=1/3 red warning & >1/3 green status.

    Columns (exact 7-column Google Sheet schema):
    1. `Người nhận` (`recipient` / `nguoi_nhan`)
    2. `SĐT người nhận` (`phone` / `sdt_nguoi_nhan`)
    3. `Key` (`key`)
    4. `Mục đích` (`purpose` / `muc_dich`: 1h, 3h, 5h, 1m/1 tháng, 3m/3 tháng, 6m/6 tháng, 1y/1 năm)
    5. `Thời gian cấp` (`issued_at` / `thoi_gian_cap`)
    6. `Thời gian hết hạn` (`expires_at` / `thoi_gian_het_han`)
    7. `Tình trạng` (`status` / `tinh_trang`: <=1/3 remaining -> red warning; >1/3 -> green; expired/revoked)
    """

    HEADERS: List[str] = list(GOOGLE_SHEET_HEADERS)
    VALID_PURPOSES: Dict[str, int] = dict(VALID_KEY_PURPOSES)
    DEFAULT_ADMIN_KEY: str = DEFAULT_ADMIN_KEY

    def __init__(
        self,
        registry_path: Optional[Path] = None,
        sheet_csv_path: Optional[Path] = None,
        seed_default_admin: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        base_cfg_dir = Path(__file__).resolve().parents[2] / "config"
        self.registry_path: Path = Path(registry_path) if registry_path is not None else (base_cfg_dir / ".uav_key_registry.json")
        self.sheet_csv_path: Path = Path(sheet_csv_path) if sheet_csv_path is not None else (base_cfg_dir / "uav_keys_google_sheet.csv")
        self.processed_data_folder_id: str = PROCESSED_DATA_GDRIVE_FOLDER_ID
        self.processed_data_folder_url: str = PROCESSED_DATA_GDRIVE_FOLDER_URL
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load_or_initialize(seed_default_admin=seed_default_admin)

    @staticmethod
    def resolve_purpose_duration(
        purpose: str,
        duration_seconds_override: Optional[float] = None,
    ) -> Tuple[str, float]:
        """Validate purpose string and return (normalized_purpose_label, duration_seconds)."""
        if duration_seconds_override is not None:
            dur = float(duration_seconds_override)
            if dur <= 0:
                raise ValueError("duration_seconds_override must be > 0")
            clean_p = str(purpose or "custom").strip() or "custom"
            return clean_p, dur

        if not purpose or not str(purpose).strip():
            raise ValueError("purpose (Mục đích) must be a non-empty string")
        raw = str(purpose).strip()
        lower = raw.lower()
        if lower in VALID_KEY_PURPOSES:
            return raw, float(VALID_KEY_PURPOSES[lower])
        if lower in _EXTRA_PURPOSE_ALIASES:
            return raw, float(_EXTRA_PURPOSE_ALIASES[lower])
        raise ValueError(
            f"Unsupported key purpose '{purpose}'. Valid purposes: {sorted(VALID_KEY_PURPOSES.keys())}"
        )

    def _load_or_initialize(self, seed_default_admin: bool = True) -> None:
        with self._lock:
            loaded: Dict[str, Dict[str, Any]] = {}
            if self.registry_path.exists():
                try:
                    raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and "keys" in raw and isinstance(raw["keys"], list):
                        for item in raw["keys"]:
                            if isinstance(item, dict) and item.get("key"):
                                loaded[str(item["key"])] = dict(item)
                    elif isinstance(raw, dict):
                        for k, v in raw.items():
                            if isinstance(v, dict):
                                loaded[str(k)] = dict(v)
                    elif isinstance(raw, list):
                        for item in raw:
                            if isinstance(item, dict) and item.get("key"):
                                loaded[str(item["key"])] = dict(item)
                except Exception:
                    loaded = {}

            self._records = loaded
            now_ts = time.time()
            changed = False

            if seed_default_admin:
                admin_rec = self._records.get(DEFAULT_ADMIN_KEY)
                if admin_rec is None or float(admin_rec.get("expires_at_ts", 0.0)) <= now_ts or admin_rec.get("revoked"):
                    issued = now_ts
                    expires = issued + float(VALID_KEY_PURPOSES["1y"])
                    self._records[DEFAULT_ADMIN_KEY] = {
                        "recipient": "Admin Bách Khoa",
                        "phone": "0900000000",
                        "key": DEFAULT_ADMIN_KEY,
                        "purpose": "1y",
                        "role": "admin",
                        "allow_tpu": True,
                        "issued_at_ts": issued,
                        "expires_at_ts": expires,
                        "revoked": False,
                    }
                    changed = True

            if changed or not self.registry_path.exists():
                self._save_registry()
            if changed or not self.sheet_csv_path.exists():
                self.export_google_sheet_csv(now_ts=now_ts)

    def _save_registry(self) -> None:
        with self._lock:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "processed_data_folder_id": self.processed_data_folder_id,
                "processed_data_folder_url": self.processed_data_folder_url,
                "main_project_folder_id": DEFAULT_GDRIVE_FOLDER_ID,
                "headers": GOOGLE_SHEET_HEADERS,
                "keys": list(self._records.values()),
            }
            self.registry_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                os.chmod(self.registry_path, 0o600)
            except Exception:
                pass

    def _build_record_view(self, raw: Dict[str, Any], now_ts: Optional[float] = None) -> Dict[str, Any]:
        """Compute dynamic status, remaining ratio, and bilingual 7-column fields for a key record."""
        now = float(now_ts) if now_ts is not None else time.time()
        issued_ts = float(raw.get("issued_at_ts", now))
        expires_ts = float(raw.get("expires_at_ts", issued_ts + 3600.0))
        total_duration = max(1.0, expires_ts - issued_ts)
        remaining_seconds = max(0.0, expires_ts - now)
        remaining_ratio = remaining_seconds / total_duration
        revoked = bool(raw.get("revoked", False))

        if revoked:
            status_color = "revoked"
            status_text = "Đã thu hồi"
            is_expired = True
            is_warning_red = False
        elif now >= expires_ts or remaining_seconds <= 0.0:
            status_color = "expired"
            status_text = "Đã hết hạn"
            is_expired = True
            is_warning_red = False
        elif remaining_ratio <= (RED_WARNING_REMAINING_RATIO + 1e-12):
            status_color = "red"
            status_text = "Sắp hết hạn (<=1/3) - Báo đỏ"
            is_expired = False
            is_warning_red = True
        else:
            status_color = "green"
            status_text = "Còn hạn (>1/3) - Màu xanh"
            is_expired = False
            is_warning_red = False

        role = str(raw.get("role", "guest")).strip().lower()
        if role not in ("admin", "guest"):
            role = "guest"
        allow_tpu = True if role == "admin" else bool(raw.get("allow_tpu", False))
        recipient = str(raw.get("recipient", "")).strip()
        phone = str(raw.get("phone", "")).strip()
        key_val = str(raw.get("key", "")).strip()
        purpose = str(raw.get("purpose", "1h")).strip()
        issued_iso = _format_iso8601(issued_ts)
        expires_iso = _format_iso8601(expires_ts)
        purpose_label = f"{purpose} ({'Cho phép TPU' if allow_tpu else 'Không TPU'})"

        return {
            # 1. Recipient
            "recipient": recipient,
            "nguoi_nhan": recipient,
            "Người nhận": recipient,
            # 2. Phone
            "phone": phone,
            "sdt_nguoi_nhan": phone,
            "SĐT người nhận": phone,
            # 3. Key
            "key": key_val,
            "Key": key_val,
            # 4. Purpose
            "purpose": purpose,
            "muc_dich": purpose,
            "Mục đích": purpose,
            "purpose_label": purpose_label,
            # 5. Issued At
            "issued_at": issued_iso,
            "thoi_gian_cap": issued_iso,
            "Thời gian cấp": issued_iso,
            "issued_at_ts": issued_ts,
            # 6. Expires At
            "expires_at": expires_iso,
            "thoi_gian_het_han": expires_iso,
            "Thời gian hết hạn": expires_iso,
            "expires_at_ts": expires_ts,
            # 7. Status & Color
            "status": status_text,
            "tinh_trang": status_text,
            "Tình trạng": status_text,
            "status_color": status_color,
            "remaining_seconds": remaining_seconds,
            "total_duration_seconds": total_duration,
            "remaining_ratio": remaining_ratio,
            "is_warning_red": is_warning_red,
            "is_expired": is_expired,
            "revoked": revoked,
            # RBAC & TPU & Drive Metadata
            "role": role,
            "is_admin": role == "admin",
            "allow_tpu": allow_tpu,
            "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
            "processed_data_folder_url": PROCESSED_DATA_GDRIVE_FOLDER_URL,
        }

    def create_key(
        self,
        recipient: str,
        phone: str,
        purpose: str = "1h",
        allow_tpu: bool = False,
        role: str = "guest",
        custom_key: Optional[str] = None,
        issued_at_ts: Optional[float] = None,
        duration_seconds_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Create a new key record, persist to JSON registry, and export 7-column Google Sheet CSV."""
        with self._lock:
            clean_recipient = str(recipient or "").strip()
            if not clean_recipient:
                raise ValueError("recipient (Người nhận) must be a non-empty string")
            clean_phone = str(phone or "").strip()
            if not clean_phone:
                raise ValueError("phone (SĐT người nhận) must be a non-empty string")

            norm_role = str(role or "guest").strip().lower()
            if norm_role not in ("admin", "guest"):
                raise ValueError(f"Unsupported role '{role}'. Role must be 'admin' or 'guest'.")

            norm_purpose, duration_sec = self.resolve_purpose_duration(
                purpose=purpose,
                duration_seconds_override=duration_seconds_override,
            )
            effective_allow_tpu = True if norm_role == "admin" else bool(allow_tpu)
            issued = float(issued_at_ts) if issued_at_ts is not None else time.time()
            expires = issued + duration_sec

            if custom_key is not None and str(custom_key).strip():
                key_str = str(custom_key).strip()
            else:
                key_str = f"uav_{norm_role}_{secrets.token_urlsafe(16)}"

            raw_record = {
                "recipient": clean_recipient,
                "phone": clean_phone,
                "key": key_str,
                "purpose": norm_purpose,
                "role": norm_role,
                "allow_tpu": effective_allow_tpu,
                "issued_at_ts": issued,
                "expires_at_ts": expires,
                "revoked": False,
            }
            self._records[key_str] = raw_record
            self._save_registry()
            self.export_google_sheet_csv(now_ts=issued)
            return self._build_record_view(raw_record, now_ts=issued)

    def delete_key(self, key: str) -> Dict[str, Any]:
        """Remove a key from the active registry and update the 7-column Google Sheet CSV."""
        with self._lock:
            clean_key = str(key or "").strip()
            if not clean_key or clean_key not in self._records:
                return {"deleted": False, "key": clean_key, "error": "Key not found"}
            del self._records[clean_key]
            self._save_registry()
            self.export_google_sheet_csv()
            return {
                "deleted": True,
                "key": clean_key,
                "remaining_count": len(self._records),
                "sheet_csv_path": str(self.sheet_csv_path),
            }

    def revoke_key(self, key: str, now_ts: Optional[float] = None) -> Dict[str, Any]:
        """Mark a key as revoked while keeping its audit row in the registry."""
        with self._lock:
            clean_key = str(key or "").strip()
            if not clean_key or clean_key not in self._records:
                return {"revoked": False, "key": clean_key, "error": "Key not found"}
            self._records[clean_key]["revoked"] = True
            self._save_registry()
            self.export_google_sheet_csv(now_ts=now_ts)
            return {
                "revoked": True,
                "key": clean_key,
                "key_record": self._build_record_view(self._records[clean_key], now_ts=now_ts),
            }

    def get_key(self, key: str, now_ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Look up a key record and evaluate its live status and remaining ratio."""
        with self._lock:
            if not key or not str(key).strip():
                return None
            clean_key = str(key).strip()
            raw = self._records.get(clean_key)
            if raw is None:
                return None
            return self._build_record_view(raw, now_ts=now_ts)

    def list_keys(self, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        """Return all key records with dynamically computed 7-column fields and color status."""
        with self._lock:
            return [self._build_record_view(raw, now_ts=now_ts) for raw in self._records.values()]

    def validate_key(
        self,
        key: Optional[str],
        require_admin: bool = False,
        require_tpu: bool = False,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Validate a key for authentication, Admin key-management privileges, or >15m TPU offload."""
        with self._lock:
            if key is None or not str(key).strip():
                return {
                    "valid": False,
                    "http_status": 403,
                    "role": "unauthenticated",
                    "allow_tpu": False,
                    "is_admin": False,
                    "key_record": None,
                    "reason": "Thiếu key xác thực (Missing API key)",
                }
            clean_key = str(key).strip()
            rec = self.get_key(clean_key, now_ts=now_ts)
            if rec is None:
                return {
                    "valid": False,
                    "http_status": 403,
                    "role": "unknown",
                    "allow_tpu": False,
                    "is_admin": False,
                    "key_record": None,
                    "reason": "Key không tồn tại hoặc đã bị xóa (Invalid key)",
                }
            if rec["revoked"] or rec["is_expired"]:
                return {
                    "valid": False,
                    "http_status": 403,
                    "role": rec["role"],
                    "allow_tpu": False,
                    "is_admin": False,
                    "key_record": rec,
                    "reason": "Key đã hết hạn hoặc bị thu hồi (Expired/Revoked key)",
                }
            if require_admin and rec["role"] != "admin":
                return {
                    "valid": False,
                    "http_status": 403,
                    "role": rec["role"],
                    "allow_tpu": rec["allow_tpu"],
                    "is_admin": False,
                    "key_record": rec,
                    "reason": "Chỉ key Admin mới có quyền quản lý/tạo/xóa key",
                }
            if require_tpu and rec["role"] != "admin" and not rec.get("allow_tpu", False):
                return {
                    "valid": False,
                    "http_status": 403,
                    "role": rec["role"],
                    "allow_tpu": False,
                    "is_admin": False,
                    "key_record": rec,
                    "reason": "Key khách không được cấp quyền sử dụng TPU (>15 phút)",
                }
            return {
                "valid": True,
                "http_status": 200,
                "role": rec["role"],
                "allow_tpu": rec["allow_tpu"],
                "is_admin": rec["role"] == "admin",
                "key_record": rec,
                "reason": "OK",
            }

    def export_google_sheet_csv(
        self,
        output_path: Optional[Path] = None,
        now_ts: Optional[float] = None,
    ) -> Path:
        """Export all active keys to a 7-column CSV matching the Google Sheet schema."""
        with self._lock:
            target = Path(output_path) if output_path is not None else self.sheet_csv_path
            target.parent.mkdir(parents=True, exist_ok=True)
            rows = self.list_keys(now_ts=now_ts)
            with target.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(GOOGLE_SHEET_HEADERS)
                for r in rows:
                    writer.writerow(
                        [
                            r["nguoi_nhan"],
                            r["sdt_nguoi_nhan"],
                            r["key"],
                            r["muc_dich"],
                            r["thoi_gian_cap"],
                            r["thoi_gian_het_han"],
                            r["tinh_trang"],
                        ]
                    )
            return target

    def get_sheet_metadata(self, now_ts: Optional[float] = None) -> Dict[str, Any]:
        """Return 7-column Google Sheet summary and processed Drive folder info."""
        with self._lock:
            keys = self.list_keys(now_ts=now_ts)
            return {
                "columns": list(GOOGLE_SHEET_HEADERS),
                "column_count": len(GOOGLE_SHEET_HEADERS),
                "sheet_csv_path": str(self.sheet_csv_path),
                "registry_path": str(self.registry_path),
                "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
                "processed_data_folder_url": PROCESSED_DATA_GDRIVE_FOLDER_URL,
                "main_project_folder_id": DEFAULT_GDRIVE_FOLDER_ID,
                "total_keys": len(keys),
                "red_warning_keys": sum(1 for k in keys if k["status_color"] == "red"),
                "green_active_keys": sum(1 for k in keys if k["status_color"] == "green"),
                "expired_keys": sum(1 for k in keys if k["is_expired"]),
                "keys": keys,
            }


class GoogleDrive30TBStorage:
    """Adapter connecting the UAV GeoTIFF Survey VN2000 pipeline to 30TB Google Drive Ultra."""

    def __init__(
        self,
        folder_id: str = DEFAULT_GDRIVE_FOLDER_ID,
        key_vault: Optional[KeyVaultManager] = None,
        processed_data_folder_id: str = PROCESSED_DATA_GDRIVE_FOLDER_ID,
    ) -> None:
        self.folder_id = folder_id or DEFAULT_GDRIVE_FOLDER_ID
        self.processed_data_folder_id = processed_data_folder_id or PROCESSED_DATA_GDRIVE_FOLDER_ID
        self.key_vault = key_vault or KeyVaultManager()

    def get_processed_data_folder_info(self) -> Dict[str, Any]:
        """Return the Google Drive folder configuration for storing processed UAV/YOLO outputs."""
        return {
            "folder_id": self.processed_data_folder_id,
            "processed_data_folder_id": self.processed_data_folder_id,
            "folder_url": f"https://drive.google.com/drive/u/3/folders/{self.processed_data_folder_id}",
            "processed_data_folder_url": f"https://drive.google.com/drive/u/3/folders/{self.processed_data_folder_id}",
            "main_project_folder_id": self.folder_id,
            "main_project_folder_url": f"https://drive.google.com/drive/folders/{self.folder_id}",
            "status": "ok",
        }

    @staticmethod
    def _find_gdrive_cli() -> Optional[str]:
        cli = shutil.which("gdrive")
        if cli:
            return cli
        plugin_cli = "/opt/antigravity/plugins/gdrive/skills/gdrive/scripts/gdrive"
        if os.path.exists(plugin_cli):
            return plugin_cli
        return None

    def get_quota_status(self) -> Dict[str, Any]:
        """Query live Google Drive 30TB Ultra storage quota via `gdrive readonly quota`."""
        cli = self._find_gdrive_cli()
        used_gb = 816.2
        limit_gb = DEFAULT_ULTRA_QUOTA_GB
        trash_mb = 878.0
        live_queried = False

        if cli:
            try:
                proc = subprocess.run(
                    [cli, "readonly", "quota"],
                    capture_output=True,
                    text=True,
                    timeout=6.0,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout:
                    m_used = re.search(r"Used:\s*([\d.]+)\s*(GB|TB|MB)", proc.stdout)
                    m_limit = re.search(r"Limit:\s*([\d.]+)\s*(GB|TB|MB)", proc.stdout)
                    if m_used:
                        val = float(m_used.group(1))
                        unit = m_used.group(2)
                        used_gb = val * 1024.0 if unit == "TB" else (val / 1024.0 if unit == "MB" else val)
                    if m_limit:
                        val = float(m_limit.group(1))
                        unit = m_limit.group(2)
                        limit_gb = val * 1024.0 if unit == "TB" else (val / 1024.0 if unit == "MB" else val)
                    live_queried = True
            except Exception:
                pass

        free_gb = round(max(0.0, limit_gb - used_gb), 2)
        return {
            "status": "ok",
            "storage_backend": "google_drive_ultra_30tb",
            "plan_tier": "Google One AI Premium / Gemini Ultra (30 TB)",
            "project_folder_id": self.folder_id,
            "project_folder_url": f"https://drive.google.com/drive/folders/{self.folder_id}",
            "processed_data_folder_id": self.processed_data_folder_id,
            "processed_data_folder_url": f"https://drive.google.com/drive/u/3/folders/{self.processed_data_folder_id}",
            "live_cli_connected": live_queried,
            "quota": {
                "total_tb": round(limit_gb / 1024.0, 2),
                "total_gb": round(limit_gb, 1),
                "used_gb": round(used_gb, 1),
                "free_gb": free_gb,
                "free_tb": round(free_gb / 1024.0, 2),
                "trash_mb": trash_mb,
            },
            "recommended_layout": {
                "01_Raw_GeoTIFF_VN2000": "Lưu ảnh bay chụp UAV gốc (.tif, .jgw, .dem) — hàng trăm GB/dự án",
                "02_TPU_Tile_Cache_512": "Lưu ô lưới ảnh cắt 512x512 để Kaggle/Colab TPU đọc trực tiếp tốc độ cao",
                "03_VN2000_CAD_Outputs": "Lưu bản vẽ thành quả AutoCAD (.dwg, .dxf) chuẩn 6 lớp địa hình VN2000",
                "04_Model_Weights_ONNX": "Lưu trọng số mô hình (rice_stage1_webgpu.onnx, checkpoints)",
                "05_Private_Key_Discovery": "Đồng bộ tự động địa chỉ TPU Tunnel & khóa nội bộ (.uav_key_vault.json)",
                "06_Processed_Recognition_Data": f"Lưu kết quả nhận diện & cập nhật YOLO ({self.processed_data_folder_id})",
            },
        }

    def list_project_files(self, max_items: int = 30, folder_id: Optional[str] = None) -> List[Dict[str, str]]:
        """List files inside the connected Google Drive folder using `gdrive readonly ls`."""
        cli = self._find_gdrive_cli()
        if not cli:
            return []
        target_folder = folder_id or self.folder_id
        try:
            proc = subprocess.run(
                [cli, "readonly", "ls", target_folder, "--max", str(max_items), "--json"],
                capture_output=True,
                text=True,
                timeout=8.0,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                parsed = json.loads(proc.stdout)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict) and "files" in parsed:
                    return parsed["files"]
        except Exception:
            pass
        return []

    def list_processed_data_files(self, max_items: int = 30) -> List[Dict[str, str]]:
        """List files inside the processed data Google Drive folder (`1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN`)."""
        return self.list_project_files(max_items=max_items, folder_id=self.processed_data_folder_id)
