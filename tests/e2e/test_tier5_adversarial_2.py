#!/usr/bin/env python3
"""Tier 5 White-Box & Adversarial Verification Suite (Challenger 2).

Targets deep white-box edge cases across:
1. `douglas_peucker` & `_point_line_distance` geometry smoothing (collinear points,
   degenerate 0/1/2-point polylines, coincident start/end loop, epsilon <= 0, multi-bend).
2. `classify_and_vectorize_tile` spectral-morphological classifier & VN2000 vectorizer
   (all 6 VN2000 terrain classes via both spectral rules and explicit hints, extreme RGB
   and slope/width values, malformed inputs, VN2000 coordinate transformations).
3. `autostart_host.py` (`UAV_WEB_PORT` / `UAV_PORT` environment overrides, `cloudflared`
   YAML structure & ingress rule validation, shutdown hook & `stop()` idempotency,
   signal handler registration).
4. `notebooks/Colab_Ultra_TPU_Server_VN2000.ipynb` code cell AST syntax validation
   (`ast.parse` + runtime execution of notebook helper functions).
5. White-box governance & TPU offload boundary checks (`AgentGovernancePolicy`,
   `TPUOffloadConfig`, `TPUOffloadWorker`).
"""

from __future__ import annotations

import ast
import json
import math
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uav_app.adapters.tpu_offload_worker import (  # noqa: E402
    VN2000_TERRAIN_CLASSES,
    TPUOffloadConfig,
    TPUOffloadError,
    TPUOffloadWorker,
    _point_line_distance,
    classify_and_vectorize_tile,
    douglas_peucker,
)
from uav_app.infrastructure.agent_governance import (  # noqa: E402
    AgentGovernancePolicy,
    ArchitectureGateError,
    ConcurrencyLimitError,
    ModelTier,
)
from uav_app.infrastructure.autostart_host import (  # noqa: E402
    CUSTOM_DOMAIN,
    DEFAULT_PORT,
    DEFAULT_TUNNEL_ID,
    AutostartHostManager,
    enable_autostart_on_boot,
    generate_cloudflared_config,
    get_default_port,
)


