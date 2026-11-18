"""One background export worker with an immutable job configuration."""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from pathlib import Path

from uav_app.infrastructure.raster import inspect_raster, plan_raster, preview_png, export_tiles, _write_json
from uav_app.infrastructure.state import StateStore, utc_now
from uav_app.domain.settings import validate_settings
from uav_app.infrastructure.warp import plan_warp, warp_preview, execute_warp
from uav_app.application.detection_pipeline import plan_detection, run_detection
from uav_app.application.review import (
    load_results,
    set_review,
    export_reviewed,
    export_reviewed_autocad,
    evaluate_result,
    post_fuse_results,
    enrich_results_with_dem,
    enrich_results_with_multispectral,
    split_merged_rice_clumps,
    auto_triage_results,
    export_ground_truth_dataset,
)
from uav_app.infrastructure.multispectral import analyze_full_orthomosaic_multispectral
from uav_app.application.advisor import propose, fingerprint
from uav_app.infrastructure.lease import ProjectLease
from uav_app.infrastructure.super_resolution import OPEN_SOURCE_SR_CATALOG, discover_render_status, enhance_uav_crop
from uav_app.infrastructure.survey_cad import DEFAULT_SURVEY_RULES, inspect_cad_library, export_survey_plan
from uav_app.infrastructure.terrain_segmentation import (
    TCVN_MAP_SCALE_SPECS,
    TERRAIN_CLASSES_META,
    export_9classes_to_dxf,
    export_9classes_to_dwg,
    export_terrain_dwg_from_dxf,
    get_tcvn_scale_spec,
    run_terrain_segmentation_and_export_dxf,
    train_terrain_model_from_dwg_folders,
)
from uav_app.infrastructure.turbo_yolo import (
    get_turbo_status,
    plan_turbo_detection,
    render_lazy_review_image,
    run_turbo_detection,
    train_turbo_models,
)
from uav_app.infrastructure.webgpu_license import (
    authenticate_and_issue_webgpu_lease,
    build_demo_terrain_geotiff_bytes,
    consume_encrypted_model_lease,
    create_license,
    list_licenses,
    record_quota_usage,
    update_license_action,
)


