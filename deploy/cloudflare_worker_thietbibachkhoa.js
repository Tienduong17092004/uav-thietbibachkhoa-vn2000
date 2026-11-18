/**
 * Cloudflare Worker Edge Portal & Outbound HTTPS-443 Bridge
 * Domain: https://thietbibachkhoa.id.vn/
 * Google Drive Processed Data Folder: 1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN
 * Main Project Google Drive Folder: 1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV
 *
 * Zero inbound ports, zero UDP 7844, zero TCP 7844, zero Windows Admin rights required
 * on the corporate workstation. Company PC communicates solely via outbound HTTPS:443.
 */

const CUSTOM_DOMAIN = "thietbibachkhoa.id.vn";
const CUSTOM_DOMAIN_URL = "https://thietbibachkhoa.id.vn/";
const PROCESSED_DATA_GDRIVE_FOLDER_ID = "1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN";
const PROCESSED_DATA_GDRIVE_FOLDER_URL =
  "https://drive.google.com/drive/u/3/folders/1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN";
const MAIN_PROJECT_GDRIVE_FOLDER_ID = "1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV";
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

const PURPOSE_DURATIONS = {
  "1h": 3600,
  "3h": 10800,
  "5h": 18000,
  "1m": 2592000,
  "3m": 7776000,
  "6m": 15552000,
  "1y": 31536000,
};

// Ephemeral edge isolate store (persists across requests when bound to env.UAV_BRIDGE_KV)
const EDGE_MEMORY_STATE = {
  keys: new Map(),
  bridgeHeartbeat: {
    online: false,
    transport: "outbound_https_443",
    processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
    last_seen_utc: null,
  },
  pendingTasks: [],
};

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
      "access-control-allow-headers": "Content-Type, Authorization, X-Admin-Key, X-UAV-Key",
      "x-uav-edge-worker": CUSTOM_DOMAIN,
    },
  });
}

function htmlResponse(html, status = 200) {
  return new Response(html, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-uav-edge-worker": CUSTOM_DOMAIN,
    },
  });
}

function extractCallerKey(request, body = {}) {
  const hdrKey =
    request.headers.get("x-admin-key") ||
    request.headers.get("x-uav-key") ||
    "";
  if (hdrKey.trim()) return hdrKey.trim();
  const auth = request.headers.get("authorization") || "";
  if (auth.toLowerCase().startsWith("bearer ")) {
    return auth.slice(7).trim();
  }
  const url = new URL(request.url);
  const qKey = url.searchParams.get("key") || url.searchParams.get("admin_key") || "";
  if (qKey.trim()) return qKey.trim();
  if (body && typeof body === "object") {
    return String(body.admin_key || body.key || body.access_key || "").trim();
  }
  return "";
}

async function loadAllKeys(env) {
  if (env && env.UAV_BRIDGE_KV) {
    const raw = await env.UAV_BRIDGE_KV.get("uav_keys_v1");
    if (raw) {
      try {
        return JSON.parse(raw);
      } catch (_err) {
        return [];
      }
    }
  }
  return Array.from(EDGE_MEMORY_STATE.keys.values());
}

async function saveAllKeys(env, list) {
  EDGE_MEMORY_STATE.keys.clear();
  for (const item of list) {
    EDGE_MEMORY_STATE.keys.set(item.key, item);
  }
  if (env && env.UAV_BRIDGE_KV) {
    await env.UAV_BRIDGE_KV.put("uav_keys_v1", JSON.stringify(list));
  }
}

function enrichKeyStatus(record, nowSec = Math.floor(Date.now() / 1000)) {
  const total = Math.max(1, Number(record.expires_at_ts) - Number(record.issued_at_ts));
  const remaining = Math.max(0, Number(record.expires_at_ts) - nowSec);
  const ratio = remaining / total;
  const isRed = remaining <= 0 || ratio <= 1 / 3;
  return {
    ...record,
    remaining_seconds: remaining,
    remaining_ratio: Number(ratio.toFixed(4)),
    status_color: isRed ? "red" : "green",
    is_warning_red: isRed,
    status_label: remaining <= 0 ? "Hết hạn (Đỏ)" : isRed ? "Sắp hết hạn <= 1/3 (Đỏ)" : "Còn hạn > 1/3 (Xanh)",
  };
}

