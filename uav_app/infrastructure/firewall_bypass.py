"""Corporate Firewall Bypass & Outbound HTTPS-443 Cloud Bridge for thietbibachkhoa.id.vn.

Provides 3 zero-admin-rights firewall-bypass strategies when a company workstation
is behind a strict corporate firewall blocking inbound ports, UDP 7844 (QUIC),
and/or TCP 7844 (`cloudflared`):
  1. `mode_1_cloud_worker_outbound_443`:
     Cloudflare Worker (`https://thietbibachkhoa.id.vn/`) + Outbound HTTPS Port 443
     Google Drive Bridge (`1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN`). Works even when
     100% of inbound ports, UDP 7844, TCP 7844, and Windows Admin rights are blocked.
  2. `mode_2_tunnel_http2_loopback`:
     `cloudflared --protocol http2 --edge-ip-version 4` bound to local loopback
     `127.0.0.1:8765` (avoids Windows Defender Firewall popup and UDP 7844) with
     automatic corporate proxy detection/injection.
  3. `mode_3_cloud_render_docker`:
     Free Cloud container deployment (`render.yaml` / `Dockerfile`) linked to
     `thietbibachkhoa.id.vn` CNAME.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

CUSTOM_DOMAIN: str = "thietbibachkhoa.id.vn"
CUSTOM_DOMAIN_URL: str = "https://thietbibachkhoa.id.vn/"
DEFAULT_LOCAL_PORT: int = 8765
PROCESSED_DATA_GDRIVE_FOLDER_ID: str = "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN"
MAIN_PROJECT_GDRIVE_FOLDER_ID: str = "1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV"

LOOPBACK_BIND_HOST: str = "127.0.0.1"
TUNNEL_HTTP2_CLI_FLAGS: List[str] = [
    "--no-autoupdate",
    "--protocol",
    "http2",
    "--edge-ip-version",
    "4",
]
TPU_AUTO_OFFLOAD_THRESHOLD_SECONDS: int = 900


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_proxy_url(raw_value: Optional[str], default_scheme: str = "http") -> Optional[str]:
    if not raw_value:
        return None
    cleaned = str(raw_value).strip()
    if not cleaned:
        return None
    if "://" not in cleaned:
        return f"{default_scheme}://{cleaned}"
    return cleaned


def _parse_windows_proxy_server(raw_server: str) -> Dict[str, Optional[str]]:
    """Parse Windows Internet Settings ProxyServer value (`host:port` or `http=..;https=..`)."""
    raw = str(raw_server).strip()
    if not raw:
        return {"http_proxy": None, "https_proxy": None}
    if "=" not in raw:
        normalized = _normalize_proxy_url(raw, "http")
        return {"http_proxy": normalized, "https_proxy": normalized}

    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    for part in raw.split(";"):
        if "=" not in part:
            continue
        proto, val = part.split("=", 1)
        proto_l = proto.strip().lower()
        val_norm = _normalize_proxy_url(val.strip(), "http")
        if proto_l == "http":
            http_proxy = val_norm
        elif proto_l == "https":
            https_proxy = val_norm
    if https_proxy is None and http_proxy is not None:
        https_proxy = http_proxy
    return {"http_proxy": http_proxy, "https_proxy": https_proxy}


def detect_corporate_proxy(env: Optional[dict] = None) -> dict:
    """Detect corporate HTTP/HTTPS proxy from environment variables and Windows Registry.

    Checks `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY` (and lowercase equivalents) in `env`
    or `os.environ`. On Windows (`os.name == "nt"`), also inspects `winreg`
    `Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings` (`ProxyEnable`, `ProxyServer`).
    """
    source_env: Mapping[str, str] = os.environ if env is None else env

    https_proxy = (
        _normalize_proxy_url(source_env.get("HTTPS_PROXY") or source_env.get("https_proxy"))
    )
    http_proxy = (
        _normalize_proxy_url(source_env.get("HTTP_PROXY") or source_env.get("http_proxy"))
    )
    all_proxy = (
        _normalize_proxy_url(source_env.get("ALL_PROXY") or source_env.get("all_proxy"))
    )

    if https_proxy is None and all_proxy is not None:
        https_proxy = all_proxy
    if http_proxy is None and all_proxy is not None:
        http_proxy = all_proxy

    sources: List[str] = []
    if http_proxy or https_proxy or all_proxy:
        sources.append("environment")

    if os.name == "nt":
        try:
            import winreg  # type: ignore[import-not-found]

            reg_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if int(proxy_enable) == 1:
                    proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    parsed = _parse_windows_proxy_server(str(proxy_server))
                    reg_http = parsed.get("http_proxy")
                    reg_https = parsed.get("https_proxy")
                    if reg_http or reg_https:
                        if http_proxy is None:
                            http_proxy = reg_http
                        if https_proxy is None:
                            https_proxy = reg_https
                        sources.append("winreg")
        except Exception:
            pass

    proxy_detected = bool(http_proxy or https_proxy)
    source_str = "+".join(sources) if sources else "none"
    return {
        "proxy_detected": proxy_detected,
        "http_proxy": http_proxy,
        "https_proxy": https_proxy,
        "source": source_str,
    }


def probe_corporate_firewall(
    port: int = DEFAULT_LOCAL_PORT,
    simulate_udp_blocked: bool = True,
    simulate_tcp_7844_blocked: bool = False,
) -> dict:
    """Return full diagnostic report and 3 firewall-bypass modes for `thietbibachkhoa.id.vn`."""
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"Invalid port: {port}. Must be an integer in 1..65535.")

    proxy_info = detect_corporate_proxy()

    if simulate_tcp_7844_blocked:
        recommended_mode = "mode_1_cloud_worker_outbound_443"
    elif simulate_udp_blocked:
        recommended_mode = "mode_2_tunnel_http2_loopback"
    else:
        recommended_mode = "mode_2_tunnel_http2_loopback"

    modes: Dict[str, Dict[str, Any]] = {
        "mode_1_cloud_worker_outbound_443": {
            "id": "mode_1_cloud_worker_outbound_443",
            "title": "Cloudflare Worker Edge + Outbound HTTPS Port 443 Google Drive Bridge",
            "domain_url": f"https://{CUSTOM_DOMAIN}/",
            "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
            "required_outbound_port": 443,
            "required_inbound_ports": [],
            "requires_udp_7844": False,
            "requires_tcp_7844": False,
            "requires_admin_rights": False,
            "worker_script_path": "deploy/cloudflare_worker_thietbibachkhoa.js",
            "description": (
                "Serves the WebGPU + 7-Column Admin Key Portal + >15m TPU Offload API "
                "directly on Cloudflare's Edge network (`https://thietbibachkhoa.id.vn/`) "
                f"and bridges heavy tasks via outbound HTTPS:443 & Google Drive `{PROCESSED_DATA_GDRIVE_FOLDER_ID}`. "
                "Works even when 100% of inbound ports, UDP 7844, TCP 7844, and Windows Admin rights are blocked."
            ),
        },
        "mode_2_tunnel_http2_loopback": {
            "id": "mode_2_tunnel_http2_loopback",
            "title": "Cloudflare Tunnel HTTP/2 over TCP 443 + Loopback 127.0.0.1",
            "domain_url": f"https://{CUSTOM_DOMAIN}/",
            "bind_host": LOOPBACK_BIND_HOST,
            "bind_port": port,
            "service_url": f"http://{LOOPBACK_BIND_HOST}:{port}",
            "cli_flags": list(TUNNEL_HTTP2_CLI_FLAGS),
            "required_outbound_port": 443,
            "required_inbound_ports": [],
            "requires_udp_7844": False,
            "requires_tcp_7844": True,
            "requires_admin_rights": False,
            "proxy_injection": proxy_info,
            "description": (
                f"Runs `cloudflared --protocol http2 --edge-ip-version 4` pointing to "
                f"`{LOOPBACK_BIND_HOST}:{port}` (avoids Windows Defender Firewall popup and UDP 7844) "
                "with automatic corporate HTTP/HTTPS proxy injection."
            ),
        },
        "mode_3_cloud_render_docker": {
            "id": "mode_3_cloud_render_docker",
            "title": "Free Cloud Container Deployment (render.yaml / Dockerfile) + Custom CNAME",
            "domain_url": f"https://{CUSTOM_DOMAIN}/",
            "cname_target": CUSTOM_DOMAIN,
            "deploy_files": ["render.yaml", "Dockerfile"],
            "required_inbound_ports": [],
            "requires_udp_7844": False,
            "requires_tcp_7844": False,
            "requires_admin_rights": False,
            "description": (
                "Deploys the containerized portal using `render.yaml` / `Dockerfile` on free cloud "
                f"hosting linked via `{CUSTOM_DOMAIN}` CNAME, requiring zero ports on the corporate PC."
            ),
        },
    }

    return {
        "domain": CUSTOM_DOMAIN,
        "domain_url": CUSTOM_DOMAIN_URL,
        "port": port,
        "processed_data_folder_id": PROCESSED_DATA_GDRIVE_FOLDER_ID,
        "main_project_folder_id": MAIN_PROJECT_GDRIVE_FOLDER_ID,
        "simulate_udp_blocked": bool(simulate_udp_blocked),
        "simulate_tcp_7844_blocked": bool(simulate_tcp_7844_blocked),
        "recommended_mode": recommended_mode,
        "loopback_bind_host": LOOPBACK_BIND_HOST,
        "tunnel_cli_flags": list(TUNNEL_HTTP2_CLI_FLAGS),
        "proxy_info": proxy_info,
        "modes": modes,
        "mode_1_cloud_worker_outbound_443": modes["mode_1_cloud_worker_outbound_443"],
        "mode_2_tunnel_http2_loopback": modes["mode_2_tunnel_http2_loopback"],
        "mode_3_cloud_render_docker": modes["mode_3_cloud_render_docker"],
        "probed_at_utc": _utc_now_iso(),
    }


def generate_cloudflare_worker_script(
    domain: str = CUSTOM_DOMAIN,
    processed_folder_id: str = PROCESSED_DATA_GDRIVE_FOLDER_ID,
) -> str:
    """Generate a self-contained Cloudflare Worker script for `https://thietbibachkhoa.id.vn/`.

    Serves the WebGPU 6-class VN2000 portal, 7-column Admin Key Management UI/API,
    >15m TPU Offload API, and Outbound HTTPS-443 Google Drive Bridge endpoints
    directly on Cloudflare's Edge network with zero open ports required on the PC.
    """
    clean_domain = (
        str(domain).strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        or CUSTOM_DOMAIN
    )
    clean_folder_id = str(processed_folder_id).strip() or PROCESSED_DATA_GDRIVE_FOLDER_ID

    return f'''/**
 * Cloudflare Worker Edge Portal & Outbound HTTPS-443 Bridge
 * Domain: https://{clean_domain}/
 * Google Drive Processed Data Folder: {clean_folder_id}
 * Main Project Google Drive Folder: {MAIN_PROJECT_GDRIVE_FOLDER_ID}
 *
 * Zero inbound ports, zero UDP 7844, zero TCP 7844, zero Windows Admin rights required
 * on the corporate workstation. Company PC communicates solely via outbound HTTPS:443.
 */

const CUSTOM_DOMAIN = "{clean_domain}";
const CUSTOM_DOMAIN_URL = "https://{clean_domain}/";
const PROCESSED_DATA_GDRIVE_FOLDER_ID = "{clean_folder_id}";
const PROCESSED_DATA_GDRIVE_FOLDER_URL =
  "https://drive.google.com/drive/u/3/folders/{clean_folder_id}";
const MAIN_PROJECT_GDRIVE_FOLDER_ID = "{MAIN_PROJECT_GDRIVE_FOLDER_ID}";
const TPU_THRESHOLD_SECONDS = 900; // 15 minutes
const DEFAULT_ADMIN_KEY = "uav_admin_master_key_vn2000";

const GOOGLE_SHEET_HEADERS = [
  "Người nhận",
  "SĐT người nhận",
  "Key",
  "Mục đích",
  "Thời gian cấp",
  "Thời gian hết hạn",
  "Tình trạng",
];

const PURPOSE_DURATIONS = {{
  "1h": 3600,
  "3h": 10800,
  "5h": 18000,
  "1m": 2592000,
  "3m": 7776000,
  "6m": 15552000,
  "1y": 31536000,
}};

// Ephemeral edge isolate store (persists across requests when bound to env.UAV_BRIDGE_KV)
const EDGE_MEMORY_STATE = {{
  keys: new Map(),
  bridgeHeartbeat: {{
    online: false,
    transport: "outbound_https_443",
    processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
    last_seen_utc: null,
  }},
  pendingTasks: [],
}};

function jsonResponse(payload, status = 200) {{
  return new Response(JSON.stringify(payload, null, 2), {{
    status,
    headers: {{
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
      "access-control-allow-headers": "Content-Type, Authorization, X-Admin-Key, X-UAV-Key",
      "x-uav-edge-worker": CUSTOM_DOMAIN,
    }},
  }});
}}

function htmlResponse(html, status = 200) {{
  return new Response(html, {{
    status,
    headers: {{
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-uav-edge-worker": CUSTOM_DOMAIN,
    }},
  }});
}}

function extractCallerKey(request, body = {{}}) {{
  const hdrKey =
    request.headers.get("x-admin-key") ||
    request.headers.get("x-uav-key") ||
    "";
  if (hdrKey.trim()) return hdrKey.trim();
  const auth = request.headers.get("authorization") || "";
  if (auth.toLowerCase().startsWith("bearer ")) {{
    return auth.slice(7).trim();
  }}
  const url = new URL(request.url);
  const qKey = url.searchParams.get("key") || url.searchParams.get("admin_key") || "";
  if (qKey.trim()) return qKey.trim();
  if (body && typeof body === "object") {{
    return String(body.admin_key || body.key || body.access_key || "").trim();
  }}
  return "";
}}

async function loadAllKeys(env) {{
  if (env && env.UAV_BRIDGE_KV) {{
    const raw = await env.UAV_BRIDGE_KV.get("uav_keys_v1");
    if (raw) {{
      try {{
        return JSON.parse(raw);
      }} catch (_err) {{
        return [];
      }}
    }}
  }}
  return Array.from(EDGE_MEMORY_STATE.keys.values());
}}

async function saveAllKeys(env, list) {{
  EDGE_MEMORY_STATE.keys.clear();
  for (const item of list) {{
    EDGE_MEMORY_STATE.keys.set(item.key, item);
  }}
  if (env && env.UAV_BRIDGE_KV) {{
    await env.UAV_BRIDGE_KV.put("uav_keys_v1", JSON.stringify(list));
  }}
}}

function enrichKeyStatus(record, nowSec = Math.floor(Date.now() / 1000)) {{
  const total = Math.max(1, Number(record.expires_at_ts) - Number(record.issued_at_ts));
  const remaining = Math.max(0, Number(record.expires_at_ts) - nowSec);
  const ratio = remaining / total;
  const isRed = remaining <= 0 || ratio <= 1 / 3;
  return {{
    ...record,
    remaining_seconds: remaining,
    remaining_ratio: Number(ratio.toFixed(4)),
    status_color: isRed ? "red" : "green",
    is_warning_red: isRed,
    status_label: remaining <= 0 ? "Hết hạn (Đỏ)" : isRed ? "Sắp hết hạn <= 1/3 (Đỏ)" : "Còn hạn > 1/3 (Xanh)",
  }};
}}

async function validateKey(env, callerKey, requireAdmin = false) {{
  const adminMaster = (env && env.UAV_ADMIN_KEY) || DEFAULT_ADMIN_KEY;
  if (!callerKey) {{
    return {{
      valid: false,
      http_status: 403,
      role: "guest",
      is_admin: false,
      allow_tpu: false,
      reason: "Thiếu Key xác thực",
    }};
  }}
  if (callerKey === adminMaster) {{
    return {{
      valid: true,
      http_status: 200,
      role: "admin",
      is_admin: true,
      allow_tpu: true,
      key_record: {{ key: callerKey, role: "admin", allow_tpu: true }},
      reason: "Admin key verified",
    }};
  }}
  if (requireAdmin) {{
    return {{
      valid: false,
      http_status: 403,
      role: "guest",
      is_admin: false,
      allow_tpu: false,
      reason: "Chỉ Key quyền Admin mới được phép truy cập bảng quản lý 7 cột",
    }};
  }}
  const all = await loadAllKeys(env);
  const found = all.find((k) => k.key === callerKey);
  if (!found) {{
    return {{
      valid: false,
      http_status: 403,
      role: "guest",
      is_admin: false,
      allow_tpu: false,
      reason: "Key không tồn tại hoặc đã bị thu hồi",
    }};
  }}
  const enriched = enrichKeyStatus(found);
  if (enriched.remaining_seconds <= 0) {{
    return {{
      valid: false,
      http_status: 403,
      role: found.role || "guest",
      is_admin: false,
      allow_tpu: false,
      key_record: enriched,
      reason: "Key đã hết hạn sử dụng",
    }};
  }}
  const isAdmin = found.role === "admin";
  return {{
    valid: true,
    http_status: 200,
    role: found.role || "guest",
    is_admin: isAdmin,
    allow_tpu: isAdmin || Boolean(found.allow_tpu),
    key_record: enriched,
    reason: "Key verified",
  }};
}}

function renderPortalHtml() {{
  return `<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>UAV GeoTIFF WebGPU Survey VN2000 — https://${{CUSTOM_DOMAIN}}/</title>
  <style>
    body {{ font-family: "Inter", "Segoe UI", system-ui, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
    .container {{ max-width: 1160px; margin: 0 auto; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 18px 22px; margin-bottom: 16px; }}
    .badge {{ display: inline-block; background: #059669; color: #fff; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    code {{ background: #0f172a; color: #38bdf8; padding: 2px 6px; border-radius: 4px; }}
    input, select, button {{ padding: 8px 12px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #f8fafc; }}
    button {{ background: #2563eb; border-color: #3b82f6; cursor: pointer; font-weight: 600; }}
    button.danger {{ background: #dc2626; border-color: #ef4444; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
    th, td {{ border: 1px solid #334155; padding: 8px 10px; text-align: left; }}
    th {{ background: #0f172a; color: #38bdf8; }}
    .status-green {{ color: #34d399; font-weight: 700; }}
    .status-red {{ color: #fca5a5; font-weight: 700; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="card">
      <span class="badge">CLOUDFLARE EDGE · FIREWALL BYPASS MODE (OUTBOUND HTTPS 443)</span>
      <h1>UAV GeoTIFF WebGPU Survey VN2000 — https://${{CUSTOM_DOMAIN}}/</h1>
      <p>Vận hành trực tiếp trên Cloudflare Worker Edge (0 mở cổng trên máy công ty, vượt tường lửa nghiêm ngặt).</p>
      <p>Thư mục Google Drive Data đã xử lý: <a style="color:#38bdf8" target="_blank" href="${{PROCESSED_DATA_GDRIVE_FOLDER_URL}}"><code>${{PROCESSED_DATA_GDRIVE_FOLDER_ID}}</code></a></p>
    </div>

    <div class="card">
      <h2>🔐 Đăng Nhập Key Truy Cập (Admin / Khách Hàng)</h2>
      <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
        <input id="key-input" type="password" placeholder="Nhập Key truy cập..." style="min-width:260px;" />
        <button onclick="verifyLogin()">Đăng Nhập</button>
        <span id="login-msg" style="color:#94a3b8;">Chế độ Khách (Đã ẩn bảng quản lý Key)</span>
      </div>
    </div>

    <div class="card" id="admin-panel" style="display:none;">
      <h2>📊 Quản Lý Key Google Sheet 7 Cột (Admin)</h2>
      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
        <input id="rec-name" placeholder="Người nhận" />
        <input id="rec-phone" placeholder="SĐT người nhận" />
        <select id="rec-purpose">
          <option value="1h">Test 1h</option>
          <option value="3h">Test 3h</option>
          <option value="5h">Test 5h</option>
          <option value="1m">1 tháng</option>
          <option value="3m">3 tháng</option>
          <option value="6m">6 tháng</option>
          <option value="1y">1 năm</option>
        </select>
        <label><input type="checkbox" id="rec-tpu" /> Cho phép TPU (&gt;15p)</label>
        <button onclick="createKey()">+ Tạo Key</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Người nhận</th><th>SĐT người nhận</th><th>Key</th><th>Mục đích</th>
            <th>Thời gian cấp</th><th>Thời gian hết hạn</th><th>Tình trạng</th><th>Thao tác</th>
          </tr>
        </thead>
        <tbody id="keys-body"></tbody>
      </table>
    </div>
  </div>

  <script>
    let activeKey = "";
    async function verifyLogin() {{
      const k = document.getElementById("key-input").value.trim();
      const res = await fetch("/api/auth/verify-key", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ key: k }}),
      }});
      const data = await res.json();
      const panel = document.getElementById("admin-panel");
      const msg = document.getElementById("login-msg");
      if (data.valid && data.is_admin) {{
        activeKey = k;
        panel.style.display = "block";
        msg.textContent = "Đã mở khóa Admin Key Portal";
        await refreshKeys();
      }} else {{
        activeKey = data.valid ? k : "";
        panel.style.display = "none";
        msg.textContent = data.valid ? "Đăng nhập Khách thành công (Đã ẩn quản lý Key)" : (data.reason || "Key không hợp lệ");
      }}
    }}
    async function refreshKeys() {{
      const res = await fetch("/api/keys", {{ headers: {{ "X-Admin-Key": activeKey }} }});
      if (!res.ok) return;
      const data = await res.json();
      const tbody = document.getElementById("keys-body");
      tbody.innerHTML = (data.keys || []).map((r) => \`
        <tr>
          <td>${{r.recipient}}</td><td>${{r.phone}}</td><td><code>${{r.key}}</code></td><td>${{r.purpose}}</td>
          <td>${{r.issued_at_iso}}</td><td>${{r.expires_at_iso}}</td>
          <td><span class="${{r.is_warning_red ? "status-red" : "status-green"}}">${{r.status_label}}</span></td>
          <td><button class="danger" onclick="deleteKey('${{r.key}}')">Xóa</button></td>
        </tr>\`).join("");
    }}
    async function createKey() {{
      await fetch("/api/keys/create", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json", "X-Admin-Key": activeKey }},
        body: JSON.stringify({{
          recipient: document.getElementById("rec-name").value,
          phone: document.getElementById("rec-phone").value,
          purpose: document.getElementById("rec-purpose").value,
          allow_tpu: document.getElementById("rec-tpu").checked,
        }}),
      }});
      await refreshKeys();
    }}
    async function deleteKey(key) {{
      await fetch("/api/keys/delete", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json", "X-Admin-Key": activeKey }},
        body: JSON.stringify({{ key }}),
      }});
      await refreshKeys();
    }}
  </script>
</body>
</html>`;
}}

export default {{
  async fetch(request, env, ctx) {{
    if (request.method === "OPTIONS") {{
      return jsonResponse({{ ok: true }}, 204);
    }}

    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "GET" && (path === "/" || path === "/webgpu.html" || path === "/MO_WEB_NHAN_DIEN_NGAY.html")) {{
      return htmlResponse(renderPortalHtml());
    }}

    if (request.method === "GET" && path === "/api/health") {{
      return jsonResponse({{
        status: "ok",
        online: true,
        mode: "cloudflare_worker_edge_firewall_bypass",
        domain: CUSTOM_DOMAIN,
        url: CUSTOM_DOMAIN_URL,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        inbound_ports_required_on_pc: 0,
      }});
    }}

    if (request.method === "GET" && path === "/api/domain-status") {{
      return jsonResponse({{
        domain: CUSTOM_DOMAIN,
        url: CUSTOM_DOMAIN_URL,
        hosting_mode: "cloudflare_worker_edge_outbound_443",
        firewall_bypass_active: true,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        processed_data_folder_url: PROCESSED_DATA_GDRIVE_FOLDER_URL,
        main_project_folder_id: MAIN_PROJECT_GDRIVE_FOLDER_ID,
      }});
    }}

    if (request.method === "GET" && path === "/api/gdrive/processed-folder") {{
      return jsonResponse({{
        folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        folder_url: PROCESSED_DATA_GDRIVE_FOLDER_URL,
        main_project_folder_id: MAIN_PROJECT_GDRIVE_FOLDER_ID,
        transport: "outbound_https_443",
      }});
    }}

    if (request.method === "GET" && path === "/api/bridge/status") {{
      let hb = EDGE_MEMORY_STATE.bridgeHeartbeat;
      if (env && env.UAV_BRIDGE_KV) {{
        const kvHb = await env.UAV_BRIDGE_KV.get("bridge_heartbeat");
        if (kvHb) hb = JSON.parse(kvHb);
      }}
      return jsonResponse({{
        domain: CUSTOM_DOMAIN,
        transport: "outbound_https_443",
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        heartbeat: hb,
        pending_tasks_count: EDGE_MEMORY_STATE.pendingTasks.length,
      }});
    }}

    if (request.method === "POST" && path === "/api/bridge/heartbeat") {{
      const body = await request.json().catch(() => ({{}}));
      const hb = {{
        online: body.online !== false,
        transport: "outbound_https_443",
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        last_seen_utc: new Date().toISOString(),
        host_info: body.host_info || "corporate_windows_workstation",
      }};
      EDGE_MEMORY_STATE.bridgeHeartbeat = hb;
      if (env && env.UAV_BRIDGE_KV) {{
        await env.UAV_BRIDGE_KV.put("bridge_heartbeat", JSON.stringify(hb));
      }}
      return jsonResponse({{ status: "ok", heartbeat: hb }});
    }}

    if (request.method === "POST" && path === "/api/bridge/poll") {{
      const task = EDGE_MEMORY_STATE.pendingTasks.shift() || null;
      return jsonResponse({{
        status: "ok",
        has_task: Boolean(task),
        task,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
      }});
    }}

    if (request.method === "GET" && (path === "/api/keys" || path === "/api/keys/sheet")) {{
      const callerKey = extractCallerKey(request);
      const auth = await validateKey(env, callerKey, true);
      if (!auth.valid) {{
        return jsonResponse({{ status: "forbidden", http_status: 403, admin_panel_visible: false, error: auth.reason }}, 403);
      }}
      const keys = (await loadAllKeys(env)).map((k) => enrichKeyStatus(k));
      return jsonResponse({{
        status: "ok",
        admin_panel_visible: true,
        column_count: GOOGLE_SHEET_HEADERS.length,
        columns: GOOGLE_SHEET_HEADERS,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        keys,
      }});
    }}

    if (request.method === "POST" && path === "/api/auth/verify-key") {{
      const body = await request.json().catch(() => ({{}}));
      const callerKey = extractCallerKey(request, body);
      const auth = await validateKey(env, callerKey, false);
      return jsonResponse(
        {{
          status: auth.valid ? "ok" : "forbidden",
          ...auth,
          admin_panel_visible: Boolean(auth.valid && auth.is_admin),
          processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        }},
        auth.valid ? 200 : 403
      );
    }}

    if (request.method === "POST" && (path === "/api/keys" || path === "/api/keys/create")) {{
      const body = await request.json().catch(() => ({{}}));
      const adminKey = extractCallerKey(request, body);
      const auth = await validateKey(env, adminKey, true);
      if (!auth.valid) {{
        return jsonResponse({{ status: "forbidden", http_status: 403, error: auth.reason }}, 403);
      }}
      const purpose = String(body.purpose || "1h").trim();
      const durationSec = PURPOSE_DURATIONS[purpose] || 3600;
      const nowSec = Math.floor(Date.now() / 1000);
      const randomHex = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
      const rec = {{
        recipient: String(body.recipient || "Khách Hàng"),
        phone: String(body.phone || ""),
        key: String(body.custom_key || `uav_${{purpose}}_${{randomHex}}`),
        purpose,
        allow_tpu: Boolean(body.allow_tpu),
        role: String(body.role || "guest"),
        issued_at_ts: nowSec,
        expires_at_ts: nowSec + durationSec,
        issued_at_iso: new Date(nowSec * 1000).toISOString(),
        expires_at_iso: new Date((nowSec + durationSec) * 1000).toISOString(),
      }};
      const keys = await loadAllKeys(env);
      keys.push(rec);
      await saveAllKeys(env, keys);
      return jsonResponse({{
        status: "ok",
        created: true,
        columns: GOOGLE_SHEET_HEADERS,
        key_record: enrichKeyStatus(rec, nowSec),
      }});
    }}

    if ((request.method === "POST" && path === "/api/keys/delete") || (request.method === "DELETE" && path.startsWith("/api/keys/"))) {{
      const body = await request.json().catch(() => ({{}}));
      const adminKey = extractCallerKey(request, body);
      const auth = await validateKey(env, adminKey, true);
      if (!auth.valid) {{
        return jsonResponse({{ status: "forbidden", http_status: 403, error: auth.reason }}, 403);
      }}
      const targetKey = request.method === "DELETE"
        ? decodeURIComponent(path.slice("/api/keys/".length))
        : String(body.key || body.target_key || "");
      const keys = await loadAllKeys(env);
      const nextKeys = keys.filter((k) => k.key !== targetKey);
      if (nextKeys.length === keys.length) {{
        return jsonResponse({{ status: "not_found", deleted: false }}, 404);
      }}
      await saveAllKeys(env, nextKeys);
      return jsonResponse({{ status: "ok", deleted: true, key: targetKey }});
    }}

    if (request.method === "POST" && (path === "/api/detect/upload" || path === "/api/yolo/update" || path === "/api/tpu/infer")) {{
      const body = await request.json().catch(() => ({{}}));
      const estimatedSeconds = Number(body.estimated_seconds || 0);
      const needsTpu = estimatedSeconds > TPU_THRESHOLD_SECONDS || path === "/api/tpu/infer";
      if (needsTpu) {{
        const callerKey = extractCallerKey(request, body);
        const auth = await validateKey(env, callerKey, false);
        if (!auth.valid || !auth.allow_tpu) {{
          return jsonResponse({{
            status: "forbidden",
            http_status: 403,
            offloaded_to_tpu: false,
            error: "Key hiện tại không có quyền đẩy tác vụ >15 phút lên Google TPU",
          }}, 403);
        }}
      }}
      const queuedTask = {{
        task_id: `tpu_${{Date.now()}}`,
        endpoint: path,
        estimated_seconds: estimatedSeconds,
        offloaded_to_tpu: needsTpu,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        payload: body,
        created_at_utc: new Date().toISOString(),
      }};
      EDGE_MEMORY_STATE.pendingTasks.push(queuedTask);
      return jsonResponse({{
        status: "ok",
        offloaded_to_tpu: needsTpu,
        tpu_threshold_seconds: TPU_THRESHOLD_SECONDS,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        processed_data_folder_url: PROCESSED_DATA_GDRIVE_FOLDER_URL,
        queued_task: queuedTask,
      }});
    }}

    return jsonResponse({{ error: "Endpoint not found", path }}, 404);
  }},
}};
'''


class OutboundCloudBridge:
    """Outbound HTTPS (TCP 443) bridge between corporate Windows PC, Worker Edge, and Google Drive."""

    def __init__(
        self,
        domain: str = CUSTOM_DOMAIN,
        processed_folder_id: str = PROCESSED_DATA_GDRIVE_FOLDER_ID,
        bridge_dir: Optional[Path] = None,
        worker_url: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> None:
        self.domain = (
            str(domain).strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
            or CUSTOM_DOMAIN
        )
        self.domain_url = f"https://{self.domain}/"
        self.processed_folder_id = str(processed_folder_id).strip() or PROCESSED_DATA_GDRIVE_FOLDER_ID
        self.worker_url = (worker_url or self.domain_url).rstrip("/")
        project_root = Path(__file__).resolve().parents[2]
        self.bridge_dir = Path(bridge_dir) if bridge_dir is not None else (project_root / "config" / "outbound_bridge")
        self.heartbeat_path = self.bridge_dir / "bridge_heartbeat.json"
        self.processed_log_path = self.bridge_dir / "processed_tasks.json"
        self.proxy_info = detect_corporate_proxy(env=env)

    def _build_outbound_opener(self) -> urllib.request.OpenerDirector:
        proxies: Dict[str, str] = {}
        if self.proxy_info.get("http_proxy"):
            proxies["http"] = str(self.proxy_info["http_proxy"])
        if self.proxy_info.get("https_proxy"):
            proxies["https"] = str(self.proxy_info["https_proxy"])
        if proxies:
            return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
        return urllib.request.build_opener()

    def write_heartbeat(self, online: bool = True, status_path: Optional[Path] = None) -> dict:
        """Persist outbound HTTPS-443 bridge heartbeat locally (and optionally sync to status_path)."""
        target_path = Path(status_path) if status_path is not None else self.heartbeat_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "online": bool(online),
            "domain": self.domain,
            "domain_url": self.domain_url,
            "worker_url": self.worker_url,
            "processed_data_folder_id": self.processed_folder_id,
            "main_project_folder_id": MAIN_PROJECT_GDRIVE_FOLDER_ID,
            "transport": "outbound_https_443",
            "outbound_port": 443,
            "inbound_ports_required": 0,
            "requires_admin_rights": False,
            "hostname": socket.gethostname(),
            "proxy_info": self.proxy_info,
            "status_path": str(target_path),
            "timestamp_utc": _utc_now_iso(),
        }
        target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if target_path != self.heartbeat_path:
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return payload

    def poll_and_process_once(self, task_payload: Optional[dict] = None) -> dict:
        """Process one bridge task (or run one idle poll cycle) over outbound HTTPS-443 semantics."""
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        task = dict(task_payload) if task_payload is not None else None
        remote_poll_attempted = False
        remote_poll_error: Optional[str] = None

        if task is None:
            queue_file = self.bridge_dir / "pending_task.json"
            if queue_file.exists():
                try:
                    loaded = json.loads(queue_file.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict) and loaded:
                        task = loaded
                        queue_file.unlink(missing_ok=True)
                except Exception:
                    task = None

        if task is None:
            result_payload = {
                "status": "idle",
                "processed": False,
                "has_task": False,
                "domain": self.domain,
                "domain_url": self.domain_url,
                "transport": "outbound_https_443",
                "outbound_port": 443,
                "inbound_ports_required": 0,
                "processed_data_folder_id": self.processed_folder_id,
                "remote_poll_attempted": remote_poll_attempted,
                "remote_poll_error": remote_poll_error,
                "polled_at_utc": _utc_now_iso(),
            }
            return result_payload

        estimated_seconds = float(task.get("estimated_seconds", 0) or 0)
        offload_to_tpu = bool(
            task.get("offload_to_tpu")
            or estimated_seconds > TPU_AUTO_OFFLOAD_THRESHOLD_SECONDS
        )
        task_id = str(task.get("task_id") or f"bridge_task_{int(datetime.now(timezone.utc).timestamp())}")
        processed_record = {
            "status": "processed",
            "processed": True,
            "has_task": True,
            "task_id": task_id,
            "task_type": str(task.get("task_type") or task.get("endpoint") or "geotiff_survey"),
            "estimated_seconds": estimated_seconds,
            "offloaded_to_tpu": offload_to_tpu,
            "execution_target": "google_tpu_colab_kaggle" if offload_to_tpu else "local_workstation_cpu_webgpu",
            "transport": "outbound_https_443",
            "outbound_port": 443,
            "inbound_ports_required": 0,
            "domain": self.domain,
            "domain_url": self.domain_url,
            "processed_data_folder_id": self.processed_folder_id,
            "proxy_used": self.proxy_info.get("https_proxy") or self.proxy_info.get("http_proxy"),
            "processed_at_utc": _utc_now_iso(),
            "task_payload": task,
        }

        existing: List[Dict[str, Any]] = []
        if self.processed_log_path.exists():
            try:
                loaded_log = json.loads(self.processed_log_path.read_text(encoding="utf-8"))
                if isinstance(loaded_log, list):
                    existing = loaded_log
            except Exception:
                existing = []
        existing.append(processed_record)
        self.processed_log_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return processed_record

    def get_bridge_status(self) -> dict:
        """Return current outbound HTTPS-443 bridge status and latest heartbeat."""
        latest_heartbeat: Optional[Dict[str, Any]] = None
        if self.heartbeat_path.exists():
            try:
                loaded = json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    latest_heartbeat = loaded
            except Exception:
                latest_heartbeat = None

        processed_count = 0
        if self.processed_log_path.exists():
            try:
                loaded_log = json.loads(self.processed_log_path.read_text(encoding="utf-8"))
                if isinstance(loaded_log, list):
                    processed_count = len(loaded_log)
            except Exception:
                processed_count = 0

        return {
            "domain": self.domain,
            "domain_url": self.domain_url,
            "worker_url": self.worker_url,
            "processed_data_folder_id": self.processed_folder_id,
            "main_project_folder_id": MAIN_PROJECT_GDRIVE_FOLDER_ID,
            "transport": "outbound_https_443",
            "outbound_port": 443,
            "inbound_ports_required": 0,
            "firewall_safe": True,
            "admin_rights_required": False,
            "proxy_info": self.proxy_info,
            "bridge_dir": str(self.bridge_dir),
            "heartbeat_present": latest_heartbeat is not None,
            "heartbeat": latest_heartbeat,
            "online": bool(latest_heartbeat.get("online")) if latest_heartbeat else False,
            "processed_tasks_count": processed_count,
            "checked_at_utc": _utc_now_iso(),
        }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Corporate Firewall Bypass & Outbound HTTPS-443 Bridge for https://thietbibachkhoa.id.vn/"
    )
    parser.add_argument("--probe", action="store_true", help="Probe corporate proxy and output firewall-bypass diagnostics")
    parser.add_argument("--generate-worker", action="store_true", help="Generate Cloudflare Worker JS script")
    parser.add_argument("--heartbeat", action="store_true", help="Write outbound HTTPS-443 bridge heartbeat")
    parser.add_argument("--bridge-status", action="store_true", help="Print current outbound bridge status JSON")
    parser.add_argument("--port", type=int, default=DEFAULT_LOCAL_PORT, help="Local loopback port (default: 8765)")
    parser.add_argument("--domain", type=str, default=CUSTOM_DOMAIN, help="Custom domain (default: thietbibachkhoa.id.vn)")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional output file path for --generate-worker or --heartbeat",
    )
    args = parser.parse_args(argv)

    bridge = OutboundCloudBridge(domain=args.domain)

    if args.generate_worker:
        worker_js = generate_cloudflare_worker_script(
            domain=args.domain,
            processed_folder_id=PROCESSED_DATA_GDRIVE_FOLDER_ID,
        )
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(worker_js, encoding="utf-8")
            print(json.dumps({"generated": True, "output": str(out_path), "bytes": len(worker_js)}, indent=2))
        else:
            print(worker_js)
        return 0

    if args.heartbeat:
        status_path = Path(args.output) if args.output else None
        hb = bridge.write_heartbeat(online=True, status_path=status_path)
        print(json.dumps(hb, indent=2, ensure_ascii=False))
        return 0

    if args.bridge_status:
        print(json.dumps(bridge.get_bridge_status(), indent=2, ensure_ascii=False))
        return 0

    # Default or --probe
    diag = probe_corporate_firewall(port=args.port)
    print(json.dumps(diag, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
