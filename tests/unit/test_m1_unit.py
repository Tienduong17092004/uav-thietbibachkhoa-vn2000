"""Comprehensive Milestone M1 Unit Test Suite (Features F1-F5).

Covers:
- F1 & F2: Multi-Agent Role & Model Tier Governance (`agent_governance.py`, `AGENTS.md`, `MODEL_TIERS_POLICY.md`, `config/agent_model_tiers.json`)
- F3: Zero-Hosting Custom Domain (`https://thietbibachkhoa.id.vn/`) & Power-Coupled Autostart Host (`autostart_host.py`, `cloudflared_thietbibachkhoa.yml`, boot scripts)
- F4: Local WebGPU Survey Server & Portal (`webgpu_public_server.py`, `LINK_TRUY_CAP_WEB.txt`, `MO_WEB_NHAN_DIEN_NGAY.html`)
- F5: Google TPU Offloading Client, Colab TPU Server, Notebook & Guide (`tpu_offload_worker.py`, `run_colab_tpu_server.py`, `Colab_Ultra_TPU_Server_VN2000.ipynb`, `TPU_OFFLOAD_ULTRA_GUIDE.md`)
"""

from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_colab_tpu_server import start_tpu_server  # noqa: E402
from uav_app.adapters.tpu_offload_worker import (  # noqa: E402
    TPUOffloadConfig,
    TPUOffloadError,
    TPUOffloadWorker,
    douglas_peucker,
)
from uav_app.adapters.webgpu_public_server import start_background_server  # noqa: E402
from uav_app.infrastructure.agent_governance import (  # noqa: E402
    MAX_CONCURRENT_CARBON,
    MAX_CONCURRENT_HYDROGEN,
    MAX_HYDROGEN_SELF_FIX_ATTEMPTS,
    AgentGovernancePolicy,
    ModelTier,
    TaskDifficulty,
)
from uav_app.infrastructure.autostart_host import (  # noqa: E402
    CUSTOM_DOMAIN,
    CUSTOM_DOMAIN_URL,
    DEFAULT_PORT,
    AutostartHostManager,
    generate_cloudflared_config,
    get_default_port,
)