class Tier5DouglasPeuckerAndVectorizationAdversarialTests(unittest.TestCase):
    """Adversarial & white-box tests for `douglas_peucker` and `classify_and_vectorize_tile`."""

    def test_douglas_peucker_degenerate_empty_single_and_two_point_polylines(self) -> None:
        """Verify 0-point, 1-point, and 2-point polylines and non-positive epsilons."""
        self.assertEqual(douglas_peucker([], epsilon=0.25), [])

        single_pt = [(584200.125, 1194500.875)]
        self.assertEqual(douglas_peucker(single_pt, epsilon=0.25), single_pt)

        two_pts = [(584200.0, 1194500.0), (584250.0, 1194525.0)]
        self.assertEqual(douglas_peucker(two_pts, epsilon=0.25), two_pts)

        # epsilon <= 0 must return all points untouched even if collinear
        collinear = [(584200.0 + i * 10.0, 1194500.0 + i * 5.0) for i in range(6)]
        self.assertEqual(douglas_peucker(collinear, epsilon=0.0), collinear)
        self.assertEqual(douglas_peucker(collinear, epsilon=-5.0), collinear)

    def test_douglas_peucker_collinear_points_collapse_to_endpoints(self) -> None:
        """Verify strictly collinear and near-collinear VN2000 points simplify to [start, end]."""
        # 20 strictly collinear points along a VN2000 survey line
        pts = [(584200.0 + i * 3.5, 1194500.0 + i * 1.75) for i in range(20)]
        simplified = douglas_peucker(pts, epsilon=0.01)
        self.assertEqual(len(simplified), 2)
        self.assertEqual(simplified[0], pts[0])
        self.assertEqual(simplified[-1], pts[-1])

        # Near-collinear points with perpendicular jitter < epsilon (0.05m < 0.25m)
        jittered = [
            (584200.0, 1194500.0),
            (584210.0, 1194500.04),
            (584220.0, 1194499.96),
            (584230.0, 1194500.02),
            (584240.0, 1194500.0),
        ]
        simplified_jitter = douglas_peucker(jittered, epsilon=0.25)
        self.assertEqual(simplified_jitter, [(584200.0, 1194500.0), (584240.0, 1194500.0)])

    def test_douglas_peucker_sharp_corners_and_closed_ring_coincident_endpoints(self) -> None:
        """Verify multi-bend polylines and closed loops (start == end -> denom < 1e-12)."""
        # Closed polygon ring where line_start == line_end
        closed_ring = [
            (584200.0, 1194500.0),
            (584250.0, 1194500.0),
            (584250.0, 1194550.0),
            (584200.0, 1194550.0),
            (584200.0, 1194500.0),
        ]
        dist = _point_line_distance(closed_ring[2], closed_ring[0], closed_ring[-1])
        self.assertAlmostEqual(dist, math.hypot(50.0, 50.0), places=6)

        simplified_ring = douglas_peucker(closed_ring, epsilon=0.25)
        self.assertGreaterEqual(len(simplified_ring), 4)
        self.assertEqual(simplified_ring[0], (584200.0, 1194500.0))
        self.assertEqual(simplified_ring[-1], (584200.0, 1194500.0))

    def test_classify_and_vectorize_tile_all_6_classes_spectral_and_explicit(self) -> None:
        """Verify all 6 VN2000 terrain classes via spectral branches and explicit class hints."""
        # 1. Spectral classification across all 6 classes without explicit hints
        spectral_cases = [
            # pond: water_idx > 0.12 and width_m >= 3.0
            ({"tile_id": "s_pond", "rgb_mean": [20, 65, 175], "width_m": 6.0}, "pond", "KS_AO_HO", 5),
            # masonry_ditch (narrow water channel): water_idx > 0.12 and width_m < 3.0
            ({"tile_id": "s_ditch_w", "rgb_mean": [20, 65, 175], "width_m": 1.2}, "masonry_ditch", "KS_MUONG_XAY", 6),
            # masonry_ditch (steep slope > 12 deg):
            ({"tile_id": "s_ditch_s", "rgb_mean": [125, 130, 120], "slope_deg": 18.5, "width_m": 2.5}, "masonry_ditch", "KS_MUONG_XAY", 6),
            # dirt_road: earth_warmth = (r - b)/255 > 0.14
            ({"tile_id": "s_dirt", "rgb_mean": [190, 130, 95], "width_m": 4.0}, "dirt_road", "KS_DUONG_DAT", 3),
            # concrete_road: luminance > 0.68 and abs(r - b) < 25
            ({"tile_id": "s_concrete", "rgb_mean": [215, 215, 210], "width_m": 5.0}, "concrete_road", "KS_DUONG_BETONG", 2),
            # asphalt_road: luminance < 0.38 and abs(r - g) < 20
            ({"tile_id": "s_asphalt", "rgb_mean": [48, 50, 54], "width_m": 6.0}, "asphalt_road", "KS_DUONG_NHUA", 1),
            # footpath (narrow width_m < 1.8 and slope <= 12):
            ({"tile_id": "s_footpath_w", "rgb_mean": [125, 130, 120], "slope_deg": 3.0, "width_m": 1.1}, "footpath", "KS_DUONG_DIBO", 4),
            # footpath (vegetated path exg >= 0.05):
            ({"tile_id": "s_footpath_exg", "rgb_mean": [105, 145, 105], "slope_deg": 2.0, "width_m": 3.5}, "footpath", "KS_DUONG_DIBO", 4),
        ]
        for tile_input, expected_class, expected_layer, expected_id in spectral_cases:
            res = classify_and_vectorize_tile(tile_input)
            self.assertEqual(res["terrain_class"], expected_class, f"Failed for {tile_input['tile_id']}")
            self.assertEqual(res["cad_layer"], expected_layer)
            self.assertEqual(res["class_id"], expected_id)
            self.assertGreaterEqual(res["confidence"], 0.70)
            self.assertLessEqual(res["confidence"], 1.0)

        # 2. Explicit hint classification for all 6 classes
        for cls_name, spec in VN2000_TERRAIN_CLASSES.items():
            res = classify_and_vectorize_tile({"tile_id": f"hint_{cls_name}", "class_hint": cls_name})
            self.assertEqual(res["terrain_class"], cls_name)
            self.assertEqual(res["cad_layer"], spec["cad_layer"])
            self.assertEqual(res["class_id"], spec["class_id"])
            self.assertEqual(res["confidence"], 0.96)

    def test_classify_and_vectorize_tile_extreme_values_and_vn2000_transforms(self) -> None:
        """Verify extreme RGB/slope/elevation values, malformed fields, and VN2000 coordinates."""
        # Non-dict tile raises ValueError
        for invalid_tile in (None, "not_a_dict", 42, [1, 2, 3]):
            with self.assertRaises(ValueError):
                classify_and_vectorize_tile(invalid_tile)  # type: ignore[arg-type]

        # Extreme black [0, 0, 0], extreme white [255, 255, 255], and out-of-range RGB + short rgb list
        res_black = classify_and_vectorize_tile({"tile_id": "blk", "rgb_mean": [0.0, 0.0, 0.0]})
        self.assertEqual(res_black["terrain_class"], "asphalt_road")
        self.assertEqual(res_black["spectral_features"]["luminance"], 0.0)

        res_white = classify_and_vectorize_tile({"tile_id": "wht", "rgb_mean": [255.0, 255.0, 255.0]})
        self.assertEqual(res_white["terrain_class"], "concrete_road")
        self.assertAlmostEqual(res_white["spectral_features"]["luminance"], 1.0, places=4)

        res_short_rgb = classify_and_vectorize_tile(
            {
                "tile_id": "fallback_rgb",
                "rgb_mean": [255.0],  # malformed length < 3 -> defaults to [128, 128, 128]
                "slope_deg": 89.9,
                "elevation_m": 3143.0,  # Fansipan extreme elevation metadata
            }
        )
        self.assertEqual(res_short_rgb["terrain_class"], "masonry_ditch")

        # VN2000 coordinate transformation with metadata and custom gsd_m / size_px
        meta = {"origin_x": 605000.0, "origin_y": 1210000.0, "gsd_m": 0.20}
        res_vn2000 = classify_and_vectorize_tile(
            {"tile_id": "vn_coord", "size_px": 1000},
            metadata=meta,
        )
        # span_m = 1000 * 0.20 = 200.0 -> start=(605000.0, 1210000.0), end=(605200.0, 1210096.0)
        poly = res_vn2000["lwpolyline_vn2000"]
        self.assertEqual(poly[0], [605000.0, 1210000.0])
        self.assertEqual(poly[-1], [605200.0, 1210096.0])

        # Degenerate 1-vertex custom `vertices` falls back to 5-point VN2000 span
        res_deg_verts = classify_and_vectorize_tile(
            {"tile_id": "deg_v", "vertices": [[584200.0, 1194500.0]]}
        )
        self.assertGreaterEqual(len(res_deg_verts["lwpolyline_vn2000"]), 2)


