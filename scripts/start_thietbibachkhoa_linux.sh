#!/usr/bin/env bash
# ==============================================================================
# Zero-Hosting Power-Coupled Startup Script (Linux)
# Domain : https://thietbibachkhoa.id.vn/
# Port   : 8765 (configurable via UAV_WEB_PORT)
# Effect :
#   - Machine turns ON  -> Starts local web server on port 8765 + cloudflared tunnel
#   - Machine turns OFF -> SIGTERM/SIGINT trap stops web server & tunnel immediately
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export UAV_WEB_PORT="${UAV_WEB_PORT:-8765}"
export UAV_CUSTOM_DOMAIN="${UAV_CUSTOM_DOMAIN:-thietbibachkhoa.id.vn}"
TUNNEL_CONFIG="${PROJECT_ROOT}/config/cloudflared_thietbibachkhoa.yml"

WEB_PID=""
TUNNEL_PID=""

cleanup_on_shutdown() {
    echo "[thietbibachkhoa.id.vn] Machine shutting down / stopping service..."
    if [[ -n "${TUNNEL_PID}" ]] && kill -0 "${TUNNEL_PID}" 2>/dev/null; then
        kill -TERM "${TUNNEL_PID}" 2>/dev/null || true
        wait "${TUNNEL_PID}" 2>/dev/null || true
    fi
    if [[ -n "${WEB_PID}" ]] && kill -0 "${WEB_PID}" 2>/dev/null; then
        kill -TERM "${WEB_PID}" 2>/dev/null || true
        wait "${WEB_PID}" 2>/dev/null || true
    fi
    echo "[thietbibachkhoa.id.vn] Web server & tunnel stopped. Domain is now OFFLINE."
    exit 0
}

trap cleanup_on_shutdown SIGTERM SIGINT SIGHUP

cd "${PROJECT_ROOT}"

if [[ "${1:-}" == "--check-config" ]]; then
    python3 -m uav_app.infrastructure.autostart_host --port "${UAV_WEB_PORT}" --domain "${UAV_CUSTOM_DOMAIN}" --status
    exit 0
fi

echo "[thietbibachkhoa.id.vn] Starting UAV GeoTIFF WebGPU Survey VN2000 on 0.0.0.0:${UAV_WEB_PORT}..."
python3 -m uav_app.adapters.webgpu_public_server --host 0.0.0.0 --port "${UAV_WEB_PORT}" &
WEB_PID=$!

if command -v cloudflared >/dev/null 2>&1; then
    echo "[thietbibachkhoa.id.vn] Launching Cloudflare Tunnel for https://${UAV_CUSTOM_DOMAIN}/ -> http://127.0.0.1:${UAV_WEB_PORT}..."
    cloudflared tunnel --config "${TUNNEL_CONFIG}" run &
    TUNNEL_PID=$!
else
    echo "[thietbibachkhoa.id.vn] Note: cloudflared binary not in PATH; local server active on port ${UAV_WEB_PORT}."
fi

wait "${WEB_PID}"