class TestAgentGovernanceM1(unittest.TestCase):
    """Unit tests for F1 & F2: Multi-Agent Role Assignment & Model Tier Governance."""

    def test_enums_and_constants(self) -> None:
        self.assertEqual(ModelTier.ARGON_HIGH.value, "argon_high")
        self.assertEqual(ModelTier.ARGON.value, "argon")
        self.assertEqual(ModelTier.HYDROGEN.value, "hydrogen")
        self.assertEqual(ModelTier.CARBON.value, "carbon")
        self.assertEqual(MAX_CONCURRENT_HYDROGEN, 300)
        self.assertEqual(MAX_CONCURRENT_CARBON, 10)
        self.assertEqual(MAX_HYDROGEN_SELF_FIX_ATTEMPTS, 2)

    def test_architecture_gate_blocks_unapproved_role_assignment(self) -> None:
        policy = AgentGovernancePolicy()
        policy.create_architecture_plan("plan-01", "Initial architecture plan")
        with self.assertRaises((PermissionError, ValueError)):
            policy.assign_role("task-01", difficulty="medium")

        approval = policy.approve_architecture("plan-01", approved_by="argon_high")
        self.assertTrue(approval["approved"])
        role = policy.assign_role("task-01", difficulty="medium")
        self.assertEqual(role["assigned_tier"], "hydrogen")
        self.assertEqual(role["effort"], "medium")

    def test_difficulty_effort_scaling_and_tier_selection(self) -> None:
        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-main")

        r_low = policy.assign_role("t-low", difficulty=TaskDifficulty.LOW)
        self.assertEqual(r_low["effort"], "low")
        self.assertEqual(r_low["assigned_tier"], "hydrogen")

        r_high = policy.assign_role("t-high", difficulty="high")
        self.assertEqual(r_high["effort"], "high")
        self.assertEqual(r_high["assigned_tier"], "hydrogen")

        r_opt = policy.assign_role(
            "t-carbon", difficulty="critical", requires_deep_optimization=True
        )
        self.assertEqual(r_opt["effort"], "max")
        self.assertEqual(r_opt["assigned_tier"], "carbon")
        self.assertEqual(r_opt["max_concurrent"], 10)

        r_argon = policy.assign_role("t-argon", difficulty="high", use_argon=True)
        self.assertEqual(r_argon["assigned_tier"], "argon")

    def test_concurrency_caps_hydrogen_300_and_carbon_10(self) -> None:
        policy = AgentGovernancePolicy()
        h_slot = policy.acquire_agent_slot("hydrogen", count=300)
        self.assertEqual(h_slot["active_count"], 300)
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("hydrogen", count=1)

        policy.release_agent_slot("hydrogen", count=50)
        self.assertEqual(policy.active_slots["hydrogen"], 250)

        c_slot = policy.acquire_agent_slot("carbon", count=10)
        self.assertEqual(c_slot["active_count"], 10)
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("carbon", count=1)

        policy.release_agent_slot("carbon", count=10)
        self.assertEqual(policy.active_slots["carbon"], 0)

    def test_two_strike_self_fix_and_carbon_escalation(self) -> None:
        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-test-loop")
        policy.assign_role("task-loop-1", difficulty="medium")

        f1 = policy.record_test_failure("task-loop-1", "SyntaxError on line 10")
        self.assertEqual(f1["attempt"], 1)
        self.assertEqual(f1["action"], "SELF_FIX")
        self.assertEqual(f1["assigned_tier"], "hydrogen")
        self.assertFalse(f1["escalated"])

        f2 = policy.record_test_failure("task-loop-1", "AssertionError in test_x")
        self.assertEqual(f2["attempt"], 2)
        self.assertEqual(f2["action"], "SELF_FIX")
        self.assertEqual(f2["assigned_tier"], "hydrogen")
        self.assertFalse(f2["escalated"])

        f3 = policy.record_test_failure("task-loop-1", "Still failing after 2 fixes")
        self.assertEqual(f3["attempt"], 3)
        self.assertEqual(f3["action"], "ESCALATE_TO_CARBON")
        self.assertEqual(f3["assigned_tier"], "carbon")
        self.assertTrue(f3["escalated"])

        s = policy.record_test_success("task-loop-1")
        self.assertEqual(s["status"], "PASSED")
        self.assertEqual(s["assigned_tier"], "carbon")


class TestZeroHostingDomainAndServerM1(unittest.TestCase):
    """Unit tests for F3 & F4: Zero-Hosting Domain (thietbibachkhoa.id.vn) & WebGPU Server."""

    def test_default_port_and_cloudflared_config(self) -> None:
        self.assertEqual(DEFAULT_PORT, 8765)
        self.assertEqual(CUSTOM_DOMAIN, "thietbibachkhoa.id.vn")
        self.assertEqual(CUSTOM_DOMAIN_URL, "https://thietbibachkhoa.id.vn/")
        self.assertEqual(get_default_port(None), 8765)
        self.assertEqual(get_default_port("8766"), 8766)
        self.assertEqual(get_default_port("7860"), 7860)
        with self.assertRaises(ValueError):
            get_default_port(0)
        with self.assertRaises(ValueError):
            get_default_port(70000)

        cfg = generate_cloudflared_config(port=8765, domain="thietbibachkhoa.id.vn")
        self.assertIn("hostname: thietbibachkhoa.id.vn", cfg)
        self.assertIn("service: http://127.0.0.1:8765", cfg)

    def test_webgpu_public_server_endpoints_and_lifecycle(self) -> None:
        mgr = AutostartHostManager(port=0, domain="thietbibachkhoa.id.vn")
        info = mgr.start_web_server(host="127.0.0.1", port=0)
        port = info["port"]
        self.assertTrue(mgr.is_running)
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/webgpu.html", timeout=3) as resp:
                html = resp.read().decode("utf-8")
                self.assertEqual(resp.status, 200)
                self.assertIn("thietbibachkhoa.id.vn", html)

            with urllib.request.urlopen(f"{base}/api/health", timeout=3) as resp:
                health = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(health["status"], "ok")
                self.assertTrue(health["online"])
                self.assertEqual(health["url"], "https://thietbibachkhoa.id.vn/")

            with urllib.request.urlopen(f"{base}/api/domain-status", timeout=3) as resp:
                dom = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(dom["domain"], "thietbibachkhoa.id.vn")
                self.assertTrue(dom["power_coupled"])
                self.assertTrue(dom["server_running"])

            with urllib.request.urlopen(f"{base}/api/agent-tiers", timeout=3) as resp:
                tiers = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(tiers["concurrency_limits"]["hydrogen"], 300)
                self.assertEqual(tiers["concurrency_limits"]["carbon"], 10)
                self.assertEqual(tiers["escalation_policy"]["max_self_fix_attempts"], 2)
        finally:
            stopped = mgr.stop()
            self.assertFalse(stopped["online"])
            self.assertFalse(mgr.is_running)