class Tier5AutostartHostAndCloudflaredAdversarialTests(unittest.TestCase):
    """Adversarial & white-box tests for `autostart_host.py` and `cloudflared` configuration."""

    def test_uav_web_port_and_uav_port_environment_overrides(self) -> None:
        """Verify `get_default_port` precedence, whitespace handling, and invalid port rejection."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_default_port(), DEFAULT_PORT)
            self.assertEqual(get_default_port(""), DEFAULT_PORT)
            self.assertEqual(get_default_port("   "), DEFAULT_PORT)

        with mock.patch.dict(os.environ, {"UAV_WEB_PORT": " 8766 "}, clear=True):
            self.assertEqual(get_default_port(), 8766)
            # Explicit parameter takes precedence over environment variable
            self.assertEqual(get_default_port(7860), 7860)

        with mock.patch.dict(os.environ, {"UAV_PORT": "7860"}, clear=True):
            self.assertEqual(get_default_port(), 7860)

        # Boundary ports 1 and 65535 succeed
        self.assertEqual(get_default_port(1), 1)
        self.assertEqual(get_default_port(65535), 65535)

        # Invalid ports raise ValueError
        for bad_port in (0, -1, 65536, 100000, "not_a_port", "8765.0", "http://8765"):
            with self.assertRaises(ValueError, msg=f"Expected ValueError for {bad_port!r}"):
                get_default_port(bad_port)

    def test_cloudflared_yaml_structure_and_domain_normalization(self) -> None:
        """Validate `generate_cloudflared_config` and `config/cloudflared_thietbibachkhoa.yml`."""
        yaml_text = generate_cloudflared_config(
            port=8765,
            domain="HTTPS://ThietBiBachKhoa.ID.VN/",
            tunnel_id="  custom-tunnel-id  ",
            secondary_port=8766,
        )
        self.assertIn("tunnel: custom-tunnel-id", yaml_text)
        self.assertIn("credentials-file: /etc/cloudflared/custom-tunnel-id.json", yaml_text)
        self.assertIn("protocol: quic", yaml_text)
        self.assertIn("no-autoupdate: true", yaml_text)
        self.assertIn("ingress:", yaml_text)
        self.assertIn("  - hostname: thietbibachkhoa.id.vn\n    service: http://127.0.0.1:8765", yaml_text)
        self.assertIn("  - hostname: www.thietbibachkhoa.id.vn\n    service: http://127.0.0.1:8765", yaml_text)
        self.assertIn("  - hostname: studio.thietbibachkhoa.id.vn\n    service: http://127.0.0.1:8766", yaml_text)

        # Last non-empty line in ingress must be the catch-all 404 service required by cloudflared
        non_empty_lines = [line.strip() for line in yaml_text.splitlines() if line.strip()]
        self.assertEqual(non_empty_lines[-1], "- service: http_status:404")

        # Validate on-disk config/cloudflared_thietbibachkhoa.yml
        disk_cfg = PROJECT_ROOT / "config" / "cloudflared_thietbibachkhoa.yml"
        self.assertTrue(disk_cfg.is_file())
        disk_lines = [line.strip() for line in disk_cfg.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertIn(f"tunnel: {DEFAULT_TUNNEL_ID}", disk_lines)
        self.assertEqual(disk_lines[-1], "- service: http_status:404")

        # Invalid arguments to generate_cloudflared_config raise ValueError
        for bad_port in (0, -80, 65536, "8765"):
            with self.assertRaises(ValueError):
                generate_cloudflared_config(port=bad_port)  # type: ignore[arg-type]
        for bad_domain in ("", "   ", "localhost", "https://", "http:///"):
            with self.assertRaises(ValueError):
                generate_cloudflared_config(port=8765, domain=bad_domain)

    def test_autostart_host_shutdown_hook_idempotency_and_signal_registration(self) -> None:
        """Verify `stop()` idempotency, callback exception isolation, and signal registration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "cloudflared_test.yml"
            mgr = AutostartHostManager(port=0, domain="https://thietbibachkhoa.id.vn/", config_path=cfg_path)

            # 1. Calling stop() before starting server is safe and idempotent
            pre_stop = mgr.stop()
            self.assertEqual(pre_stop["status"], "stopped")
            self.assertFalse(pre_stop["online"])
            self.assertFalse(mgr.is_running)

            # 2. Start server on ephemeral port and register both a working and a failing callback
            callback_Counter = {"count": 0}

            def good_cb() -> None:
                callback_Counter["count"] += 1

            def failing_cb() -> None:
                raise RuntimeError("Simulated shutdown hook error")

            mgr._shutdown_callbacks.extend([failing_cb, good_cb])
            started = mgr.start_web_server(host="127.0.0.1", port=0)
            self.assertEqual(started["status"], "started")
            self.assertTrue(mgr.is_running)
            self.assertGreater(mgr.port, 0)

            # 3. Call stop() 3 times in a row to verify full idempotency
            stop1 = mgr.stop()
            stop2 = mgr.stop()
            stop3 = mgr.stop()
            self.assertEqual(stop1["status"], "stopped")
            self.assertEqual(stop2["status"], "stopped")
            self.assertEqual(stop3["status"], "stopped")
            self.assertFalse(mgr.is_running)
            self.assertIsNone(mgr._server)
            self.assertEqual(callback_Counter["count"], 3)

            # 4. Verify signal registration and restore original signal handlers
            orig_sigterm = signal.getsignal(signal.SIGTERM)
            orig_sigint = signal.getsignal(signal.SIGINT)
            try:
                mgr.register_shutdown_signals()
                self.assertTrue(mgr.get_domain_lifecycle_status()["signals_registered"])
            finally:
                signal.signal(signal.SIGTERM, orig_sigterm)
                signal.signal(signal.SIGINT, orig_sigint)


