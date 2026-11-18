"""UAV GeoTIFF WebGPU Survey VN2000 Public Server, Admin Key Portal & >15m Auto-TPU Offload API.

Serves the web portal and REST APIs on the local machine's default port (8765,
with 8766 and 7860 compatibility) for zero-hosting custom domain access via
`https://thietbibachkhoa.id.vn/`:
  - GET  / , /webgpu.html , /MO_WEB_NHAN_DIEN_NGAY.html
  - GET  /api/health
  - GET  /api/domain-status
  - GET  /api/agent-tiers
  - POST /api/agent-tiers/divide-tasks
  - GET  /api/tpu/status
  - POST /api/tpu/infer
  - POST /api/detect/upload       (>15m auto-TPU offload + Admin/Guest allow_tpu RBAC)
  - POST /api/yolo/update         (>15m auto-TPU offload + Admin/Guest allow_tpu RBAC)
  - POST /api/auth/verify-key     (Verify Admin vs Guest key & unlock Admin UI)
  - GET  /api/keys                (Admin-only 7-column Google Sheet key table; 403 for Guest)
  - POST /api/keys , /api/keys/create (Admin-only key creation with allow_tpu; 403 for Guest)
  - POST /api/keys/delete , DELETE /api/keys/<key> (Admin-only key deletion; 403 for Guest)
  - GET  /api/gdrive/processed-folder (Processed data folder 1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN)
"""

from __future__ import annotations

import argparse
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from uav_app.adapters.tpu_offload_worker import (
    PROCESSED_DATA_GDRIVE_FOLDER_ID,
    PROCESSED_DATA_GDRIVE_FOLDER_URL,
    TPU_AUTO_OFFLOAD_THRESHOLD_MINUTES,
    TPU_AUTO_OFFLOAD_THRESHOLD_SECONDS,
    TPUOffloadError,
    TPUOffloadWorker,
    VN2000_TERRAIN_CLASSES,
)
from uav_app.infrastructure.agent_governance import AgentGovernancePolicy
from uav_app.infrastructure.autostart_host import (
    CUSTOM_DOMAIN,
    CUSTOM_DOMAIN_URL,
    DEFAULT_PORT,
    AutostartHostManager,
    get_default_port,
)
from uav_app.infrastructure.gdrive_key_storage import (
    DEFAULT_ADMIN_KEY,
    DEFAULT_GDRIVE_FOLDER_ID,
    GOOGLE_SHEET_HEADERS,
    GoogleDrive30TBStorage,
    GoogleSheetKeyManager,
    KeyVaultManager,
)


_CACHED_PORTAL_HTML: Optional[str] = None


def render_webgpu_portal_html(port: int = DEFAULT_PORT, domain: str = CUSTOM_DOMAIN) -> str:
    """Render the UAV GeoTIFF Studio VN2000 HTML portal with Single-Input Key Gate & 4-Step Studio UI."""
    global _CACHED_PORTAL_HTML
    if _CACHED_PORTAL_HTML is None:
        from pathlib import Path
        mo_path = Path(__file__).resolve().parents[2] / "MO_WEB_NHAN_DIEN_NGAY.html"
        if mo_path.is_file():
            _CACHED_PORTAL_HTML = mo_path.read_text(encoding="utf-8")
    if _CACHED_PORTAL_HTML:
        return _CACHED_PORTAL_HTML.replace("thietbibachkhoa.id.vn", domain).replace(":8765", f":{port}")
    return f"<html><body>UAV GeoTIFF Studio VN2000 — https://{domain}/ (Port {port})</body></html>"


