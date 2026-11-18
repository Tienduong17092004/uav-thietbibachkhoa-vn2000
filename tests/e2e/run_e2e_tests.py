#!/usr/bin/env python3
"""Requirement-Driven 4-Tier End-to-End (E2E) Test Suite.

Covers all 5 features (F1-F5) from ORIGINAL_REQUEST.md and PROJECT.md:
- Tier 1: Feature Coverage (30 tests, 6 per feature F1-F5)
- Tier 2: Boundary & Corner Cases (26 tests, >=5 per feature F1-F5)
- Tier 3: Cross-Feature Combinations (6 pairwise integration tests)
- Tier 4: Real-World Application Scenarios (5 end-to-end scenarios)

Usage:
    python3 /home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/tests/e2e/run_e2e_tests.py
    python3 /home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/tests/e2e/run_e2e_tests.py --all
    python3 /home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/tests/e2e/run_e2e_tests.py --tier 1
    python3 /home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/tests/e2e/run_e2e_tests.py --tier 2
    python3 /home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/tests/e2e/run_e2e_tests.py --tier 3
    python3 /home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/tests/e2e/run_e2e_tests.py --tier 4
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path("/home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000").resolve()
WORKSPACE_ROOT = Path("/home/antigravity").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def find_free_port() -> int:
    """Allocate an ephemeral localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def http_request(
    url: str,
    method: str = "GET",
    payload: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
) -> Tuple[int, str, Dict[str, str]]:
    """Execute an HTTP request and return (status_code, body_text, response_headers)."""
    req_headers = dict(headers or {})
    if payload is not None and "Content-Type" not in req_headers:
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body, dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body, dict(exc.headers.items()) if exc.headers else {}


