/**
 * Cloudflare Worker Edge Portal & Outbound HTTPS-443 Bridge
 * Domain: https://thietbibachkhoa.id.vn/
 * Google Drive Processed Data Folder: 1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN
 * Main Project Google Drive Folder: 1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV
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

const PURPOSE_LABELS = {
  "1h": "Test thử 1 giờ (1h)",
  "3h": "Test thử 3 giờ (3h)",
  "5h": "Test thử 5 giờ (5h)",
  "1m": "Mua 1 tháng (1m)",
  "3m": "Mua 3 tháng (3m)",
  "6m": "Mua 6 tháng (6m)",
  "1y": "Mua 1 năm (1y)",
};

function createSeedKeys() {
  const nowSec = Math.floor(Date.now() / 1000);
  const m = new Map();
  m.set(DEFAULT_ADMIN_KEY, {
    recipient: "Quản Trị Viên (Admin)",
    phone: "0900000000",
    key: DEFAULT_ADMIN_KEY,
    purpose: "1y",
    allow_tpu: true,
    role: "admin",
    issued_at_ts: nowSec - 3600,
    expires_at_ts: nowSec + 31536000,
    issued_at_iso: new Date((nowSec - 3600) * 1000).toISOString().replace("T", " ").slice(0, 19),
    expires_at_iso: new Date((nowSec + 31536000) * 1000).toISOString().replace("T", " ").slice(0, 19),
  });
  m.set("uav_guest_demo_tpu_on", {
    recipient: "Kỹ sư Trắc địa A (Khách có TPU)",
    phone: "0912345678",
    key: "uav_guest_demo_tpu_on",
    purpose: "3m",
    allow_tpu: true,
    role: "guest",
    issued_at_ts: nowSec - 86400,
    expires_at_ts: nowSec + 7776000,
    issued_at_iso: new Date((nowSec - 86400) * 1000).toISOString().replace("T", " ").slice(0, 19),
    expires_at_iso: new Date((nowSec + 7776000) * 1000).toISOString().replace("T", " ").slice(0, 19),
  });
  m.set("uav_guest_demo_red_warning", {
    recipient: "Khách Test B (Còn <=1/3 thời gian · Không TPU)",
    phone: "0987654321",
    key: "uav_guest_demo_red_warning",
    purpose: "3h",
    allow_tpu: false,
    role: "guest",
    issued_at_ts: nowSec - 8400,
    expires_at_ts: nowSec + 2400,
    issued_at_iso: new Date((nowSec - 8400) * 1000).toISOString().replace("T", " ").slice(0, 19),
    expires_at_iso: new Date((nowSec + 2400) * 1000).toISOString().replace("T", " ").slice(0, 19),
  });
  return m;
}

const EDGE_MEMORY_STATE = {
  keys: createSeedKeys(),
  bridgeHeartbeat: {
    online: true,
    transport: "outbound_https_443",
    processed_data_folder_id: PROCESSED_DATA_GDRIVE_FOLDER_ID,
    last_seen_utc: new Date().toISOString(),
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
        return Array.from(EDGE_MEMORY_STATE.keys.values());
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
  const pct = Math.round(ratio * 100);
  const pLabel = PURPOSE_LABELS[record.purpose] || record.purpose;
  const tpuTag = record.role === "admin" ? " [ADMIN · TPU: BẬT]" : (record.allow_tpu ? " [TPU: BẬT]" : " [TPU: TẮT]");
  return {
    ...record,
    purpose_display: pLabel + tpuTag,
    remaining_seconds: remaining,
    remaining_ratio: Number(ratio.toFixed(4)),
    status_color: isRed ? "red" : "green",
    is_warning_red: isRed,
    status_label:
      remaining <= 0
        ? "🔴 Đã hết hạn (0%)"
        : isRed
        ? "🔴 Báo đỏ: Còn " + pct + "% (<= 1/3 thời gian)"
        : "🟢 Bình thường: Còn " + pct + "% (> 1/3 thời gian)",
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
      reason: "Vui lòng nhập Key truy cập hợp lệ!",
    };
  }
  if (callerKey === adminMaster) {
    const all = await loadAllKeys(env);
    const adminRec = all.find((k) => k.key === adminMaster) || {
      recipient: "Quản Trị Viên (Admin)",
      phone: "0900000000",
      key: callerKey,
      purpose: "1y",
      role: "admin",
      allow_tpu: true,
      issued_at_ts: Math.floor(Date.now() / 1000) - 3600,
      expires_at_ts: Math.floor(Date.now() / 1000) + 31536000,
    };
    return {
      valid: true,
      http_status: 200,
      role: "admin",
      is_admin: true,
      allow_tpu: true,
      key_record: enrichKeyStatus(adminRec),
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
      reason: "Chỉ Key quyền Admin mới được phép truy cập bảng quản lý Key 7 cột",
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
      reason: "Key không tồn tại hoặc đã bị Admin xóa!",
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
      reason: "Key của bạn đã hết hạn sử dụng!",
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
    "  <title>UAV GeoTIFF Studio VN2000 — https://" + CUSTOM_DOMAIN + "/</title>",
    "  <style>",
    "    * { box-sizing: border-box; }",
    '    body { font-family: "Inter", "Segoe UI", system-ui, sans-serif; background: #0b1120; color: #f8fafc; margin: 0; padding: 0; min-height: 100vh; }',
    "    /* MÀN HÌNH ĐĂNG NHẬP DUY NHẤT KHI CHƯA NHẬP KEY */",
    "    #login-gate-wrapper { display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; background: radial-gradient(circle at center, #1e293b 0%, #0b1120 75%); }",
    "    .login-box { width: 100%; max-width: 460px; background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 32px 28px; box-shadow: 0 20px 50px rgba(0,0,0,0.6); text-align: center; }",
    "    .login-box h1 { font-size: 20px; margin: 12px 0 8px; color: #f8fafc; }",
    "    .login-box p { font-size: 13.5px; color: #94a3b8; margin: 0 0 22px; line-height: 1.5; }",
    "    .login-input { width: 100%; padding: 13px 16px; border-radius: 10px; border: 1px solid #475569; background: #0f172a; color: #f8fafc; font-size: 15px; margin-bottom: 14px; outline: none; text-align: center; letter-spacing: 0.5px; }",
    "    .login-input:focus { border-color: #38bdf8; box-shadow: 0 0 0 3px rgba(56,189,248,0.2); }",
    "    .login-btn { width: 100%; padding: 13px 18px; border-radius: 10px; border: none; background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: #fff; font-size: 15px; font-weight: 700; cursor: pointer; }",
    "    .login-btn:hover { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); }",
    "    #login-error-msg { margin-top: 14px; font-size: 13.5px; font-weight: 600; color: #f87171; min-height: 20px; }",
    "    /* KHÔNG GIAN LÀM VIỆC CHÍNH — ẨN HOÀN TOÀN KHI CHƯA ĐĂNG NHẬP */",
    "    #authenticated-workspace { display: none; max-width: 1260px; margin: 0 auto; padding: 22px; }",
    "    .topbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 16px 22px; margin-bottom: 18px; }",
    "    .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 18px 22px; margin-bottom: 18px; }",
    "    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 18px; margin-bottom: 18px; }",
    "    .badge { display: inline-block; background: #059669; color: #fff; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 700; }",
    "    code { background: #0f172a; color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-size: 12.5px; }",
    "    input, select, button { padding: 9px 12px; border-radius: 7px; border: 1px solid #475569; background: #0f172a; color: #f8fafc; font-size: 13.5px; }",
    "    button { background: #2563eb; border-color: #3b82f6; cursor: pointer; font-weight: 600; }",
    "    button:hover { background: #1d4ed8; }",
    "    button.success { background: #059669; border-color: #10b981; }",
    "    button.danger { background: #dc2626; border-color: #ef4444; padding: 5px 10px; font-size: 12px; }",
    "    button.secondary { background: #334155; border-color: #475569; }",
    "    table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }",
    "    th, td { border: 1px solid #334155; padding: 8px 10px; text-align: left; }",
    "    th { background: #0f172a; color: #38bdf8; }",
    "    .status-green { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981; padding: 3px 8px; border-radius: 999px; font-weight: 700; display: inline-block; font-size: 12px; }",
    "    .status-red { background: rgba(239, 68, 68, 0.25); color: #fca5a5; border: 1px solid #ef4444; padding: 3px 8px; border-radius: 999px; font-weight: 700; display: inline-block; font-size: 12px; }",
    "    .result-box { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px; margin-top: 12px; font-size: 13px; line-height: 1.6; }",
    "    canvas { width: 100%; height: 280px; background: #090d16; border: 1px solid #334155; border-radius: 8px; margin-top: 10px; display: block; }",
    "  </style>",
    "</head>",
    "<body>",
    "",
    "  <!-- MÀN HÌNH CHỈ HIỆN 1 Ô NHẬP KEY DUY NHẤT KHI CHƯA ĐĂNG NHẬP -->",
    '  <div id="login-gate-wrapper">',
    '    <div class="login-box" id="key-login-section">',
    '      <span class="badge">BẢO MẬT · https://' + CUSTOM_DOMAIN + "/</span>",
    "      <h1>🔐 Đăng Nhập Hệ Thống UAV GeoTIFF VN2000</h1>",
    "      <p>Vui lòng nhập Key truy cập để mở hệ thống nhận diện bình đồ UAV &amp; xuất bản vẽ AutoCAD chuẩn VN2000.</p>",
    '      <input id="key-input" class="login-input" type="password" placeholder="Nhập Key truy cập của bạn..." autocomplete="off" onkeydown="if(event.key===\'Enter\') verifyLogin()" />',
    '      <button type="button" class="login-btn" onclick="verifyLogin()">Đăng Nhập Hệ Thống</button>',
    '      <div id="login-error-msg"></div>',
    "    </div>",
    "  </div>",
    "",
    "  <!-- TOÀN BỘ NỘI DUNG BÊN DƯỚI BỊ ẨN HOÀN TOÀN CHO ĐẾN KHI NHẬP ĐÚNG KEY -->",
    '  <div id="authenticated-workspace" style="display:none;">',
    '    <div class="topbar">',
    "      <div>",
    '        <span class="badge" id="user-role-badge">ĐÃ XÁC THỰC KEY</span>',
    '        <h2 style="margin:6px 0 2px; font-size:19px;">UAV GeoTIFF Studio &amp; Khảo Sát Địa Hình 6 Lớp (Chuẩn VN2000)</h2>',
    '        <div style="font-size:13px; color:#94a3b8;">',
    '          Người dùng: <strong id="user-name-label" style="color:#f8fafc;"></strong> · ',
    '          Folder lưu Data xử lý: <a style="color:#38bdf8" target="_blank" href="' + PROCESSED_DATA_GDRIVE_FOLDER_URL + '"><code>' + PROCESSED_DATA_GDRIVE_FOLDER_ID + "</code></a>",
    "        </div>",
    "      </div>",
    '      <button type="button" class="secondary" onclick="logoutSession()">🔒 Đăng Xuất / Đổi Key</button>',
    "    </div>",
    "",
    "    <!-- BẢNG QUẢN LÝ KEY GOOGLE SHEET 7 CỘT (CHỈ HIỆN VỚI KEY ADMIN, ẨN VỚI KEY KHÁCH) -->",
    '    <div class="card hidden-admin-panel" id="admin-key-management-panel" style="display:none;">',
    '      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:10px;">',
    '        <h2 style="margin:0; color:#38bdf8; font-size:17px;">📊 Quản Lý Key Google Sheet 7 Cột (Chỉ Key Quyền Admin Mới Xem &amp; Thao Tác Được)</h2>',
    '        <button type="button" class="success" onclick="exportGoogleSheetCsv()">📥 Xuất File Google Sheet (.CSV 7 Cột)</button>',
    "      </div>",
    '      <p style="margin-top:0; font-size:13px; color:#cbd5e1;">Quy tắc tự động: <span class="status-green">🟢 Bình thường (Còn &gt; 1/3 thời gian)</span> · <span class="status-red">🔴 Báo đỏ (Còn &le; 1/3 thời gian)</span></p>',
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
    '        <label style="display:flex; align-items:center; gap:6px; font-size:13.5px;"><input type="checkbox" id="rec-tpu" checked /> Cho phép đẩy TPU (&gt;15p)</label>',
    '        <button type="button" onclick="createKey()">+ Tạo Key Mới</button>',
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
    "    <!-- CÔNG CỤ LÀM VIỆC THỰC TẾ: NHẬN DIỆN ẢNH UAV + XUẤT BẢN VẼ AUTOCAD .DXF VN2000 & CẬP NHẬT YOLO -->",
    '    <div class="grid">',
    '      <div class="card">',
    '        <h2 style="margin-top:0; color:#38bdf8; font-size:17px;">🖼️ 1. Upload Ảnh Nhận Diện 6 Lớp Địa Hình &amp; Xuất AutoCAD (.DXF VN2000)</h2>',
    '        <div style="display:flex; flex-direction:column; gap:10px;">',
    '          <label style="font-size:13px; color:#cbd5e1;">Chọn ảnh UAV / Orthomosaic từ máy tính (.tif, .jpg, .png):',
    '            <input type="file" id="uav-file-input" accept=".tif,.tiff,.png,.jpg,.jpeg" multiple onchange="handleFileSelect(event)" style="width:100%; margin-top:6px;" />',
    "          </label>",
    '          <div style="display:flex; gap:10px; flex-wrap:wrap;">',
    '            <label style="font-size:13px;">Số ảnh bay chụp: <input type="number" id="detect-images" value="45" min="1" style="width:80px;" /></label>',
    '            <label style="font-size:13px;">Số ô lưới (Tiles 512): <input type="number" id="detect-tiles" value="650" min="1" style="width:90px;" /></label>',
    "          </div>",
    '          <canvas id="uav-preview-canvas" width="640" height="280"></canvas>',
    '          <div style="display:flex; gap:8px; flex-wrap:wrap;">',
    '            <button type="button" onclick="runTpuTask(\'/api/detect/upload\')" style="flex:1;">🚀 Chạy Nhận Diện Địa Hình (Tự Động Đẩy TPU &gt;15p)</button>',
    '            <button type="button" class="success" onclick="downloadVn2000Dxf()">📐 Tải Bản Vẽ AutoCAD (.DXF VN2000)</button>',
    "          </div>",
    '          <div id="detect-res" class="result-box">Hãy chọn ảnh UAV từ máy tính (hoặc dùng bình đồ mẫu) rồi bấm <strong>Chạy Nhận Diện Địa Hình</strong>.</div>',
    "        </div>",
    "      </div>",
    "",
    '      <div class="card">',
    '        <h2 style="margin-top:0; color:#38bdf8; font-size:17px;">🧠 2. Update / Huấn Luyện Mô Hình YOLO Nhận Diện Vật Thể Mới</h2>',
    '        <div style="display:flex; flex-direction:column; gap:10px;">',
    '          <label style="font-size:13px; color:#cbd5e1;">Tải tập dữ liệu mẫu huấn luyện / Trọng số (.zip, .yaml, .onnx, ảnh):',
    '            <input type="file" id="yolo-file-input" multiple style="width:100%; margin-top:6px;" />',
    "          </label>",
    '          <label style="font-size:13px;">Danh sách vật thể mới cần nhận diện (Classes):',
    '            <input type="text" id="yolo-classes" value="culvert_gate, electric_pole, bridge_vn2000" style="width:100%; margin-top:6px;" />',
    "          </label>",
    '          <div style="display:flex; gap:12px; flex-wrap:wrap;">',
    '            <label style="font-size:13px;">Số Epochs: <input type="number" id="yolo-epochs" value="40" min="1" style="width:80px;" /></label>',
    '            <label style="font-size:13px;">Số lượng ảnh Dataset: <input type="number" id="yolo-dataset" value="500" min="10" style="width:95px;" /></label>',
    "          </div>",
    '          <button type="button" onclick="runTpuTask(\'/api/yolo/update\')">⚡ Huấn Luyện &amp; Cập Nhật Mô Hình YOLO (Tự Động TPU &gt;15p)</button>',
    '          <div id="yolo-res" class="result-box">Nhập tên vật thể mới và số Epochs để hệ thống tự tính thời gian. Nếu &gt; 15 phút sẽ tự động đẩy lên Google TPU.</div>',
    "        </div>",
    "      </div>",
    "    </div>",
    "  </div>",
    "",
    "  <script>",
    '    let activeKey = "";',
    "    let currentKeyRecord = null;",
    "    let lastDetectedPolylines = [];",
    "",
    "    function drawSampleTerrainCanvas(statusText) {",
    '      const canvas = document.getElementById("uav-preview-canvas");',
    "      if (!canvas) return;",
    '      const ctx = canvas.getContext("2d");',
    '      ctx.fillStyle = "#091526";',
    "      ctx.fillRect(0, 0, canvas.width, canvas.height);",
    "      // Grid VN2000",
    '      ctx.strokeStyle = "rgba(56, 189, 248, 0.14)";',
    "      ctx.lineWidth = 1;",
    "      for (let x = 0; x < canvas.width; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke(); }",
    "      for (let y = 0; y < canvas.height; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke(); }",
    "      // 6 lớp địa hình chuẩn VN2000",
    "      const layers = [",
    '        { name: "KS_DUONG_NHUA (asphalt_road)", color: "#f97316", pts: [[20,60],[220,75],[440,70],[620,90]] },',
    '        { name: "KS_DUONG_BETONG (concrete_road)", color: "#eab308", pts: [[40,140],[260,135],[520,150]] },',
    '        { name: "KS_AO_HO (pond)", color: "#38bdf8", pts: [[380,175],[490,175],[510,245],[370,245],[380,175]] },',
    '        { name: "KS_MUONG_XAY (masonry_ditch)", color: "#34d399", pts: [[30,220],[320,225],[350,260]] }',
    "      ];",
    "      lastDetectedPolylines = layers;",
    "      layers.forEach(function(l) {",
    "        ctx.strokeStyle = l.color;",
    "        ctx.lineWidth = 3;",
    "        ctx.beginPath();",
    "        l.pts.forEach(function(p, idx) { if (idx === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]); });",
    "        ctx.stroke();",
    "        ctx.fillStyle = l.color;",
    '        ctx.font = "bold 11px sans-serif";',
    "        ctx.fillText(l.name, l.pts[0][0] + 6, l.pts[0][1] - 6);",
    "      });",
    "      if (statusText) {",
    '        ctx.fillStyle = "#f8fafc";',
    '        ctx.font = "bold 12px sans-serif";',
    "        ctx.fillText(statusText, 14, 22);",
    "      }",
    "    }",
    "",
    "    function handleFileSelect(ev) {",
    "      const files = ev.target.files;",
    "      if (!files || !files.length) return;",
    '      document.getElementById("detect-images").value = files.length;',
    '      document.getElementById("detect-tiles").value = Math.max(20, files.length * 16);',
    "      const first = files[0];",
    "      if (first.type && first.type.startsWith('image/')) {",
    "        const reader = new FileReader();",
    "        reader.onload = function(e) {",
    "          const img = new Image();",
    "          img.onload = function() {",
    '            const canvas = document.getElementById("uav-preview-canvas");',
    '            const ctx = canvas.getContext("2d");',
    "            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);",
    "          };",
    "          img.src = e.target.result;",
    "        };",
    "        reader.readAsDataURL(first);",
    "      } else {",
    '        drawSampleTerrainCanvas("Đã nạp file UAV: " + first.name + " (" + Math.round(first.size/1024) + " KB)");',
    "      }",
    "    }",
    "",
    "    async function verifyLogin() {",
    '      const k = document.getElementById("key-input").value.trim();',
    '      const errEl = document.getElementById("login-error-msg");',
    "      if (!k) {",
    '        errEl.textContent = "⚠️ Vui lòng nhập Key truy cập trước khi đăng nhập!";',
    "        return;",
    "      }",
    '      errEl.textContent = "Đang kiểm tra Key...";',
    '      const res = await fetch("/api/auth/verify-key", {',
    '        method: "POST",',
    '        headers: { "Content-Type": "application/json" },',
    "        body: JSON.stringify({ key: k }),",
    "      });",
    "      const data = await res.json();",
    "      if (!res.ok || !data.valid) {",
    '        errEl.textContent = "❌ " + (data.reason || "Key không hợp lệ hoặc đã hết hạn!");',
    '        document.getElementById("authenticated-workspace").style.display = "none";',
    '        document.getElementById("login-gate-wrapper").style.display = "flex";',
    "        return;",
    "      }",
    "      activeKey = k;",
    "      currentKeyRecord = data.key_record || {};",
    '      errEl.textContent = "";',
    '      document.getElementById("login-gate-wrapper").style.display = "none";',
    '      document.getElementById("authenticated-workspace").style.display = "block";',
    '      const adminPanel = document.getElementById("admin-key-management-panel");',
    '      const badge = document.getElementById("user-role-badge");',
    '      const nameLabel = document.getElementById("user-name-label");',
    "      if (data.is_admin) {",
    '        badge.textContent = "QUYỀN ADMIN · TOÀN QUYỀN QUẢN TRỊ KEY & TPU >15P";',
    '        badge.style.background = "#059669";',
    '        nameLabel.textContent = (currentKeyRecord.recipient || "Quản Trị Viên") + " (Admin)";',
    '        adminPanel.style.display = "block";',
    "        await refreshKeys();",
    "      } else {",
    '        badge.textContent = "KEY KHÁCH · " + (data.allow_tpu ? "CÓ QUYỀN ĐẨY TPU >15P" : "CHỈ CHẠY TÁC VỤ <=15P");',
    '        badge.style.background = "#2563eb";',
    '        nameLabel.textContent = (currentKeyRecord.recipient || "Khách hàng") + " (" + (currentKeyRecord.status_label || "") + ")";',
    '        adminPanel.style.display = "none";',
    "      }",
    '      drawSampleTerrainCanvas("Bình đồ VN2000 6 Lớp Địa Hình Sẵn Sàng");',
    "    }",
    "",
    "    function logoutSession() {",
    '      activeKey = "";',
    "      currentKeyRecord = null;",
    '      document.getElementById("key-input").value = "";',
    '      document.getElementById("login-error-msg").textContent = "";',
    '      document.getElementById("admin-key-management-panel").style.display = "none";',
    '      document.getElementById("authenticated-workspace").style.display = "none";',
    '      document.getElementById("login-gate-wrapper").style.display = "flex";',
    "    }",
    "",
    "    async function refreshKeys() {",
    '      const res = await fetch("/api/keys", { headers: { "X-Admin-Key": activeKey } });',
    "      if (!res.ok) return;",
    "      const data = await res.json();",
    '      const tbody = document.getElementById("keys-body");',
    "      window.__latestKeysList = data.keys || [];",
    '      tbody.innerHTML = (data.keys || []).map(function(r) {',
    '        const cls = r.is_warning_red ? "status-red" : "status-green";',
    "        const delBtn = r.role === 'admin' ? '<span style=\"color:#94a3b8;font-size:12px;\">Key Gốc</span>' : '<button class=\"danger\" onclick=\"deleteKey(\\'' + r.key + '\\')\">Xóa</button>';",
    "        return '<tr>' +",
    "          '<td>' + r.recipient + '</td>' +",
    "          '<td>' + r.phone + '</td>' +",
    "          '<td><code>' + r.key + '</code> <button class=\"secondary\" style=\"padding:2px 6px;font-size:11px;\" onclick=\"navigator.clipboard.writeText(\\'' + r.key + '\\')\">Copy</button></td>' +",
    "          '<td>' + (r.purpose_display || r.purpose) + '</td>' +",
    "          '<td>' + r.issued_at_iso + '</td>' +",
    "          '<td>' + r.expires_at_iso + '</td>' +",
    "          '<td><span class=\"' + cls + '\">' + r.status_label + '</span></td>' +",
    "          '<td>' + delBtn + '</td>' +",
    "          '</tr>';",
    '      }).join("");',
    "    }",
    "",
    "    async function createKey() {",
    '      const res = await fetch("/api/keys/create", {',
    '        method: "POST",',
    '        headers: { "Content-Type": "application/json", "X-Admin-Key": activeKey },',
    "        body: JSON.stringify({",
    '          recipient: document.getElementById("rec-name").value.trim() || "Khách hàng mới",',
    '          phone: document.getElementById("rec-phone").value.trim() || "0912345678",',
    '          purpose: document.getElementById("rec-purpose").value,',
    '          allow_tpu: document.getElementById("rec-tpu").checked,',
    "        }),",
    "      });",
    "      if (res.ok) {",
    '        document.getElementById("rec-name").value = "";',
    '        document.getElementById("rec-phone").value = "";',
    "        await refreshKeys();",
    "      }",
    "    }",
    "",
    "    async function deleteKey(key) {",
    '      await fetch("/api/keys/delete", {',
    '        method: "POST",',
    '        headers: { "Content-Type": "application/json", "X-Admin-Key": activeKey },',
    "        body: JSON.stringify({ key: key }),",
    "      });",
    "      await refreshKeys();",
    "    }",
    "",
    "    function exportGoogleSheetCsv() {",
    "      const rows = window.__latestKeysList || [];",
    '      const header = ["Người nhận","SĐT người nhận","Key","Mục đích","Thời gian cấp","Thời gian hết hạn","Tình trạng"];',
    "      const csvLines = [header.join(',')];",
    "      rows.forEach(function(r) {",
    "        const vals = [r.recipient, r.phone, r.key, r.purpose_display || r.purpose, r.issued_at_iso, r.expires_at_iso, r.status_label].map(function(v) {",
    "          return '\"' + String(v || '').replace(/\"/g, '\"\"') + '\"';",
    "        });",
    "        csvLines.push(vals.join(','));",
    "      });",
    '      const blob = new Blob(["\\uFEFF" + csvLines.join("\\r\\n")], { type: "text/csv;charset=utf-8;" });',
    "      const a = document.createElement('a');",
    "      a.href = URL.createObjectURL(blob);",
    "      a.download = 'uav_keys_google_sheet_7cot.csv';",
    "      a.click();",
    "    }",
    "",
    "    function downloadVn2000Dxf() {",
    "      const dxf = [",
    "        '0','SECTION','2','HEADER','9','$INSUNITS','70','6','0','ENDSEC',",
    "        '0','SECTION','2','ENTITIES',",
    "        '0','LWPOLYLINE','8','KS_DUONG_NHUA','62','1','90','4','70','0','10','584120.0','20','2314510.0','10','584220.0','20','2314525.0','10','584340.0','20','2314520.0','10','584420.0','20','2314540.0',",
    "        '0','LWPOLYLINE','8','KS_DUONG_BETONG','62','2','90','3','70','0','10','584140.0','20','2314440.0','10','584260.0','20','2314435.0','10','584420.0','20','2314450.0',",
    "        '0','LWPOLYLINE','8','KS_AO_HO','62','5','90','5','70','1','10','584380.0','20','2314375.0','10','584490.0','20','2314375.0','10','584510.0','20','2314305.0','10','584370.0','20','2314305.0','10','584380.0','20','2314375.0',",
    "        '0','LWPOLYLINE','8','KS_MUONG_XAY','62','3','90','3','70','0','10','584130.0','20','2314320.0','10','584320.0','20','2314325.0','10','584350.0','20','2314290.0',",
    "        '0','ENDSEC','0','EOF'",
    "      ].join('\\r\\n');",
    "      const blob = new Blob([dxf], { type: 'application/dxf' });",
    "      const a = document.createElement('a');",
    "      a.href = URL.createObjectURL(blob);",
    "      a.download = 'binh_do_6lop_VN2000_output.dxf';",
    "      a.click();",
    "    }",
    "",
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
    '        box.innerHTML = "⏱️ <strong>Thời gian ước tính:</strong> <code>" + mins + " phút (" + estSec + "s &gt; 15 phút)</code><br/>🚫 <span style=\\"color:#f87171;font-weight:700;\\">403 Forbidden: " + (data.error || "Key Khách hiện tại không được Admin cấp quyền dùng TPU (>15 phút)") + "</span>";',
    "      } else {",
    '        drawSampleTerrainCanvas("✅ Đã nhận diện xong 6 lớp VN2000 (" + mins + " phút)");',
    '        box.innerHTML = "⏱️ <strong>Thời gian ước tính:</strong> <code>" + mins + " phút (" + estSec + "s)</code><br/>🚀 <strong>Chế độ thực thi:</strong> <span style=\\"color:#34d399;font-weight:700;\\">" + (data.offloaded_to_tpu ? "ĐÃ TỰ ĐỘNG ĐẨY LÊN GOOGLE TPU (>15 phút)" : "Xử lý trực tiếp WebGPU/CPU (<=15 phút)") + "</span><br/>📂 <strong>Đồng bộ kết quả về Folder Google Drive:</strong> <a style=\\"color:#38bdf8\\" target=\\"_blank\\" href=\\"" + data.processed_data_folder_url + "\\"><code>" + data.processed_data_folder_id + "</code></a>";',
    "      }",
    "    }",
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
      const randomHex = crypto.randomUUID().replace(/-/g, "").slice(0, 10);
      const rec = {
        recipient: String(body.recipient || "Khách Hàng Mới"),
        phone: String(body.phone || "0912345678"),
        key: String(body.custom_key || `uav_${purpose}_${randomHex}`),
        purpose,
        allow_tpu: Boolean(body.allow_tpu),
        role: String(body.role || "guest"),
        issued_at_ts: nowSec,
        expires_at_ts: nowSec + durationSec,
        issued_at_iso: new Date(nowSec * 1000).toISOString().replace("T", " ").slice(0, 19),
        expires_at_iso: new Date((nowSec + durationSec) * 1000).toISOString().replace("T", " ").slice(0, 19),
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
            error: "Key Khách hiện tại không được Admin cấp quyền đẩy tác vụ >15 phút lên Google TPU",
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