class WebGPUPublicServer(ThreadingHTTPServer):
    """ThreadingHTTPServer holding references to TPUOffloadWorker, AgentGovernancePolicy, AutostartHostManager, and GoogleSheetKeyManager."""

    allow_reuse_address = True
    request_queue_size = 128

    def __init__(
        self,
        server_address: Tuple[str, int],
        RequestHandlerClass: Any,
        tpu_worker: Optional[TPUOffloadWorker] = None,
        governance_policy: Optional[AgentGovernancePolicy] = None,
        autostart_manager: Optional[AutostartHostManager] = None,
        key_manager: Optional[GoogleSheetKeyManager] = None,
        gdrive_storage: Optional[GoogleDrive30TBStorage] = None,
        key_vault: Optional[KeyVaultManager] = None,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.tpu_worker = tpu_worker or TPUOffloadWorker()
        self.governance_policy = governance_policy or AgentGovernancePolicy()
        self.key_vault = key_vault or KeyVaultManager()
        self.key_manager = key_manager or GoogleSheetKeyManager()
        self.gdrive_storage = gdrive_storage or GoogleDrive30TBStorage(key_vault=self.key_vault)
        actual_port = int(self.server_address[1])
        self.autostart_manager = autostart_manager or AutostartHostManager(
            port=actual_port, domain=CUSTOM_DOMAIN
        )
        self.autostart_manager._running = True
        self.autostart_manager.port = actual_port


class WebGPUPublicRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for UAV GeoTIFF WebGPU Survey VN2000."""

    server_version = "UAVWebGPUPublicServer/3.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    @property
    def app_server(self) -> WebGPUPublicServer:
        return self.server  # type: ignore[return-value]

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Custom-Domain", CUSTOM_DOMAIN)
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, status_code: int, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Custom-Domain", CUSTOM_DOMAIN)
        self.end_headers()
        self.wfile.write(raw)

    def _extract_caller_key(
        self,
        body: Optional[Dict[str, Any]] = None,
        prefer_admin_field: bool = False,
    ) -> Optional[str]:
        """Extract API/Admin key from headers, query string, or JSON body."""
        for hdr in ("X-Admin-Key", "X-API-Key", "X-TPU-API-Key"):
            val = self.headers.get(hdr)
            if val and val.strip():
                return val.strip()

        auth = self.headers.get("Authorization")
        if auth and auth.strip():
            clean_auth = auth.strip()
            if clean_auth.lower().startswith("bearer "):
                return clean_auth[7:].strip()
            return clean_auth

        if "?" in self.path:
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1])
            for qk in ("admin_key", "key", "api_key"):
                if qk in qs and qs[qk]:
                    return str(qs[qk][0]).strip()

        if isinstance(body, dict):
            fields = (
                ("admin_key", "auth_key", "api_key", "key")
                if prefer_admin_field
                else ("key", "api_key", "admin_key", "auth_key")
            )
            for f in fields:
                v = body.get(f)
                if v and str(v).strip():
                    return str(v).strip()
        return None

    def _read_json_body(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        if not raw_body:
            return {}, None
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            return None, f"Invalid JSON body: {exc}"
        if not isinstance(parsed, dict):
            return None, "JSON payload must be an object"
        return parsed, None

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        actual_port = int(self.app_server.server_address[1])

        if path in ("/", "/webgpu.html", "/index.html", "/advanced.html", "/MO_WEB_NHAN_DIEN_NGAY.html"):
            html = render_webgpu_portal_html(port=actual_port, domain=CUSTOM_DOMAIN)
            self._send_html(200, html)
            return

        if path == "/api/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "online": True,
                    "domain": CUSTOM_DOMAIN,
                    "url": CUSTOM_DOMAIN_URL,
                    "custom_domain_url": CUSTOM_DOMAIN_URL,
                    "port": actual_port,
                    "default_port": DEFAULT_PORT,
                    "service": "uav-geotiff-webgpu-vn2000",
                    "power_coupled": True,
                    "vn2000_classes": list(VN2000_TERRAIN_CLASSES.keys()),
                    "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
                    "processed_data_folder_url": PROCESSED_DATA_GDRIVE_FOLDER_URL,
                    "main_project_folder_id": DEFAULT_GDRIVE_FOLDER_ID,
                    "auto_tpu_threshold_seconds": TPU_AUTO_OFFLOAD_THRESHOLD_SECONDS,
                    "auto_tpu_threshold_minutes": TPU_AUTO_OFFLOAD_THRESHOLD_MINUTES,
                },
            )
            return

        if path == "/api/domain-status":
            status = self.app_server.autostart_manager.get_domain_lifecycle_status()
            status["server_running"] = True
            status["port"] = actual_port
            status["processed_data_folder_id"] = PROCESSED_DATA_GDRIVE_FOLDER_ID
            status["processed_data_folder_url"] = PROCESSED_DATA_GDRIVE_FOLDER_URL
            self._send_json(200, status)
            return

        if path == "/api/agent-tiers":
            summary = self.app_server.governance_policy.get_status_summary()
            self._send_json(200, summary)
            return

        if path == "/api/agent-tiers/divide-tasks":
            division = self.app_server.governance_policy.auto_divide_and_spawn_tasks()
            self._send_json(200, division)
            return

        if path == "/api/tpu/status":
            tpu_status = self.app_server.tpu_worker.check_remote_tpu_health()
            self._send_json(200, tpu_status)
            return

        if path in ("/api/gdrive/processed-folder", "/api/storage-keys/status"):
            info = self.app_server.gdrive_storage.get_processed_data_folder_info()
            info["quota_status"] = self.app_server.gdrive_storage.get_quota_status()
            info["key_vault"] = self.app_server.key_vault.get_masked_status()
            self._send_json(200, info)
            return

        if path in ("/api/firewall/status", "/api/firewall/probe"):
            from uav_app.infrastructure.firewall_bypass import OutboundCloudBridge, probe_corporate_firewall

            probe = probe_corporate_firewall(port=self.app_server.server_address[1])
            bridge = OutboundCloudBridge()
            probe["outbound_bridge"] = bridge.get_bridge_status()
            self._send_json(200, probe)
            return

        if path in ("/api/keys", "/api/keys/sheet"):
            caller_key = self._extract_caller_key(prefer_admin_field=True)
            auth = self.app_server.key_manager.validate_key(caller_key, require_admin=True)
            if not auth["valid"]:
                self._send_json(
                    403,
                    {
                        "status": "forbidden",
                        "http_status": 403,
                        "admin_panel_visible": False,
                        "error": auth["reason"],
                    },
                )
                return
            meta = self.app_server.key_manager.get_sheet_metadata()
            meta["status"] = "ok"
            meta["admin_panel_visible"] = True
            self._send_json(200, meta)
            return

        if path == "/api/fpga/status":
            res = self.app_server.tpu_worker.run_fpga_parallel_edges(payload={"width": 256, "height": 256})
            self._send_json(200, res)
            return

        self._send_json(404, {"error": "Endpoint not found", "path": path})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/api/tpu/infer":
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(content_length) if content_length > 0 else b""
            if not raw_body:
                self._send_json(400, {"error": "Request body is empty; expected JSON with 'tiles' list"})
                return
            try:
                body = json.loads(raw_body.decode("utf-8"))
            except Exception as exc:
                self._send_json(400, {"error": f"Invalid JSON body: {exc}"})
                return
            if not isinstance(body, dict):
                self._send_json(400, {"error": "JSON payload must be an object containing 'tiles'"})
                return

            tiles = body.get("tiles")
            metadata = body.get("metadata") or {}
            if not isinstance(tiles, list) or len(tiles) == 0:
                self._send_json(400, {"error": "Field 'tiles' must be a non-empty list of tile dicts"})
                return

            try:
                result = self.app_server.tpu_worker.infer_tile_batch(tiles, metadata=metadata)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except TPUOffloadError as exc:
                self._send_json(503, {"error": str(exc)})
                return

            result["processed_data_folder_id"] = PROCESSED_DATA_GDRIVE_FOLDER_ID
            result["processed_data_folder_url"] = PROCESSED_DATA_GDRIVE_FOLDER_URL
            self._send_json(200, result)
            return

        body, err = self._read_json_body()
        if err is not None or body is None:
            self._send_json(400, {"error": err or "Invalid JSON body"})
            return

        if path == "/api/agent-tiers/divide-tasks":
            tasks = body.get("tasks") if isinstance(body.get("tasks"), list) else None
            plan_id = str(body.get("plan_id") or "plan_auto")
            try:
                division = self.app_server.governance_policy.auto_divide_and_spawn_tasks(
                    tasks=tasks,
                    plan_id=plan_id,
                )
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, division)
            return

        if path == "/api/auth/verify-key":
            caller_key = self._extract_caller_key(body=body, prefer_admin_field=False)
            now_ts = body.get("now_ts")
            auth = self.app_server.key_manager.validate_key(caller_key, now_ts=now_ts)
            is_admin = bool(auth["valid"] and auth.get("is_admin"))
            payload = {
                "status": "ok" if auth["valid"] else "forbidden",
                "valid": auth["valid"],
                "http_status": auth["http_status"],
                "role": auth["role"],
                "is_admin": is_admin,
                "allow_tpu": auth["allow_tpu"],
                "admin_panel_visible": is_admin,
                "can_create_or_delete_keys": is_admin,
                "key_record": auth["key_record"],
                "reason": auth["reason"],
                "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
                "processed_data_folder_url": PROCESSED_DATA_GDRIVE_FOLDER_URL,
            }
            self._send_json(200 if auth["valid"] else 403, payload)
            return

        if path in ("/api/keys", "/api/keys/create"):
            admin_key = self._extract_caller_key(body=body, prefer_admin_field=True)
            auth = self.app_server.key_manager.validate_key(admin_key, require_admin=True)
            if not auth["valid"]:
                self._send_json(
                    403,
                    {
                        "status": "forbidden",
                        "http_status": 403,
                        "admin_panel_visible": False,
                        "error": auth["reason"],
                    },
                )
                return

            recipient = body.get("recipient") or body.get("nguoi_nhan") or body.get("Người nhận")
            phone = body.get("phone") or body.get("sdt_nguoi_nhan") or body.get("SĐT người nhận")
            purpose = body.get("purpose") or body.get("muc_dich") or body.get("Mục đích") or "1h"
            allow_tpu = bool(body.get("allow_tpu", False))
            role = str(body.get("role") or "guest")
            custom_key = body.get("custom_key") or body.get("new_key")
            issued_at_ts = body.get("issued_at_ts")
            duration_override = body.get("duration_seconds_override")

            try:
                created = self.app_server.key_manager.create_key(
                    recipient=str(recipient or ""),
                    phone=str(phone or ""),
                    purpose=str(purpose),
                    allow_tpu=allow_tpu,
                    role=role,
                    custom_key=str(custom_key) if custom_key else None,
                    issued_at_ts=float(issued_at_ts) if issued_at_ts is not None else None,
                    duration_seconds_override=float(duration_override) if duration_override is not None else None,
                )
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return

            self._send_json(
                200,
                {
                    "status": "ok",
                    "created": True,
                    "key_record": created,
                    "columns": list(GOOGLE_SHEET_HEADERS),
                    "keys": self.app_server.key_manager.list_keys(),
                },
            )
            return

        if path == "/api/keys/delete":
            admin_key = self._extract_caller_key(body=body, prefer_admin_field=True)
            auth = self.app_server.key_manager.validate_key(admin_key, require_admin=True)
            if not auth["valid"]:
                self._send_json(
                    403,
                    {
                        "status": "forbidden",
                        "http_status": 403,
                        "admin_panel_visible": False,
                        "error": auth["reason"],
                    },
                )
                return

            target_key = str(body.get("target_key") or body.get("key_to_delete") or body.get("key") or "").strip()
            if not target_key:
                self._send_json(400, {"error": "Missing 'key' or 'target_key' to delete"})
                return

            res = self.app_server.key_manager.delete_key(target_key)
            if not res.get("deleted"):
                self._send_json(404, {"status": "not_found", "deleted": False, "error": res.get("error")})
                return
            res["status"] = "ok"
            res["keys"] = self.app_server.key_manager.list_keys()
            self._send_json(200, res)
            return

        if path in ("/api/detect/upload", "/api/detect"):
            caller_key = self._extract_caller_key(body=body, prefer_admin_field=False)
            key_info = self._resolve_request_key_info(caller_key, body)
            try:
                res = self.app_server.tpu_worker.detect_uploaded_images(payload=body, key_info=key_info)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except TPUOffloadError as exc:
                self._send_json(503, {"error": str(exc)})
                return
            status_code = int(res.get("http_status", 200))
            self._send_json(status_code, res)
            return

        if path in ("/api/yolo/update", "/api/yolo/train"):
            caller_key = self._extract_caller_key(body=body, prefer_admin_field=False)
            key_info = self._resolve_request_key_info(caller_key, body)
            try:
                res = self.app_server.tpu_worker.update_yolo_model(payload=body, key_info=key_info)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except TPUOffloadError as exc:
                self._send_json(503, {"error": str(exc)})
                return
            status_code = int(res.get("http_status", 200))
            self._send_json(status_code, res)
            return

        if path in ("/api/rtk/restore-crown", "/api/orthomosaic/patch-replace"):
            caller_key = self._extract_caller_key(body=body, prefer_admin_field=False)
            key_info = self._resolve_request_key_info(caller_key, body)
            try:
                res = self.app_server.tpu_worker.restore_rtk_crown_patch(payload=body, key_info=key_info)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except TPUOffloadError as exc:
                self._send_json(503, {"error": str(exc)})
                return
            status_code = int(res.get("http_status", 200))
            self._send_json(status_code, res)
            return

        if path in ("/api/fpga/parallel-edges", "/api/fpga/accelerate"):
            try:
                res = self.app_server.tpu_worker.run_fpga_parallel_edges(payload=body)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, res)
            return

        self._send_json(404, {"error": "Endpoint not found", "path": path})

    def do_DELETE(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/keys/"):
            target_key = urllib.parse.unquote(path[len("/api/keys/") :]).strip()
            body, _ = self._read_json_body()
            admin_key = self._extract_caller_key(body=body, prefer_admin_field=True)
            auth = self.app_server.key_manager.validate_key(admin_key, require_admin=True)
            if not auth["valid"]:
                self._send_json(
                    403,
                    {
                        "status": "forbidden",
                        "http_status": 403,
                        "admin_panel_visible": False,
                        "error": auth["reason"],
                    },
                )
                return
            res = self.app_server.key_manager.delete_key(target_key)
            if not res.get("deleted"):
                self._send_json(404, {"status": "not_found", "deleted": False, "error": res.get("error")})
                return
            res["status"] = "ok"
            self._send_json(200, res)
            return

        self._send_json(404, {"error": "Endpoint not found", "path": path})

    def _resolve_request_key_info(
        self,
        caller_key: Optional[str],
        body: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if isinstance(body.get("key_info"), dict):
            return body["key_info"]
        if caller_key:
            return self.app_server.key_manager.validate_key(caller_key)
        if "role" in body or "allow_tpu" in body:
            role_val = str(body.get("role") or "guest").strip().lower()
            return {
                "valid": True,
                "role": role_val,
                "is_admin": role_val == "admin",
                "allow_tpu": True if role_val == "admin" else bool(body.get("allow_tpu", False)),
            }
        return {
            "valid": False,
            "role": "unauthenticated",
            "is_admin": False,
            "allow_tpu": False,
            "reason": "Thiếu key xác thực cho tác vụ >15 phút trên TPU",
        }


def make_public_webgpu_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    tpu_worker: Optional[TPUOffloadWorker] = None,
    governance_policy: Optional[AgentGovernancePolicy] = None,
    autostart_manager: Optional[AutostartHostManager] = None,
    key_manager: Optional[GoogleSheetKeyManager] = None,
    gdrive_storage: Optional[GoogleDrive30TBStorage] = None,
) -> WebGPUPublicServer:
    """Create an instance of WebGPUPublicServer bound to (host, port)."""
    return WebGPUPublicServer(
        (host, port),
        WebGPUPublicRequestHandler,
        tpu_worker=tpu_worker,
        governance_policy=governance_policy,
        autostart_manager=autostart_manager,
        key_manager=key_manager,
        gdrive_storage=gdrive_storage,
    )


def start_background_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    tpu_worker: Optional[TPUOffloadWorker] = None,
    governance_policy: Optional[AgentGovernancePolicy] = None,
    autostart_manager: Optional[AutostartHostManager] = None,
    key_manager: Optional[GoogleSheetKeyManager] = None,
    gdrive_storage: Optional[GoogleDrive30TBStorage] = None,
) -> Tuple[WebGPUPublicServer, threading.Thread]:
    """Start WebGPUPublicServer in a daemon background thread and return (server, thread)."""
    server = make_public_webgpu_server(
        host=host,
        port=port,
        tpu_worker=tpu_worker,
        governance_policy=governance_policy,
        autostart_manager=autostart_manager,
        key_manager=key_manager,
        gdrive_storage=gdrive_storage,
    )
    thread = threading.Thread(target=server.serve_forever, name="UAVWebGPUPublicServer", daemon=True)
    thread.start()
    return server, thread


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="UAV GeoTIFF WebGPU Survey VN2000 Server (https://thietbibachkhoa.id.vn/)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument(
        "--port",
        type=int,
        default=get_default_port(),
        help="Bind port (default: 8765 or UAV_WEB_PORT)",
    )
    args = parser.parse_args(argv)

    server = make_public_webgpu_server(host=args.host, port=args.port)
    actual_port = server.server_address[1]
    print(
        f"[UAV WebGPU Server] Serving https://{CUSTOM_DOMAIN}/ on http://{args.host}:{actual_port} "
        f"(Processed Data Drive Folder: {PROCESSED_DATA_GDRIVE_FOLDER_ID}) ..."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