class TestGoogleTPUOffloadM1(unittest.TestCase):
    """Unit tests for F5: Google TPU Offloading Client & Remote Colab TPU Server."""

    def test_remote_tpu_server_offload_and_local_fallback(self) -> None:
        tpu_srv, _ = start_tpu_server(host="127.0.0.1", port=0)
        tpu_port = tpu_srv.server_address[1]
        tpu_url = f"http://127.0.0.1:{tpu_port}"

        try:
            worker = TPUOffloadWorker(
                TPUOffloadConfig(
                    tpu_endpoint_url=tpu_url,
                    batch_size=2,
                    timeout_sec=3.0,
                    fallback_to_local=True,
                )
            )
            health = worker.check_remote_tpu_health()
            self.assertTrue(health["tpu_available"])
            self.assertEqual(health["backend"], "remote_google_tpu")
            self.assertGreaterEqual(health["gpu_load_saved_pct"], 90.0)

            sample_tiles = [
                {"tile_id": "t1", "rgb_mean": [60, 62, 65], "vn2000_x": 584200.0, "vn2000_y": 1194500.0},
                {"tile_id": "t2", "rgb_mean": [200, 202, 200], "vn2000_x": 584280.0, "vn2000_y": 1194500.0},
                {"tile_id": "t3", "rgb_mean": [40, 90, 160], "width_m": 12.0, "vn2000_x": 584360.0, "vn2000_y": 1194500.0},
            ]
            res = worker.infer_tile_batch(sample_tiles, metadata={"crs": "VN2000"})
            self.assertEqual(res["backend_used"], "remote_google_tpu")
            self.assertEqual(res["tile_count"], 3)
            self.assertEqual(res["batch_count"], 2)
            self.assertGreaterEqual(res["gpu_load_saved_pct"], 90.0)
            self.assertIn("KS_AO_HO", res["vn2000_layers"])
        finally:
            tpu_srv.shutdown()
            tpu_srv.server_close()

        # After remote TPU server shuts down, worker automatically falls back to local inference
        fallback_res = worker.infer_tile_batch(
            [{"tile_id": "t4", "rgb_mean": [180, 120, 80]}], metadata={"crs": "VN2000"}
        )
        self.assertEqual(fallback_res["backend_used"], "local_fallback")
        self.assertEqual(fallback_res["tile_count"], 1)

        # When fallback_to_local=False and remote TPU is offline, raises TPUOffloadError (ConnectionError/RuntimeError)
        strict_worker = TPUOffloadWorker(
            TPUOffloadConfig(
                tpu_endpoint_url=tpu_url,
                fallback_to_local=False,
                timeout_sec=1.0,
            )
        )
        with self.assertRaises((ConnectionError, RuntimeError, TPUOffloadError)):
            strict_worker.infer_tile_batch([{"tile_id": "t5", "rgb_mean": [100, 100, 100]}])

    def test_douglas_peucker_and_notebook_validity(self) -> None:
        pts = [(0.0, 0.0), (1.0, 0.01), (2.0, -0.01), (3.0, 0.0), (3.0, 4.0)]
        simplified = douglas_peucker(pts, epsilon=0.1)
        self.assertEqual(simplified, [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)])

        nb_path = PROJECT_ROOT / "notebooks" / "Colab_Ultra_TPU_Server_VN2000.ipynb"
        self.assertTrue(nb_path.exists())
        nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
        self.assertEqual(nb_data["nbformat"], 4)
        self.assertGreaterEqual(len(nb_data["cells"]), 3)


