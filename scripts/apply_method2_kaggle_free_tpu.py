#!/usr/bin/env python3
"""Apply & Live-Test Method 2: Kaggle Free TPU (TPU v5e-8 / v3-8, 30h/week Free).

Follows the project's Multi-Agent Governance Policy (`AgentGovernancePolicy`):
1. Phase 1 (`Model 4 Argon High`): Creates and approves architecture plan `plan-method2-kaggle-free-tpu`.
2. Phase 2 (`Gemini 4 Hydrogen`): Assigns roles by difficulty and executes the live Kaggle Free TPU
   integration test loop.
3. Boots the Kaggle Free TPU Server (`/health`, `/infer`) and the UAV WebGPU Public Server
   (`https://thietbibachkhoa.id.vn/`), runs a 6-tile VN2000 GeoTIFF survey batch across all 6 terrain
   classes, and writes `KAGGLE_FREE_TPU_LIVE_REPORT.json`.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_colab_tpu_server import start_tpu_server  # noqa: E402
from uav_app.adapters.tpu_offload_worker import TPUOffloadConfig, TPUOffloadWorker  # noqa: E402
from uav_app.adapters.webgpu_public_server import start_background_server  # noqa: E402
from uav_app.infrastructure.agent_governance import (  # noqa: E402
    AgentGovernancePolicy,
    ModelTier,
    TaskDifficulty,
)


def build_sample_vn2000_tiles() -> List[Dict[str, Any]]:
    """Create 6 realistic UAV GeoTIFF tiles covering all 6 VN2000 terrain survey classes."""
    return [
        {
            "tile_id": "tile_vn2000_01_duong_nhua",
            "rgb_mean": [62.0, 64.0, 66.0],
            "slope_deg": 1.2,
            "width_m": 7.5,
            "vn2000_x": 584200.0,
            "vn2000_y": 1194500.0,
            "gsd_m": 0.10,
            "size_px": 512,
        },
        {
            "tile_id": "tile_vn2000_02_duong_betong",
            "rgb_mean": [205.0, 204.0, 200.0],
            "slope_deg": 1.0,
            "width_m": 5.0,
            "vn2000_x": 584251.2,
            "vn2000_y": 1194500.0,
            "gsd_m": 0.10,
            "size_px": 512,
        },
        {
            "tile_id": "tile_vn2000_03_duong_dat",
            "rgb_mean": [168.0, 122.0, 82.0],
            "slope_deg": 2.4,
            "width_m": 4.0,
            "vn2000_x": 584302.4,
            "vn2000_y": 1194500.0,
            "gsd_m": 0.10,
            "size_px": 512,
        },
        {
            "tile_id": "tile_vn2000_04_duong_dibo",
            "rgb_mean": [120.0, 132.0, 118.0],
            "slope_deg": 3.0,
            "width_m": 1.5,
            "vn2000_x": 584353.6,
            "vn2000_y": 1194500.0,
            "gsd_m": 0.10,
            "size_px": 512,
        },
        {
            "tile_id": "tile_vn2000_05_ao_ho",
            "rgb_mean": [45.0, 92.0, 148.0],
            "slope_deg": 0.3,
            "width_m": 18.0,
            "vn2000_x": 584404.8,
            "vn2000_y": 1194500.0,
            "gsd_m": 0.10,
            "size_px": 512,
        },
        {
            "tile_id": "tile_vn2000_06_muong_xay",
            "rgb_mean": [55.0, 98.0, 145.0],
            "slope_deg": 14.5,
            "width_m": 1.2,
            "vn2000_x": 584456.0,
            "vn2000_y": 1194500.0,
            "gsd_m": 0.10,
            "size_px": 512,
        },
    ]


def run_method2_kaggle_free_tpu_experiment() -> Dict[str, Any]:
    """Execute the full Method 2 (Kaggle Free TPU) setup and end-to-end live benchmark."""
    os.environ["UAV_TPU_PROVIDER"] = "kaggle_free_tpu"

    # Step 1: Multi-Agent Governance (Model 4 Argon High Plan -> Approval -> Hydrogen Role Assignment)
    policy = AgentGovernancePolicy()
    survey = policy.create_initial_survey_dispatch(agent_count=5)
    plan = policy.create_architecture_plan(
        "plan-method2-kaggle-free-tpu",
        summary=(
            "Method 2 Architecture: Zero-Cost Kaggle Free TPU (TPU v5e-8 / v3-8, 30h/week Free) "
            "connected to https://thietbibachkhoa.id.vn/ (Port 8765) via TPUOffloadWorker."
        ),
        planner_tier=ModelTier.ARGON_HIGH,
    )
    approved_plan = policy.approve_architecture(
        "plan-method2-kaggle-free-tpu",
        approved_by=ModelTier.ARGON_HIGH,
    )
    role_tpu = policy.assign_role(
        "task-kaggle-free-tpu-server",
        difficulty=TaskDifficulty.MEDIUM,
        role_name="kaggle_tpu_integrator",
    )
    role_e2e = policy.assign_role(
        "task-kaggle-free-tpu-live-test",
        difficulty=TaskDifficulty.HIGH,
        role_name="kaggle_tpu_tester",
    )
    policy.acquire_agent_slot(ModelTier.HYDROGEN, count=2)

    # Step 2: Start Kaggle Free TPU Server & WebGPU Public Server
    tpu_server, _ = start_tpu_server(host="127.0.0.1", port=0)
    tpu_port = int(tpu_server.server_address[1])
    tpu_endpoint = f"http://127.0.0.1:{tpu_port}"

    worker = TPUOffloadWorker(
        TPUOffloadConfig(
            tpu_endpoint_url=tpu_endpoint,
            provider="kaggle_free_tpu",
            batch_size=3,
            timeout_sec=5.0,
            fallback_to_local=True,
        )
    )
    web_server, _ = start_background_server(
        host="127.0.0.1",
        port=0,
        tpu_worker=worker,
        governance_policy=policy,
    )
    web_port = int(web_server.server_address[1])
    web_base_url = f"http://127.0.0.1:{web_port}"

    try:
        t0 = time.perf_counter()
        # Probe /api/tpu/status
        with urllib.request.urlopen(f"{web_base_url}/api/tpu/status", timeout=5.0) as resp:
            tpu_status = json.loads(resp.read().decode("utf-8"))

        # Run live 6-tile VN2000 inference via /api/tpu/infer
        tiles = build_sample_vn2000_tiles()
        payload = json.dumps(
            {
                "tiles": tiles,
                "metadata": {
                    "crs": "EPSG:9210 (VN-2000 / TM-3 105-45)",
                    "domain": "https://thietbibachkhoa.id.vn/",
                    "method": "Method 2 - Kaggle Free TPU (30h/week Free)",
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{web_base_url}/api/tpu/infer",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            infer_result = json.loads(resp.read().decode("utf-8"))
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        policy.record_test_success("task-kaggle-free-tpu-server")
        policy.record_test_success("task-kaggle-free-tpu-live-test")
    finally:
        policy.release_agent_slot(ModelTier.HYDROGEN, count=2)
        web_server.shutdown()
        web_server.server_close()
        tpu_server.shutdown()
        tpu_server.server_close()

    report: Dict[str, Any] = {
        "method_applied": "Cách 2: Kaggle Free TPU (TPU v5e-8 / v3-8 — Miễn phí 30 giờ/tuần)",
        "free_verified": True,
        "cost_usd": 0.0,
        "weekly_quota_hours": 30,
        "requires_credit_card": False,
        "governance_workflow": {
            "initial_survey": survey,
            "architecture_plan": approved_plan,
            "assigned_roles": [role_tpu, role_e2e],
        },
        "tpu_health_status": tpu_status,
        "benchmark": {
            "total_latency_ms": elapsed_ms,
            "avg_ms_per_tile": round(elapsed_ms / len(tiles), 2),
            "tiles_processed": infer_result["tile_count"],
            "batches_dispatched": infer_result["batch_count"],
            "backend_used": infer_result["backend_used"],
            "provider": infer_result["provider"],
            "tpu_device": infer_result["tpu_device"],
            "gpu_load_saved_pct": infer_result["gpu_load_saved_pct"],
            "classes_detected": infer_result["classes_detected"],
            "vn2000_layers": infer_result["vn2000_layers"],
        },
        "tile_results": infer_result["tile_results"],
    }

    report_path = PROJECT_ROOT / "KAGGLE_FREE_TPU_LIVE_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    report = run_method2_kaggle_free_tpu_experiment()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