async function validateKey(env, callerKey, requireAdmin = false) {
  const adminMaster = (env && env.UAV_ADMIN_KEY) || DEFAULT_ADMIN_KEY;
  if (!callerKey) {
    return {
      valid: false,
      http_status: 403,
      role: "guest",
      is_admin: false,
      allow_tpu: false,
      reason: "Thiếu Key xác thực",
    };
  }
  if (callerKey === adminMaster) {
    return {
      valid: true,
      http_status: 200,
      role: "admin",
      is_admin: true,
      allow_tpu: true,
      key_record: { key: callerKey, role: "admin", allow_tpu: true },
      reason: "Admin key verified",
    };
  }
  if (requireAdmin) {
    return {
      valid: false,
      http_status: 403,
      role: "guest",
      is_admin: false,
      allow_tpu: false,
      reason: "Chỉ Key quyền Admin mới được phép truy cập bảng quản lý 7 cột",
    };
  }
  const all = await loadAllKeys(env);
  const found = all.find((k) => k.key === callerKey);
  if (!found) {
    return {
      valid: false,
      http_status: 403,
      role: "guest",
      is_admin: false,
      allow_tpu: false,
      reason: "Key không tồn tại hoặc đã bị thu hồi",
    };
  }
  const enriched = enrichKeyStatus(found);
  if (enriched.remaining_seconds <= 0) {
    return {
      valid: false,
      http_status: 403,
      role: found.role || "guest",
      is_admin: false,
      allow_tpu: false,
      key_record: enriched,
      reason: "Key đã hết hạn sử dụng",
    };
  }
  const isAdmin = found.role === "admin";
  return {
    valid: true,
    http_status: 200,
    role: found.role || "guest",
    is_admin: isAdmin,
    allow_tpu: isAdmin || Boolean(found.allow_tpu),
    key_record: enriched,
    reason: "Key verified",
  };
}