class TestRound3KeyManagementAndAutoTPUM3(unittest.TestCase):
    """Unit tests for F2 Auto Task Division, F6 >15m Auto-TPU Offload & YOLO Update RBAC, F7 7-Column Google Sheet Key Management, and F8 Processed Data Folder."""

    def test_auto_divide_and_spawn_tasks(self) -> None:
        policy = AgentGovernancePolicy()
        res = policy.auto_divide_and_spawn_tasks()
        self.assertEqual(res["survey_agents_count"], 5)
        self.assertTrue(res["architecture_approved"])
        self.assertGreaterEqual(len(res["assigned_tasks"]), 6)

    def test_7_column_google_sheet_key_manager_red_and_green_thresholds(self) -> None:
        import tempfile

        from uav_app.infrastructure.gdrive_key_storage import (
            GOOGLE_SHEET_HEADERS,
            PROCESSED_DATA_GDRIVE_FOLDER_ID,
            GoogleSheetKeyManager,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            km = GoogleSheetKeyManager(
                registry_path=tmp_path / "reg.json",
                sheet_csv_path=tmp_path / "sheet.csv",
            )
            self.assertEqual(len(GOOGLE_SHEET_HEADERS), 7)
            self.assertEqual(km.processed_data_folder_id, "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN")
            self.assertEqual(PROCESSED_DATA_GDRIVE_FOLDER_ID, "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN")

            # Create a 3h (10800s) guest key with allow_tpu=False at t=1000
            rec = km.create_key(
                recipient="Khách Hàng A",
                phone="0912345678",
                purpose="3h",
                allow_tpu=False,
                role="guest",
                issued_at_ts=1000.0,
            )
            key_str = rec["key"]
            self.assertEqual(rec["status_color"], "green")

            # At 50% remaining (t = 1000 + 5400 = 6400 -> remaining_ratio = 0.5 > 1/3): GREEN
            v_green = km.get_key(key_str, now_ts=6400.0)
            self.assertIsNotNone(v_green)
            assert v_green is not None
            self.assertEqual(v_green["status_color"], "green")
            self.assertFalse(v_green["is_warning_red"])

            # At exactly 1/3 remaining (t = 1000 + 7200 = 8200 -> remaining_ratio = 1/3): RED
            v_red = km.get_key(key_str, now_ts=8200.0)
            self.assertIsNotNone(v_red)
            assert v_red is not None
            self.assertEqual(v_red["status_color"], "red")
            self.assertTrue(v_red["is_warning_red"])

            # Delete key
            del_res = km.delete_key(key_str)
            self.assertTrue(del_res["deleted"])
            self.assertIsNone(km.get_key(key_str))

    def test_web_admin_key_endpoints_and_over_15m_auto_tpu_offload(self) -> None:
        import tempfile

        from uav_app.infrastructure.gdrive_key_storage import (
            DEFAULT_ADMIN_KEY,
            GoogleSheetKeyManager,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            km = GoogleSheetKeyManager(
                registry_path=tmp_path / "reg.json",
                sheet_csv_path=tmp_path / "sheet.csv",
            )
            srv, _ = start_background_server(host="127.0.0.1", port=0, key_manager=km)
            port = srv.server_address[1]
            base = f"http://127.0.0.1:{port}"
            try:
                # 1. Guest/unauthenticated GET /api/keys must return 403
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"{base}/api/keys", timeout=3)
                self.assertEqual(ctx.exception.code, 403)

                # 2. Admin GET /api/keys returns 200 with 7-column schema
                req_admin = urllib.request.Request(
                    f"{base}/api/keys",
                    headers={"X-Admin-Key": DEFAULT_ADMIN_KEY},
                )
                with urllib.request.urlopen(req_admin, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(data["column_count"], 7)
                    self.assertTrue(data["admin_panel_visible"])

                # 3. Admin creates 2 guest keys: one without TPU, one with allow_tpu=True
                def _post_json(url: str, payload: dict, headers: dict | None = None) -> tuple[int, dict]:
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json", **(headers or {})},
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=3) as r:
                            return r.status, json.loads(r.read().decode("utf-8"))
                    except urllib.error.HTTPError as e:
                        return e.code, json.loads(e.read().decode("utf-8"))

                st1, k_no_tpu = _post_json(
                    f"{base}/api/keys/create",
                    {"recipient": "Guest No TPU", "phone": "0901111111", "purpose": "1m", "allow_tpu": False},
                    {"X-Admin-Key": DEFAULT_ADMIN_KEY},
                )
                self.assertEqual(st1, 200)
                guest_no_tpu_key = k_no_tpu["key_record"]["key"]

                st2, k_with_tpu = _post_json(
                    f"{base}/api/keys/create",
                    {"recipient": "Guest With TPU", "phone": "0902222222", "purpose": "3m", "allow_tpu": True},
                    {"X-Admin-Key": DEFAULT_ADMIN_KEY},
                )
                self.assertEqual(st2, 200)
                guest_with_tpu_key = k_with_tpu["key_record"]["key"]

                # 4. Image detection > 15m (estimated_seconds=1200):
                #    - Guest without allow_tpu -> 403 Forbidden
                st_forbid, res_forbid = _post_json(
                    f"{base}/api/detect/upload",
                    {"key": guest_no_tpu_key, "estimated_seconds": 1200, "num_images": 4},
                )
                self.assertEqual(st_forbid, 403)
                self.assertFalse(res_forbid["offloaded_to_tpu"])

                #    - Guest WITH allow_tpu -> 200 OK & offloaded_to_tpu=True
                st_ok_guest, res_ok_guest = _post_json(
                    f"{base}/api/detect/upload",
                    {"key": guest_with_tpu_key, "estimated_seconds": 1200, "num_images": 4},
                )
                self.assertEqual(st_ok_guest, 200)
                self.assertTrue(res_ok_guest["offloaded_to_tpu"])
                self.assertEqual(
                    res_ok_guest["processed_data_folder_id"],
                    "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN",
                )

                #    - Admin key on YOLO update > 15m -> 200 OK & offloaded_to_tpu=True
                st_yolo, res_yolo = _post_json(
                    f"{base}/api/yolo/update",
                    {
                        "key": DEFAULT_ADMIN_KEY,
                        "new_classes": ["tram_bien_ap", "cot_dien_cao_the"],
                        "epochs": 50,
                        "dataset_size": 500,
                    },
                )
                self.assertEqual(st_yolo, 200)
                self.assertTrue(res_yolo["offloaded_to_tpu"])
                self.assertEqual(
                    res_yolo["processed_data_folder_id"],
                    "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN",
                )
                # 5. RTK Raw-Image Crown Patch Restoration (<=15m local GPU vs >15m TPU offload + DEM/DSM invariance)
                st_rtk_local, res_rtk_local = _post_json(
                    f"{base}/api/rtk/restore-crown",
                    {
                        "key": guest_no_tpu_key,
                        "estimated_seconds": 320,
                        "flight_sorties_count": 2,
                        "raw_images_count": 120,
                        "crown_center_vn2000": {"x": 570305.94, "y": 1178840.24, "z_dsm": 14.2},
                    },
                )
                self.assertEqual(st_rtk_local, 200)
                self.assertFalse(res_rtk_local["offloaded_to_tpu"])
                self.assertFalse(res_rtk_local["dem_dsm_invariance"]["dem_modified"])
                self.assertFalse(res_rtk_local["dem_dsm_invariance"]["dsm_modified"])
                self.assertEqual(
                    res_rtk_local["dem_dsm_invariance"]["dem_sha256_before"],
                    res_rtk_local["dem_dsm_invariance"]["dem_sha256_after"],
                )

                st_rtk_forbid, res_rtk_forbid = _post_json(
                    f"{base}/api/rtk/restore-crown",
                    {
                        "key": guest_no_tpu_key,
                        "estimated_seconds": 1400,
                        "flight_sorties_count": 6,
                        "raw_images_count": 1200,
                    },
                )
                self.assertEqual(st_rtk_forbid, 403)

                st_rtk_tpu, res_rtk_tpu = _post_json(
                    f"{base}/api/rtk/restore-crown",
                    {
                        "key": guest_with_tpu_key,
                        "estimated_seconds": 1400,
                        "flight_sorties_count": 6,
                        "raw_images_count": 1200,
                    },
                )
                self.assertEqual(st_rtk_tpu, 200)
                self.assertTrue(res_rtk_tpu["offloaded_to_tpu"])
                self.assertFalse(res_rtk_tpu["dem_dsm_invariance"]["dem_modified"])

                # 6. FPGA Many-Pixels-at-Once Parallel Edge Stencil
                with urllib.request.urlopen(f"{base}/api/fpga/status", timeout=3) as r_fpga_st:
                    fpga_st_data = json.loads(r_fpga_st.read().decode("utf-8"))
                    self.assertEqual(r_fpga_st.status, 200)
                    self.assertEqual(fpga_st_data["paradigm"], "many_pixels_at_once_parallel_stencil")

                st_fpga, res_fpga = _post_json(
                    f"{base}/api/fpga/parallel-edges",
                    {"key": DEFAULT_ADMIN_KEY, "parallel_lanes": 64, "tile_size": 256},
                )
                self.assertEqual(st_fpga, 200)
                self.assertGreater(res_fpga["benchmark"]["speedup_factor"], 1.0)
                self.assertGreater(res_fpga["cad_polylines_count"], 0)
            finally:
                srv.shutdown()
                srv.server_close()

    def test_full_resolution_preview_and_rtk_fpga_algorithms(self) -> None:
        from pathlib import Path
        import numpy as np
        from uav_app.infrastructure.rtk_patch_and_fpga_stencil import (
            FPGAParallelEdgeStencil,
            RTKRawCameraFrame,
            RTKRawPatchRestorer,
            project_vn2000_to_raw_pixel,
        )

        # 1. Verify 1600px downsampling cap was removed in raster.py & MO_WEB_NHAN_DIEN_NGAY.html
        raster_src = (Path(__file__).resolve().parents[2] / "uav_app/infrastructure/raster.py").read_text(encoding="utf-8")
        self.assertIn("MAX_PREVIEW_SIZE = 32768", raster_src)
        html = (Path(__file__).resolve().parents[2] / "MO_WEB_NHAN_DIEN_NGAY.html").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_REAL_UAV_ORTHO_URI", html)
        self.assertIn("URL.createObjectURL(imgFile)", html)
        self.assertNotIn("Ảnh tổng quan được giảm mẫu, cạnh dài tối đa 1600 px", html)

        # 2. Verify 3D Collinearity back-projection & RTK crown restoration without modifying DEM/DSM
        cam = RTKRawCameraFrame(
            frame_id="DJI_RTK_TEST_01.JPG",
            flight_sortie_id="SORTIE_01",
            x0_vn2000=570305.0,
            y0_vn2000=1178840.0,
            z0_m=95.0,
            omega_deg=0.1,
            phi_deg=-0.1,
            kappa_deg=0.0,
            focal_px=3666.6,
            width_px=5472,
            height_px=3648,
        )
        proj = project_vn2000_to_raw_pixel(570305.5, 1178840.2, 14.2, cam)
        self.assertTrue(proj["inside_fov"])
        self.assertLess(proj["nadir_angle_deg"], 5.0)

        ortho_rgb = np.full((64, 64, 3), 110, dtype=np.uint8)
        dem_grid = np.full((64, 64), 14.2, dtype=np.float32)
        restorer = RTKRawPatchRestorer()
        res_restore = restorer.restore_blurred_region_from_rtk_raw(
            ortho_rgb=ortho_rgb,
            dem_dsm_grid=dem_grid,
            target_vn2000_x=570305.5,
            target_vn2000_y=1178840.2,
            patch_bbox_px=(8, 8, 56, 56),
            raw_frames=[cam],
        )
        self.assertFalse(res_restore["dem_modified"])
        self.assertTrue(res_restore["dsm_checksum_preserved"])
        self.assertEqual(
            res_restore["dem_sha256_before"],
            res_restore["dem_sha256_after"],
        )

        # 3. Verify FPGA Many-Pixels-at-Once Stencil
        stencil = FPGAParallelEdgeStencil(parallel_lanes=64)
        bm = stencil.benchmark_cpu_vs_fpga_parallel(width=128, height=128)
        self.assertEqual(bm["hardware_telemetry"]["mode"], "many_pixels_at_once")
        self.assertGreater(bm["simd_webgpu_speedup_x"], 1.0)


if __name__ == "__main__":
    unittest.main()