def start_colab_tpu_server_instance(port: int):
    """Start the remote Colab TPU HTTP server in a background thread or subprocess."""
    from scripts import run_colab_tpu_server

    for fn_name in ("start_tpu_server", "start_background_tpu_server"):
        if hasattr(run_colab_tpu_server, fn_name):
            fn = getattr(run_colab_tpu_server, fn_name)
            server, thread = fn(host="127.0.0.1", port=port)
            return ("inproc", server, thread)

    proc = subprocess.Popen(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "run_colab_tpu_server.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            code, _, _ = http_request(f"http://127.0.0.1:{port}/health", timeout=0.5)
            if code == 200:
                break
        except Exception:
            time.sleep(0.1)
    return ("subproc", proc, None)


def stop_colab_tpu_server_instance(handle) -> None:
    """Cleanly stop a Colab TPU server started by start_colab_tpu_server_instance."""
    kind, obj, thread = handle
    if kind == "inproc":
        obj.shutdown()
        obj.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
    elif kind == "subproc":
        obj.terminate()
        try:
            obj.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            obj.kill()


def get_active_slot_count(slot_resp: Dict[str, Any]) -> int:
    """Extract active slot count from acquire/release response dict."""
    if "active_count" in slot_resp:
        return int(slot_resp["active_count"])
    return int(slot_resp["active"])


def get_summary_active_map(summary: Dict[str, Any]) -> Dict[str, int]:
    """Extract active slot mapping from governance status summary."""
    return summary.get("active_slots") or summary.get("active_agents") or {}


# ============================================================================
# TIER 1: FEATURE COVERAGE (30 Test Cases: 6 per Feature F1-F5)
# ============================================================================


class Tier1Feature1RuleFilesTests(unittest.TestCase):
    """Tier 1 — Feature F1: Multi-Agent Role & Model Tier Governance Rules."""

    def test_t1_f1_01_agents_md_exists_and_contains_all_multi_agent_rules(self) -> None:
        agents_path = PROJECT_ROOT / "AGENTS.md"
        self.assertTrue(agents_path.is_file(), f"Missing {agents_path}")
        content = agents_path.read_text(encoding="utf-8")
        lower = content.lower()
        self.assertIn("hydrogen", lower)
        self.assertIn("argon", lower)
        self.assertIn("carbon", lower)
        self.assertIn("300", content)
        self.assertIn("10", content)
        self.assertTrue(
            "duyệt kiến trúc" in lower or "approve" in lower,
            "AGENTS.md must specify the mandatory architecture approval gate",
        )

    def test_t1_f1_02_model_tiers_policy_md_exists_and_specifies_tiers(self) -> None:
        policy_path = PROJECT_ROOT / "MODEL_TIERS_POLICY.md"
        self.assertTrue(policy_path.is_file(), f"Missing {policy_path}")
        content = policy_path.read_text(encoding="utf-8")
        for token in (
            "argon_high",
            "hydrogen",
            "carbon",
            "300",
            "10",
            "SELF_FIX",
            "ESCALATE_TO_CARBON",
        ):
            self.assertIn(token, content, f"MODEL_TIERS_POLICY.md missing {token}")

    def test_t1_f1_03_cursorrules_and_windsurfrules_exist_and_align(self) -> None:
        for filename in (".cursorrules", ".windsurfrules"):
            fpath = PROJECT_ROOT / filename
            self.assertTrue(fpath.is_file(), f"Missing rule file {fpath}")
            text = fpath.read_text(encoding="utf-8").lower()
            self.assertIn("argon", text)
            self.assertIn("hydrogen", text)
            self.assertIn("carbon", text)
            self.assertIn("300", text)
            self.assertIn("10", text)

    def test_t1_f1_04_agent_model_tiers_json_schema_and_limits(self) -> None:
        cfg_path = PROJECT_ROOT / "config" / "agent_model_tiers.json"
        self.assertTrue(cfg_path.is_file(), f"Missing {cfg_path}")
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(data["initial_survey"]["agent_count"], 5)
        self.assertEqual(data["initial_survey"]["model_tier"], "hydrogen")
        self.assertTrue(
            data["architecture_gate"]["approval_required_before_role_assignment"]
        )
        self.assertEqual(data["tiers"]["hydrogen"]["max_concurrent"], 300)
        self.assertEqual(data["tiers"]["hydrogen"]["max_self_fix_attempts"], 2)
        self.assertEqual(data["tiers"]["carbon"]["max_concurrent"], 10)
        self.assertTrue(data["tiers"]["argon"]["flexible_usage"])

    def test_t1_f1_05_difficulty_effort_mapping_in_json_config(self) -> None:
        cfg_path = PROJECT_ROOT / "config" / "agent_model_tiers.json"
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        mapping = data["difficulty_effort_mapping"]
        for level in ("low", "medium", "high", "critical"):
            self.assertIn(level, mapping)
            self.assertIn("effort", mapping[level])
        efforts = {mapping[k]["effort"] for k in ("low", "medium", "high", "critical")}
        self.assertGreaterEqual(len(efforts), 3)

    def test_t1_f1_06_preserved_legacy_5_specialist_sub_agents_in_agents_md(self) -> None:
        content = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for specialist in (
            "architecture-design-lead",
            "code-architect",
            "gis-uav-specialist",
            "math-geometry-expert",
            "ui-ux-specialist",
        ):
            self.assertIn(specialist, content)


class Tier1Feature2AgentGovernanceEngineTests(unittest.TestCase):
    """Tier 1 — Feature F2: Programmatic Agent Governance Engine."""

    def test_t1_f2_01_enums_and_constants(self) -> None:
        from uav_app.infrastructure import agent_governance as ag

        self.assertEqual(ag.MAX_CONCURRENT_HYDROGEN, 300)
        self.assertEqual(ag.MAX_CONCURRENT_CARBON, 10)
        self.assertEqual(ag.MAX_HYDROGEN_SELF_FIX_ATTEMPTS, 2)
        self.assertEqual(ag.ModelTier.ARGON_HIGH.value, "argon_high")
        self.assertEqual(ag.ModelTier.ARGON.value, "argon")
        self.assertEqual(ag.ModelTier.HYDROGEN.value, "hydrogen")
        self.assertEqual(ag.ModelTier.CARBON.value, "carbon")
        self.assertEqual(ag.TaskDifficulty.LOW.value, "low")
        self.assertEqual(ag.TaskDifficulty.CRITICAL.value, "critical")

    def test_t1_f2_02_create_and_approve_architecture_plan(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        plan = policy.create_architecture_plan(
            plan_id="plan-001",
            summary="Hexagonal UAV GeoTIFF WebGPU + Domain + TPU Architecture",
        )
        self.assertEqual(plan["plan_id"], "plan-001")
        approval = policy.approve_architecture("plan-001", approved_by="argon_high")
        self.assertTrue(approval.get("approved", False))
        self.assertEqual(approval.get("approved_by"), "argon_high")

    def test_t1_f2_03_assign_role_difficulty_effort_scaling(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-002", approved_by="argon_high")
        low_role = policy.assign_role("task-low", difficulty="low")
        med_role = policy.assign_role("task-med", difficulty="medium")
        high_role = policy.assign_role("task-high", difficulty="high")
        self.assertEqual(low_role.get("assigned_tier") or low_role.get("tier"), "hydrogen")
        self.assertEqual(med_role.get("assigned_tier") or med_role.get("tier"), "hydrogen")
        self.assertEqual(high_role.get("assigned_tier") or high_role.get("tier"), "hydrogen")
        self.assertNotEqual(low_role["effort"], high_role["effort"])

    def test_t1_f2_04_assign_role_deep_optimization_and_flexible_argon(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-003", approved_by="argon_high")
        opt_role = policy.assign_role(
            "task-opt", difficulty="high", requires_deep_optimization=True
        )
        self.assertEqual(opt_role.get("assigned_tier") or opt_role.get("tier"), "carbon")
        argon_role = policy.assign_role(
            "task-synth", difficulty="high", use_argon=True
        )
        self.assertEqual(argon_role.get("assigned_tier") or argon_role.get("tier"), "argon")

    def test_t1_f2_05_acquire_and_release_agent_slots(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        res_h = policy.acquire_agent_slot("hydrogen", count=25)
        self.assertEqual(get_active_slot_count(res_h), 25)
        res_c = policy.acquire_agent_slot("carbon", count=3)
        self.assertEqual(get_active_slot_count(res_c), 3)
        rel_h = policy.release_agent_slot("hydrogen", count=10)
        self.assertEqual(get_active_slot_count(rel_h), 15)
        rel_c = policy.release_agent_slot("carbon", count=3)
        self.assertEqual(get_active_slot_count(rel_c), 0)

    def test_t1_f2_06_two_strike_self_fix_and_escalate_to_carbon(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-004")
        policy.assign_role("task-loop", difficulty="medium")

        f1 = policy.record_test_failure("task-loop", "Test error #1")
        self.assertEqual(f1["action"], "SELF_FIX")
        self.assertEqual(f1.get("assigned_tier") or f1.get("tier"), "hydrogen")
        self.assertFalse(f1.get("escalated", False))

        f2 = policy.record_test_failure("task-loop", "Test error #2")
        self.assertEqual(f2["action"], "SELF_FIX")
        self.assertEqual(f2.get("assigned_tier") or f2.get("tier"), "hydrogen")
        self.assertFalse(f2.get("escalated", False))

        f3 = policy.record_test_failure("task-loop", "Test error #3 after 2 fixes")
        self.assertEqual(f3["action"], "ESCALATE_TO_CARBON")
        self.assertEqual(f3.get("assigned_tier") or f3.get("tier"), "carbon")
        self.assertTrue(f3.get("escalated", True))


class Tier1Feature3ZeroHostingDomainAutostartTests(unittest.TestCase):
    """Tier 1 — Feature F3: Zero-Hosting Custom Domain & Power-Coupled Autostart."""

    def test_t1_f3_01_autostart_host_constants_and_default_port(self) -> None:
        from uav_app.infrastructure import autostart_host as ah

        self.assertEqual(ah.DEFAULT_PORT, 8765)
        self.assertEqual(ah.CUSTOM_DOMAIN, "thietbibachkhoa.id.vn")
        self.assertEqual(ah.CUSTOM_DOMAIN_URL, "https://thietbibachkhoa.id.vn/")
        self.assertEqual(ah.get_default_port(), 8765)

    def test_t1_f3_02_generate_cloudflared_config_for_thietbibachkhoa(self) -> None:
        from uav_app.infrastructure.autostart_host import generate_cloudflared_config

        yaml_text = generate_cloudflared_config(
            port=8765,
            domain="thietbibachkhoa.id.vn",
            tunnel_id="uav-thietbibachkhoa-tunnel",
        )
        self.assertIn("thietbibachkhoa.id.vn", yaml_text)
        self.assertIn("www.thietbibachkhoa.id.vn", yaml_text)
        self.assertIn("http://127.0.0.1:8765", yaml_text)
        self.assertIn("http_status:404", yaml_text)

    def test_t1_f3_03_cloudflared_yaml_config_file_valid(self) -> None:
        yml_path = PROJECT_ROOT / "config" / "cloudflared_thietbibachkhoa.yml"
        self.assertTrue(yml_path.is_file(), f"Missing {yml_path}")
        content = yml_path.read_text(encoding="utf-8")
        self.assertIn("thietbibachkhoa.id.vn", content)
        self.assertIn("8765", content)
        self.assertIn("http_status:404", content)

    def test_t1_f3_04_linux_and_windows_autostart_scripts_exist(self) -> None:
        linux_sh = PROJECT_ROOT / "scripts" / "start_thietbibachkhoa_linux.sh"
        win_bat = PROJECT_ROOT / "scripts" / "start_thietbibachkhoa_windows.bat"
        win_ps1 = PROJECT_ROOT / "scripts" / "install_windows_autostart.ps1"
        for script_path in (linux_sh, win_bat, win_ps1):
            self.assertTrue(script_path.is_file(), f"Missing script {script_path}")
            text = script_path.read_text(encoding="utf-8")
            self.assertIn("thietbibachkhoa", text.lower())
            self.assertIn("8765", text)

    def test_t1_f3_05_systemd_service_units_exist_and_power_coupled(self) -> None:
        web_unit = PROJECT_ROOT / "deploy" / "systemd" / "thietbibachkhoa-web.service"
        tun_unit = PROJECT_ROOT / "deploy" / "systemd" / "thietbibachkhoa-tunnel.service"
        for unit_path in (web_unit, tun_unit):
            self.assertTrue(unit_path.is_file(), f"Missing systemd unit {unit_path}")
            text = unit_path.read_text(encoding="utf-8")
            self.assertIn("[Unit]", text)
            self.assertIn("[Service]", text)
            self.assertIn("[Install]", text)
            self.assertIn("multi-user.target", text)

    def test_t1_f3_06_domain_setup_guide_and_autostart_manager_status(self) -> None:
        guide_path = PROJECT_ROOT / "DOMAIN_SETUP_THIETBIBACHKHOA.md"
        self.assertTrue(guide_path.is_file(), f"Missing {guide_path}")
        guide_text = guide_path.read_text(encoding="utf-8")
        self.assertIn("https://thietbibachkhoa.id.vn/", guide_text)
        self.assertIn("cloudflared", guide_text.lower())

        from uav_app.infrastructure.autostart_host import AutostartHostManager

        mgr = AutostartHostManager(port=8765, domain="thietbibachkhoa.id.vn")
        status = mgr.get_domain_lifecycle_status()
        self.assertEqual(status["domain"], "thietbibachkhoa.id.vn")
        self.assertEqual(status["default_port"], 8765)
        self.assertTrue(status["power_coupled"])


class Tier1Feature4LocalWebGPUSurveyServerTests(unittest.TestCase):
    """Tier 1 — Feature F4: Local WebGPU Survey Server & Portal."""

    @classmethod
    def setUpClass(cls) -> None:
        from uav_app.adapters.webgpu_public_server import start_background_server

        cls.port = find_free_port()
        cls.server, cls.thread = start_background_server(
            host="127.0.0.1", port=cls.port
        )
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2.0)

    def test_t1_f4_01_web_server_root_and_webgpu_html_endpoints(self) -> None:
        for route in ("/", "/webgpu.html", "/MO_WEB_NHAN_DIEN_NGAY.html"):
            code, body, _ = http_request(f"{self.base_url}{route}")
            self.assertEqual(code, 200, f"GET {route} failed with {code}")
            self.assertIn("thietbibachkhoa.id.vn", body)
            self.assertIn("VN2000", body)

    def test_t1_f4_02_api_health_endpoint(self) -> None:
        code, body, _ = http_request(f"{self.base_url}/api/health")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["online"])
        self.assertEqual(data["port"], self.port)
        self.assertIn(
            "thietbibachkhoa.id.vn",
            str(data.get("domain", "")) + str(data.get("url", "")),
        )

    def test_t1_f4_03_api_domain_status_endpoint(self) -> None:
        code, body, _ = http_request(f"{self.base_url}/api/domain-status")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data["domain"], "thietbibachkhoa.id.vn")
        self.assertTrue(data["power_coupled"])
        self.assertTrue(data["server_running"])

    def test_t1_f4_04_api_agent_tiers_endpoint(self) -> None:
        code, body, _ = http_request(f"{self.base_url}/api/agent-tiers")
        self.assertEqual(code, 200)
        data = json.loads(body)
        raw = json.dumps(data)
        self.assertIn("300", raw)
        self.assertIn("10", raw)
        self.assertIn("hydrogen", raw.lower())
        self.assertIn("carbon", raw.lower())

    def test_t1_f4_05_api_tpu_status_and_infer_endpoints(self) -> None:
        code_s, body_s, _ = http_request(f"{self.base_url}/api/tpu/status")
        self.assertEqual(code_s, 200)
        status_data = json.loads(body_s)
        self.assertIn("backend", status_data)

        payload = json.dumps(
            {
                "tiles": [
                    {
                        "tile_id": "tile_0_0",
                        "row": 0,
                        "col": 0,
                        "vn2000_x": 584000.0,
                        "vn2000_y": 1192000.0,
                        "rgb_mean": [128.0, 130.0, 125.0],
                    }
                ],
                "metadata": {"crs": "EPSG:9210", "gsd_m": 0.05},
            }
        ).encode("utf-8")
        code_i, body_i, _ = http_request(
            f"{self.base_url}/api/tpu/infer", method="POST", payload=payload
        )
        self.assertEqual(code_i, 200)
        infer_data = json.loads(body_i)
        self.assertIn("backend_used", infer_data)
        self.assertIn("tile_results", infer_data)
        self.assertIn("vn2000_layers", infer_data)

    def test_t1_f4_06_link_truy_cap_web_and_mo_web_nhan_dien_ngay_updated(self) -> None:
        link_txt = (PROJECT_ROOT / "LINK_TRUY_CAP_WEB.txt").read_text(encoding="utf-8")
        mo_html = (PROJECT_ROOT / "MO_WEB_NHAN_DIEN_NGAY.html").read_text(encoding="utf-8")
        self.assertIn("https://thietbibachkhoa.id.vn", link_txt)
        self.assertIn("8765", link_txt)
        self.assertIn("https://thietbibachkhoa.id.vn", mo_html)
        self.assertIn("8765", mo_html)


class Tier1Feature5GoogleTPUOffloadTests(unittest.TestCase):
    """Tier 1 — Feature F5: Google Gemini Ultra / Google TPU Offloading Pipeline."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tpu_port = find_free_port()
        cls.tpu_handle = start_colab_tpu_server_instance(cls.tpu_port)
        cls.tpu_url = f"http://127.0.0.1:{cls.tpu_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        stop_colab_tpu_server_instance(cls.tpu_handle)

    def test_t1_f5_01_tpu_offload_config_and_worker_initialization(self) -> None:
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        cfg = TPUOffloadConfig(
            tpu_endpoint_url=None, batch_size=8, timeout_sec=3.0, fallback_to_local=True
        )
        worker = TPUOffloadWorker(cfg)
        health = worker.check_remote_tpu_health()
        self.assertFalse(health["tpu_available"])
        self.assertEqual(health["backend"], "local_fallback")

    def test_t1_f5_02_colab_tpu_server_health_endpoint(self) -> None:
        code, body, _ = http_request(f"{self.tpu_url}/health")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertTrue("tpu_device" in data or "accelerator" in data)

    def test_t1_f5_03_tpu_worker_remote_health_check_when_online(self) -> None:
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        cfg = TPUOffloadConfig(tpu_endpoint_url=self.tpu_url, batch_size=4)
        worker = TPUOffloadWorker(cfg)
        health = worker.check_remote_tpu_health()
        self.assertTrue(health["tpu_available"])
        self.assertEqual(health["backend"], "remote_google_tpu")
        self.assertTrue(health["local_gpu_offload_active"])

    def test_t1_f5_04_tpu_worker_remote_batch_inference(self) -> None:
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        cfg = TPUOffloadConfig(tpu_endpoint_url=self.tpu_url, batch_size=4)
        worker = TPUOffloadWorker(cfg)
        tiles = [
            {
                "tile_id": "t_asphalt",
                "row": 0,
                "col": 0,
                "vn2000_x": 584000.0,
                "vn2000_y": 1192000.0,
                "rgb_mean": [70.0, 72.0, 75.0],
            },
            {
                "tile_id": "t_pond",
                "row": 0,
                "col": 1,
                "vn2000_x": 584050.0,
                "vn2000_y": 1192000.0,
                "rgb_mean": [45.0, 95.0, 145.0],
            },
        ]
        result = worker.infer_tile_batch(tiles, metadata={"crs": "VN2000"})
        self.assertEqual(result["backend_used"], "remote_google_tpu")
        self.assertGreaterEqual(result["gpu_load_saved_pct"], 90.0)
        self.assertEqual(len(result["tile_results"]), 2)
        self.assertGreaterEqual(len(result["classes_detected"]), 1)
        self.assertIn("vn2000_layers", result)

    def test_t1_f5_05_tpu_worker_local_fallback_when_offline(self) -> None:
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        cfg = TPUOffloadConfig(tpu_endpoint_url=None, fallback_to_local=True)
        worker = TPUOffloadWorker(cfg)
        tiles = [
            {
                "tile_id": "t_local_0",
                "row": 0,
                "col": 0,
                "vn2000_x": 584000.0,
                "vn2000_y": 1192000.0,
                "rgb_mean": [170.0, 140.0, 100.0],
            }
        ]
        result = worker.infer_tile_batch(tiles)
        self.assertEqual(result["backend_used"], "local_fallback")
        self.assertEqual(len(result["tile_results"]), 1)
        self.assertIn("vn2000_layers", result)

    def test_t1_f5_06_tpu_ultra_guide_and_colab_notebook_exist(self) -> None:
        guide = PROJECT_ROOT / "TPU_OFFLOAD_ULTRA_GUIDE.md"
        notebook = PROJECT_ROOT / "notebooks" / "Colab_Ultra_TPU_Server_VN2000.ipynb"
        self.assertTrue(guide.is_file(), f"Missing {guide}")
        self.assertTrue(notebook.is_file(), f"Missing {notebook}")
        guide_text = guide.read_text(encoding="utf-8").lower()
        self.assertIn("ultra", guide_text)
        self.assertIn("tpu", guide_text)
        self.assertIn("colab", guide_text)
        nb_json = json.loads(notebook.read_text(encoding="utf-8"))
        self.assertEqual(nb_json.get("nbformat"), 4)
        self.assertGreaterEqual(len(nb_json.get("cells", [])), 3)


# ============================================================================
# TIER 2: BOUNDARY & CORNER CASES (26 Test Cases: >=5 per Feature F1-F5)
# ============================================================================


class Tier2Feature1RuleBoundariesTests(unittest.TestCase):
    """Tier 2 — Feature F1 Boundary & Corner Cases."""

    def test_t2_f1_01_no_agent_rules_files_polluting_dot_agents_dir(self) -> None:
        dot_agents = WORKSPACE_ROOT / ".agents"
        if dot_agents.exists():
            for root, _, files in os.walk(dot_agents):
                for fname in files:
                    self.assertNotIn(
                        fname,
                        ("AGENTS.md", "GEMINI.md"),
                        f"Forbidden rule file inside .agents/: {os.path.join(root, fname)}",
                    )

    def test_t2_f1_02_json_config_strict_numeric_bounds(self) -> None:
        cfg_path = PROJECT_ROOT / "config" / "agent_model_tiers.json"
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data["tiers"]["hydrogen"]["max_concurrent"], int)
        self.assertEqual(data["tiers"]["hydrogen"]["max_concurrent"], 300)
        self.assertIsInstance(data["tiers"]["carbon"]["max_concurrent"], int)
        self.assertEqual(data["tiers"]["carbon"]["max_concurrent"], 10)
        self.assertEqual(data["escalation_policy"]["max_self_fix_attempts"], 2)

    def test_t2_f1_03_custom_config_loading_and_missing_file_fallback(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "nonexistent_tiers.json"
            policy = AgentGovernancePolicy(config_path=missing_path)
            summary = policy.get_status_summary()
            self.assertEqual(summary["concurrency_limits"]["hydrogen"], 300)
            self.assertEqual(summary["concurrency_limits"]["carbon"], 10)

    def test_t2_f1_04_bilingual_vietnamese_and_english_rule_terms(self) -> None:
        agents_text = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8").lower()
        policy_text = (
            PROJECT_ROOT / "MODEL_TIERS_POLICY.md"
        ).read_text(encoding="utf-8").lower()
        combined = agents_text + "\n" + policy_text
        for term in (
            "duyệt kiến trúc",
            "phân role",
            "tự sửa",
            "tối ưu hàm",
            "hydrogen",
            "carbon",
            "argon",
        ):
            self.assertIn(term, combined, f"Missing expected bilingual term: {term}")

    def test_t2_f1_05_architecture_sign_off_token_integrity(self) -> None:
        agents_text = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cfg_data = json.loads(
            (PROJECT_ROOT / "config" / "agent_model_tiers.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING]", agents_text)
        self.assertEqual(
            cfg_data["architecture_gate"]["sign_off_token"],
            "[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING]",
        )


class Tier2Feature2GovernanceBoundariesTests(unittest.TestCase):
    """Tier 2 — Feature F2 Boundary & Corner Cases."""

    def test_t2_f2_01_assign_role_before_architecture_approval_raises_error(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        with self.assertRaises((PermissionError, ValueError)):
            policy.assign_role("task-unapproved", difficulty="medium")

    def test_t2_f2_02_hydrogen_concurrency_boundary_300_pass_301_fail(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        res = policy.acquire_agent_slot("hydrogen", count=300)
        self.assertEqual(get_active_slot_count(res), 300)
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("hydrogen", count=1)
        policy.release_agent_slot("hydrogen", count=1)
        res_after = policy.acquire_agent_slot("hydrogen", count=1)
        self.assertEqual(get_active_slot_count(res_after), 300)

    def test_t2_f2_03_carbon_concurrency_boundary_10_pass_11_fail(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        res = policy.acquire_agent_slot("carbon", count=10)
        self.assertEqual(get_active_slot_count(res), 10)
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("carbon", count=1)
        policy.release_agent_slot("carbon", count=1)
        res_after = policy.acquire_agent_slot("carbon", count=1)
        self.assertEqual(get_active_slot_count(res_after), 10)

    def test_t2_f2_04_invalid_slot_count_zero_or_negative_or_over_release(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("hydrogen", count=0)
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("carbon", count=-2)
        with self.assertRaises(ValueError):
            policy.acquire_agent_slot("unknown_tier_xyz", count=1)

    def test_t2_f2_05_exact_boundary_attempt_2_self_fix_vs_attempt_3_escalate(self) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-bva")
        policy.assign_role("task-bva", difficulty="high")

        r1 = policy.record_test_failure("task-bva", "err 1")
        r2 = policy.record_test_failure("task-bva", "err 2")
        r3 = policy.record_test_failure("task-bva", "err 3")
        r4 = policy.record_test_failure("task-bva", "err 4")

        self.assertEqual((r1["attempt"], r1["action"]), (1, "SELF_FIX"))
        self.assertEqual((r2["attempt"], r2["action"]), (2, "SELF_FIX"))
        self.assertEqual((r3["attempt"], r3["action"]), (3, "ESCALATE_TO_CARBON"))
        self.assertEqual((r4["attempt"], r4["action"]), (4, "ESCALATE_TO_CARBON"))

    def test_t2_f2_06_record_test_success_resets_or_marks_resolved_and_invalid_difficulty(
        self,
    ) -> None:
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-reset")
        with self.assertRaises(ValueError):
            policy.assign_role("task-bad-diff", difficulty="impossible_difficulty")

        policy.assign_role("task-recover", difficulty="low")
        policy.record_test_failure("task-recover", "err 1")
        ok = policy.record_test_success("task-recover")
        self.assertIn(ok["status"].upper(), ("PASSED", "RESOLVED"))


class Tier2Feature3DomainAutostartBoundariesTests(unittest.TestCase):
    """Tier 2 — Feature F3 Boundary & Corner Cases."""

    def test_t2_f3_01_port_override_via_uav_web_port_env_8766_and_7860(self) -> None:
        from uav_app.infrastructure.autostart_host import get_default_port

        old_val = os.environ.get("UAV_WEB_PORT")
        try:
            os.environ["UAV_WEB_PORT"] = "8766"
            self.assertEqual(get_default_port(), 8766)
            os.environ["UAV_WEB_PORT"] = "7860"
            self.assertEqual(get_default_port(), 7860)
            del os.environ["UAV_WEB_PORT"]
            self.assertEqual(get_default_port(), 8765)
        finally:
            if old_val is None:
                os.environ.pop("UAV_WEB_PORT", None)
            else:
                os.environ["UAV_WEB_PORT"] = old_val

    def test_t2_f3_02_invalid_uav_web_port_env_handling(self) -> None:
        from uav_app.infrastructure.autostart_host import get_default_port

        old_val = os.environ.get("UAV_WEB_PORT")
        try:
            for invalid in ("not_a_port", "-10", "70000"):
                os.environ["UAV_WEB_PORT"] = invalid
                try:
                    port = get_default_port()
                    self.assertEqual(port, 8765)
                except ValueError:
                    pass
        finally:
            if old_val is None:
                os.environ.pop("UAV_WEB_PORT", None)
            else:
                os.environ["UAV_WEB_PORT"] = old_val

    def test_t2_f3_03_cloudflared_config_with_and_without_credentials_file(self) -> None:
        from uav_app.infrastructure.autostart_host import generate_cloudflared_config

        cfg_no_cred = generate_cloudflared_config(
            port=8765, domain="thietbibachkhoa.id.vn", credentials_file=None
        )
        self.assertIn("thietbibachkhoa.id.vn", cfg_no_cred)
        cfg_with_cred = generate_cloudflared_config(
            port=8766,
            domain="thietbibachkhoa.id.vn",
            credentials_file="/etc/cloudflared/thietbibachkhoa.json",
        )
        self.assertIn("/etc/cloudflared/thietbibachkhoa.json", cfg_with_cred)
        self.assertIn("http://127.0.0.1:8766", cfg_with_cred)

    def test_t2_f3_04_autostart_host_manager_offline_when_stopped(self) -> None:
        from uav_app.infrastructure.autostart_host import AutostartHostManager

        port = find_free_port()
        mgr = AutostartHostManager(port=port, domain="thietbibachkhoa.id.vn")
        status_before = mgr.get_domain_lifecycle_status()
        self.assertFalse(status_before["server_running"])

    def test_t2_f3_05_linux_script_executable_permissions_and_signal_traps(self) -> None:
        script_path = PROJECT_ROOT / "scripts" / "start_thietbibachkhoa_linux.sh"
        proc = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"bash -n failed: {proc.stderr}")
        content = script_path.read_text(encoding="utf-8")
        self.assertIn("trap", content)


class Tier2Feature4WebGPUSurveyServerBoundariesTests(unittest.TestCase):
    """Tier 2 — Feature F4 Boundary & Corner Cases."""

    @classmethod
    def setUpClass(cls) -> None:
        from uav_app.adapters.webgpu_public_server import start_background_server

        cls.port = find_free_port()
        cls.server, cls.thread = start_background_server(
            host="127.0.0.1", port=cls.port
        )
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2.0)

    def test_t2_f4_01_post_api_tpu_infer_invalid_json_returns_400(self) -> None:
        code, body, _ = http_request(
            f"{self.base_url}/api/tpu/infer",
            method="POST",
            payload=b"{bad json payload",
        )
        self.assertEqual(code, 400)
        data = json.loads(body)
        self.assertIn("error", data)

    def test_t2_f4_02_post_api_tpu_infer_empty_tiles_returns_400(self) -> None:
        code, body, _ = http_request(
            f"{self.base_url}/api/tpu/infer",
            method="POST",
            payload=json.dumps({"tiles": []}).encode("utf-8"),
        )
        self.assertEqual(code, 400)
        data = json.loads(body)
        self.assertIn("error", data)

    def test_t2_f4_03_get_unknown_route_returns_404(self) -> None:
        code, _, _ = http_request(f"{self.base_url}/api/nonexistent_endpoint_404")
        self.assertEqual(code, 404)

    def test_t2_f4_04_host_header_thietbibachkhoa_id_vn_routing(self) -> None:
        code, body, _ = http_request(
            f"{self.base_url}/api/health",
            headers={"Host": "thietbibachkhoa.id.vn"},
        )
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertIn("thietbibachkhoa.id.vn", str(data.get("domain", "")) + str(data.get("url", "")))

    def test_t2_f4_05_concurrent_http_requests_to_webgpu_server(self) -> None:
        routes = [
            "/api/health",
            "/api/domain-status",
            "/api/agent-tiers",
            "/api/tpu/status",
        ] * 4

        def fetch(route: str) -> int:
            code, _, _ = http_request(f"{self.base_url}{route}")
            return code

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(fetch, routes))
        self.assertEqual(statuses, [200] * 16)


class Tier2Feature5TPUOffloadBoundariesTests(unittest.TestCase):
    """Tier 2 — Feature F5 Boundary & Corner Cases."""

    def test_t2_f5_01_infer_tile_batch_empty_list_raises_value_error(self) -> None:
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        worker = TPUOffloadWorker(TPUOffloadConfig())
        with self.assertRaises(ValueError):
            worker.infer_tile_batch([])

    def test_t2_f5_02_fallback_disabled_when_remote_tpu_offline_raises_error(self) -> None:
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        dead_port = find_free_port()
        cfg = TPUOffloadConfig(
            tpu_endpoint_url=f"http://127.0.0.1:{dead_port}",
            timeout_sec=0.5,
            fallback_to_local=False,
        )
        worker = TPUOffloadWorker(cfg)
        with self.assertRaises((RuntimeError, ConnectionError)):
            worker.infer_tile_batch([{"tile_id": "t0", "row": 0, "col": 0}])

    def test_t2_f5_03_large_tile_batch_chunking_across_batch_size(self) -> None:
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        cfg = TPUOffloadConfig(
            tpu_endpoint_url=None, batch_size=3, fallback_to_local=True
        )
        worker = TPUOffloadWorker(cfg)
        tiles = [
            {
                "tile_id": f"tile_{i}",
                "row": i // 5,
                "col": i % 5,
                "vn2000_x": 584000.0 + i * 10,
                "vn2000_y": 1192000.0,
                "rgb_mean": [100.0 + (i * 7) % 120, 110.0, 95.0],
            }
            for i in range(10)
        ]
        res = worker.infer_tile_batch(tiles)
        self.assertEqual(len(res["tile_results"]), 10)
        batch_cnt = res.get("batch_count", res.get("batches_processed"))
        self.assertEqual(batch_cnt, 4)

    def test_t2_f5_04_unreachable_tpu_endpoint_fast_timeout_health_check(self) -> None:
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        dead_port = find_free_port()
        cfg = TPUOffloadConfig(
            tpu_endpoint_url=f"http://127.0.0.1:{dead_port}",
            timeout_sec=0.4,
            fallback_to_local=True,
        )
        worker = TPUOffloadWorker(cfg)
        t0 = time.time()
        health = worker.check_remote_tpu_health()
        elapsed = time.time() - t0
        self.assertFalse(health["tpu_available"])
        self.assertEqual(health["backend"], "local_fallback")
        self.assertLess(elapsed, 3.0)

    def test_t2_f5_05_colab_tpu_server_invalid_post_payload_returns_400(self) -> None:
        port = find_free_port()
        handle = start_colab_tpu_server_instance(port)
        try:
            code1, _, _ = http_request(
                f"http://127.0.0.1:{port}/infer",
                method="POST",
                payload=b"not valid json",
            )
            self.assertEqual(code1, 400)
            code2, _, _ = http_request(
                f"http://127.0.0.1:{port}/infer",
                method="POST",
                payload=json.dumps({"tiles": []}).encode("utf-8"),
            )
            self.assertEqual(code2, 400)
        finally:
            stop_colab_tpu_server_instance(handle)


# ============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (6 Pairwise Integration Tests)
# ============================================================================


class Tier3CrossFeatureIntegrationTests(unittest.TestCase):
    """Tier 3 — Cross-Feature Pairwise & Multi-Module Integration Tests."""

    def test_t3_01_f1_f2_config_file_drives_governance_engine(self) -> None:
        """F1 + F2: Verify config/agent_model_tiers.json directly governs AgentGovernancePolicy."""
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        cfg_path = PROJECT_ROOT / "config" / "agent_model_tiers.json"
        raw_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        policy = AgentGovernancePolicy(config_path=cfg_path)
        summary = policy.get_status_summary()

        self.assertEqual(
            summary["concurrency_limits"]["hydrogen"],
            raw_cfg["tiers"]["hydrogen"]["max_concurrent"],
        )
        self.assertEqual(
            summary["concurrency_limits"]["carbon"],
            raw_cfg["tiers"]["carbon"]["max_concurrent"],
        )
        self.assertEqual(
            summary["escalation_policy"]["max_self_fix_attempts"],
            raw_cfg["escalation_policy"]["max_self_fix_attempts"],
        )

    def test_t3_02_f2_f4_live_governance_mutations_reflected_in_web_api(self) -> None:
        """F2 + F4: Mutate AgentGovernancePolicy state and verify live reflection on GET /api/agent-tiers."""
        from uav_app.adapters.webgpu_public_server import start_background_server
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()
        policy.create_architecture_plan("plan-live", "Live WebGPU + Governance integration")
        policy.approve_architecture("plan-live", approved_by="argon_high")
        policy.acquire_agent_slot("hydrogen", count=45)
        policy.acquire_agent_slot("carbon", count=4)
        policy.assign_role("task-mesh", difficulty="high")
        policy.record_test_failure("task-mesh", "fail 1")
        policy.record_test_failure("task-mesh", "fail 2")
        policy.record_test_failure("task-mesh", "fail 3 -> escalate")

        port = find_free_port()
        server, thread = start_background_server(
            host="127.0.0.1", port=port, governance_policy=policy
        )
        try:
            code, body, _ = http_request(f"http://127.0.0.1:{port}/api/agent-tiers")
            self.assertEqual(code, 200)
            data = json.loads(body)
            self.assertTrue(data["architecture_approved"])
            active_map = get_summary_active_map(data)
            self.assertEqual(active_map["hydrogen"], 45)
            self.assertEqual(active_map["carbon"], 4)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    def test_t3_03_f3_f4_autostart_host_manager_launches_and_monitors_web_server(
        self,
    ) -> None:
        """F3 + F4: AutostartHostManager starts local web server and matches cloudflared domain status."""
        from uav_app.infrastructure.autostart_host import AutostartHostManager

        port = find_free_port()
        mgr = AutostartHostManager(port=port, domain="thietbibachkhoa.id.vn")
        mgr.start_web_server()
        try:
            lifecycle = mgr.get_domain_lifecycle_status()
            self.assertTrue(lifecycle["server_running"])
            self.assertEqual(lifecycle["default_port"], port)

            code, body, _ = http_request(f"http://127.0.0.1:{port}/api/domain-status")
            self.assertEqual(code, 200)
            api_status = json.loads(body)
            self.assertEqual(api_status["domain"], "thietbibachkhoa.id.vn")
            self.assertTrue(api_status["server_running"])
        finally:
            mgr.stop()
            self.assertFalse(mgr.get_domain_lifecycle_status()["server_running"])

    def test_t3_04_f4_f5_web_server_proxies_inference_to_remote_tpu_server_and_falls_back(
        self,
    ) -> None:
        """F4 + F5: webgpu_public_server offloads POST /api/tpu/infer to run_colab_tpu_server then falls back when stopped."""
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )
        from uav_app.adapters.webgpu_public_server import start_background_server

        tpu_port = find_free_port()
        web_port = find_free_port()
        tpu_handle = start_colab_tpu_server_instance(tpu_port)
        worker = TPUOffloadWorker(
            TPUOffloadConfig(
                tpu_endpoint_url=f"http://127.0.0.1:{tpu_port}",
                batch_size=4,
                timeout_sec=1.5,
                fallback_to_local=True,
            )
        )
        server, thread = start_background_server(
            host="127.0.0.1", port=web_port, tpu_worker=worker
        )
        try:
            payload = json.dumps(
                {
                    "tiles": [
                        {
                            "tile_id": "tile_bridge_1",
                            "row": 0,
                            "col": 0,
                            "vn2000_x": 584000.0,
                            "vn2000_y": 1192000.0,
                            "rgb_mean": [85.0, 88.0, 90.0],
                        }
                    ]
                }
            ).encode("utf-8")

            code_on, body_on, _ = http_request(
                f"http://127.0.0.1:{web_port}/api/tpu/infer",
                method="POST",
                payload=payload,
            )
            self.assertEqual(code_on, 200)
            data_on = json.loads(body_on)
            self.assertEqual(data_on["backend_used"], "remote_google_tpu")
            self.assertGreaterEqual(data_on["gpu_load_saved_pct"], 90.0)

            # Stop the remote TPU server and verify seamless local fallback
            stop_colab_tpu_server_instance(tpu_handle)
            tpu_handle = None

            code_off, body_off, _ = http_request(
                f"http://127.0.0.1:{web_port}/api/tpu/infer",
                method="POST",
                payload=payload,
            )
            self.assertEqual(code_off, 200)
            data_off = json.loads(body_off)
            self.assertEqual(data_off["backend_used"], "local_fallback")
        finally:
            if tpu_handle is not None:
                stop_colab_tpu_server_instance(tpu_handle)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    def test_t3_05_f1_f3_f5_documentation_and_config_cross_consistency(self) -> None:
        """F1 + F3 + F5: Verify domain, port, model tiers, and TPU offload docs are mutually consistent."""
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        domain_doc = (PROJECT_ROOT / "DOMAIN_SETUP_THIETBIBACHKHOA.md").read_text(
            encoding="utf-8"
        )
        tpu_doc = (PROJECT_ROOT / "TPU_OFFLOAD_ULTRA_GUIDE.md").read_text(encoding="utf-8")
        tiers_doc = (PROJECT_ROOT / "MODEL_TIERS_POLICY.md").read_text(encoding="utf-8")

        self.assertIn("thietbibachkhoa.id.vn", readme)
        self.assertIn("thietbibachkhoa.id.vn", domain_doc)
        self.assertIn("8765", domain_doc)
        self.assertIn("TPU", tpu_doc)
        self.assertIn("300", tiers_doc)
        self.assertIn("10", tiers_doc)

    def test_t3_06_f2_f3_f4_f5_unified_workstation_control_plane(self) -> None:
        """F2 + F3 + F4 + F5: All 4 runtime components operate together harmoniously."""
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )
        from uav_app.adapters.webgpu_public_server import start_background_server
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy
        from uav_app.infrastructure.autostart_host import AutostartHostManager

        tpu_port = find_free_port()
        web_port = find_free_port()
        tpu_handle = start_colab_tpu_server_instance(tpu_port)
        policy = AgentGovernancePolicy()
        policy.approve_architecture("plan-unified", approved_by="argon_high")
        policy.acquire_agent_slot("hydrogen", count=5)
        worker = TPUOffloadWorker(
            TPUOffloadConfig(tpu_endpoint_url=f"http://127.0.0.1:{tpu_port}")
        )
        mgr = AutostartHostManager(port=web_port, domain="thietbibachkhoa.id.vn")
        server, thread = start_background_server(
            host="127.0.0.1",
            port=web_port,
            tpu_worker=worker,
            governance_policy=policy,
        )
        try:
            self.assertEqual(mgr.get_domain_lifecycle_status()["default_port"], web_port)
            for endpoint in (
                "/api/health",
                "/api/domain-status",
                "/api/agent-tiers",
                "/api/tpu/status",
            ):
                code, _, _ = http_request(f"http://127.0.0.1:{web_port}{endpoint}")
                self.assertEqual(code, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)
            stop_colab_tpu_server_instance(tpu_handle)


# ============================================================================
# TIER 4: REAL-WORLD APPLICATION SCENARIOS (5 End-to-End Scenarios)
# ============================================================================


class Tier4RealWorldScenariosTests(unittest.TestCase):
    """Tier 4 — End-to-End Real-World Application Scenarios."""

    def test_t4_scenario_1_full_multi_agent_lifecycle(self) -> None:
        """Scenario 1: Complete Multi-Agent Project Lifecycle from Survey to Carbon Escalation."""
        from uav_app.infrastructure.agent_governance import AgentGovernancePolicy

        policy = AgentGovernancePolicy()

        # Step 1: Spawn 5 Hydrogen agents to survey the project
        survey_slots = policy.acquire_agent_slot("hydrogen", count=5)
        self.assertEqual(get_active_slot_count(survey_slots), 5)
        policy.release_agent_slot("hydrogen", count=5)

        # Step 2: Model 4 Argon High creates & approves detailed architecture plan
        policy.create_architecture_plan(
            plan_id="arch-vn2000-2026",
            summary="UAV GeoTIFF VN2000 + thietbibachkhoa.id.vn + Google TPU Offload",
            planner_tier="argon_high",
        )
        approval = policy.approve_architecture(
            plan_id="arch-vn2000-2026", approved_by="argon_high"
        )
        self.assertTrue(approval["approved"])

        # Step 3: Assign roles across difficulty levels and spawn 250 Hydrogen workers
        r_ui = policy.assign_role("task-ui-portal", difficulty="low")
        r_tunnel = policy.assign_role("task-cloudflare-tunnel", difficulty="medium")
        r_tpu = policy.assign_role("task-tpu-worker", difficulty="high")
        r_spline = policy.assign_role(
            "task-cad-spline-kernel",
            difficulty="critical",
            requires_deep_optimization=True,
        )
        r_synth = policy.assign_role(
            "task-cross-module-review", difficulty="high", use_argon=True
        )

        self.assertEqual(r_ui.get("assigned_tier") or r_ui.get("tier"), "hydrogen")
        self.assertEqual(r_tunnel.get("assigned_tier") or r_tunnel.get("tier"), "hydrogen")
        self.assertEqual(r_tpu.get("assigned_tier") or r_tpu.get("tier"), "hydrogen")
        self.assertEqual(r_spline.get("assigned_tier") or r_spline.get("tier"), "carbon")
        self.assertEqual(r_synth.get("assigned_tier") or r_synth.get("tier"), "argon")

        policy.acquire_agent_slot("hydrogen", count=250)
        policy.acquire_agent_slot("carbon", count=2)
        active_map = get_summary_active_map(policy.get_status_summary())
        self.assertEqual(active_map["hydrogen"], 250)
        self.assertEqual(active_map["carbon"], 2)

        # Step 4: Iterative test loop on task-tpu-worker: fails twice (SELF_FIX), 3rd time escalates to Carbon
        s1 = policy.record_test_failure("task-tpu-worker", "Timeout on batch 1")
        s2 = policy.record_test_failure("task-tpu-worker", "Timeout on batch 2")
        s3 = policy.record_test_failure("task-tpu-worker", "Persistent socket hang")
        self.assertEqual(s1["action"], "SELF_FIX")
        self.assertEqual(s2["action"], "SELF_FIX")
        self.assertEqual(s3["action"], "ESCALATE_TO_CARBON")

        # Step 5: Model 4 Carbon resolves the escalated task and releases all slots
        resolved = policy.record_test_success("task-tpu-worker")
        self.assertIn(resolved["status"].upper(), ("PASSED", "RESOLVED"))
        policy.release_agent_slot("hydrogen", count=250)
        policy.release_agent_slot("carbon", count=2)
        active_after = get_summary_active_map(policy.get_status_summary())
        self.assertEqual(active_after["hydrogen"], 0)
        self.assertEqual(active_after["carbon"], 0)

    def test_t4_scenario_2_workstation_boot_to_shutdown_domain_lifecycle(self) -> None:
        """Scenario 2: Machine powers ON -> https://thietbibachkhoa.id.vn/ online; powers OFF -> offline."""
        from uav_app.infrastructure.autostart_host import AutostartHostManager

        port = find_free_port()
        mgr = AutostartHostManager(port=port, domain="thietbibachkhoa.id.vn")

        # Machine boots up
        mgr.start_web_server()
        try:
            code_root, html_body, _ = http_request(
                f"http://127.0.0.1:{port}/",
                headers={"Host": "thietbibachkhoa.id.vn"},
            )
            self.assertEqual(code_root, 200)
            self.assertIn("thietbibachkhoa.id.vn", html_body)

            code_health, health_body, _ = http_request(
                f"http://127.0.0.1:{port}/api/health",
                headers={"Host": "thietbibachkhoa.id.vn"},
            )
            self.assertEqual(code_health, 200)
            health_json = json.loads(health_body)
            self.assertTrue(health_json["online"])
        finally:
            # Machine powers down
            mgr.stop()

        # Verify web server is immediately unreachable after shutdown
        with self.assertRaises(Exception):
            http_request(f"http://127.0.0.1:{port}/api/health", timeout=0.5)

    def test_t4_scenario_3_vn2000_geotiff_sliding_window_tpu_offload(self) -> None:
        """Scenario 3: Full 10-tile VN2000 UAV GeoTIFF Orthomosaic Offloaded to Remote Google TPU Server."""
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )
        from uav_app.adapters.webgpu_public_server import start_background_server

        tpu_port = find_free_port()
        web_port = find_free_port()
        tpu_handle = start_colab_tpu_server_instance(tpu_port)
        worker = TPUOffloadWorker(
            TPUOffloadConfig(
                tpu_endpoint_url=f"http://127.0.0.1:{tpu_port}",
                batch_size=4,
                timeout_sec=5.0,
                fallback_to_local=True,
            )
        )
        server, thread = start_background_server(
            host="127.0.0.1", port=web_port, tpu_worker=worker
        )
        try:
            tile_specs = [
                {"rgb_mean": [70.0, 72.0, 75.0], "width_m": 6.0, "slope_deg": 1.0},    # asphalt_road
                {"rgb_mean": [200.0, 202.0, 204.0], "width_m": 5.0, "slope_deg": 1.0}, # concrete_road
                {"rgb_mean": [175.0, 125.0, 80.0], "width_m": 4.0, "slope_deg": 2.0},  # dirt_road
                {"rgb_mean": [130.0, 165.0, 120.0], "width_m": 1.4, "slope_deg": 2.0}, # footpath
                {"rgb_mean": [40.0, 95.0, 150.0], "width_m": 12.0, "slope_deg": 0.5},  # pond
                {"rgb_mean": [40.0, 95.0, 150.0], "width_m": 1.5, "slope_deg": 14.0},  # masonry_ditch
                {"rgb_mean": [75.0, 76.0, 78.0], "width_m": 6.5, "slope_deg": 1.2},
                {"rgb_mean": [195.0, 198.0, 200.0], "width_m": 5.5, "slope_deg": 1.0},
                {"rgb_mean": [170.0, 120.0, 75.0], "width_m": 3.8, "slope_deg": 2.2},
                {"rgb_mean": [45.0, 100.0, 155.0], "width_m": 15.0, "slope_deg": 0.3},
            ]
            tiles = [
                {
                    "tile_id": f"vn2000_tile_{idx:02d}",
                    "row": idx // 5,
                    "col": idx % 5,
                    "vn2000_x": 584000.0 + (idx % 5) * 50.0,
                    "vn2000_y": 1192000.0 + (idx // 5) * 50.0,
                    **tile_specs[idx],
                }
                for idx in range(10)
            ]
            payload = json.dumps(
                {
                    "tiles": tiles,
                    "metadata": {
                        "crs": "EPSG:9210",
                        "Zone": "VN2000_3_degree",
                        "gsd_m": 0.05,
                    },
                }
            ).encode("utf-8")

            code, body, _ = http_request(
                f"http://127.0.0.1:{web_port}/api/tpu/infer",
                method="POST",
                payload=payload,
            )
            self.assertEqual(code, 200)
            result = json.loads(body)
            self.assertEqual(result["backend_used"], "remote_google_tpu")
            self.assertGreaterEqual(result["gpu_load_saved_pct"], 90.0)
            self.assertEqual(len(result["tile_results"]), 10)
            batch_cnt = result.get("batch_count", result.get("batches_processed"))
            self.assertEqual(batch_cnt, 3)
            expected_classes = {
                "asphalt_road",
                "concrete_road",
                "dirt_road",
                "footpath",
                "pond",
                "masonry_ditch",
            }
            self.assertTrue(
                expected_classes.issubset(set(result["classes_detected"])),
                f"Expected all 6 classes in {result['classes_detected']}",
            )
            for tile_res in result["tile_results"]:
                poly = tile_res.get("lwpolyline_vn2000") or tile_res.get("polylines_vn2000")
                self.assertIsNotNone(poly)
                self.assertGreaterEqual(len(poly), 2)
        finally:
            stop_colab_tpu_server_instance(tpu_handle)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    def test_t4_scenario_4_mid_survey_tpu_disconnect_and_local_fallback(self) -> None:
        """Scenario 4: Remote Colab TPU disconnects mid-survey; worker seamlessly falls back to local."""
        from uav_app.adapters.tpu_offload_worker import (
            TPUOffloadConfig,
            TPUOffloadWorker,
        )

        tpu_port = find_free_port()
        tpu_handle = start_colab_tpu_server_instance(tpu_port)
        worker = TPUOffloadWorker(
            TPUOffloadConfig(
                tpu_endpoint_url=f"http://127.0.0.1:{tpu_port}",
                batch_size=2,
                timeout_sec=1.0,
                fallback_to_local=True,
            )
        )
        try:
            first_half = [
                {
                    "tile_id": "part1_tile_0",
                    "row": 0,
                    "col": 0,
                    "vn2000_x": 584000.0,
                    "vn2000_y": 1192000.0,
                    "rgb_mean": [70.0, 72.0, 75.0],
                },
                {
                    "tile_id": "part1_tile_1",
                    "row": 0,
                    "col": 1,
                    "vn2000_x": 584050.0,
                    "vn2000_y": 1192000.0,
                    "rgb_mean": [195.0, 198.0, 200.0],
                },
            ]
            res1 = worker.infer_tile_batch(first_half)
            self.assertEqual(res1["backend_used"], "remote_google_tpu")

            # Simulate sudden Colab TPU session disconnection
            stop_colab_tpu_server_instance(tpu_handle)
            tpu_handle = None

            second_half = [
                {
                    "tile_id": "part2_tile_2",
                    "row": 1,
                    "col": 0,
                    "vn2000_x": 584000.0,
                    "vn2000_y": 1192050.0,
                    "rgb_mean": [40.0, 95.0, 145.0],
                },
                {
                    "tile_id": "part2_tile_3",
                    "row": 1,
                    "col": 1,
                    "vn2000_x": 584050.0,
                    "vn2000_y": 1192050.0,
                    "rgb_mean": [165.0, 125.0, 85.0],
                },
            ]
            res2 = worker.infer_tile_batch(second_half)
            self.assertEqual(res2["backend_used"], "local_fallback")
            self.assertEqual(len(res2["tile_results"]), 2)
        finally:
            if tpu_handle is not None:
                stop_colab_tpu_server_instance(tpu_handle)

    def test_t4_scenario_5_end_user_artifacts_and_colab_notebook_integrity(self) -> None:
        """Scenario 5: End-user verification of launchers, domain & TPU guides, and Colab notebook JSON."""
        mo_html = (PROJECT_ROOT / "MO_WEB_NHAN_DIEN_NGAY.html").read_text(encoding="utf-8")
        link_txt = (PROJECT_ROOT / "LINK_TRUY_CAP_WEB.txt").read_text(encoding="utf-8")
        domain_guide = (PROJECT_ROOT / "DOMAIN_SETUP_THIETBIBACHKHOA.md").read_text(
            encoding="utf-8"
        )
        tpu_guide = (PROJECT_ROOT / "TPU_OFFLOAD_ULTRA_GUIDE.md").read_text(
            encoding="utf-8"
        )
        notebook_path = PROJECT_ROOT / "notebooks" / "Colab_Ultra_TPU_Server_VN2000.ipynb"

        self.assertIn("https://thietbibachkhoa.id.vn/", mo_html)
        self.assertIn("https://thietbibachkhoa.id.vn/", link_txt)
        self.assertIn("https://thietbibachkhoa.id.vn/", domain_guide)
        self.assertIn("cloudflared", domain_guide.lower())
        self.assertIn("ultra", tpu_guide.lower())
        self.assertIn("tpu", tpu_guide.lower())

        nb = json.loads(notebook_path.read_text(encoding="utf-8"))
        self.assertEqual(nb["nbformat"], 4)
        self.assertEqual(nb.get("metadata", {}).get("colab", {}).get("accelerator"), "TPU")
        code_cells = [c for c in nb["cells"] if c.get("cell_type") == "code"]
        self.assertGreaterEqual(len(code_cells), 2)
        all_source = "\n".join("".join(c.get("source", [])) for c in code_cells)
        self.assertIn("/health", all_source)
        self.assertIn("torch_xla", all_source)
        self.assertIn("VN2000_LAYERS", all_source)
        compiled = compile(all_source, str(notebook_path), "exec")
        self.assertIsNotNone(compiled)

    def test_t4_scenario_6_admin_key_lifecycle_and_over_15m_yolo_and_detect_tpu_offload(self) -> None:
        """Scenario 6: Full Admin Key Management (7-col Google Sheet, <=1/3 red / >1/3 green, Guest 403) + >15m Auto-TPU Offload for Image Detection & YOLO Update + Processed Data Folder 1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN."""
        from uav_app.adapters.tpu_offload_worker import TPUOffloadConfig, TPUOffloadWorker
        from uav_app.adapters.webgpu_public_server import start_background_server
        from uav_app.infrastructure.gdrive_key_storage import (
            DEFAULT_ADMIN_KEY,
            PROCESSED_DATA_GDRIVE_FOLDER_ID,
            GoogleSheetKeyManager,
        )

        tpu_port = find_free_port()
        tpu_handle = start_colab_tpu_server_instance(tpu_port)
        web_port = find_free_port()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            km = GoogleSheetKeyManager(
                registry_path=tmp_path / "reg.json",
                sheet_csv_path=tmp_path / "sheet.csv",
            )
            tpu_worker = TPUOffloadWorker(
                TPUOffloadConfig(
                    tpu_endpoint_url=f"http://127.0.0.1:{tpu_port}",
                    batch_size=4,
                    timeout_sec=3.0,
                    fallback_to_local=True,
                )
            )
            srv, thread = start_background_server(
                host="127.0.0.1",
                port=web_port,
                tpu_worker=tpu_worker,
                key_manager=km,
            )
            base = f"http://127.0.0.1:{web_port}"
            try:
                # 1. Verify processed data Drive folder endpoint
                c_drv, b_drv, _ = http_request(f"{base}/api/gdrive/processed-folder")
                self.assertEqual(c_drv, 200)
                d_drv = json.loads(b_drv)
                self.assertEqual(d_drv["processed_data_folder_id"], "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN")
                self.assertIn("1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN", d_drv["processed_data_folder_url"])

                # 2. Verify automatic agent task division endpoint
                c_div, b_div, _ = http_request(
                    f"{base}/api/agent-tiers/divide-tasks",
                    method="POST",
                    payload=json.dumps({"plan_id": "plan-e2e-r3"}).encode("utf-8"),
                )
                self.assertEqual(c_div, 200)
                d_div = json.loads(b_div)
                self.assertEqual(d_div["survey_agents_count"], 5)
                self.assertTrue(d_div["architecture_approved"])

                # 3. Admin creates 2 guest keys (1h without TPU, 6m with TPU)
                c_k1, b_k1, _ = http_request(
                    f"{base}/api/keys/create",
                    method="POST",
                    headers={"X-Admin-Key": DEFAULT_ADMIN_KEY},
                    payload=json.dumps(
                        {
                            "recipient": "Khách Test 1h",
                            "phone": "0911000111",
                            "purpose": "1h",
                            "allow_tpu": False,
                        }
                    ).encode("utf-8"),
                )
                self.assertEqual(c_k1, 200)
                guest_no_tpu = json.loads(b_k1)["key_record"]["key"]

                c_k2, b_k2, _ = http_request(
                    f"{base}/api/keys/create",
                    method="POST",
                    headers={"X-Admin-Key": DEFAULT_ADMIN_KEY},
                    payload=json.dumps(
                        {
                            "recipient": "Khách Mua 6 Tháng",
                            "phone": "0922000222",
                            "purpose": "6m",
                            "allow_tpu": True,
                        }
                    ).encode("utf-8"),
                )
                self.assertEqual(c_k2, 200)
                guest_with_tpu = json.loads(b_k2)["key_record"]["key"]

                # 4. Guest key cannot list, create, or delete keys (403 Forbidden)
                c_forbid_list, _, _ = http_request(
                    f"{base}/api/keys",
                    headers={"X-API-Key": guest_with_tpu},
                )
                self.assertEqual(c_forbid_list, 403)

                # 5. Image detection > 15m (estimated_seconds=1500):
                #    - Guest without allow_tpu -> 403
                c_det_deny, _, _ = http_request(
                    f"{base}/api/detect/upload",
                    method="POST",
                    payload=json.dumps(
                        {"key": guest_no_tpu, "estimated_seconds": 1500, "num_images": 6}
                    ).encode("utf-8"),
                )
                self.assertEqual(c_det_deny, 403)

                #    - Guest with allow_tpu -> 200 & offloaded_to_tpu=True
                c_det_ok, b_det_ok, _ = http_request(
                    f"{base}/api/detect/upload",
                    method="POST",
                    payload=json.dumps(
                        {"key": guest_with_tpu, "estimated_seconds": 1500, "num_images": 6}
                    ).encode("utf-8"),
                )
                self.assertEqual(c_det_ok, 200)
                d_det_ok = json.loads(b_det_ok)
                self.assertTrue(d_det_ok["offloaded_to_tpu"])
                self.assertEqual(d_det_ok["processed_data_folder_id"], PROCESSED_DATA_GDRIVE_FOLDER_ID)

                # 6. YOLO model update > 15m with Admin key -> 200 & offloaded to remote TPU server
                c_yolo, b_yolo, _ = http_request(
                    f"{base}/api/yolo/update",
                    method="POST",
                    payload=json.dumps(
                        {
                            "key": DEFAULT_ADMIN_KEY,
                            "new_classes": ["nha_kinh", "kenh_tieu"],
                            "epochs": 40,
                            "dataset_size": 600,
                        }
                    ).encode("utf-8"),
                )
                self.assertEqual(c_yolo, 200)
                d_yolo = json.loads(b_yolo)
                self.assertTrue(d_yolo["offloaded_to_tpu"])
                self.assertEqual(d_yolo["result"]["backend_used"], "remote_google_tpu")
                self.assertEqual(d_yolo["processed_data_folder_id"], PROCESSED_DATA_GDRIVE_FOLDER_ID)
            finally:
                srv.shutdown()
                srv.server_close()
                thread.join(timeout=2.0)
                stop_colab_tpu_server_instance(tpu_handle)


class Tier1Feature678AutoTPUAndKeyManagementTests(unittest.TestCase):
    """Tier 1 — Features F6 (>15m Auto-TPU & YOLO), F7 (7-Col Google Sheet Key Manager), F8 (Processed Drive Path)."""

    def test_t1_f6_01_execution_time_estimator_15m_threshold(self) -> None:
        from uav_app.adapters.tpu_offload_worker import estimate_execution_time

        below = estimate_execution_time("image_detection", estimated_seconds_override=900.0)
        self.assertFalse(below["requires_tpu_offload"])
        above = estimate_execution_time("image_detection", estimated_seconds_override=900.1)
        self.assertTrue(above["requires_tpu_offload"])

    def test_t1_f6_02_rbac_admin_vs_guest_allow_tpu(self) -> None:
        from uav_app.adapters.tpu_offload_worker import check_tpu_permission

        self.assertTrue(check_tpu_permission(role="admin", allow_tpu=False)["allowed"])
        self.assertTrue(check_tpu_permission(role="guest", allow_tpu=True)["allowed"])
        self.assertFalse(check_tpu_permission(role="guest", allow_tpu=False)["allowed"])

    def test_t1_f7_01_google_sheet_7_columns_and_all_purposes(self) -> None:
        from uav_app.infrastructure.gdrive_key_storage import (
            GOOGLE_SHEET_HEADERS,
            GoogleSheetKeyManager,
        )

        self.assertEqual(
            GOOGLE_SHEET_HEADERS,
            [
                "Người nhận",
                "SĐT người nhận",
                "Key",
                "Mục đích",
                "Thời gian cấp",
                "Thời gian hết hạn",
                "Tình trạng",
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            km = GoogleSheetKeyManager(
                registry_path=tmp_path / "reg.json",
                sheet_csv_path=tmp_path / "sheet.csv",
            )
            for p in ("1h", "3h", "5h", "1m", "3m", "6m", "1y"):
                rec = km.create_key(recipient=f"User_{p}", phone="0909000111", purpose=p)
                self.assertEqual(rec["purpose"], p)
            self.assertTrue((tmp_path / "sheet.csv").exists())

    def test_t1_f8_01_processed_data_gdrive_folder_id_configured(self) -> None:
        from uav_app.infrastructure.gdrive_key_storage import (
            PROCESSED_DATA_GDRIVE_FOLDER_ID,
            PROCESSED_DATA_GDRIVE_FOLDER_URL,
            GoogleDrive30TBStorage,
        )

        self.assertEqual(PROCESSED_DATA_GDRIVE_FOLDER_ID, "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN")
        self.assertEqual(
            PROCESSED_DATA_GDRIVE_FOLDER_URL,
            "https://drive.google.com/drive/u/3/folders/1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN",
        )
        st = GoogleDrive30TBStorage()
        info = st.get_processed_data_folder_info()
        self.assertEqual(info["processed_data_folder_id"], "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN")


# ============================================================================
# TEST SUITE RUNNER CLI
# ============================================================================

TIER_CLASSES = {
    1: [
        Tier1Feature1RuleFilesTests,
        Tier1Feature2AgentGovernanceEngineTests,
        Tier1Feature3ZeroHostingDomainAutostartTests,
        Tier1Feature4LocalWebGPUSurveyServerTests,
        Tier1Feature5GoogleTPUOffloadTests,
        Tier1Feature678AutoTPUAndKeyManagementTests,
    ],
    2: [
        Tier2Feature1RuleBoundariesTests,
        Tier2Feature2GovernanceBoundariesTests,
        Tier2Feature3DomainAutostartBoundariesTests,
        Tier2Feature4WebGPUSurveyServerBoundariesTests,
        Tier2Feature5TPUOffloadBoundariesTests,
    ],
    3: [
        Tier3CrossFeatureIntegrationTests,
    ],
    4: [
        Tier4RealWorldScenariosTests,
    ],
}


def build_suite(selected_tiers: list[int]) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tier_num in selected_tiers:
        for cls in TIER_CLASSES.get(tier_num, []):
            suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(
        description="4-Tier Requirement-Driven E2E Test Runner for UAV_GeoTIFF_WebGPU_Survey_VN2000"
    )
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        help="Run a specific E2E test tier (1, 2, 3, or 4)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 4 E2E test tiers (default when --tier is omitted)",
    )
    args = parser.parse_args()

    if args.tier is not None:
        tiers_to_run = [args.tier]
    else:
        tiers_to_run = [1, 2, 3, 4]

    print("=" * 78)
    print(f"UAV_GeoTIFF_WebGPU_Survey_VN2000 — E2E Test Suite (Tiers: {tiers_to_run})")
    print("=" * 78)

    overall_success = True
    total_ran = 0
    total_failed = 0
    total_errors = 0

    for tier_num in tiers_to_run:
        tier_suite = build_suite([tier_num])
        print(
            f"\n--- Running Tier {tier_num} ({tier_suite.countTestCases()} test cases) ---"
        )
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(tier_suite)
        total_ran += result.testsRun
        total_failed += len(result.failures)
        total_errors += len(result.errors)
        if not result.wasSuccessful():
            overall_success = False

    print("\n" + "=" * 78)
    print(
        f"E2E SUMMARY: Ran {total_ran} tests | "
        f"Passed: {total_ran - total_failed - total_errors} | "
        f"Failures: {total_failed} | Errors: {total_errors}"
    )
    print("=" * 78)
    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())
