"""Loopback-only application server; no raster upload or cloud access."""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from uav_app.adapters.autostart_and_argon_routes import (
    handle_automation_get,
    handle_automation_post,
)
from uav_app.application.service import ProjectService


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can let two processes serve the same endpoint.
    # Reserve it before opening state, so a duplicate launch cannot recover
    # the first process's live job as if it had crashed.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(project_root: Path, app_root: Path, port: int) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(32)
    browse_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Avoid logging full local input paths or future credentials.
            pass

        def send_content(self, status: int, data: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.end_headers()
            self.wfile.write(data)

        def json_response(self, status, data):
            payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_content(status, payload, "application/json; charset=utf-8")

        def valid_origin(self):
            host_hdr = (self.headers.get("Host") or "").strip()
            if not host_hdr:
                return False
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            return origin in (f"http://{host_hdr}", f"https://{host_hdr}")

        def do_GET(self):
            if not self.valid_origin():
                self.json_response(403, {"error": "Chỉ cho phép ứng dụng local cùng nguồn."})
                return
            try:
                parsed = urlsplit(self.path)
                route = unquote(parsed.path)
                if route == "/api/health":
                    self.json_response(200, {"status": "ok", "phase": 1})
                elif route == "/api/state":
                    state = service.store.read()
                    self.json_response(200, {"state": state, "token": token,
                        "proposals": state.get("pending_proposals", []),
                        "defaults": state["active_pipeline_config"],
                        "project_root": str(service.root), "detection_defaults": service.detection_settings(),
                        "turbo_status": service.turbo_status()})
                elif route == "/api/turbo/status":
                    self.json_response(200, service.turbo_status())
                elif route == "/api/job":
                    self.json_response(200, service.job())
                elif route == "/api/telemetry":
                    self.json_response(200, service.telemetry())
                elif route == "/api/results":
                    query=parse_qs(parsed.query)
                    self.json_response(200,service.results(int(query.get("offset",["0"])[0]),int(query.get("limit",["50"])[0]),query.get("filter",["all"])[0]))
                elif route == "/api/results-boxes":
                    query=parse_qs(parsed.query)
                    self.json_response(200,service.results_boxes(query.get("job",[None])[0]))
                elif route == "/api/sessions":
                    self.json_response(200,service.list_sessions())
                elif route == "/api/survey/library":
                    query=parse_qs(parsed.query)
                    lib_path=query.get("path",[None])[0]
                    self.json_response(200,service.survey_library(lib_path))
                elif route in {"/api/terrain/scale-specs", "/api/terrain-9classes/scale-specs"}:
                    query = parse_qs(parsed.query)
                    raw_sc = query.get("map_scale", [None])[0]
                    sc_val = int(raw_sc) if raw_sc and str(raw_sc).strip().isdigit() else None
                    self.json_response(200, service.terrain_scale_specs(map_scale=sc_val))
                elif route in {"/api/terrain/dxf", "/api/terrain-9classes/dxf"}:
                    query = parse_qs(parsed.query)
                    raw_sc = query.get("map_scale", [None])[0]
                    sc_val = int(raw_sc) if raw_sc and str(raw_sc).strip().isdigit() else None
                    dxf_path = service.terrain_dxf_file(map_scale=sc_val)
                    self.send_content(200, dxf_path.read_bytes(), "application/dxf")
                elif route in {"/api/terrain/dwg", "/api/terrain-9classes/dwg"}:
                    query = parse_qs(parsed.query)
                    raw_sc = query.get("map_scale", [None])[0]
                    sc_val = int(raw_sc) if raw_sc and str(raw_sc).strip().isdigit() else None
                    dwg_path = service.terrain_dwg_file(map_scale=sc_val)
                    self.send_content(200, dwg_path.read_bytes(), "application/acad")
                elif route == "/api/terrain/train-status":
                    self.json_response(200, service.terrain_train_status())
                elif (auto_get := handle_automation_get(route, parse_qs(parsed.query), project_root, app_root)) is not None:
                    self.json_response(200, auto_get)
                elif route == "/api/webgpu/licenses":
                    self.json_response(200, service.webgpu_licenses())
                elif route == "/api/webgpu/model-stream":
                    query = parse_qs(parsed.query)
                    lease_tok = query.get("lease", [""])[0]
                    self.send_content(200, service.webgpu_model_stream(lease_tok), "application/octet-stream")
                elif route == "/api/webgpu/demo-geotiff":
                    self.send_content(200, service.webgpu_demo_geotiff(), "image/tiff")
                elif route == "/api/result-file":
                    query=parse_qs(parsed.query)
                    path=service.result_file(query.get("name",[""])[0],query.get("job",[None])[0])
                    kind=mimetypes.guess_type(str(path))[0] or "application/octet-stream"
                    self.send_content(200,path.read_bytes(),kind)
                elif route == "/api/warp-preview":
                    query=parse_qs(parsed.query)
                    self.send_content(200,service.preview_warp(query.get("signature",[""])[0]),"image/png")
                elif route == "/api/preview":
                    query = parse_qs(parsed.query)
                    path = query.get("path", [""])[0]
                    window_keys = ("col", "row", "width", "height")
                    window = None
                    if any(k in query for k in window_keys):
                        if not all(k in query for k in window_keys):
                            raise ValueError("Cửa sổ xem trước phải có col, row, width, height.")
                        window = {k: int(query[k][0]) for k in window_keys}
                    self.send_content(200, service.preview(path, window), "image/png")
                else:
                    if route.startswith("/vendor/three/"):
                        root = app_root / "node_modules" / "three"
                        relative = route[len("/vendor/three/"):]
                    elif route.startswith("/vendor/ort/"):
                        root = app_root / "node_modules" / "onnxruntime-web" / "dist"
                        relative = route[len("/vendor/ort/"):]
                    elif route.startswith("/vendor/geotiff/"):
                        root = app_root / "node_modules" / "geotiff" / "dist-browser"
                        relative = route[len("/vendor/geotiff/"):]
                    elif route.startswith("/vendor/anime/"):
                        root = app_root.parent / "skills" / "anime-master" / "dist" / "bundles"
                        relative = route[len("/vendor/anime/"):]
                    elif route in {"/graph.html", "/callflow.html", "/graph.json", "/GRAPH_REPORT.md"}:
                        root = app_root / "graphify-out"
                        relative = route.lstrip("/")
                    else:
                        root = app_root / "ui"
                        relative = route.lstrip("/") or "index.html"
                    requested = (root / relative).resolve()
                    if not requested.is_relative_to(root.resolve()) or not requested.is_file():
                        self.json_response(404, {"error": "Không tìm thấy tài nguyên."})
                        return
                    sfx = requested.suffix.lower()
                    if sfx in {".js", ".mjs"}:
                        kind = "text/javascript"
                    elif sfx == ".wasm":
                        kind = "application/wasm"
                    elif sfx == ".css":
                        kind = "text/css; charset=utf-8"
                    elif sfx == ".html":
                        kind = "text/html; charset=utf-8"
                    else:
                        kind = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
                    self.send_content(200, requested.read_bytes(), kind)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except Exception as error:
                self.json_response(400, {"error": str(error)})

        def do_POST(self):
            if not self.valid_origin() or not secrets.compare_digest(
                self.headers.get("X-Session-Token", ""), token
            ):
                self.json_response(403, {"error": "Yêu cầu không có mã phiên hợp lệ."})
                return
            try:
                route = urlsplit(self.path).path
                size = int(self.headers.get("Content-Length", "0"))
                max_body = 16 * 1024 * 1024 if route == "/api/terrain/dwg" else 65536
                if size < 0 or size > max_body:
                    raise ValueError("Yêu cầu vượt quá kích thước cho phép.")
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    raise ValueError("Yêu cầu phải dùng JSON.")
                data = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Yêu cầu phải là một đối tượng JSON.")
                if route == "/api/inspect":
                    result = service.inspect(data.get("path", ""))
                elif route == "/api/plan":
                    result = service.plan(data.get("path", ""), data.get("config", {}))
                elif route == "/api/export":
                    result = service.start_export(data.get("path", ""), data.get("config", {}))
                elif route == "/api/cancel":
                    result = service.cancel()
                elif route == "/api/pause":
                    result = service.pause()
                elif route in {"/api/detect/resume", "/api/resume-detection"}:
                    result = service.resume_detection(data.get("job_id") or data.get("id"))
                elif route == "/api/detection-settings":
                    result=service.save_settings(data.get("settings",{}))
                elif route == "/api/detection-plan":
                    result=service.detection_plan(data.get("path",""),data.get("config",{}),data.get("settings",{}),data.get("scope","selected"),data.get("tile_id","tile_000001"),regions=data.get("regions"))
                elif route == "/api/detect":
                    result=service.start_detection(data.get("path",""),data.get("config",{}),data.get("settings",{}),data.get("scope","selected"),data.get("tile_id","tile_000001"),regions=data.get("regions"),sr_mode=data.get("sr_mode"),spectral_mode=data.get("spectral_mode"))
                elif route == "/api/sr-enhance":
                    result=service.sr_enhance_object(data.get("id",""),data.get("job_id"),data.get("mode","ttst"),data.get("scale",2))
                elif route == "/api/review":
                    result=service.review(data.get("id"),data.get("decision"),data.get("revision"),data.get("job_id"),sub_class=data.get("sub_class"),custom_box=data.get("custom_box"),offset=data.get("offset"))
                elif route == "/api/export-cad":
                    result=service.export_cad(data.get("revision"),data.get("job_id"))
                elif route == "/api/export-dwg":
                    result=service.export_autocad_dwg(data.get("revision"),data.get("job_id"))
                elif route == "/api/fuse-results":
                    result=service.fuse_existing(data.get("revision"),data.get("job_id"),data.get("mode","smart_overlap"),data.get("threshold",0.50),data.get("stitch_large",True))
                elif route == "/api/enrich-dem":
                    result=service.enrich_dem(data.get("revision"),data.get("job_id"),data.get("dem_path"))
                elif route == "/api/dem/repair":
                    result=service.repair_dem(data.get("dem_path"),data.get("min_valid_z"),data.get("job_id"))
                elif route == "/api/enrich-multispectral":
                    result=service.enrich_multispectral(data.get("revision"),data.get("job_id"),data.get("source_path"))
                elif route == "/api/split-clumps":
                    result=service.split_clumps(data.get("revision"),data.get("job_id"),data.get("object_id") or data.get("id"))
                elif route == "/api/auto-triage":
                    result=service.auto_triage(data.get("revision"),data.get("job_id"),data.get("threshold",0.72))
                elif route == "/api/dataset-export":
                    result=service.save_ground_truth(data.get("job_id"))
                elif route == "/api/turbo/train":
                    result=service.start_turbo_training(data.get("mode", "both"), int(data.get("epochs", 50)))
                elif route == "/api/sessions/load":
                    result=service.load_session(data.get("id",""))
                elif route == "/api/survey/library":
                    result=service.survey_library(data.get("path"))
                elif route == "/api/survey/rules":
                    result=service.save_survey_rules(data.get("rules",[]),data.get("library_path"))
                elif route == "/api/survey/export":
                    result=service.export_survey_cad(
                        data.get("job_id"),
                        rules=data.get("rules"),
                        library_path=data.get("library_path"),
                        survey_polylines=data.get("survey_polylines"),
                        include_unreviewed=data.get("include_unreviewed",True),
                    )
                elif route in {"/api/terrain/segment", "/api/terrain-9classes"}:
                    query = parse_qs(parsed.query)
                    raw_sc = data.get("map_scale") or query.get("map_scale", [500])[0]
                    result = service.segment_terrain_cad(
                        path=data.get("path"),
                        base=data.get("base"),
                        enabled_classes=data.get("enabled_classes"),
                        region_window=data.get("region_window"),
                        job_id=data.get("job_id"),
                        map_scale=int(raw_sc or 500),
                    )
                elif route in {"/api/terrain/dxf", "/api/terrain-9classes/dxf"}:
                    query = parse_qs(parsed.query)
                    raw_sc = data.get("map_scale") or query.get("map_scale", [None])[0]
                    sc_val = int(raw_sc) if raw_sc is not None and str(raw_sc).strip().isdigit() else None
                    dxf_path = service.terrain_dxf_file(map_scale=sc_val)
                    self.send_content(200, dxf_path.read_bytes(), "application/dxf")
                    return
                elif route in {"/api/terrain/dwg", "/api/terrain-9classes/dwg"}:
                    query = parse_qs(parsed.query)
                    raw_sc = data.get("map_scale") or query.get("map_scale", [None])[0]
                    sc_val = int(raw_sc) if raw_sc is not None and str(raw_sc).strip().isdigit() else None
                    dwg_path = service.terrain_dwg_file(dxf_content=data.get("dxf_content"), map_scale=sc_val)
                    self.send_content(200, dwg_path.read_bytes(), "application/acad")
                    return
                elif route == "/api/terrain/train-dwg":
                    result = service.train_terrain_from_dwg(
                        survey_roots=data.get("survey_roots"),
                        steps=int(data.get("steps") or 160),
                    )
                elif route == "/api/webgpu/auth":
                    result = service.webgpu_auth(
                        license_key=data.get("license_key", ""),
                        device_fingerprint=data.get("device_fingerprint", ""),
                        gpu_label=data.get("gpu_label", ""),
                        model_id=data.get("model_id", "terrain_seg"),
                    )
                elif route == "/api/webgpu/quota":
                    result = service.webgpu_consume_quota(
                        license_key=data.get("license_key", ""),
                        area_ha=float(data.get("area_ha") or 0.01),
                    )
                elif route == "/api/webgpu/license/create":
                    result = service.webgpu_create_license(
                        owner=data.get("owner", "Khách hàng mới"),
                        plan=data.get("plan", "Pro Survey WebGPU"),
                        quota_ha=float(data.get("quota_ha") or 200.0),
                        max_devices=int(data.get("max_devices") or 2),
                        days_valid=int(data.get("days_valid") or 365),
                    )
                elif route == "/api/webgpu/license/action":
                    result = service.webgpu_license_action(
                        key=data.get("key", ""),
                        action=data.get("action", ""),
                    )
                elif route == "/api/evaluate":
                    result=service.evaluate(data.get("path",""),data.get("job_id"))
                elif route == "/api/advise":
                    result=service.advise(data.get("request",""),data.get("provider","local"),data.get("api_key",""),data.get("model",""),data.get("workspace",""))
                elif route == "/api/warp-plan":
                    result=service.prepare_warp(data.get("path",""),data.get("target_crs",""),data.get("resolution_cm"),data.get("resampling","bilinear"))
                elif route == "/api/warp":
                    result=service.start_warp(data.get("signature",""))
                elif route == "/api/proposal":
                    result = service.decide(data.get("id"), data.get("decision"))
                elif route == "/api/open-output":
                    import os
                    job = service.job()
                    if not job or not Path(job["output_dir"]).is_dir():
                        raise ValueError("Chưa có thư mục kết quả.")
                    os.startfile(job["output_dir"])
                    result = {"opened": True}
                elif route == "/api/open-detection-output":
                    import os
                    det_dir = service.detection_output_dir()
                    if not Path(det_dir).is_dir():
                        raise ValueError("Chưa có thư mục kết quả nhận diện.")
                    os.startfile(det_dir)
                    result = {"opened": True, "path": det_dir}
                elif route == "/api/browse-detection":
                    if not browse_lock.acquire(blocking=False):
                        raise ValueError("Hộp chọn tệp đang mở.")
                    try:
                        import tkinter as tk
                        from tkinter.filedialog import askopenfilename
                        dialog = tk.Tk()
                        try:
                            dialog.withdraw()
                            dialog.attributes("-topmost", True)
                            init_dir = service.root / "outputs" / "detection_runs"
                            chosen = askopenfilename(
                                parent=dialog,
                                initialdir=str(init_dir if init_dir.is_dir() else service.root),
                                title="Chọn tệp kết quả nhận diện (detections.json)",
                                filetypes=[("Tệp nhận diện JSON", "detections.json *.json"), ("Tất cả tệp", "*.*")],
                            )
                            if chosen:
                                job_rec = service.load_session_path(chosen)
                                result = {"loaded": True, "session": job_rec}
                            else:
                                result = {"loaded": False}
                        finally:
                            dialog.destroy()
                    finally:
                        browse_lock.release()
                elif route == "/api/browse":
                    if not browse_lock.acquire(blocking=False):
                        raise ValueError("Hộp chọn tệp đang mở.")
                    try:
                        import tkinter as tk
                        from tkinter.filedialog import askopenfilename
                        dialog = tk.Tk()
                        try:
                            dialog.withdraw()
                            dialog.attributes("-topmost", True)
                            result = {"path": askopenfilename(parent=dialog,
                                title="Chọn ảnh màu ORTHO (.JPG kèm .JGW/.PRJ hoặc GeoTIFF RGB)",
                                filetypes=[("Ảnh ORTHO / GeoTIFF", "*.jpg *.jpeg *.tif *.tiff *.png"), ("Tất cả tệp", "*.*")])}
                        finally:
                            dialog.destroy()
                    finally:
                        browse_lock.release()
                elif (auto_post := handle_automation_post(route, data, project_root, app_root)) is not None:
                    result = auto_post
                else:
                    self.json_response(404, {"error": "Tính năng chưa được triển khai."})
                    return
                self.json_response(200, result)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except Exception as error:
                self.json_response(400, {"error": str(error)})

    bind_host = (os.environ.get("UAV_BIND_HOST") or "0.0.0.0").strip()
    server = LocalHTTPServer((bind_host, port), Handler)
    try:
        service = ProjectService(project_root)
    except Exception:
        server.server_close()
        raise
    server.service = service
    return server