class ProjectService:
    def __init__(self, project_root: Path):
        self.root = Path(project_root).resolve()
        self._lease=ProjectLease(self.root)
        try:
            self.store = StateStore(self.root / "project_state.json")
        except Exception:
            self._lease.close()
            raise
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._pause_requested = False
        self._thread = None
        self._job = self.store.read().get("last_job")
        self._last_persisted = 0.0
        self._warp_plan = None
        det_job = self.store.read().get("last_detection_job")
        if det_job and isinstance(det_job, dict):
            det_dir = det_job.get("output_dir")
            if not det_dir or not ((Path(det_dir) / "detections.json").is_file() or (Path(det_dir) / "summary.json").is_file()):
                det_job = None
                self.store.update(last_detection_job=None)
        self._detection_job = det_job

    def _idle(self):
        if self._thread and self._thread.is_alive():
            raise ValueError("Đang xuất tile. Hãy đợi hoàn tất hoặc hủy tác vụ trước khi đổi cấu hình.")

    def _idle_unless_detecting(self):
        if self._thread and self._thread.is_alive():
            if not (self._job and self._job.get("kind") == "detection"):
                raise ValueError("Đang xuất tile. Hãy đợi hoàn tất hoặc hủy tác vụ trước khi đổi cấu hình.")

    def _is_detection_running(self) -> bool:
        return bool(
            self._thread
            and self._thread.is_alive()
            and self._job
            and self._job.get("kind") == "detection"
        )

    @staticmethod
    def input_path(path: str) -> str:
        value = Path(str(path).strip().strip('"')).expanduser()
        if value.suffix.lower() not in {".tif", ".tiff", ".jpg", ".jpeg"}:
            raise ValueError("Chọn GeoTIFF hoặc JPG đi kèm world file (.jgw/.wld) và .prj.")
        if not value.is_file():
            raise ValueError(f"Không tìm thấy tệp: {value}")
        return str(value.resolve())

    def inspect(self, path: str) -> dict:
        return inspect_raster(self.input_path(path))

    def plan(self, path: str, config: dict) -> dict:
        with self._lock:
            self._idle()
            path = self.input_path(path)
            result = plan_raster(path, config)
            active = self.store.read()["active_pipeline_config"]
            active.update(copy.deepcopy(result["config"]))
            active["input_path"] = path
            self.store.update(active_pipeline_config=active)
            return result

    def preview(self, path: str, window=None) -> bytes:
        return preview_png(self.input_path(path), max_size=1600, window=window)

    def job(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._job)

    def start_export(self, path: str, config: dict) -> dict:
        with self._lock:
            self._idle()
            plan = self.plan(path, config)
            path = self.input_path(path)
            snapshot = copy.deepcopy(plan["config"])
            job_id = "run_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
            output = self.root / "outputs" / "geotiff_runs" / job_id
            output.parent.mkdir(parents=True, exist_ok=True)
            self._cancel.clear()
            self._job = {"id": job_id, "status": "running", "done": 0,
                         "total": plan["tile_count"], "output_dir": str(output),
                         "started_at": utc_now(), "config": snapshot,
                         "message": "Đang đọc và xuất từng cửa sổ GeoTIFF."}
            self.store.update(last_job=self._job)
            self._thread = threading.Thread(target=self._run,
                args=(path, output, snapshot), name="geotiff-export", daemon=True)
            self._thread.start()
            return self.job()

    def _progress(self, done: int, total: int, message=None, **extra):
        with self._lock:
            self._job.update(done=done, total=total)
            if message:
                self._job["message"] = message
            if extra:
                self._job.update(extra)
            if (
                self._job.get("kind") == "detection"
                and self._job.get("output_dir")
                and (Path(self._job["output_dir"]) / "detections.json").is_file()
            ):
                self._detection_job = copy.deepcopy(self._job)
            now = time.monotonic()
            if now - self._last_persisted > 1:
                changes = dict(last_job=self._job)
                if self._detection_job and self._job.get("kind") == "detection":
                    changes["last_detection_job"] = self._detection_job
                self.store.update(**changes)
                self._last_persisted = now

    def _run(self, path, output, config):
        try:
            summary = export_tiles(path, str(output), config,
                                   progress=self._progress, cancelled=self._cancel.is_set)
            with self._lock:
                status = summary.get("status", "completed")
                self._job.update(status=status, summary=summary,
                                 message="Đã hủy tại ranh giới tile." if status == "cancelled"
                                 else "Đã xuất xong các tile và manifest tọa độ.")
        except Exception as error:
            with self._lock:
                self._job.update(status="failed", message=str(error))
        finally:
            with self._lock:
                self._job["finished_at"] = utc_now()
                self.store.update(last_job=self._job)

    def cancel(self) -> dict | None:
        with self._lock:
            if (self._thread and self._thread.is_alive() and self._job
                    and self._job.get("status") in {"running", "cancelling", "queued"}):
                self._pause_requested = False
                self._cancel.set()
                self._job.update(status="cancelling", message="Sẽ dừng sau tile đang ghi.")
                self.store.update(last_job=self._job)
            return self.job()

    def pause(self) -> dict | None:
        with self._lock:
            if (self._thread and self._thread.is_alive() and self._job
                    and self._job.get("status") in {"running", "cancelling", "queued"}):
                self._pause_requested = True
                self._cancel.set()
                self._job.update(status="cancelling", message="Đang tạm dừng sau ảnh hiện tại và giải phóng Card GPU…")
                self.store.update(last_job=self._job)
            return self.job()

    def decide(self, proposal_id, decision):
        with self._lock:
            self._idle()
            state=self.store.read()
            proposal=next((p for p in state.get("pending_proposals",[]) if p["id"]==proposal_id),None)
            if proposal and proposal.get("approval_scope")=="configuration":
                if decision not in {"approve","reject"}:
                    raise ValueError("Quyết định không hợp lệ.")
                pending=[p for p in state["pending_proposals"] if p["id"]!=proposal_id]
                if decision=="reject":
                    return self.store.update(pending_proposals=pending)
                current=self.detection_settings()
                if fingerprint(current)!=proposal["base_fingerprint"]:
                    raise ValueError("Cấu hình đã đổi sau lúc gợi ý. Hãy tạo gợi ý mới.")
                settings=validate_settings({**current,**proposal["patch"]})
                active=state["active_pipeline_config"]; active["detection"]=settings
                applied=state.get("applied_configuration_changes",[])
                applied.append({**proposal,"applied_at":utc_now(),"implementation_status":"applied"})
                return self.store.update(pending_proposals=pending,active_pipeline_config=active,
                                         applied_configuration_changes=applied[-50:])
            return self.store.decide(proposal_id, decision)

    def detection_settings(self):
        return validate_settings(self.store.read()["active_pipeline_config"].get("detection"))

    def save_settings(self,settings):
        with self._lock:
            self._idle()
            settings=validate_settings(settings)
            active=self.store.read()["active_pipeline_config"]
            active["detection"]=settings
            self.store.update(active_pipeline_config=active)
            return settings

    def advise(self,request,provider="local",api_key="",model="",workspace=""):
        current=self.detection_settings()
        if provider=="local":
            proposal=propose(request,current)
        else:
            from uav_app.infrastructure.cloud_advisor import cloud_proposal
            proposal=cloud_proposal(request,current,provider,api_key,model,workspace)
        with self._lock:
            pending=self.store.read().get("pending_proposals",[])
            if len(pending)>=20:
                raise ValueError("Hãy duyệt hoặc xóa bớt các gợi ý cũ trước.")
            self.store.update(pending_proposals=[*pending,proposal])
            return proposal

    def prepare_warp(self,path,target_crs,resolution_cm,resampling="bilinear"):
        with self._lock:
            self._idle()
            self._warp_plan=plan_warp(self.input_path(path),target_crs,resolution_cm,resampling)
            return copy.deepcopy(self._warp_plan)

    def preview_warp(self,signature):
        with self._lock:
            if not self._warp_plan or self._warp_plan["signature"]!=signature:
                raise ValueError("Hãy tính lại bản xem trước chuẩn hóa.")
            return warp_preview(copy.deepcopy(self._warp_plan))

    def start_warp(self,signature):
        with self._lock:
            self._idle()
            if not self._warp_plan or self._warp_plan["signature"]!=signature:
                raise ValueError("Cấu hình chuẩn hóa đã đổi; hãy xem trước lại.")
            plan=copy.deepcopy(self._warp_plan)
            if plan_warp(**plan["params"])["signature"]!=signature:
                raise ValueError("Ảnh nguồn đã đổi. Hãy xem trước lại.")
            total=((plan["width"]+511)//512)*((plan["height"]+511)//512)
            return self._start_operation("warp",plan,total)

    def turbo_status(self) -> dict:
        return get_turbo_status(self.root)

    def start_turbo_training(self, mode: str = "both", epochs: int = 50) -> dict:
        with self._lock:
            self._idle()
            mode = str(mode or "both").strip().lower()
            if mode not in {"both", "zone", "clump"}:
                raise ValueError("Chế độ huấn luyện phải là 'both', 'zone' hoặc 'clump'.")
            epochs = max(1, min(300, int(epochs or 50)))
            st = get_turbo_status(self.root)
            if not st["gpu_venv_ready"]:
                raise ValueError("Thiếu môi trường Python GPU (.venv) tại thư mục dự án chính.")
            if not st["dataset"]["ready_to_train"]:
                raise ValueError("Chưa có mẫu dương đã lưu trong Ground Truth Dataset. Hãy bấm '💾 Lưu mẫu huấn luyện' trước.")
            return self._start_operation("turbo_train", {"mode": mode, "epochs": epochs}, 100)

    def detection_plan(self,path,config,settings,scope,tile_id,regions=None):
        with self._lock:
            self._idle()
            engine = str((settings or {}).get("engine") or "locateanything")
            if engine in {"turbo_zone", "turbo_clump"}:
                plan, _ = plan_turbo_detection(self.input_path(path), config, settings, scope, tile_id, regions=regions)
                return plan
            plan,_=plan_detection(self.input_path(path),config,settings,scope,tile_id,regions=regions)
            return plan

    def start_detection(self,path,config,settings,scope="selected",tile_id="tile_000001",regions=None,sr_mode=None,spectral_mode=None):
        with self._lock:
            self._idle()
            path=self.input_path(path)
            validated_user_settings = validate_settings(settings)
            engine = validated_user_settings.get("engine", "locateanything")
            if engine in {"turbo_zone", "turbo_clump"}:
                mode_key = "zone" if engine == "turbo_zone" else "clump"
                weights_file = self.root / "models" / "turbo_yolo" / f"turbo_{mode_key}" / "best.pt"
                if not weights_file.is_file():
                    raise ValueError(
                        f"Mô hình {'Turbo Vùng' if mode_key == 'zone' else 'Turbo Khóm lẻ'} chưa được huấn luyện. "
                        "Hãy chuyển sang Bước 04 → mục 02 bấm '🚀 Huấn luyện Mô hình Turbo' trước."
                    )
                if not (self.root / ".venv" / "Scripts" / "python.exe").is_file():
                    raise ValueError("Thiếu môi trường GPU .venv tại thư mục dự án chính.")
                plan, _ = plan_turbo_detection(path, config, validated_user_settings, scope, tile_id, regions=regions)
                self.plan(path, config)
                self.save_settings(validated_user_settings)
                return self._start_operation(
                    "detection",
                    dict(
                        path=path,
                        config=plan["grid_config"],
                        settings=plan["settings"],
                        scope=scope,
                        tile_id=tile_id,
                        regions=regions,
                        sr_mode=sr_mode,
                        spectral_mode=spectral_mode,
                    ),
                    plan["query_count"],
                )
            plan,_=plan_detection(path,config,validated_user_settings,scope,tile_id,regions=regions)
            if not (self.root/".venv"/"Scripts"/"python.exe").is_file() or not (self.root/"detect_batch.py").is_file():
                raise ValueError("Thiếu môi trường hoặc detect_batch.py của mô hình tại thư mục dự án chính.")
            self.plan(path,config)
            self.save_settings(plan["settings"])
            return self._start_operation("detection",dict(path=path,config=plan["grid_config"],settings=plan["settings"],
                scope=scope,tile_id=tile_id,regions=regions,sr_mode=sr_mode,spectral_mode=spectral_mode),plan["query_count"])

    def _start_operation(self,kind,request,total):
        job_id=kind+"_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:8]
        folder_map = {"detection": "detection_runs", "turbo_train": "turbo_train_runs", "warp": "warp_runs"}
        output=self.root/"outputs"/folder_map.get(kind, "warp_runs")/job_id
        output.parent.mkdir(parents=True,exist_ok=True)
        self._cancel.clear()
        self._pause_requested = False
        init_msg = (
            "Đang chuẩn bị nhận diện…"
            if kind == "detection"
            else "Đang chuẩn bị dữ liệu & khởi động huấn luyện Turbo YOLO11s-FP16 trên RTX GPU…"
            if kind == "turbo_train"
            else "Đang chuẩn hóa ảnh…"
        )
        self._job=dict(id=job_id,kind=kind,status="running",done=0,total=total,output_dir=str(output),
                       started_at=utc_now(),config=copy.deepcopy(request.get("config",{})),request=copy.deepcopy(request),
                       message=init_msg)
        if kind == "detection":
            self._detection_job = copy.deepcopy(self._job)
            self.store.update(last_job=self._job, last_detection_job=self._detection_job)
        else:
            self.store.update(last_job=self._job)
        self._thread=threading.Thread(target=self._run_operation,args=(kind,output,copy.deepcopy(request)),daemon=True)
        self._thread.start()
        return self.job()

    def _run_operation(self,kind,output,request):
        try:
            if kind=="warp":
                summary=execute_warp(request,output,self._progress,self._cancel.is_set)
            elif kind=="turbo_train":
                summary=train_turbo_models(
                    self.root,
                    output,
                    mode=str(request.get("mode", "both")),
                    epochs=int(request.get("epochs", 50)),
                    progress=self._progress,
                    cancelled=self._cancel.is_set,
                )
            else:
                extra_kw={}
                if request.get("regions"):
                    extra_kw["regions"]=request["regions"]
                if request.get("sr_mode"):
                    extra_kw["sr_mode"]=request["sr_mode"]
                if request.get("spectral_mode"):
                    extra_kw["spectral_mode"]=request["spectral_mode"]
                if request.get("resume"):
                    extra_kw["resume"]=bool(request["resume"])
                req_engine = str((request.get("settings") or {}).get("engine") or "locateanything")
                if req_engine in {"turbo_zone", "turbo_clump"}:
                    summary=run_turbo_detection(self.root,request["path"],output,request["config"],request["settings"],
                        request["scope"],request["tile_id"],self._progress,self._cancel.is_set,**extra_kw)
                else:
                    summary=run_detection(self.root,request["path"],output,request["config"],request["settings"],
                        request["scope"],request["tile_id"],self._progress,self._cancel.is_set,**extra_kw)
            with self._lock:
                if kind == "detection" and self._pause_requested and summary.get("status") == "cancelled":
                    summary["status"] = "paused"
                    _write_json(Path(output) / "summary.json", summary)
                    self._job.update(
                        status="paused",
                        summary=summary,
                        done=summary.get("completed_queries", self._job.get("done", 0)),
                        message=f"Đã tạm dừng ({summary.get('completed_queries', 0)}/{self._job.get('total', 0)}) & giải phóng Card GPU. Bấm 'Tiếp tục quét' để chạy tiếp.",
                    )
                else:
                    done_msg = (
                        "Đã nhận diện xong. Hãy xem và duyệt các khung."
                        if kind == "detection" and summary["status"] == "completed"
                        else "✅ Đã huấn luyện xong Mô hình Turbo YOLO11s-FP16! Chuyển sang Bước 03 chọn Động cơ Turbo để quét siêu tốc."
                        if kind == "turbo_train" and summary["status"] == "completed"
                        else "Đã chuẩn hóa xong. Nạp ảnh mới và nhập Base theo hệ tọa độ đích."
                        if summary["status"] == "completed"
                        else "Tác vụ đã dừng; dữ liệu đã ghi được giữ lại."
                    )
                    self._job.update(status=summary["status"],summary=summary,message=done_msg)
        except Exception as error:
            with self._lock: self._job.update(status="failed",message=str(error))
        finally:
            with self._lock:
                self._pause_requested = False
                self._job["finished_at"]=utc_now()
                changes=dict(last_job=self._job)
                if kind=="detection" and ((output/"detections.json").is_file() or (output/"summary.json").is_file()):
                    self._detection_job=copy.deepcopy(self._job)
                    changes["last_detection_job"]=self._detection_job
                self.store.update(**changes)

    def resume_detection(self, job_id: str | None = None) -> dict:
        with self._lock:
            self._idle()
            runs_dir = (self.root / "outputs" / "detection_runs").resolve()
            target_dir: Path | None = None
            if job_id:
                candidate = (runs_dir / str(job_id)).resolve()
                if candidate.is_relative_to(runs_dir) and candidate.is_dir():
                    target_dir = candidate
                elif self._detection_job and self._detection_job.get("id") == job_id and self._detection_job.get("output_dir"):
                    target_dir = Path(self._detection_job["output_dir"]).resolve()
                elif self._job and self._job.get("id") == job_id and self._job.get("output_dir"):
                    target_dir = Path(self._job["output_dir"]).resolve()
            else:
                if self._detection_job and self._detection_job.get("output_dir"):
                    cand = Path(self._detection_job["output_dir"]).resolve()
                    if (cand / "summary.json").is_file():
                        target_dir = cand
                if target_dir is None and self._job and self._job.get("kind") == "detection" and self._job.get("output_dir"):
                    cand = Path(self._job["output_dir"]).resolve()
                    if (cand / "summary.json").is_file():
                        target_dir = cand
                if target_dir is None and runs_dir.is_dir():
                    for child in sorted(runs_dir.iterdir(), key=lambda p: p.name, reverse=True):
                        sum_file = child / "summary.json"
                        if sum_file.is_file():
                            try:
                                s = json.loads(sum_file.read_text(encoding="utf-8"))
                                if not s.get("coverage_complete", False):
                                    target_dir = child.resolve()
                                    break
                            except Exception:
                                pass

            if target_dir is None or not (target_dir / "summary.json").is_file():
                raise ValueError("Không tìm thấy phiên nhận diện để tiếp tục.")

            summary = json.loads((target_dir / "summary.json").read_text(encoding="utf-8"))
            plan = summary.get("plan") or {}
            if summary.get("coverage_complete") and summary.get("completed_queries", 0) >= plan.get("query_count", 1):
                raise ValueError("Phiên nhận diện này đã hoàn tất 100%.")

            prev_req = {}
            if self._job and self._job.get("id") == target_dir.name and isinstance(self._job.get("request"), dict):
                prev_req = copy.deepcopy(self._job["request"])
            elif self._detection_job and self._detection_job.get("id") == target_dir.name and isinstance(self._detection_job.get("request"), dict):
                prev_req = copy.deepcopy(self._detection_job["request"])

            path = prev_req.get("path") or (plan.get("metadata") or {}).get("path")
            if not path or not Path(path).is_file():
                raise ValueError("Không tìm thấy tệp ảnh gốc của phiên nhận diện này.")
            settings = prev_req.get("settings") or plan.get("settings") or self.detection_settings()
            grid_cfg = prev_req.get("config") or plan.get("grid_config") or {}
            scope = prev_req.get("scope") or plan.get("scope", "selected")
            tile_id = prev_req.get("tile_id") or plan.get("tile_id", "tile_000001")
            regions = prev_req.get("regions") if prev_req.get("regions") is not None else plan.get("regions")
            sr_mode = prev_req.get("sr_mode") or settings.get("sr_mode")
            spectral_mode = prev_req.get("spectral_mode") or settings.get("spectral_mode")

            request = dict(
                path=path,
                config=grid_cfg,
                settings=settings,
                scope=scope,
                tile_id=tile_id,
                regions=regions,
                sr_mode=sr_mode,
                spectral_mode=spectral_mode,
                resume=True,
            )
            done_count = int(summary.get("completed_queries", 0))
            total_count = int(plan.get("query_count", 0))
            self._cancel.clear()
            self._pause_requested = False
            self._job = dict(
                id=target_dir.name,
                kind="detection",
                status="running",
                done=done_count,
                total=total_count,
                output_dir=str(target_dir),
                started_at=utc_now(),
                config=copy.deepcopy(grid_cfg),
                request=copy.deepcopy(request),
                message=f"Đang tiếp tục quét từ {done_count}/{total_count} truy vấn…",
            )
            self._detection_job = copy.deepcopy(self._job)
            self.store.update(last_job=self._job, last_detection_job=self._detection_job)
            self._thread = threading.Thread(
                target=self._run_operation,
                args=("detection", target_dir, copy.deepcopy(request)),
                daemon=True,
            )
            self._thread.start()
            return self.job()

    def _result_directory(self):
        if not self._detection_job:
            raise ValueError("Chưa có lượt nhận diện. Hãy chạy thử tile đang chọn.")
        return Path(self._detection_job["output_dir"])

    def results(self,offset=0,limit=50,status_filter="all"):
        with self._lock:
            if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100:
                raise ValueError("Trang kết quả không hợp lệ.")
            directory=self._result_directory()
            if not (directory / "detections.json").is_file():
                if self._detection_job and self._detection_job.get("status") in {"running", "queued", "paused"}:
                    req = self._detection_job.get("request") or {}
                    return dict(
                        revision=0,
                        source=str(req.get("path") or ""),
                        metadata={},
                        base=[0, 0],
                        settings=req.get("settings") or {},
                        scope=req.get("scope") or "selected",
                        region=None,
                        records=[],
                        total=0,
                        total_all=0,
                        offset=offset,
                        reviewed=0,
                        output_dir=str(directory),
                        job=self._detection_job,
                        saved_cursor=self.store.read().get("review_cursors", {}).get(self._detection_job["id"]),
                    )
            data=load_results(directory, _copy=False)
            all_records=data["records"]
            if status_filter == "unreviewed":
                filtered = [r for r in all_records if r.get("review_status") == "unreviewed"]
            elif status_filter == "low_confidence":
                filtered = [r for r in all_records if r.get("review_status") == "unreviewed" and (r.get("confidence_score") or 0.5) < 0.75]
            elif status_filter == "accepted":
                filtered = [r for r in all_records if r.get("review_status") in {"accepted_raw", "accepted_candidate"}]
            else:
                filtered = all_records
            page_records = copy.deepcopy(filtered[offset:offset+limit])
            meta_copy = {k: copy.deepcopy(v) for k, v in data.items() if k != "records"}
            return dict(**meta_copy,records=page_records,total=len(filtered),total_all=len(all_records),offset=offset,
                        reviewed=sum(r.get("review_status")!="unreviewed" for r in all_records),
                        output_dir=str(directory),job=self._detection_job,
                        saved_cursor=self.store.read().get("review_cursors",{}).get(self._detection_job["id"]))

    def results_boxes(self, job_id=None):
        with self._lock:
            if job_id:
                self._check_result_job(job_id)
            directory = self._result_directory()
            if not (directory / "detections.json").is_file():
                return dict(revision=0, job_id=self._detection_job["id"] if self._detection_job else "", total_all=0, records=[])
            data = load_results(directory, _copy=False)
            slim = [
                {
                    "id": r.get("id"),
                    "box": r.get("box"),
                    "candidate_box": r.get("candidate_box"),
                    "review_status": r.get("review_status"),
                    "sub_class": r.get("sub_class"),
                    "category": r.get("category"),
                }
                for r in data.get("records", [])
                if isinstance(r.get("box"), list) and len(r["box"]) == 4
            ]
            return dict(
                revision=data.get("revision", 0),
                job_id=self._detection_job["id"] if self._detection_job else "",
                total_all=len(slim),
                records=slim,
            )

    def result_file(self,name,job_id=None):
        if job_id:
            self._check_result_job(job_id)
        directory=self._result_directory().resolve()
        path=(directory/name).resolve()
        if path.is_relative_to(directory) and not path.is_file() and str(name).replace("\\", "/").startswith("review/object_"):
            try:
                render_lazy_review_image(directory, str(name))
            except Exception:
                pass
        if not path.is_relative_to(directory) or not path.is_file() or path.suffix.lower() not in {".png",".jpg",".json",".csv",".dxf",".dwg",".jsonl",".log"}:
            raise ValueError("Không tìm thấy tệp kết quả hợp lệ.")
        return path

    def _check_result_job(self,job_id):
        if not self._detection_job or job_id!=self._detection_job["id"]:
            raise ValueError("Lượt nhận diện đã đổi. Hãy tải lại kết quả trước khi duyệt hoặc xuất.")

    def review(self,object_id,decision,revision,job_id=None,sub_class=None,custom_box=None,offset=None):
        with self._lock:
            self._idle_unless_detecting()
            self._check_result_job(job_id)
            res = set_review(
                self._result_directory(),
                object_id,
                decision,
                revision,
                sub_class=sub_class,
                custom_box=custom_box,
                allow_live_drift=self._is_detection_running(),
            )
            if isinstance(offset, int) and offset >= 0 and self._detection_job:
                cursors = copy.deepcopy(self.store.read().get("review_cursors", {}))
                cursors[self._detection_job["id"]] = {"offset": offset, "object_id": object_id, "updated_at": utc_now()}
                self.store.update(review_cursors=cursors)
            return res

    def export_cad(self,revision,job_id=None):
        with self._lock:
            self._idle_unless_detecting()
            self._check_result_job(job_id)
            return export_reviewed(self._result_directory(),revision)

    def export_autocad_dwg(self,revision,job_id=None):
        with self._lock:
            self._idle_unless_detecting()
            self._check_result_job(job_id)
            return export_reviewed_autocad(self._result_directory(),revision)

    def fuse_existing(self,revision,job_id=None,mode="smart_overlap",threshold=0.50,stitch_large=True):
        with self._lock:
            self._idle_unless_detecting()
            self._check_result_job(job_id)
            return post_fuse_results(self._result_directory(),revision,mode=mode,threshold=threshold,stitch_large=stitch_large)

    def enrich_dem(self,revision,job_id=None,dem_path=None):
        with self._lock:
            self._idle_unless_detecting()
            self._check_result_job(job_id)
            return enrich_results_with_dem(self._result_directory(),revision,dem_path=dem_path)

    def repair_dem(self,dem_path=None,min_valid_z=None,job_id=None):
        with self._lock:
            self._idle_unless_detecting()
            from uav_app.infrastructure.dem import find_companion_dem, repair_dem_noise
            target_dem = dem_path
            if not target_dem:
                try:
                    directory = self._result_directory()
                    data = load_results(directory, _copy=False)
                    if data.get("source"):
                        found = find_companion_dem(data["source"])
                        if found:
                            target_dem = str(found)
                except Exception:
                    pass
            if not target_dem:
                raise ValueError("Hãy nhập đường dẫn tệp DEM (.tif) hoặc đặt tệp DEM cùng thư mục ảnh gốc.")
            return repair_dem_noise(target_dem, min_valid_z=min_valid_z)

    def enrich_multispectral(self,revision=None,job_id=None,source_path=None):
        with self._lock:
            self._idle_unless_detecting()
            has_session = bool(
                self._detection_job
                and self._detection_job.get("output_dir")
                and (Path(self._detection_job["output_dir"]) / "detections.json").is_file()
            )
            if has_session:
                if job_id:
                    self._check_result_job(job_id)
                return enrich_results_with_multispectral(self._result_directory(),revision=revision,source_path=source_path)
            eff_source = source_path or self.store.read().get("active_pipeline_config", {}).get("input_path")
            if not eff_source:
                raise ValueError("Hãy chọn tệp ảnh nguồn trước khi phân tích phổ toàn ảnh.")
            eff_source = self.input_path(eff_source)
            out_dir = self.root / "outputs" / "spectral_analysis"
            field_summary = analyze_full_orthomosaic_multispectral(eff_source, output_dir=out_dir)
            return {
                "revision": revision or 0,
                "enriched_count": 0,
                "total": 0,
                "bands_used": field_summary["bands_used"],
                "indices_computed": field_summary["indices_computed"],
                "class_counts": {},
                "field_summary": field_summary,
                "land_cover_pct": field_summary.get("land_cover_pct"),
                "overview_image": field_summary.get("overview_image"),
            }

    def split_clumps(self,revision=None,job_id=None,object_id=None):
        with self._lock:
            self._idle_unless_detecting()
            if job_id:
                self._check_result_job(job_id)
            return split_merged_rice_clumps(self._result_directory(),revision=revision,object_id=object_id)

    def auto_triage(self,revision=None,job_id=None,threshold=0.72):
        with self._lock:
            self._idle_unless_detecting()
            if job_id:
                self._check_result_job(job_id)
            return auto_triage_results(self._result_directory(),revision=revision,threshold=threshold)

    def save_ground_truth(self,job_id=None):
        with self._lock:
            self._idle_unless_detecting()
            if job_id:
                self._check_result_job(job_id)
            res = export_ground_truth_dataset(self.root, self._result_directory())
            res["turbo_status"] = self.turbo_status()
            return res

    def sr_enhance_object(self,object_id,job_id=None,mode="ttst",scale=2):
        with self._lock:
            self._idle_unless_detecting()
            if job_id:
                self._check_result_job(job_id)
            directory=self._result_directory()
            data=load_results(directory,_copy=False)
            record=next((r for r in data["records"] if r["id"]==object_id),None)
            if not record:
                raise ValueError("Không tìm thấy đối tượng cần làm nét.")
            import io
            import math
            import numpy as np
            from PIL import Image, ImageDraw
            from uav_app.infrastructure.refinement import propose_refinement

            source_path = data.get("source")
            raw = record.get("box")
            meta_info = data.get("metadata") or {}
            clean_img = None
            left = top = 0
            window = None

            if source_path and Path(source_path).is_file() and isinstance(raw, list) and len(raw) == 4:
                pad = 20
                w_max = int(meta_info.get("width") or 100000)
                h_max = int(meta_info.get("height") or 100000)
                left = max(0, math.floor(raw[0]) - pad)
                top = max(0, math.floor(raw[1]) - pad)
                right = min(w_max, math.ceil(raw[2]) + pad)
                bottom = min(h_max, math.ceil(raw[3]) + pad)
                window = dict(col=left, row=top, width=max(4, right - left), height=max(4, bottom - top))
                try:
                    with Image.open(io.BytesIO(preview_png(source_path, max_size=1600, window=window))) as src_win:
                        clean_img = src_win.convert("RGB").copy()
                except Exception:
                    clean_img = None

            if clean_img is None:
                src_rel = record.get("raw_crop") or record.get("raw_image")
                src_path = (directory / src_rel).resolve()
                if not src_path.is_file():
                    raise ValueError("Không tìm thấy ảnh gốc của đối tượng.")
                with Image.open(src_path) as src_img:
                    clean_img = src_img.convert("RGB").copy()

            eff_scale = max(int(scale), 2)
            if min(clean_img.width, clean_img.height) * eff_scale < 360:
                eff_scale = 4

            out_img, sr_meta = enhance_uav_crop(clean_img, scale=eff_scale, mode=mode, project_root=self.root)
            sr_rel = f"review/{record['id']}_sr_{mode}_{scale}x.png"
            sr_cand_rel = f"review/{record['id']}_sr_cand_{mode}_{scale}x.png"
            out_path = directory / sr_rel
            out_cand_path = directory / sr_cand_rel
            out_path.parent.mkdir(parents=True, exist_ok=True)

            if window is not None and isinstance(raw, list) and len(raw) == 4:
                sx = out_img.width / window["width"]
                sy = out_img.height / window["height"]
                local_hi = [
                    (raw[0] - left) * sx,
                    (raw[1] - top) * sy,
                    (raw[2] - left) * sx,
                    (raw[3] - top) * sy,
                ]
                pad_px = int((data.get("settings") or {}).get("padding") or 0) * eff_scale
                cand_info = propose_refinement(np.array(out_img), local_hi, pad_px)
                cand_box_hi = cand_info.get("candidate_box")
                mask_hi = cand_info.get("mask")

                before_hi = out_img.copy()
                ImageDraw.Draw(before_hi).rectangle(local_hi, outline="#ffad33", width=max(2, eff_scale))
                before_hi.save(out_path, format="PNG")

                after_hi = out_img.copy()
                if mask_hi is not None and "crop" in cand_info:
                    crop_hi = cand_info["crop"]
                    cw = max(1, crop_hi[2] - crop_hi[0])
                    ch = max(1, crop_hi[3] - crop_hi[1])
                    tint = Image.new("RGB", (cw, ch), "#38ff82")
                    alpha = Image.fromarray((mask_hi * 0.30).astype("uint8"))
                    after_hi.paste(tint, (crop_hi[0], crop_hi[1]), alpha)
                draw_after = ImageDraw.Draw(after_hi)
                draw_after.rectangle(local_hi, outline="#ffad33", width=2)
                if cand_box_hi:
                    draw_after.rectangle(cand_box_hi, outline="#20e9ef", width=max(2, eff_scale))
                elif record.get("candidate_box"):
                    cb = record["candidate_box"]
                    cb_hi = [(cb[0] - left) * sx, (cb[1] - top) * sy, (cb[2] - left) * sx, (cb[3] - top) * sy]
                    draw_after.rectangle(cb_hi, outline="#20e9ef", width=max(2, eff_scale))
                after_hi.save(out_cand_path, format="PNG")
            else:
                out_img.save(out_path, format="PNG")
                out_img.save(out_cand_path, format="PNG")

            return {
                "object_id": object_id,
                "sr_image": sr_rel,
                "sr_candidate_image": sr_cand_rel,
                "sr_meta": sr_meta,
            }

    def list_sessions(self):
        with self._lock:
            runs_dir = self.root / "outputs" / "detection_runs"
            sessions = []
            cursors = self.store.read().get("review_cursors", {})
            if runs_dir.is_dir():
                for child in sorted(runs_dir.iterdir(), key=lambda p: p.name, reverse=True):
                    sum_file = child / "summary.json"
                    if sum_file.is_file():
                        try:
                            s = json.loads(sum_file.read_text(encoding="utf-8"))
                            completed_q = s.get("completed_queries", 0)
                            query_q = s.get("plan", {}).get("query_count", 0)
                            cov_complete = bool(s.get("coverage_complete", False))
                            sessions.append({
                                "id": child.name,
                                "output_dir": str(child),
                                "status": s.get("status", "completed"),
                                "count": s.get("count", 0),
                                "completed_queries": completed_q,
                                "query_count": query_q,
                                "coverage_complete": cov_complete,
                                "resumable": not cov_complete and completed_q < query_q,
                                "scope": s.get("plan", {}).get("scope", "selected"),
                                "categories": s.get("plan", {}).get("settings", {}).get("categories", []),
                                "cursor": cursors.get(child.name),
                                "active": bool(self._detection_job and self._detection_job.get("id") == child.name),
                            })
                        except Exception:
                            pass
            return {
                "sessions": sessions,
                "sr_catalog": OPEN_SOURCE_SR_CATALOG,
                "render_status": discover_render_status(self.root),
            }

    def load_session(self, session_id: str):
        with self._lock:
            self._idle_unless_detecting()
            runs_dir = (self.root / "outputs" / "detection_runs").resolve()
            target = (runs_dir / str(session_id)).resolve()
            if not target.is_relative_to(runs_dir) or not ((target / "detections.json").is_file() or (target / "summary.json").is_file()):
                raise ValueError("Không tìm thấy phiên nhận diện đã lưu.")
            summary = json.loads((target / "summary.json").read_text(encoding="utf-8")) if (target / "summary.json").is_file() else {}
            job_record = {
                "id": target.name,
                "kind": "detection",
                "status": summary.get("status", "completed"),
                "done": summary.get("completed_queries", 0),
                "total": summary.get("plan", {}).get("query_count", 0),
                "output_dir": str(target),
                "summary": summary,
                "message": "Đã mở lại phiên nhận diện đã lưu.",
            }
            self._detection_job = job_record
            self.store.update(last_detection_job=job_record)
            return job_record

    def load_session_path(self, raw_path: str):
        with self._lock:
            self._idle_unless_detecting()
            p = Path(str(raw_path).strip()).expanduser().resolve()
            if p.is_file() and p.name.lower() == "detections.json":
                target = p.parent
            elif p.is_file() and (p.parent / "detections.json").is_file():
                target = p.parent
            elif p.is_dir() and (p / "detections.json").is_file():
                target = p
            else:
                raise ValueError("Tệp chọn không phải là detections.json hoặc thư mục phiên nhận diện hợp lệ.")
            summary = json.loads((target / "summary.json").read_text(encoding="utf-8")) if (target / "summary.json").is_file() else {}
            job_record = {
                "id": target.name,
                "kind": "detection",
                "status": summary.get("status", "completed"),
                "done": summary.get("completed_queries", 0),
                "total": summary.get("plan", {}).get("query_count", 0),
                "output_dir": str(target),
                "summary": summary,
                "message": "Đã mở tệp kết quả nhận diện.",
            }
            self._detection_job = job_record
            self.store.update(last_detection_job=job_record)
            return job_record

    def detection_output_dir(self) -> str:
        with self._lock:
            return str(self._result_directory())

    def evaluate(self,path,job_id=None):
        with self._lock:
            self._idle_unless_detecting()
            self._check_result_job(job_id)
            return evaluate_result(self._result_directory(),path)

    def survey_library(self, dxf_path: str | None = None):
        with self._lock:
            state = self.store.read()
            saved_lib = dxf_path if dxf_path is not None else state.get("survey_library_path")
            info = inspect_cad_library(saved_lib)
            saved_rules = state.get("survey_rules")
            if isinstance(saved_rules, list) and saved_rules:
                info["rules"] = copy.deepcopy(saved_rules)
            else:
                info["rules"] = copy.deepcopy(DEFAULT_SURVEY_RULES)
            if dxf_path is not None and info.get("library_path"):
                self.store.update(survey_library_path=info["library_path"])
            return info

    def save_survey_rules(self, rules: list[dict], library_path: str | None = None):
        with self._lock:
            if not isinstance(rules, list) or not rules:
                raise ValueError("Danh sách quy tắc ánh xạ CAD khảo sát không hợp lệ.")
            clean_rules = []
            for r in rules:
                if not isinstance(r, dict):
                    continue
                clean_rules.append({
                    "category": str(r.get("category") or "ornamental tree").strip(),
                    "label_vi": str(r.get("label_vi") or r.get("category") or "").strip(),
                    "cad_type": str(r.get("cad_type") or "BLOCK").strip().upper(),
                    "block_name": str(r.get("block_name") or "").strip(),
                    "layer": str(r.get("layer") or "KS_CAY_CANH").strip(),
                    "color": max(1, min(255, int(r.get("color") or 3))),
                    "linetype": str(r.get("linetype") or "CONTINUOUS").strip().upper(),
                    "scale": max(0.05, min(100.0, float(r.get("scale") or 1.0))),
                    "width_m": max(0.0, min(100.0, float(r.get("width_m") or 0.0))),
                    "centerline": bool(r.get("centerline")),
                })
            updates: dict = {"survey_rules": clean_rules}
            if library_path is not None:
                updates["survey_library_path"] = str(library_path).strip()
            self.store.update(**updates)
            return {"rules": clean_rules, "saved": True}

    def export_survey_cad(self, job_id=None, rules=None, library_path=None, survey_polylines=None, include_unreviewed=True):
        with self._lock:
            self._idle_unless_detecting()
            if job_id:
                self._check_result_job(job_id)
            directory = self._result_directory()
            data = load_results(directory, _copy=False)
            state = self.store.read()
            active_rules = rules if isinstance(rules, list) and rules else (state.get("survey_rules") or DEFAULT_SURVEY_RULES)
            lib_path = library_path if library_path is not None else state.get("survey_library_path")
            return export_survey_plan(
                output_dir=directory,
                metadata=data["metadata"],
                base=data["base"],
                records=data["records"],
                survey_polylines=survey_polylines,
                rules=active_rules,
                library_dxf_path=lib_path,
                include_unreviewed=bool(include_unreviewed),
            )

    def terrain_scale_specs(self, map_scale: int | None = None) -> dict:
        scale_val = int(map_scale or 500)
        return {
            "default_scale": 500,
            "supported_scales": [500, 1000, 2000, 5000],
            "selected_scale": scale_val,
            "selected_spec": get_tcvn_scale_spec(scale_val),
            "specs": TCVN_MAP_SCALE_SPECS,
        }

    def segment_terrain_cad(
        self,
        path: str | None = None,
        base: list[float] | None = None,
        enabled_classes: list[str] | None = None,
        region_window: dict | None = None,
        job_id: str | None = None,
        map_scale: int = 500,
    ) -> dict:
        with self._lock:
            self._idle_unless_detecting()
            state = self.store.read()
            active_cfg = state.get("active_pipeline_config") or {}
            det_dir: Path | None = None
            det_data: dict | None = None

            if self._detection_job and self._detection_job.get("output_dir"):
                cand_dir = Path(self._detection_job["output_dir"])
                if (cand_dir / "detections.json").is_file():
                    if not job_id or job_id == self._detection_job.get("id"):
                        det_dir = cand_dir
                        try:
                            det_data = load_results(cand_dir, _copy=False)
                        except Exception:
                            det_data = None

            raw_path = (path or "").strip()
            if not raw_path and det_data and det_data.get("source"):
                raw_path = str(det_data["source"])
            if not raw_path and active_cfg.get("input_path"):
                raw_path = str(active_cfg["input_path"])
            if not raw_path:
                raise ValueError("Hãy chọn tệp ảnh GeoTIFF nguồn ở Bước 01 trước khi phân vùng địa hình.")
            eff_path = self.input_path(raw_path)

            if isinstance(base, (list, tuple)) and len(base) >= 2:
                eff_base = [float(base[0]), float(base[1])]
            elif det_data and isinstance(det_data.get("base"), (list, tuple)) and len(det_data["base"]) >= 2:
                eff_base = [float(det_data["base"][0]), float(det_data["base"][1])]
            elif isinstance(active_cfg.get("base"), (list, tuple)) and len(active_cfg["base"]) >= 2:
                eff_base = [float(active_cfg["base"][0]), float(active_cfg["base"][1])]
            else:
                eff_base = [0.0, 0.0]

            eff_scale = int(map_scale or 500)
            terrain_out = self.root / "outputs" / "terrain_survey"
            res = run_terrain_segmentation_and_export_dxf(
                project_root=self.root,
                raster_path=eff_path,
                base=eff_base,
                output_dir=terrain_out,
                enabled_classes=enabled_classes,
                region_window=region_window,
                map_scale=eff_scale,
            )
            if det_dir and det_dir.is_dir():
                import shutil
                try:
                    shutil.copy2(terrain_out / res["dxf_file"], det_dir / res["dxf_file"])
                except Exception:
                    pass
            res["classes_meta"] = TERRAIN_CLASSES_META
            res["scale_specs"] = TCVN_MAP_SCALE_SPECS
            return res

    def terrain_dxf_file(self, map_scale: int | None = None) -> Path:
        out_dir = (self.root / "outputs" / "terrain_survey").resolve()
        p = out_dir / "binh_do_duong_ao_muong.dxf"
        if map_scale is not None:
            vec_json = out_dir / "terrain_vectors.json"
            if vec_json.is_file():
                try:
                    vec_data = json.loads(vec_json.read_text(encoding="utf-8"))
                    export_9classes_to_dxf(vec_data, p, map_scale=int(map_scale))
                except Exception:
                    pass
        if not p.is_file():
            raise ValueError("Chưa có tệp bình đồ địa hình DXF. Hãy chạy Phân vùng Địa hình trước.")
        return p

    def terrain_dwg_file(self, dxf_content: str | None = None, map_scale: int | None = None) -> Path:
        out_dir = (self.root / "outputs" / "terrain_survey").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        dxf_path = out_dir / "binh_do_duong_ao_muong.dxf"
        dwg_path = out_dir / "binh_do_duong_ao_muong.dwg"
        if dxf_content and str(dxf_content).strip():
            dxf_path.write_text(str(dxf_content), encoding="utf-8")
        elif map_scale is not None:
            vec_json = out_dir / "terrain_vectors.json"
            if vec_json.is_file():
                try:
                    vec_data = json.loads(vec_json.read_text(encoding="utf-8"))
                    export_9classes_to_dxf(vec_data, dxf_path, map_scale=int(map_scale))
                except Exception:
                    pass
        if not dxf_path.is_file():
            raise ValueError("Chưa có dữ liệu đường PL để xuất sang .DWG. Hãy chạy Phân vùng Địa hình trước.")
        res_dwg = export_terrain_dwg_from_dxf(dxf_path, output_dwg_path=dwg_path)
        if res_dwg is None or not res_dwg.is_file():
            raise ValueError("Không thể chuyển đổi sang .DWG trên máy này (cần AutoCAD hoặc ODA Converter).")
        return res_dwg

    def train_terrain_from_dwg(self, survey_roots: list[str] | None = None, steps: int = 160) -> dict:
        return train_terrain_model_from_dwg_folders(self.root, survey_roots=survey_roots, steps=steps)

    def terrain_train_status(self) -> dict:
        meta_p = self.root / "models" / "turbo_yolo" / "terrain_webgpu.json"
        if not meta_p.is_file():
            app_meta = Path(__file__).resolve().parents[2] / "models" / "turbo_yolo" / "terrain_webgpu.json"
            if app_meta.is_file():
                meta_p = app_meta
        if meta_p.is_file():
            try:
                return json.loads(meta_p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"model_name": "TerrainSegUNetLite-WebGPU", "real_dwg_zones_count": 0}

    def webgpu_licenses(self) -> dict:
        return list_licenses(self.root)

    def webgpu_create_license(
        self,
        owner: str,
        plan: str = "Pro Survey WebGPU",
        quota_ha: float = 200.0,
        max_devices: int = 2,
        days_valid: int = 365,
    ) -> dict:
        return create_license(
            self.root,
            owner=owner,
            plan=plan,
            quota_ha=quota_ha,
            max_devices=max_devices,
            days_valid=days_valid,
        )

    def webgpu_license_action(self, key: str, action: str) -> dict:
        return update_license_action(self.root, key=key, action=action)

    def webgpu_auth(
        self,
        license_key: str,
        device_fingerprint: str,
        gpu_label: str = "",
        model_id: str = "terrain_seg",
    ) -> dict:
        return authenticate_and_issue_webgpu_lease(
            self.root,
            license_key=license_key,
            device_fingerprint=device_fingerprint,
            gpu_label=gpu_label,
            model_id=model_id,
        )

    def webgpu_model_stream(self, lease_token: str) -> bytes:
        return consume_encrypted_model_lease(lease_token)

    def webgpu_consume_quota(self, license_key: str, area_ha: float) -> dict:
        return record_quota_usage(self.root, license_key=license_key, area_ha=area_ha)

    def webgpu_demo_geotiff(self) -> bytes:
        return build_demo_terrain_geotiff_bytes()

    def telemetry(self) -> dict:
        from uav_app.infrastructure.telemetry import sample_hardware_telemetry
        hw = copy.deepcopy(sample_hardware_telemetry())
        with self._lock:
            job = copy.deepcopy(self._job or self._detection_job or {})
            det_job = copy.deepcopy(self._detection_job or {})

        obj_stats = {
            "job_id": det_job.get("id") or job.get("id") or None,
            "job_status": job.get("status") or det_job.get("status") or "idle",
            "job_done": int(job.get("done") or det_job.get("done") or 0),
            "job_total": int(job.get("total") or det_job.get("total") or 0),
            "done_queries": int(job.get("done") or det_job.get("done") or 0),
            "total_queries": int(job.get("total") or det_job.get("total") or 0),
            "progress_pct": round(
                (float(job.get("done") or 0) / max(1.0, float(job.get("total") or 1))) * 100.0,
                1,
            ) if (job.get("total") or 0) > 0 else 0.0,
            "active_tile": (job.get("active_window") or {}).get("tile_id"),
            "active_region": (job.get("active_window") or {}).get("region_name"),
            "total": 0,
            "reviewed": 0,
            "unreviewed": 0,
            "total_clumps": 0,
            "total_objects": 0,
            "reviewed_objects": 0,
            "unreviewed_objects": 0,
            "accepted_objects": 0,
            "rejected_objects": 0,
            "clump_objects": 0,
            "estimated_rice_plants": 0,
            "avg_confidence_pct": 0.0,
            "class_counts": {},
        }

        out_dir = det_job.get("output_dir") or (job.get("output_dir") if job.get("kind") == "detection" else None)
        if out_dir and (Path(out_dir) / "detections.json").is_file():
            try:
                data = load_results(Path(out_dir), _copy=False)
                records = data.get("records") or []
                total_obj = len(records)
                reviewed = 0
                accepted = 0
                rejected = 0
                clump_objs = 0
                est_plants = 0
                conf_sum = 0.0
                class_counts: dict[str, int] = {}
                for r in records:
                    st = r.get("review_status") or "unreviewed"
                    if st != "unreviewed":
                        reviewed += 1
                    if st in {"accepted_raw", "accepted_candidate"}:
                        accepted += 1
                    elif st == "rejected":
                        rejected += 1
                    cls_name = str(r.get("sub_class") or r.get("label") or r.get("category") or "Other")
                    class_counts[cls_name] = class_counts.get(cls_name, 0) + 1
                    ref = r.get("refinement") or {}
                    c_cnt = r.get("clump_count") or ref.get("estimated_plant_count") or ref.get("clump_count") or 1
                    if isinstance(c_cnt, (int, float)) and c_cnt > 1:
                        clump_objs += 1
                        est_plants += int(c_cnt)
                    else:
                        est_plants += 1
                    conf_sum += float(r.get("confidence_score") or 0.5)
                obj_stats.update({
                    "total": total_obj,
                    "reviewed": reviewed,
                    "unreviewed": max(0, total_obj - reviewed),
                    "total_clumps": est_plants,
                    "total_objects": total_obj,
                    "reviewed_objects": reviewed,
                    "unreviewed_objects": max(0, total_obj - reviewed),
                    "accepted_objects": accepted,
                    "rejected_objects": rejected,
                    "clump_objects": clump_objs,
                    "estimated_rice_plants": est_plants,
                    "avg_confidence_pct": round((conf_sum / total_obj) * 100.0, 1) if total_obj > 0 else 0.0,
                    "class_counts": class_counts,
                })
            except Exception:
                pass

        hw["objects"] = obj_stats
        return hw

    def close(self):
        self.cancel()
        if self._thread:
            self._thread.join(timeout=15)
        if not self._thread or not self._thread.is_alive():
            self._lease.close()
