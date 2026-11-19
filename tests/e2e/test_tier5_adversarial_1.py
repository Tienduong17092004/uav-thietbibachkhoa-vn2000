#!/usr/bin/env python3
"""Tier 5 Adversarial Stress & White-Box Coverage Hardening Suite (Instance 1).

Targets:
1. High-concurrency thread-safety and boundary conditions in `AgentGovernancePolicy`
   (rapid slot acquisition/release up to 300 Hydrogen and 10 Carbon slots, interleaved
   multi-task failure/escalation sequences, unapproved plan rejection, invalid tier names).
2. Concurrent HTTP stress requests against `webgpu_public_server.py` and
   `scripts/run_colab_tpu_server.py` (malformed JSON, oversized payloads, missing fields,
   concurrent `/api/tpu/infer` calls, abrupt TPU server termination mid-batch).
3. White-box numeric, spectral, and lifecycle edge cases across `tpu_offload_worker.py`
   and `autostart_host.py`.
"""

from __future__ import annotations

import concurrent.futures
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_colab_tpu_server import (  # noqa: E402
    detect_google_tpu_device,
    start_tpu_server,
)
from uav_app.adapters.tpu_offload_worker import (  # noqa: E402
    TPUOffloadConfig,
    TPUOffloadError,
    TPUOffloadWorker,
    VN2000_TERRAIN_CLASSES,
    classify_and_vectorize_tile,
    douglas_peucker,
)
from uav_app.adapters.webgpu_public_server import (  # noqa: E402
    CUSTOM_DOMAIN,
    start_background_server,
)
from uav_app.infrastructure.agent_governance import (  # noqa: E402
    AgentGovernancePolicy,
    ArchitectureGateError,
    ConcurrencyLimitError,
    ModelTier,
    TaskDifficulty,
    main as governance_cli_main,
)
from uav_app.infrastructure.autostart_host import (  # noqa: E402
    AutostartHostManager,
    enable_autostart_on_boot,
    generate_cloudflared_config,
    get_default_port,
    main as autostart_cli_main,
)