function renderPortalHtml() {
  return [
    "<!doctype html>",
    '<html lang="vi">',
    "<head>",
    '  <meta charset="utf-8" />',
    '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
    "  <title>UAV GeoTIFF WebGPU Survey VN2000 — https://" + CUSTOM_DOMAIN + "/</title>",
    "  <style>",
    '    * { box-sizing: border-box; }',
    '    body { font-family: "Inter", "Segoe UI", system-ui, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }',
    "    .container { max-width: 1200px; margin: 0 auto; }",
    "    .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 18px 22px; margin-bottom: 16px; }",
    "    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 16px; margin-bottom: 16px; }",
    "    .badge { display: inline-block; background: #059669; color: #fff; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 700; }",
    "    code { background: #0f172a; color: #38bdf8; padding: 2px 6px; border-radius: 4px; }",
    "    input, select, button { padding: 8px 12px; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #f8fafc; font-size: 13.5px; }",
    "    button { background: #2563eb; border-color: #3b82f6; cursor: pointer; font-weight: 600; }",
    "    button:hover { background: #1d4ed8; }",
    "    button.danger { background: #dc2626; border-color: #ef4444; padding: 5px 10px; font-size: 12px; }",
    "    button.secondary { background: #334155; border-color: #475569; }",
    "    table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }",
    "    th, td { border: 1px solid #334155; padding: 8px 10px; text-align: left; }",
    "    th { background: #0f172a; color: #38bdf8; }",
    "    .status-green { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981; padding: 3px 8px; border-radius: 999px; font-weight: 700; display: inline-block; }",
    "    .status-red { background: rgba(239, 68, 68, 0.25); color: #fca5a5; border: 1px solid #ef4444; padding: 3px 8px; border-radius: 999px; font-weight: 700; display: inline-block; }",
    "    .result-box { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px; margin-top: 12px; font-size: 13px; line-height: 1.5; }",
    "  </style>",
    "</head>",
    "<body>",
    '  <div class="container">',
    '    <div class="card">',
    '      <span class="badge">ONLINE 24/7 · CLOUDFLARE EDGE · https://' + CUSTOM_DOMAIN + '/</span>',
    "      <h1>UAV GeoTIFF Studio &amp; Cổng WebGPU Khảo Sát Địa Hình 6 Lớp (Chuẩn VN2000)</h1>",
    "      <p>Vận hành độc lập 24/7 trên đám mây Cloudflare (Vượt 100% tường lửa công ty · Tự động đẩy tác vụ &gt; 15 phút lên Google TPU).</p>",
    '      <p>Thư mục Google Drive lưu Data xử lý: <a style="color:#38bdf8" target="_blank" href="' + PROCESSED_DATA_GDRIVE_FOLDER_URL + '"><code>' + PROCESSED_DATA_GDRIVE_FOLDER_ID + "</code></a></p>",
    "    </div>",
    "",
    '    <div class="card">',
    "      <h2>🔐 1. Đăng Nhập Key Truy Cập (Admin / Khách Hàng)</h2>",
    "      <p>Nhập <strong>Key Admin</strong> (<code>uav_admin_master_key_vn2000</code>) để mở bảng Quản lý Key Google Sheet 7 cột. Nếu đăng nhập bằng <strong>Key Khách</strong>, bảng quản lý Key sẽ tự động ẩn hoàn toàn.</p>",
    '      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">',
    '        <input id="key-input" type="text" value="uav_admin_master_key_vn2000" placeholder="Nhập Key truy cập..." style="min-width:280px;" />',
    '        <button onclick="verifyLogin()">Đăng Nhập Key</button>',
    '        <button class="secondary" onclick="quickKey(\'uav_admin_master_key_vn2000\')">Dùng Key Admin</button>',
    '        <span id="login-msg" style="font-weight:700; color:#34d399;"></span>',
    "      </div>",
    "    </div>",
    "",
    '    <div class="card" id="admin-panel" style="display:none;">',
    "      <h2>📊 2. Quản Lý Key Google Sheet 7 Cột (Chỉ Key Quyền Admin Mới Xem &amp; Thao Tác Được)</h2>",
    '      <p>Trạng thái thời hạn: <span class="status-green">🟢 Bình thường (Còn &gt; 1/3 thời gian)</span> · <span class="status-red">🔴 Báo đỏ (Còn &le; 1/3 thời gian)</span></p>',
    '      <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px;">',
    '        <input id="rec-name" placeholder="1. Người nhận (VD: Kỹ sư Minh)" />',
    '        <input id="rec-phone" placeholder="2. SĐT người nhận (VD: 0912345678)" />',
    '        <select id="rec-purpose">',
    '          <option value="1h">Test thử 1 giờ (1h)</option>',
    '          <option value="3h">Test thử 3 giờ (3h)</option>',
    '          <option value="5h">Test thử 5 giờ (5h)</option>',
    '          <option value="1m">Mua 1 tháng (1m)</option>',
    '          <option value="3m">Mua 3 tháng (3m)</option>',
    '          <option value="6m">Mua 6 tháng (6m)</option>',
    '          <option value="1y">Mua 1 năm (1y)</option>',
    "        </select>",
    '        <label style="display:flex; align-items:center; gap:6px;"><input type="checkbox" id="rec-tpu" checked /> Cho phép đẩy TPU (&gt;15p)</label>',
    '        <button onclick="createKey()">+ Tạo Key Mới</button>',
    "      </div>",
    "      <table>",
    "        <thead>",
    "          <tr>",
    "            <th>1. Người nhận</th><th>2. SĐT người nhận</th><th>3. Key</th><th>4. Mục đích (TPU)</th>",
    "            <th>5. Thời gian cấp</th><th>6. Thời gian hết hạn</th><th>7. Tình trạng</th><th>Thao tác</th>",
    "          </tr>",
    "        </thead>",
    '        <tbody id="keys-body"></tbody>',
    "      </table>",
    "    </div>",
    "",
    '    <div class="grid">',
    '      <div class="card">',
    "        <h2>🖼️ 3. Upload Ảnh Nhận Diện (Tự Động Đẩy TPU Nếu &gt; 15 Phút)</h2>",
    '        <div style="display:flex; flex-direction:column; gap:10px;">',
    '          <label>Số lượng ảnh GeoTIFF / Orthomosaic: <input type="number" id="detect-images" value="45" min="1" style="width:90px;" /></label>',
    '          <label>Số lượng ô lưới (Tiles 512x512): <input type="number" id="detect-tiles" value="650" min="1" style="width:90px;" /></label>',
    '          <button onclick="runTpuTask(\'/api/detect/upload\')">Chạy Nhận Diện &amp; Kiểm Tra Tự Động Đẩy TPU</button>',
    '          <div id="detect-res" class="result-box">Nhấn nút để tự động tính thời gian xử lý và kiểm tra quyền đẩy TPU (&gt; 15 phút).</div>',
    "        </div>",
    "      </div>",
    '      <div class="card">',
    "        <h2>🧠 4. Update Mô Hình YOLO Vật Thể Mới (Tự Động Đẩy TPU Nếu &gt; 15 Phút)</h2>",
    '        <div style="display:flex; flex-direction:column; gap:10px;">',
    '          <label>Vật thể mới (Classes): <input type="text" id="yolo-classes" value="culvert_gate, electric_pole, bridge_vn2000" style="width:100%; margin-top:4px;" /></label>',
    '          <div style="display:flex; gap:10px;">',
    '            <label>Epochs: <input type="number" id="yolo-epochs" value="40" min="1" style="width:80px;" /></label>',
    '            <label>Dataset: <input type="number" id="yolo-dataset" value="500" min="10" style="width:90px;" /></label>',
    "          </div>",
    '          <button onclick="runTpuTask(\'/api/yolo/update\')">Update Mô Hình YOLO &amp; Kiểm Tra Đẩy TPU</button>',
    '          <div id="yolo-res" class="result-box">Nhấn nút để tính thời gian huấn luyện YOLO và kiểm tra quyền đẩy TPU (&gt; 15 phút).</div>',
    "        </div>",
    "      </div>",
    "    </div>",
    "  </div>",
    "",
    "  <script>",
    '    let activeKey = "";',
    "    function quickKey(k) {",
    '      document.getElementById("key-input").value = k;',
    "      verifyLogin();",
    "    }",
    "    async function verifyLogin() {",
    '      const k = document.getElementById("key-input").value.trim();',
    '      const res = await fetch("/api/auth/verify-key", {',
    '        method: "POST",',
    '        headers: { "Content-Type": "application/json" },',
    "        body: JSON.stringify({ key: k }),",
    "      });",
    "      const data = await res.json();",
    '      const panel = document.getElementById("admin-panel");',
    '      const msg = document.getElementById("login-msg");',
    "      if (data.valid && data.is_admin) {",
    "        activeKey = k;",
    '        panel.style.display = "block";',
    '        msg.style.color = "#34d399";',
    '        msg.textContent = "✅ Đang đăng nhập: QUYỀN ADMIN (Toàn quyền Quản lý Key 7 cột & TPU >15p)";',
    "        await refreshKeys();",
    "      } else {",
    '        activeKey = data.valid ? k : "";',
    '        panel.style.display = "none";',
    '        msg.style.color = data.valid ? "#38bdf8" : "#f87171";',
    '        msg.textContent = data.valid ? ("👤 Đang đăng nhập: KEY KHÁCH (" + (data.allow_tpu ? "Có quyền TPU >15p" : "Không có quyền TPU >15p") + ") · Đã ẩn bảng quản lý Key") : ("❌ " + (data.reason || "Key không hợp lệ"));',
    "      }",
    "    }",
    "    async function refreshKeys() {",
    '      const res = await fetch("/api/keys", { headers: { "X-Admin-Key": activeKey } });',
    "      if (!res.ok) return;",
    "      const data = await res.json();",
    '      const tbody = document.getElementById("keys-body");',
    '      tbody.innerHTML = (data.keys || []).map(function(r) {',
    '        const cls = r.is_warning_red ? "status-red" : "status-green";',
    '        const tpuTag = r.allow_tpu ? " [TPU: BẬT]" : " [TPU: TẮT]";',
    "        return '<tr>' +",
    "          '<td>' + r.recipient + '</td>' +",
    "          '<td>' + r.phone + '</td>' +",
    "          '<td><code>' + r.key + '</code></td>' +",
    "          '<td>' + r.purpose + tpuTag + '</td>' +",
    "          '<td>' + r.issued_at_iso + '</td>' +",
    "          '<td>' + r.expires_at_iso + '</td>' +",
    "          '<td><span class=\"' + cls + '\">' + r.status_label + '</span></td>' +",
    "          '<td><button class=\"danger\" onclick=\"deleteKey(\\'' + r.key + '\\')\">Xóa</button></td>' +",
    "          '</tr>';",
    '      }).join("");',
    "    }",
    "    async function createKey() {",
    '      const res = await fetch("/api/keys/create", {',
    '        method: "POST",',
    '        headers: { "Content-Type": "application/json", "X-Admin-Key": activeKey },',
    "        body: JSON.stringify({",
    '          recipient: document.getElementById("rec-name").value || "Khách hàng mới",',
    '          phone: document.getElementById("rec-phone").value || "0912345678",',
    '          purpose: document.getElementById("rec-purpose").value,',
    '          allow_tpu: document.getElementById("rec-tpu").checked,',
    "        }),",
    "      });",
    "      if (res.ok) {",
    "        await refreshKeys();",
    "      }",
    "    }",
    "    async function deleteKey(key) {",
    '      await fetch("/api/keys/delete", {',
    '        method: "POST",',
    '        headers: { "Content-Type": "application/json", "X-Admin-Key": activeKey },',
    "        body: JSON.stringify({ key: key }),",
    "      });",
    "      await refreshKeys();",
    "    }",
    "    async function runTpuTask(endpoint) {",
    "      let estSec = 0;",
    "      let box = null;",
    '      if (endpoint === "/api/detect/upload") {',
    '        const imgs = parseInt(document.getElementById("detect-images").value || "1", 10);',
    '        const tiles = parseInt(document.getElementById("detect-tiles").value || "1", 10);',
    "        estSec = Math.round(imgs * 12 + tiles * 1.45);",
    '        box = document.getElementById("detect-res");',
    "      } else {",
    '        const epochs = parseInt(document.getElementById("yolo-epochs").value || "1", 10);',
    '        const ds = parseInt(document.getElementById("yolo-dataset").value || "100", 10);',
    "        estSec = Math.round(epochs * 24 + ds * 0.85);",
    '        box = document.getElementById("yolo-res");',
    "      }",
    "      const res = await fetch(endpoint, {",
    '        method: "POST",',
    '        headers: { "Content-Type": "application/json", "X-UAV-Key": activeKey },',
    "        body: JSON.stringify({ estimated_seconds: estSec, key: activeKey }),",
    "      });",
    "      const data = await res.json();",
    "      const mins = (estSec / 60).toFixed(1);",
    "      if (res.status === 403) {",
    '        box.innerHTML = "⏱️ <strong>Thời gian ước tính:</strong> <code>" + mins + " phút (" + estSec + "s &gt; 15 phút)</code><br/>🚫 <span style=\\"color:#f87171;font-weight:700;\\">403 Forbidden: " + (data.error || "Key không có quyền dùng TPU >15p") + "</span>";',
    "      } else {",
    '        box.innerHTML = "⏱️ <strong>Thời gian ước tính:</strong> <code>" + mins + " phút (" + estSec + "s)</code><br/>🚀 <strong>Đẩy lên Google TPU:</strong> <span style=\\"color:#34d399;font-weight:700;\\">" + (data.offloaded_to_tpu ? "ĐÃ KÍCH HOẠT (>15 phút -> Google TPU)" : "Xử lý thông thường (<=15 phút)") + "</span><br/>📂 <strong>Folder Drive:</strong> <code>" + data.processed_data_folder_id + "</code>";',
    "      }",
    "    }",
    "    verifyLogin();",
    "  </script>",
    "</body>",
    "</html>",
  ].join("\n");
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return jsonResponse({ ok: true }, 204);
    }

    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "GET" && (path === "/" || path === "/webgpu.html" || path === "/MO_WEB_NHAN_DIEN_NGAY.html")) {
      return htmlResponse(renderPortalHtml());
    }

    if (request.method === "GET" && path === "/api/health") {
      return jsonResponse({
        status: "ok",
        online: true,
        mode: "cloudflare_worker_edge_firewall_bypass",
        domain: CUSTOM_DOMAIN,
        url: CUSTOM_DOMAIN_URL,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        inbound_ports_required_on_pc: 0,
      });
    }

    if (request.method === "GET" && path === "/api/domain-status") {
      return jsonResponse({
        domain: CUSTOM_DOMAIN,
        url: CUSTOM_DOMAIN_URL,
        hosting_mode: "cloudflare_worker_edge_outbound_443",
        firewall_bypass_active: true,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        processed_data_folder_url: PROCESSED_DATA_GDRIVE_FOLDER_URL,
        main_project_folder_id: MAIN_PROJECT_GDRIVE_FOLDER_ID,
      });
    }

    if (request.method === "GET" && path === "/api/gdrive/processed-folder") {
      return jsonResponse({
        folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        folder_url: PROCESSED_DATA_GDRIVE_FOLDER_URL,
        main_project_folder_id: MAIN_PROJECT_GDRIVE_FOLDER_ID,
        transport: "outbound_https_443",
      });
    }

    if (request.method === "GET" && path === "/api/bridge/status") {
      let hb = EDGE_MEMORY_STATE.bridgeHeartbeat;
      if (env && env.UAV_BRIDGE_KV) {
        const kvHb = await env.UAV_BRIDGE_KV.get("bridge_heartbeat");
        if (kvHb) hb = JSON.parse(kvHb);
      }
      return jsonResponse({
        domain: CUSTOM_DOMAIN,
        transport: "outbound_https_443",
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        heartbeat: hb,
        pending_tasks_count: EDGE_MEMORY_STATE.pendingTasks.length,
      });
    }

    if (request.method === "POST" && path === "/api/bridge/heartbeat") {
      const body = await request.json().catch(() => ({}));
      const hb = {
        online: body.online !== false,
        transport: "outbound_https_443",
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        last_seen_utc: new Date().toISOString(),
        host_info: body.host_info || "corporate_windows_workstation",
      };
      EDGE_MEMORY_STATE.bridgeHeartbeat = hb;
      if (env && env.UAV_BRIDGE_KV) {
        await env.UAV_BRIDGE_KV.put("bridge_heartbeat", JSON.stringify(hb));
      }
      return jsonResponse({ status: "ok", heartbeat: hb });
    }

    if (request.method === "POST" && path === "/api/bridge/poll") {
      const task = EDGE_MEMORY_STATE.pendingTasks.shift() || null;
      return jsonResponse({
        status: "ok",
        has_task: Boolean(task),
        task,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
      });
    }

    if (request.method === "GET" && (path === "/api/keys" || path === "/api/keys/sheet")) {
      const callerKey = extractCallerKey(request);
      const auth = await validateKey(env, callerKey, true);
      if (!auth.valid) {
        return jsonResponse({ status: "forbidden", http_status: 403, admin_panel_visible: false, error: auth.reason }, 403);
      }
      const keys = (await loadAllKeys(env)).map((k) => enrichKeyStatus(k));
      return jsonResponse({
        status: "ok",
        admin_panel_visible: true,
        column_count: GOOGLE_SHEET_HEADERS.length,
        columns: GOOGLE_SHEET_HEADERS,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        keys,
      });
    }

    if (request.method === "POST" && path === "/api/auth/verify-key") {
      const body = await request.json().catch(() => ({}));
      const callerKey = extractCallerKey(request, body);
      const auth = await validateKey(env, callerKey, false);
      return jsonResponse(
        {
          status: auth.valid ? "ok" : "forbidden",
          ...auth,
          admin_panel_visible: Boolean(auth.valid && auth.is_admin),
          processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        },
        auth.valid ? 200 : 403
      );
    }

    if (request.method === "POST" && (path === "/api/keys" || path === "/api/keys/create")) {
      const body = await request.json().catch(() => ({}));
      const adminKey = extractCallerKey(request, body);
      const auth = await validateKey(env, adminKey, true);
      if (!auth.valid) {
        return jsonResponse({ status: "forbidden", http_status: 403, error: auth.reason }, 403);
      }
      const purpose = String(body.purpose || "1h").trim();
      const durationSec = PURPOSE_DURATIONS[purpose] || 3600;
      const nowSec = Math.floor(Date.now() / 1000);
      const randomHex = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
      const rec = {
        recipient: String(body.recipient || "Khách Hàng"),
        phone: String(body.phone || ""),
        key: String(body.custom_key || `uav_${purpose}_${randomHex}`),
        purpose,
        allow_tpu: Boolean(body.allow_tpu),
        role: String(body.role || "guest"),
        issued_at_ts: nowSec,
        expires_at_ts: nowSec + durationSec,
        issued_at_iso: new Date(nowSec * 1000).toISOString(),
        expires_at_iso: new Date((nowSec + durationSec) * 1000).toISOString(),
      };
      const keys = await loadAllKeys(env);
      keys.push(rec);
      await saveAllKeys(env, keys);
      return jsonResponse({
        status: "ok",
        created: true,
        columns: GOOGLE_SHEET_HEADERS,
        key_record: enrichKeyStatus(rec, nowSec),
      });
    }

    if ((request.method === "POST" && path === "/api/keys/delete") || (request.method === "DELETE" && path.startsWith("/api/keys/"))) {
      const body = await request.json().catch(() => ({}));
      const adminKey = extractCallerKey(request, body);
      const auth = await validateKey(env, adminKey, true);
      if (!auth.valid) {
        return jsonResponse({ status: "forbidden", http_status: 403, error: auth.reason }, 403);
      }
      const targetKey = request.method === "DELETE"
        ? decodeURIComponent(path.slice("/api/keys/".length))
        : String(body.key || body.target_key || "");
      const keys = await loadAllKeys(env);
      const nextKeys = keys.filter((k) => k.key !== targetKey);
      if (nextKeys.length === keys.length) {
        return jsonResponse({ status: "not_found", deleted: false }, 404);
      }
      await saveAllKeys(env, nextKeys);
      return jsonResponse({ status: "ok", deleted: true, key: targetKey });
    }

    if (request.method === "POST" && (path === "/api/detect/upload" || path === "/api/yolo/update" || path === "/api/tpu/infer")) {
      const body = await request.json().catch(() => ({}));
      const estimatedSeconds = Number(body.estimated_seconds || 0);
      const needsTpu = estimatedSeconds > TPU_THRESHOLD_SECONDS || path === "/api/tpu/infer";
      if (needsTpu) {
        const callerKey = extractCallerKey(request, body);
        const auth = await validateKey(env, callerKey, false);
        if (!auth.valid || !auth.allow_tpu) {
          return jsonResponse({
            status: "forbidden",
            http_status: 403,
            offloaded_to_tpu: false,
            error: "Key hiện tại không có quyền đẩy tác vụ >15 phút lên Google TPU",
          }, 403);
        }
      }
      const queuedTask = {
        task_id: `tpu_${Date.now()}`,
        endpoint: path,
        estimated_seconds: estimatedSeconds,
        offloaded_to_tpu: needsTpu,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        payload: body,
        created_at_utc: new Date().toISOString(),
      };
      EDGE_MEMORY_STATE.pendingTasks.push(queuedTask);
      return jsonResponse({
        status: "ok",
        offloaded_to_tpu: needsTpu,
        tpu_threshold_seconds: TPU_THRESHOLD_SECONDS,
        processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
        processed_data_folder_url: PROCESSED_DATA_GDRIVE_FOLDER_URL,
        queued_task: queuedTask,
      });
    }

    return jsonResponse({ error: "Endpoint not found", path }, 404);
  },
};