class Tier5ColabNotebookSyntaxAndWhiteBoxGovernanceTests(unittest.TestCase):
    """Verify `Colab_Ultra_TPU_Server_VN2000.ipynb` Python AST syntax and governance white-box paths."""

    def test_colab_notebook_code_cells_are_valid_python_ast_and_executable(self) -> None:
        """Parse every code cell in `Colab_Ultra_TPU_Server_VN2000.ipynb` with `ast.parse`."""
        nb_path = PROJECT_ROOT / "notebooks" / "Colab_Ultra_TPU_Server_VN2000.ipynb"
        self.assertTrue(nb_path.is_file(), f"Missing notebook: {nb_path}")

        nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
        self.assertEqual(nb_data.get("nbformat"), 4)
        self.assertEqual(nb_data.get("metadata", {}).get("colab", {}).get("accelerator"), "TPU")

        cells = nb_data.get("cells", [])
        code_cells = [c for c in cells if c.get("cell_type") == "code"]
        self.assertGreaterEqual(len(code_cells), 2, "Expected at least 2 code cells in Colab TPU notebook")

        exec_namespace: dict = {}
        for idx, cell in enumerate(code_cells):
            source_lines = cell.get("source", [])
            source_text = "".join(source_lines) if isinstance(source_lines, list) else str(source_lines)
            self.assertTrue(source_text.strip(), f"Code cell {idx} is empty")

            # Verify valid Python syntax via ast.parse
            parsed_ast = ast.parse(source_text, filename=f"Colab_Ultra_TPU_Server_VN2000_cell_{idx}.py")
            self.assertIsInstance(parsed_ast, ast.Module)

            # Compile and execute cell in isolated namespace to verify no NameError/SyntaxError
            code_obj = compile(parsed_ast, filename=f"cell_{idx}", mode="exec")
            exec(code_obj, exec_namespace)  # noqa: S102

        self.assertIn("verify_google_tpu_accelerator", exec_namespace)
        self.assertIn("ColabTPUHandler", exec_namespace)
        tpu_check = exec_namespace["verify_google_tpu_accelerator"]()
        self.assertEqual(tpu_check["status"], "ok")

    def test_governance_and_tpu_config_whitebox_edge_cases(self) -> None:
        """Verify white-box edge cases in `AgentGovernancePolicy` and `TPUOffloadConfig`."""
        policy = AgentGovernancePolicy()

        # Hydrogen or Carbon cannot create or approve architecture plans
        for non_planner in ("hydrogen", "carbon"):
            with self.assertRaises(ValueError):
                policy.create_architecture_plan("p1", planner_tier=non_planner)
            with self.assertRaises(ValueError):
                policy.approve_architecture("p1", approved_by=non_planner)

        # Unapproved specific plan_id raises ArchitectureGateError even if another plan was approved
        policy.approve_architecture("approved-plan", approved_by=ModelTier.ARGON_HIGH)
        policy.create_architecture_plan("unapproved-plan", planner_tier=ModelTier.ARGON_HIGH)
        with self.assertRaises(ArchitectureGateError):
            policy.assign_role("task-blocked", difficulty="low", plan_id="unapproved-plan")

        # Deep optimization on low/medium difficulty automatically upgrades effort to "high"
        deep_low = policy.assign_role("task-deep-low", difficulty="low", requires_deep_optimization=True)
        self.assertEqual(deep_low["assigned_tier"], "carbon")
        self.assertEqual(deep_low["effort"], "high")
        self.assertEqual(deep_low["max_concurrent"], 10)

        # TPUOffloadConfig synchronizes api_key <-> gemini_api_key and validates batch_size/timeout
        cfg1 = TPUOffloadConfig(gemini_api_key="ultra-secret-key", tpu_endpoint_url="http://127.0.0.1:8470///")
        self.assertEqual(cfg1.api_key, "ultra-secret-key")
        self.assertEqual(cfg1.tpu_endpoint_url, "http://127.0.0.1:8470")

        with self.assertRaises(ValueError):
            TPUOffloadConfig(batch_size=0)
        with self.assertRaises(ValueError):
            TPUOffloadConfig(timeout_sec=0.0)

        # TPUOffloadWorker with no endpoint and fallback_to_local=False raises TPUOffloadError
        strict_worker = TPUOffloadWorker(TPUOffloadConfig(tpu_endpoint_url=None, fallback_to_local=False))
        with self.assertRaises(TPUOffloadError):
            strict_worker.infer_tile_batch([{"tile_id": "t1"}])

    def test_per_tile_rice_counting_100pct_quality_and_geotiff_binary_ifd_tags(self) -> None:
        """White-box verification of per-cropped-tile individual rice plant counting, 11 GeoTIFF IFD tags, DEM/DSM SHA-256 invariance, and selective replacement of only user_approved=True plants."""
        import base64
        import struct
        import numpy as np
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadWorker,
            build_lossless_geotiff_bytes,
            count_rice_plants_in_tile,
        )

        # 1. Per-tile individual rice plant counting with explicit and synthesized plants
        t_synth = count_rice_plants_in_tile({"tile_id": "tile_000010", "row": 2, "col": 1, "size_px": 512}, tile_idx=9)
        self.assertEqual(t_synth["quality_preserved_pct"], 100)
        self.assertTrue(t_synth["native_resolution_preserved"])
        self.assertEqual(t_synth["downsampling_factor"], 1.0)
        self.assertGreaterEqual(t_synth["plant_count"], 10)
        self.assertEqual(len(t_synth["plants"]), t_synth["plant_count"])
        self.assertGreater(t_synth["blurry_tip_count"], 0)

        # 2. Direct binary verification of all 11 sorted GeoTIFF IFD tags
        rgb_test = np.full((24, 36, 3), 128, dtype=np.uint8)
        tiff_raw = build_lossless_geotiff_bytes(
            rgb_test,
            base_x=572184.450,
            base_y=1181420.180,
            gsd_x=0.015,
            gsd_y=0.015,
        )
        self.assertEqual(tiff_raw[:4], b"II*\x00")
        (num_tags,) = struct.unpack_from("<H", tiff_raw, 8)
        self.assertEqual(num_tags, 11)

        ifd_map = {}
        tag_list = []
        for idx in range(num_tags):
            tag, ftype, count, val_off = struct.unpack_from("<HHII", tiff_raw, 10 + idx * 12)
            tag_list.append(tag)
            ifd_map[tag] = (ftype, count, val_off)

        self.assertEqual(tag_list, sorted(tag_list))
        self.assertEqual(tag_list, [256, 257, 258, 259, 262, 273, 277, 278, 279, 33550, 33922])
        self.assertEqual(ifd_map[256][2], 36)  # ImageWidth = 36
        self.assertEqual(ifd_map[257][2], 24)  # ImageLength = 24
        self.assertEqual(ifd_map[259][2], 1)   # Compression = 1 (Uncompressed lossless)
        self.assertEqual(ifd_map[262][2], 2)   # PhotometricInterpretation = 2 (RGB)
        self.assertEqual(ifd_map[277][2], 3)   # SamplesPerPixel = 3

        scale_vals = struct.unpack_from("<3d", tiff_raw, ifd_map[33550][2])
        self.assertAlmostEqual(scale_vals[0], 0.015, places=6)
        self.assertAlmostEqual(scale_vals[1], 0.015, places=6)
        tie_vals = struct.unpack_from("<6d", tiff_raw, ifd_map[33922][2])
        self.assertAlmostEqual(tie_vals[3], 572184.450, places=3)
        self.assertAlmostEqual(tie_vals[4], 1181420.180, places=3)

        # 3. Selective replacement of only user_approved=True plants & DEM/DSM SHA-256 invariance
        worker = TPUOffloadWorker()
        det = worker.detect_uploaded_images({"num_tiles": 2, "estimated_seconds": 45})
        blurry_all = det["blurry_tip_plants"]
        self.assertGreaterEqual(len(blurry_all), 2)
        p_yes = blurry_all[0]["plant_id"]
        p_no = blurry_all[1]["plant_id"]

        # Export with 0 approved plants
        exp_none = worker.export_edited_geotiff({"width": 32, "height": 32, "approved_plant_ids": []})
        self.assertEqual(exp_none["approved_replacements_applied"], 0)
        self.assertEqual(exp_none["rgb_sha256_before"], exp_none["rgb_sha256_after"])
        self.assertFalse(exp_none["dem_modified"])
        self.assertEqual(exp_none["dem_sha256_before"], exp_none["dem_sha256_after"])

        # Export with only p_yes approved and p_no unapproved
        worker.approve_blurry_plant_replacements(
            {"approve_all": False, "approved_plant_ids": [p_yes], "rejected_plant_ids": [p_no]}
        )
        exp_one = worker.export_edited_geotiff({"width": 32, "height": 32})
        self.assertEqual(exp_one["approved_replacements_applied"], 1)
        self.assertEqual(exp_one["applied_plant_ids"], [p_yes])
        self.assertIn(p_no, exp_one["skipped_unapproved_plant_ids"])
        self.assertNotEqual(exp_one["rgb_sha256_before"], exp_one["rgb_sha256_after"])
        self.assertFalse(exp_one["dem_modified"])
        self.assertTrue(exp_one["dsm_checksum_preserved"])
        self.assertEqual(exp_one["dem_sha256_before"], exp_one["dem_sha256_after"])

        # Verify pixel buffer inside exported GeoTIFF changed only at p_yes patch and not at p_no patch
        buf_none = base64.b64decode(exp_none["tiff_base64"])
        buf_one = base64.b64decode(exp_one["tiff_base64"])
        px_off = ifd_map[273][2]
        arr_none = np.frombuffer(buf_none[px_off:], dtype=np.uint8).reshape((32, 32, 3))
        arr_one = np.frombuffer(buf_one[px_off:], dtype=np.uint8).reshape((32, 32, 3))
        box_yes = exp_one["patch_placements"][p_yes]
        box_no = exp_one["patch_placements"][p_no]
        self.assertFalse(
            np.array_equal(
                arr_none[box_yes[1] : box_yes[3], box_yes[0] : box_yes[2]],
                arr_one[box_yes[1] : box_yes[3], box_yes[0] : box_yes[2]],
            )
        )
        self.assertTrue(
            np.array_equal(
                arr_none[box_no[1] : box_no[3], box_no[0] : box_no[2]],
                arr_one[box_no[1] : box_no[3], box_no[0] : box_no[2]],
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