def _http_request(
    url: str,
    method: str = "GET",
    raw_body: bytes | None = None,
    headers: Dict[str, str] | None = None,
    timeout: float = 10.0,
) -> Tuple[int, Dict[str, str], bytes]:
    req_headers = dict(headers or {})
    req = urllib.request.Request(url, data=raw_body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


class Tier5AdversarialStressTests(unittest.TestCase):
    """Tier 5 Adversarial & White-Box Stress Tests for UAV_GeoTIFF_WebGPU_Survey_VN2000."""

    def test_t5_01_governance_300_hydrogen_and_10_carbon_concurrent_slot_stress(self) -> None:
        """Stress-test rapid concurrent slot acquisition/release up to 300 Hydrogen and 10 Carbon slots."""
        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-stress-01", approved_by=ModelTier.ARGON_HIGH)

        # 60 worker invocations each acquiring 5 Hydrogen slots -> exact 300 boundary
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
            futures = [pool.submit(policy.acquire_agent_slot, "hydrogen", 5) for _ in range(60)]
            results = [f.result() for f in futures]
        self.assertEqual(len(results), 60)
        self.assertEqual(policy.active_slots["hydrogen"], 300)

        # 301st Hydrogen slot must fail with ConcurrencyLimitError
        with self.assertRaises(ConcurrencyLimitError):
            policy.acquire_agent_slot("hydrogen", 1)

        # 10 worker invocations each acquiring 1 Carbon slot -> exact 10 boundary
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            c_futures = [pool.submit(policy.acquire_agent_slot, ModelTier.CARBON, 1) for _ in range(10)]
            c_results = [f.result() for f in c_futures]
        self.assertEqual(len(c_results), 10)
        self.assertEqual(policy.active_slots["carbon"], 10)

        # 11th Carbon slot must fail with ConcurrencyLimitError
        with self.assertRaises(ConcurrencyLimitError):
            policy.acquire_agent_slot("carbon", 1)

        # Flexible Argon and Argon High tiers allow >500 slots without cap
        res_argon = policy.acquire_agent_slot("argon", 500)
        res_argon_high = policy.acquire_agent_slot("argon_high", 500)
        self.assertIsNone(res_argon["max_concurrent"])
        self.assertIsNone(res_argon_high["max_concurrent"])
        self.assertEqual(policy.active_slots["argon"], 500)
        self.assertEqual(policy.active_slots["argon_high"], 500)

        # Release all slots across threads and verify exact zero return
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
            rel_h = [pool.submit(policy.release_agent_slot, "hydrogen", 5) for _ in range(60)]
            rel_c = [pool.submit(policy.release_agent_slot, "carbon", 1) for _ in range(10)]
            for f in rel_h + rel_c:
                f.result()
        policy.release_agent_slot("argon", 500)
        policy.release_agent_slot("argon_high", 500)

        self.assertEqual(policy.active_slots["hydrogen"], 0)
        self.assertEqual(policy.active_slots["carbon"], 0)
        self.assertEqual(policy.active_slots["argon"], 0)
        self.assertEqual(policy.active_slots["argon_high"], 0)

    def test_t5_02_governance_interleaved_multitask_failure_escalation_and_recovery(self) -> None:
        """Stress-test interleaved failure/escalation sequences across 50 tasks."""
        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-interleaved", approved_by="argon_high")

        for i in range(50):
            diff = ["low", "medium", "high", "critical"][i % 4]
            policy.assign_role(f"task-{i}", difficulty=diff)

        def _drive_task(idx: int) -> Dict[str, Any]:
            tid = f"task-{idx}"
            if idx % 3 == 0:
                # 1 failure then pass -> stays on hydrogen
                f1 = policy.record_test_failure(tid, "syntax error")
                assert f1["action"] == "SELF_FIX" and not f1["escalated"]
                return policy.record_test_success(tid)
            if idx % 3 == 1:
                # 2 failures then pass -> stays on hydrogen
                f1 = policy.record_test_failure(tid, "fail 1")
                f2 = policy.record_test_failure(tid, "fail 2")
                assert f1["action"] == "SELF_FIX" and f2["action"] == "SELF_FIX"
                assert f2["self_fix_attempts"] == 2 and not f2["escalated"]
                return policy.record_test_success(tid)
            # 3 failures -> escalates to carbon, then 4th failure stays carbon, then pass
            f1 = policy.record_test_failure(tid, "fail 1")
            f2 = policy.record_test_failure(tid, "fail 2")
            f3 = policy.record_test_failure(tid, "fail 3")
            f4 = policy.record_test_failure(tid, "fail 4")
            assert f1["action"] == "SELF_FIX" and f2["action"] == "SELF_FIX"
            assert f3["action"] == "ESCALATE_TO_CARBON" and f3["escalated"] is True
            assert f3["assigned_tier"] == "carbon"
            assert f4["action"] == "ESCALATE_TO_CARBON" and f4["failure_count"] == 4
            return policy.record_test_success(tid)

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            outcomes = list(pool.map(_drive_task, range(50)))

        for idx, res in enumerate(outcomes):
            self.assertEqual(res["status"], "PASSED")
            if idx % 3 == 2:
                self.assertTrue(res["escalated"])
                self.assertEqual(res["assigned_tier"], "carbon")
                self.assertEqual(res["failure_count"], 4)
            else:
                self.assertFalse(res["escalated"])
                self.assertEqual(res["assigned_tier"], "hydrogen")

        # Also test auto-registration of previously unassigned tasks on failure & success
        auto_fail = policy.record_test_failure("unregistered-task-fail", "spontaneous error")
        self.assertEqual(auto_fail["action"], "SELF_FIX")
        self.assertEqual(auto_fail["tier"], "hydrogen")

        auto_pass = policy.record_test_success("unregistered-task-pass")
        self.assertEqual(auto_pass["status"], "PASSED")
        self.assertEqual(auto_pass["tier"], "hydrogen")

    def test_t5_03_governance_unapproved_plan_rejection_and_invalid_inputs(self) -> None:
        """Verify white-box error branches in AgentGovernancePolicy."""
        policy = AgentGovernancePolicy()

        # Survey agent boundary validation
        with self.assertRaises(ValueError):
            policy.create_initial_survey_dispatch(0)
        with self.assertRaises(ValueError):
            policy.create_initial_survey_dispatch(301)
        survey = policy.create_initial_survey_dispatch(5)
        self.assertEqual(survey["agent_count"], 5)

        # Architecture gate blocks role assignment prior to approval
        with self.assertRaises(ArchitectureGateError):
            policy.assign_role("task-blocked", difficulty="medium")

        # Non-Argon tiers cannot create or approve architecture plans
        with self.assertRaises(ValueError):
            policy.create_architecture_plan("bad-plan", planner_tier="hydrogen")
        with self.assertRaises(ValueError):
            policy.create_architecture_plan("   ")
        with self.assertRaises(ValueError):
            policy.approve_architecture("bad-plan", approved_by="carbon")
        with self.assertRaises(ValueError):
            policy.approve_architecture("")

        # Approve plan-A, create unapproved plan-B, and verify plan-B is still rejected
        policy.approve_architecture("plan-A", approved_by="argon_high")
        policy.create_architecture_plan("plan-B", planner_tier="argon")
        with self.assertRaises(ArchitectureGateError):
            policy.assign_role("task-on-unapproved-plan", plan_id="plan-B")
        with self.assertRaises(ArchitectureGateError):
            policy.assign_role("task-on-nonexistent-plan", plan_id="plan-does-not-exist")

        # Deep optimization upgrades low/medium difficulty effort to high and assigns carbon
        opt_task = policy.assign_role(
            "task-deep-opt",
            difficulty=TaskDifficulty.LOW,
            requires_deep_optimization=True,
        )
        self.assertEqual(opt_task["assigned_tier"], "carbon")
        self.assertEqual(opt_task["effort"], "high")
        self.assertEqual(opt_task["max_concurrent"], 10)

        # Flexible Argon assignment
        argon_task = policy.assign_role("task-argon", difficulty="high", use_argon=True)
        self.assertEqual(argon_task["assigned_tier"], "argon")
        self.assertIsNone(argon_task["max_concurrent"])

        # Invalid task_id, tier names, difficulties, and slot counts
        with self.assertRaises(ValueError):
            policy.assign_role("   ")
        with self.assertRaises(ValueError):
            policy.assign_role("task-bad-diff", difficulty="ultra_impossible")
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("invalid_tier_xyz", 1)
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("hydrogen", 0)
        with self.assertRaises(ValueError):
            policy.release_agent_slot("hydrogen", 0)
        with self.assertRaises(ValueError):
            policy.release_agent_slot("hydrogen", 1)
        with self.assertRaises(ValueError):
            policy.record_test_failure("   ", "err")
        with self.assertRaises(ValueError):
            policy.record_test_success("")

        # CLI main entrypoint verification
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = governance_cli_main(["--status"])
        self.assertEqual(rc, 0)
        cli_data = json.loads(buf.getvalue())
        self.assertEqual(cli_data["concurrency_limits"]["hydrogen"], 300)
        self.assertEqual(cli_data["concurrency_limits"]["carbon"], 10)

    def test_t5_04_webgpu_server_malformed_json_missing_fields_and_invalid_types(self) -> None:
        """Send malformed JSON, non-object JSON, missing fields, and invalid tile items to webgpu_public_server."""
        server, _ = start_background_server(host="127.0.0.1", port=0)
        port = server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        try:
            # 1. Empty body
            code, _, body = _http_request(f"{base_url}/api/tpu/infer", method="POST", raw_body=b"")
            self.assertEqual(code, 400)
            self.assertIn("empty", json.loads(body)["error"].lower())

            # 2. Malformed JSON syntax
            code, _, body = _http_request(
                f"{base_url}/api/tpu/infer",
                method="POST",
                raw_body=b'{"tiles": [{"tile_id": "t1"',
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(code, 400)
            self.assertIn("invalid json", json.loads(body)["error"].lower())

            # 3. Non-UTF8 binary garbage
            code, _, body = _http_request(
                f"{base_url}/api/tpu/infer",
                method="POST",
                raw_body=b"\xff\xfe\xfd\x00\x80",
            )
            self.assertEqual(code, 400)

            # 4. Valid JSON but not a dict (JSON array, string, number)
            for non_dict_payload in (b"[1, 2, 3]", b'"hello"', b"42"):
                code, _, body = _http_request(
                    f"{base_url}/api/tpu/infer",
                    method="POST",
                    raw_body=non_dict_payload,
                )
                self.assertEqual(code, 400)
                self.assertIn("object", json.loads(body)["error"].lower())

            # 5. Missing 'tiles', null 'tiles', empty 'tiles', string 'tiles'
            for bad_tiles_obj in (
                {"metadata": {"crs": "VN2000"}},
                {"tiles": None},
                {"tiles": []},
                {"tiles": "not-a-list"},
            ):
                code, _, body = _http_request(
                    f"{base_url}/api/tpu/infer",
                    method="POST",
                    raw_body=json.dumps(bad_tiles_obj).encode("utf-8"),
                )
                self.assertEqual(code, 400)

            # 6. 'tiles' list containing non-dict items triggers ValueError -> HTTP 400
            code, _, body = _http_request(
                f"{base_url}/api/tpu/infer",
                method="POST",
                raw_body=json.dumps({"tiles": ["not_a_dict_item"]}).encode("utf-8"),
            )
            self.assertEqual(code, 400)
            self.assertIn("dict", json.loads(body)["error"].lower())

            # 7. Unknown GET and POST endpoints -> HTTP 404
            code_get, _, _ = _http_request(f"{base_url}/api/nonexistent_route", method="GET")
            code_post, _, _ = _http_request(
                f"{base_url}/api/nonexistent_route",
                method="POST",
                raw_body=b"{}",
            )
            self.assertEqual(code_get, 404)
            self.assertEqual(code_post, 404)

            # 8. All HTML portal paths return HTTP 200 with X-Custom-Domain header
            for html_path in ("/", "/webgpu.html", "/index.html", "/advanced.html", "/MO_WEB_NHAN_DIEN_NGAY.html"):
                c, hdrs, html_bytes = _http_request(f"{base_url}{html_path}", method="GET")
                self.assertEqual(c, 200)
                self.assertIn(CUSTOM_DOMAIN, html_bytes.decode("utf-8"))
                self.assertEqual(hdrs.get("X-Custom-Domain"), CUSTOM_DOMAIN)
        finally:
            server.shutdown()
            server.server_close()

    def test_t5_05_colab_tpu_server_adversarial_payloads_and_routes(self) -> None:
        """Stress-test run_colab_tpu_server.py with malformed requests, bad routes, and env device detection."""
        tpu_server, _ = start_tpu_server(host="127.0.0.1", port=0)
        tpu_port = tpu_server.server_address[1]
        base_url = f"http://127.0.0.1:{tpu_port}"
        try:
            # Health routes
            for h_path in ("/", "/health", "/api/tpu/health"):
                code, _, raw = _http_request(f"{base_url}{h_path}", method="GET")
                self.assertEqual(code, 200)
                data = json.loads(raw)
                self.assertTrue(data["tpu_available"])
                self.assertEqual(data["gpu_load_saved_pct"], 92.5)

            # 404 routes
            c_get, _, _ = _http_request(f"{base_url}/unknown", method="GET")
            c_post, _, _ = _http_request(f"{base_url}/unknown", method="POST", raw_body=b"{}")
            self.assertEqual(c_get, 404)
            self.assertEqual(c_post, 404)

            # Malformed JSON on /infer
            c_bad_json, _, _ = _http_request(f"{base_url}/infer", method="POST", raw_body=b"{bad_json")
            self.assertEqual(c_bad_json, 400)

            # Empty body / missing tiles on /infer
            c_empty, _, _ = _http_request(f"{base_url}/infer", method="POST", raw_body=b"")
            self.assertEqual(c_empty, 400)

            # Non-dict tile item on /api/tpu/infer
            c_bad_tile, _, _ = _http_request(
                f"{base_url}/api/tpu/infer",
                method="POST",
                raw_body=json.dumps({"tiles": [12345]}).encode("utf-8"),
            )
            self.assertEqual(c_bad_tile, 400)

            # Test COLAB_TPU_ADDR environment variable detection
            old_env = os.environ.get("COLAB_TPU_ADDR")
            try:
                os.environ["COLAB_TPU_ADDR"] = "10.0.0.2:8470"
                dev = detect_google_tpu_device()
                self.assertTrue(dev["tpu_detected"])
                self.assertIn("10.0.0.2:8470", dev["tpu_device"])
            finally:
                if old_env is None:
                    os.environ.pop("COLAB_TPU_ADDR", None)
                else:
                    os.environ["COLAB_TPU_ADDR"] = old_env
        finally:
            tpu_server.shutdown()
            tpu_server.server_close()

    def test_t5_06_oversized_payload_and_high_concurrency_http_stress(self) -> None:
        """Stress-test oversized 120-tile batch payloads and 40 concurrent HTTP requests across both servers."""
        tpu_server, _ = start_tpu_server(host="127.0.0.1", port=0)
        tpu_port = tpu_server.server_address[1]
        tpu_worker = TPUOffloadWorker(
            tpu_endpoint_url=f"http://127.0.0.1:{tpu_port}",
            api_key="ultra-tpu-stress-key",
            batch_size=8,
            timeout_sec=10.0,
            fallback_to_local=True,
        )
        web_server, _ = start_background_server(
            host="127.0.0.1",
            port=0,
            tpu_worker=tpu_worker,
        )
        web_port = web_server.server_address[1]
        web_url = f"http://127.0.0.1:{web_port}"

        try:
            # 1. Oversized 120-tile batch with dense custom vertices (15 batches of 8 tiles)
            classes = list(VN2000_TERRAIN_CLASSES.keys())
            oversized_tiles = [
                {
                    "tile_id": f"oversized_tile_{i:03d}",
                    "terrain_class": classes[i % len(classes)],
                    "rgb_mean": [40.0 + (i % 150), 50.0 + (i % 120), 60.0 + (i % 100)],
                    "vn2000_x": 584000.0 + i * 25.0,
                    "vn2000_y": 1194000.0 + i * 25.0,
                    "vertices": [
                        [584000.0 + i * 25.0 + k * 2.0, 1194000.0 + i * 25.0 + (k % 3) * 0.5]
                        for k in range(25)
                    ],
                }
                for i in range(120)
            ]
            payload = json.dumps(
                {
                    "tiles": oversized_tiles,
                    "metadata": {"crs": "EPSG:9210", "survey_region": "VN2000_STRESS_TEST"},
                }
            ).encode("utf-8")

            code, _, raw = _http_request(
                f"{web_url}/api/tpu/infer",
                method="POST",
                raw_body=payload,
                headers={"Content-Type": "application/json"},
                timeout=15.0,
            )
            self.assertEqual(code, 200)
            resp_data = json.loads(raw)
            self.assertEqual(resp_data["backend_used"], "remote_google_tpu")
            self.assertTrue(resp_data["tpu_offloaded"])
            self.assertEqual(resp_data["tile_count"], 120)
            self.assertEqual(resp_data["batch_count"], 15)
            self.assertEqual(len(resp_data["tile_results"]), 120)
            self.assertEqual(sorted(resp_data["classes_detected"]), sorted(classes))

            # 2. 40 concurrent mixed GET/POST requests
            def _worker_req(idx: int) -> int:
                mode = idx % 5
                if mode == 0:
                    c, _, b = _http_request(f"{web_url}/api/health")
                    assert json.loads(b)["status"] == "ok"
                    return c
                if mode == 1:
                    c, _, b = _http_request(f"{web_url}/api/domain-status")
                    assert json.loads(b)["domain"] == CUSTOM_DOMAIN
                    return c
                if mode == 2:
                    c, _, b = _http_request(f"{web_url}/api/agent-tiers")
                    assert json.loads(b)["concurrency_limits"]["hydrogen"] == 300
                    return c
                if mode == 3:
                    c, _, b = _http_request(f"{web_url}/api/tpu/status")
                    assert json.loads(b)["tpu_available"] is True
                    return c
                small_batch = json.dumps(
                    {
                        "tiles": [
                            {"tile_id": f"conc_{idx}_a", "rgb_mean": [35, 35, 35]},
                            {"tile_id": f"conc_{idx}_b", "rgb_mean": [30, 80, 160], "width_m": 6.0},
                        ]
                    }
                ).encode("utf-8")
                c, _, b = _http_request(
                    f"{web_url}/api/tpu/infer",
                    method="POST",
                    raw_body=small_batch,
                    headers={"Content-Type": "application/json"},
                )
                parsed = json.loads(b)
                assert parsed["tile_count"] == 2 and parsed["backend_used"] == "remote_google_tpu"
                return c

            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                statuses = list(pool.map(_worker_req, range(40)))
            self.assertEqual(statuses, [200] * 40)
        finally:
            web_server.shutdown()
            web_server.server_close()
            tpu_server.shutdown()
            tpu_server.server_close()

    def test_t5_07_abrupt_tpu_server_termination_mid_batch_fallback_and_strict_503(self) -> None:
        """Simulate abrupt TPU server failure after batch 1 of a multi-batch job (fallback=True vs False)."""
        call_counter = {"count": 0}

        class _MidBatchDropHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_POST(self) -> None:
                call_counter["count"] += 1
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if call_counter["count"] == 1:
                    # Succeed on batch 1
                    results = [
                        classify_and_vectorize_tile(t, accelerator="TPU-Batch-1")
                        for t in body.get("tiles", [])
                    ]
                    raw = json.dumps({"status": "ok", "tile_results": results}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                else:
                    # Abruptly fail with HTTP 500 on batch 2 (simulating TPU runtime crash mid-batch)
                    self.send_response(500)
                    self.end_headers()

        drop_server = ThreadingHTTPServer(("127.0.0.1", 0), _MidBatchDropHandler)
        drop_thread = threading.Thread(target=drop_server.serve_forever, daemon=True)
        drop_thread.start()
        drop_port = drop_server.server_address[1]

        tiles_4 = [{"tile_id": f"mid_drop_{i}", "rgb_mean": [190, 190, 190]} for i in range(4)]

        try:
            # Case A: fallback_to_local=True -> seamlessly recovers via local fallback on batch 2 failure
            worker_resilient = TPUOffloadWorker(
                tpu_endpoint_url=f"http://127.0.0.1:{drop_port}",
                batch_size=2,
                timeout_sec=3.0,
                fallback_to_local=True,
            )
            res = worker_resilient.infer_tile_batch(tiles_4)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["backend_used"], "local_fallback")
            self.assertFalse(res["tpu_offloaded"])
            self.assertEqual(res["tile_count"], 4)

            # Case B: fallback_to_local=False -> web server returns HTTP 503 Service Unavailable
            call_counter["count"] = 0
            worker_strict = TPUOffloadWorker(
                tpu_endpoint_url=f"http://127.0.0.1:{drop_port}",
                batch_size=2,
                timeout_sec=3.0,
                fallback_to_local=False,
            )
            web_srv, _ = start_background_server(
                host="127.0.0.1",
                port=0,
                tpu_worker=worker_strict,
            )
            web_port = web_srv.server_address[1]
            try:
                code, _, raw = _http_request(
                    f"http://127.0.0.1:{web_port}/api/tpu/infer",
                    method="POST",
                    raw_body=json.dumps({"tiles": tiles_4}).encode("utf-8"),
                )
                self.assertEqual(code, 503)
                self.assertIn("Failed to offload", json.loads(raw)["error"])
            finally:
                web_srv.shutdown()
                web_srv.server_close()

            # Case C: fallback_to_local=False with no endpoint configured -> raises TPUOffloadError
            worker_no_url = TPUOffloadWorker(tpu_endpoint_url=None, fallback_to_local=False)
            with self.assertRaises(TPUOffloadError):
                worker_no_url.infer_tile_batch(tiles_4)
        finally:
            drop_server.shutdown()
            drop_server.server_close()

    def test_t5_08_whitebox_spectral_vectorization_and_autostart_edge_cases(self) -> None:
        """Cover remaining white-box branches in tpu_offload_worker.py and autostart_host.py."""
        # 1. Douglas-Peucker degenerate coincident endpoints (start == end -> denom < 1e-12)
        loop_pts = [(100.0, 200.0), (105.0, 208.0), (100.0, 200.0)]
        simplified_loop = douglas_peucker(loop_pts, epsilon=0.5)
        self.assertGreaterEqual(len(simplified_loop), 2)
        self.assertEqual(douglas_peucker([(1.0, 1.0)], epsilon=0.5), [(1.0, 1.0)])
        self.assertEqual(douglas_peucker(loop_pts, epsilon=0.0), loop_pts)

        # 2. All 6 spectral terrain classification branches (without explicit terrain_class hint)
        # - pond: high blue water index, width_m >= 3.0
        r_pond = classify_and_vectorize_tile({"tile_id": "p", "rgb_mean": [20, 60, 150], "width_m": 5.0})
        self.assertEqual(r_pond["terrain_class"], "pond")

        # - masonry_ditch via water index with narrow width_m < 3.0
        r_ditch_w = classify_and_vectorize_tile({"tile_id": "dw", "rgb_mean": [20, 60, 150], "width_m": 1.5})
        self.assertEqual(r_ditch_w["terrain_class"], "masonry_ditch")

        # - dirt_road: high earth warmth (R - B) / 255 > 0.14
        r_dirt = classify_and_vectorize_tile({"tile_id": "dr", "rgb_mean": [180, 120, 80]})
        self.assertEqual(r_dirt["terrain_class"], "dirt_road")

        # - concrete_road: high luminance > 0.68 and |R - B| < 25
        r_conc = classify_and_vectorize_tile({"tile_id": "cr", "rgb_mean": [210, 210, 205]})
        self.assertEqual(r_conc["terrain_class"], "concrete_road")

        # - asphalt_road: low luminance < 0.38 and |R - G| < 20
        r_asph = classify_and_vectorize_tile({"tile_id": "ar", "rgb_mean": [50, 52, 55]})
        self.assertEqual(r_asph["terrain_class"], "asphalt_road")

        # - masonry_ditch via steep slope > 12.0 deg (moderate luminance, low warmth)
        r_ditch_s = classify_and_vectorize_tile(
            {"tile_id": "ds", "rgb_mean": [120, 130, 120], "slope_deg": 15.0, "width_m": 2.5}
        )
        self.assertEqual(r_ditch_s["terrain_class"], "masonry_ditch")

        # - footpath via slope 9.0 deg or narrow width < 1.8m
        r_foot = classify_and_vectorize_tile(
            {"tile_id": "fp", "rgb_mean": [120, 130, 120], "slope_deg": 9.5, "width_m": 1.2}
        )
        self.assertEqual(r_foot["terrain_class"], "footpath")

        # - default fallback branch with malformed/short rgb (defaults to [128, 128, 128])
        r_def = classify_and_vectorize_tile({"tile_id": "def", "rgb": [100]})
        self.assertIn(r_def["terrain_class"], VN2000_TERRAIN_CLASSES)

        # - non-dict tile raises ValueError
        with self.assertRaises(ValueError):
            classify_and_vectorize_tile("invalid_tile")  # type: ignore[arg-type]

        # 3. TPUOffloadConfig validation & key synchronization
        with self.assertRaises(ValueError):
            TPUOffloadConfig(batch_size=0)
        with self.assertRaises(ValueError):
            TPUOffloadConfig(timeout_sec=-1.0)
        cfg_sync = TPUOffloadConfig(gemini_api_key="gem-ultra-key")
        self.assertEqual(cfg_sync.api_key, "gem-ultra-key")

        # 4. AutostartHostManager boundaries, subprocess cleanup, and callback resilience
        with self.assertRaises(ValueError):
            get_default_port(0)
        with self.assertRaises(ValueError):
            get_default_port(70000)
        with self.assertRaises(ValueError):
            generate_cloudflared_config(port=0)
        with self.assertRaises(ValueError):
            generate_cloudflared_config(domain="invalid_domain_without_dot")

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "cloudflared_test.yml"
            mgr = AutostartHostManager(port=0, domain=CUSTOM_DOMAIN, config_path=cfg_file)
            mgr.ensure_cloudflared_config()
            self.assertTrue(cfg_file.exists())

            # Attach a dummy sleeping subprocess and two shutdown callbacks (one raising, one succeeding)
            cb_called = {"ok": False}

            def _bad_cb() -> None:
                raise RuntimeError("simulated callback error")

            def _good_cb() -> None:
                cb_called["ok"] = True

            mgr._shutdown_callbacks.extend([_bad_cb, _good_cb])
            mgr._tunnel_process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            mgr.start_web_server(port=0)
            self.assertTrue(mgr.is_running)

            stop_info = mgr.stop()
            self.assertFalse(mgr.is_running)
            self.assertFalse(stop_info["online"])
            self.assertTrue(cb_called["ok"])
            self.assertIsNone(mgr._tunnel_process)

        # 5. enable_autostart_on_boot and CLI main
        boot_status = enable_autostart_on_boot()
        self.assertTrue(boot_status["autostart_enabled"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = autostart_cli_main(["--status"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())["domain"], CUSTOM_DOMAIN)

    def test_t5_09_realtime_telemetry_blurry_plant_approval_and_tiff_export_stress(self) -> None:
        """Concurrent real-time hardware telemetry polling, malformed approval payload rejection (HTTP 400), and lossless GeoTIFF (.tiff) IFD binary verification."""
        import base64
        import struct
        from concurrent.futures import ThreadPoolExecutor

        srv, thread = start_background_server(host="127.0.0.1", port=0)
        port = srv.server_address[1]
        base = f"http://127.0.0.1:{port}"
        try:
            # 1. Concurrent polling of /api/hardware/realtime across 16 parallel requests
            with ThreadPoolExecutor(max_workers=8) as pool:
                futs = [pool.submit(_http_request, f"{base}/api/hardware/realtime") for _ in range(16)]
                results = [f.result() for f in futs]

            poll_seqs = []
            for code, _hdrs, raw in results:
                self.assertEqual(code, 200)
                data = json.loads(raw.decode("utf-8"))
                self.assertEqual(data["status"], "ok")
                self.assertTrue(data["realtime"])
                self.assertGreaterEqual(data["active_worker_threads"], 1)
                poll_seqs.append(data["poll_seq"])
            self.assertEqual(len(set(poll_seqs)), 16)

            # 2. Malformed approval & export payloads must return HTTP 400
            bad_approval_payloads = [
                {"approved_plant_ids": "not-a-list"},
                {"approved_plant_ids": [""]},
                {"rejected_plant_ids": [123]},
                {"decisions": "not-a-list"},
                {"decisions": [{"plant_id": "p1"}]},
                {"decisions": [{"plant_id": "p1", "approved": "yes"}]},
                {"approve_all": "true"},
            ]
            for bad in bad_approval_payloads:
                code, _hdrs, raw = _http_request(
                    f"{base}/api/plants/approve-replacement",
                    method="POST",
                    raw_body=json.dumps(bad).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(code, 400, f"Expected 400 for {bad}, got {code}: {raw!r}")

            for bad_tiff in ({"width": 0}, {"height": -5}, {"width": 5000}, {"gsd_x": 0}):
                code, _hdrs, raw = _http_request(
                    f"{base}/api/tiff/export",
                    method="POST",
                    raw_body=json.dumps(bad_tiff).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(code, 400, f"Expected 400 for {bad_tiff}, got {code}: {raw!r}")

            # 3. Approve 2 blurry-tip plants, reject 1, and verify both JSON base64 and binary image/tiff export
            c_app, _hdrs, r_app = _http_request(
                f"{base}/api/plants/approve-replacement",
                method="POST",
                raw_body=json.dumps(
                    {
                        "approve_all": False,
                        "approved_plant_ids": ["tile_000001_plant_001", "tile_000001_plant_005"],
                        "rejected_plant_ids": ["tile_000001_plant_012"],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(c_app, 200)
            d_app = json.loads(r_app.decode("utf-8"))
            self.assertEqual(d_app["approved_count"], 2)

            c_tiff, _hdrs, r_tiff = _http_request(
                f"{base}/api/tiff/export",
                method="POST",
                raw_body=json.dumps({"width": 40, "height": 30}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(c_tiff, 200)
            d_tiff = json.loads(r_tiff.decode("utf-8"))
            self.assertEqual(d_tiff["tiff_magic_hex"], "49492a00")
            self.assertEqual(d_tiff["approved_replacements_applied"], 2)
            self.assertFalse(d_tiff["dem_modified"])
            self.assertTrue(d_tiff["dsm_checksum_preserved"])

            tiff_buf = base64.b64decode(d_tiff["tiff_base64"])
            magic, version, ifd_offset = struct.unpack_from("<2sHI", tiff_buf, 0)
            self.assertEqual(magic, b"II")
            self.assertEqual(version, 42)
            self.assertEqual(ifd_offset, 8)
            (num_tags,) = struct.unpack_from("<H", tiff_buf, ifd_offset)
            self.assertEqual(num_tags, 11)
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


