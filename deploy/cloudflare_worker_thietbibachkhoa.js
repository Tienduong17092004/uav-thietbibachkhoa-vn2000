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
  return "<!doctype html>\n<html lang=\"vi\" data-theme=\"light\">\n<head>\n  <meta charset=\"utf-8\" />\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n  <title>UAV GeoTIFF Studio · Chuẩn bị dữ liệu ảnh địa lý (VN2000 · https://thietbibachkhoa.id.vn/)</title>\n  <style>\n    :root {\n      color-scheme: light;\n      --bg: #f2f5f3;\n      --surface: #ffffff;\n      --surface-subtle: #f7faf8;\n      --surface-input: #ffffff;\n      --surface-media: #141917;\n      --header-bg: rgba(255, 255, 255, 0.96);\n      --ink: #18241e;\n      --ink-pure: #0b1410;\n      --ink-secondary: #43544b;\n      --muted: #62736a;\n      --border: #d2ddd7;\n      --border-strong: #9bb0a5;\n      --accent-emerald: #009966;\n      --accent-mint: #007a52;\n      --accent-teal: #0b7290;\n      --warning-amber: #b46900;\n      --danger-coral: #d92d20;\n      --btn-hover-bg: #ecf7f2;\n      --btn-primary-bg: #6f7c75;\n      --btn-primary-active-bg: #009966;\n      --shadow-card: rgba(15, 23, 20, 0.05) 0px 2px 10px, rgba(15, 23, 20, 0.04) 0px 0px 0px 1px;\n      --font-body: \"Inter\", system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif;\n      --font-mono: \"SFMono-Regular\", Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace;\n      font-family: var(--font-body);\n    }\n    * { box-sizing: border-box; }\n    [hidden] { display: none !important; }\n    html, body { width: 100%; min-height: 100vh; margin: 0; padding: 0; background: var(--bg); color: var(--ink); font-size: 13.5px; line-height: 1.5; -webkit-font-smoothing: antialiased; }\n\n    /* =========================================================================\n       1. CỔNG KHÓA ĐĂNG NHẬP DUY NHẤT 1 Ô NHẬP KEY (ẨN MỌI THỨ KHÁC KHI CHƯA NHẬP KEY)\n       ========================================================================= */\n    #login-gate-wrapper {\n      display: flex;\n      align-items: center;\n      justify-content: center;\n      min-height: 100vh;\n      padding: 20px;\n      background: radial-gradient(circle at 50% 25%, #ffffff 0%, #e7efeb 100%);\n    }\n    .login-box {\n      width: 100%;\n      max-width: 420px;\n      background: #ffffff;\n      border: 1px solid var(--border);\n      border-radius: 10px;\n      padding: 28px 26px;\n      box-shadow: 0 12px 36px rgba(15, 23, 20, 0.08);\n      text-align: center;\n    }\n    .login-brand {\n      display: inline-flex;\n      align-items: center;\n      gap: 10px;\n      margin-bottom: 16px;\n      text-align: left;\n    }\n    .brand-mark {\n      display: grid;\n      grid-template-columns: repeat(2, 9px);\n      gap: 3px;\n      padding: 6px;\n      background: var(--surface);\n      border: 1px solid var(--border);\n      border-radius: 6px;\n    }\n    .brand-mark i { height: 9px; background: var(--accent-emerald); border-radius: 1.5px; display: block; }\n    .brand-mark i:nth-child(2) { background: var(--accent-teal); }\n    .brand-mark i:last-child { background: var(--warning-amber); }\n    .login-input {\n      width: 100%;\n      padding: 11px 14px;\n      border-radius: 6px;\n      border: 1px solid var(--border-strong);\n      background: #ffffff;\n      color: var(--ink-pure);\n      font-size: 14px;\n      margin-bottom: 12px;\n      outline: none;\n      text-align: center;\n    }\n    .login-input:focus {\n      border-color: var(--accent-emerald);\n      box-shadow: 0 0 0 3px rgba(0, 153, 102, 0.15);\n    }\n    .login-btn {\n      width: 100%;\n      padding: 11px 16px;\n      border-radius: 6px;\n      border: 1px solid #007f55;\n      background: var(--accent-emerald);\n      color: #ffffff;\n      font-size: 14px;\n      font-weight: 600;\n      cursor: pointer;\n    }\n    .login-btn:hover { background: var(--accent-mint); }\n    #login-error-msg {\n      margin-top: 10px;\n      font-size: 12.5px;\n      font-weight: 600;\n      color: var(--danger-coral);\n      min-height: 18px;\n    }\n\n    /* =========================================================================\n       2. GIAO DIỆN UAV GEOTIFF STUDIO GỐC (CHỈ HIỆN SAU KHI NHẬP ĐÚNG KEY)\n       ========================================================================= */\n    #authenticated-workspace { display: none; }\n\n    button, input, select, textarea { font: inherit; }\n    button {\n      cursor: pointer;\n      border: 1px solid var(--border);\n      border-radius: 6px;\n      min-height: 36px;\n      padding: 6px 13px;\n      font-weight: 500;\n      font-size: 13px;\n      color: var(--ink-pure);\n      background: var(--surface);\n      transition: all 120ms ease;\n    }\n    button:hover:not(:disabled) {\n      background: var(--btn-hover-bg);\n      border-color: var(--accent-emerald);\n      color: var(--accent-mint);\n    }\n    button:disabled { cursor: not-allowed; opacity: 0.5; }\n    button.primary {\n      background: var(--accent-emerald);\n      border-color: #007f55;\n      color: #ffffff;\n      font-weight: 600;\n    }\n    button.primary:hover:not(:disabled) {\n      background: var(--accent-mint);\n      color: #ffffff;\n    }\n    button.export-tile-btn {\n      background: #76827c;\n      border-color: #65706a;\n      color: #ffffff;\n      font-weight: 600;\n      width: 100%;\n      min-height: 38px;\n    }\n    button.export-tile-btn:hover:not(:disabled) {\n      background: var(--accent-emerald);\n      border-color: #007f55;\n      color: #ffffff;\n    }\n    button.secondary {\n      background: var(--surface-subtle);\n      border-color: var(--border);\n      color: var(--ink);\n    }\n    .wide { width: 100%; margin-top: 10px; }\n\n    input, select, textarea {\n      background: var(--surface-input);\n      border: 1px solid var(--border);\n      border-radius: 6px;\n      width: 100%;\n      min-height: 36px;\n      padding: 6px 10px;\n      color: var(--ink);\n      font-size: 13px;\n    }\n    input:focus, select:focus, textarea:focus {\n      outline: none;\n      border-color: var(--accent-emerald);\n      box-shadow: 0 0 0 2px rgba(0, 153, 102, 0.14);\n    }\n    label {\n      display: block;\n      font-size: 12.5px;\n      font-weight: 600;\n      margin-bottom: 5px;\n      color: var(--ink);\n    }\n    h1, h2, h3, p { margin: 0; }\n    h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; color: var(--ink-pure); margin-top: 3px; }\n    h2 { font-size: 15px; font-weight: 700; letter-spacing: -0.2px; color: var(--ink-pure); }\n    .eyebrow {\n      font-size: 10.5px;\n      font-weight: 700;\n      letter-spacing: 1.4px;\n      text-transform: uppercase;\n      color: var(--muted);\n    }\n    .muted, .field-help, .empty-note { color: var(--muted); font-size: 12px; line-height: 1.5; }\n\n    /* Top Header */\n    .app-header {\n      width: 100%;\n      min-height: 54px;\n      display: flex;\n      justify-content: space-between;\n      align-items: center;\n      padding: 8px 24px;\n      border-bottom: 1px solid var(--border);\n      background: var(--header-bg);\n      position: sticky;\n      top: 0;\n      z-index: 30;\n    }\n    .brand { display: flex; align-items: center; gap: 10px; }\n    .brand strong { display: block; font-size: 15px; font-weight: 700; color: var(--ink-pure); }\n    .brand div > span { display: block; color: var(--muted); font-size: 11.5px; }\n    .header-meta { display: flex; align-items: center; gap: 12px; font-size: 12px; color: var(--ink-secondary); flex-wrap: wrap; }\n    .local-badge {\n      display: inline-flex;\n      align-items: center;\n      gap: 6px;\n      padding: 4px 10px;\n      background: #ecf7f2;\n      border: 1px solid rgba(0, 153, 102, 0.35);\n      border-radius: 999px;\n      color: var(--accent-mint);\n      font-weight: 600;\n      font-size: 11.5px;\n    }\n    .local-badge > span {\n      height: 7px;\n      width: 7px;\n      border-radius: 50%;\n      background: var(--accent-emerald);\n    }\n\n    /* 4-Step Bar matching screenshot */\n    .steps {\n      width: 100%;\n      background: var(--surface);\n      border-bottom: 1px solid var(--border);\n      padding: 0 180px;\n    }\n    .steps ol {\n      list-style: none;\n      display: grid;\n      grid-template-columns: repeat(4, 1fr);\n      margin: 0 auto;\n      padding: 0;\n      max-width: 1180px;\n    }\n    .steps li { min-width: 0; }\n    .steps button {\n      display: flex;\n      align-items: center;\n      gap: 10px;\n      width: 100%;\n      min-height: 54px;\n      border: 0;\n      border-radius: 0;\n      background: transparent;\n      text-align: left;\n      position: relative;\n      padding: 10px 14px;\n      color: var(--ink-secondary);\n    }\n    .steps button:hover:not(:disabled) {\n      background: rgba(0, 153, 102, 0.04);\n      color: var(--ink-pure);\n    }\n    .steps button[aria-current=\"step\"] {\n      color: var(--ink-pure);\n    }\n    .steps button[aria-current=\"step\"]::after {\n      content: \"\";\n      position: absolute;\n      bottom: 0;\n      left: 14px;\n      right: 14px;\n      height: 2.5px;\n      background: #2c4c3e;\n    }\n    .step-number {\n      flex-shrink: 0;\n      display: grid;\n      place-items: center;\n      font-size: 11px;\n      font-family: var(--font-mono);\n      width: 24px;\n      height: 24px;\n      border: 1px solid var(--border);\n      border-radius: 4px;\n      color: var(--muted);\n      background: var(--surface-subtle);\n    }\n    .steps button[aria-current=\"step\"] .step-number {\n      border-color: #2c4c3e;\n      color: #2c4c3e;\n      font-weight: 700;\n    }\n    .steps button .step-label-wrap strong {\n      display: block;\n      font-size: 12.5px;\n      font-weight: 600;\n      color: var(--ink-pure);\n    }\n    .steps button .step-label-wrap small {\n      display: block;\n      font-size: 11px;\n      color: var(--muted);\n      font-weight: 400;\n      margin-top: 1px;\n    }\n\n    /* Main Workspace Grid matching screenshot */\n    .workspace {\n      max-width: 1220px;\n      margin: 0 auto;\n      padding: 18px 20px 28px;\n      display: grid;\n      grid-template-columns: 280px minmax(0, 1fr);\n      gap: 18px;\n      align-items: start;\n    }\n    .config-panel, .map-panel {\n      background: var(--surface);\n      border: 1px solid var(--border);\n      border-radius: 8px;\n      box-shadow: var(--shadow-card);\n      overflow: hidden;\n    }\n    .config-panel {\n      padding: 18px 16px;\n      display: flex;\n      flex-direction: column;\n    }\n    .panel-heading {\n      padding-bottom: 12px;\n      margin-bottom: 14px;\n    }\n    .panel-heading > p:last-child {\n      margin-top: 6px;\n      font-size: 12px;\n      color: var(--muted);\n      line-height: 1.45;\n    }\n\n    /* Review Summary & Metadata Box */\n    .metadata, .review-summary {\n      margin: 8px 0 12px;\n      padding: 12px 14px;\n      background: var(--surface-subtle);\n      border: 1px solid var(--border);\n      border-radius: 6px;\n    }\n    .metadata dl, .review-summary dl {\n      display: grid;\n      grid-template-columns: 78px minmax(0, 1fr);\n      gap: 8px 10px;\n      margin: 0;\n      font-size: 12px;\n      align-items: baseline;\n    }\n    .metadata dt, .review-summary dt {\n      color: var(--muted);\n      font-weight: 500;\n      line-height: 1.35;\n    }\n    .metadata dd, .review-summary dd {\n      margin: 0;\n      text-align: right;\n      font-weight: 600;\n      color: var(--ink-pure);\n      font-variant-numeric: tabular-nums;\n      word-break: break-word;\n    }\n    .review-source {\n      font-size: 11px;\n      color: var(--muted);\n      overflow-wrap: anywhere;\n      border-top: 1px solid var(--border);\n      padding-top: 8px;\n      margin-top: 10px;\n      font-family: var(--font-mono);\n      line-height: 1.4;\n    }\n\n    /* Linear Job Progress matching screenshot */\n    .job-panel {\n      margin-top: 16px;\n      padding-top: 14px;\n      border-top: 1px solid var(--border);\n    }\n    #job-status {\n      font-size: 12.5px;\n      font-weight: 700;\n      color: var(--ink-pure);\n      margin-bottom: 8px;\n    }\n    .linear-progress-track {\n      width: 100%;\n      height: 7px;\n      background: #dfe7e2;\n      border-radius: 999px;\n      overflow: hidden;\n      margin-bottom: 8px;\n    }\n    .linear-progress-fill {\n      height: 100%;\n      background: #2b5b47;\n      border-radius: 999px;\n      transition: width 250ms ease;\n    }\n    .job-actions {\n      display: flex;\n      gap: 8px;\n      margin-top: 8px;\n    }\n    .output-path {\n      font-family: var(--font-mono);\n      font-size: 10.5px;\n      color: var(--muted);\n      overflow-wrap: anywhere;\n      margin-top: 10px;\n      line-height: 1.4;\n    }\n\n    .field-grid {\n      display: grid;\n      grid-template-columns: repeat(2, minmax(0, 1fr));\n      gap: 10px;\n      margin-bottom: 10px;\n    }\n    .path-row { display: flex; gap: 6px; margin-bottom: 8px; }\n    .path-row button { white-space: nowrap; }\n\n    .plan-stats {\n      margin-top: 12px;\n      padding: 12px;\n      background: var(--surface-subtle);\n      border: 1px solid var(--border);\n      border-left: 3px solid var(--accent-emerald);\n      border-radius: 6px;\n    }\n    .plan-count {\n      font-size: 26px;\n      font-weight: 700;\n      color: var(--accent-emerald);\n      line-height: 1.1;\n    }\n    .plan-count span {\n      font-size: 12px;\n      font-weight: 500;\n      color: var(--muted);\n      margin-left: 6px;\n    }\n    .stat-grid {\n      display: grid;\n      grid-template-columns: repeat(2, 1fr);\n      gap: 8px;\n      margin-top: 10px;\n      font-size: 11.5px;\n    }\n    .stat-grid span { display: block; color: var(--muted); font-size: 11px; }\n    .stat-grid strong { font-family: var(--font-mono); color: var(--ink-pure); }\n\n    /* Right Column: Map Panel & Tile Inspector & Detection Results */\n    .map-heading {\n      display: flex;\n      justify-content: space-between;\n      align-items: center;\n      padding: 12px 18px;\n      background: var(--surface);\n      border-bottom: 1px solid var(--border);\n    }\n    .status-tag {\n      display: inline-flex;\n      align-items: center;\n      padding: 3px 9px;\n      border: 1px solid var(--border);\n      border-radius: 999px;\n      font-size: 11px;\n      font-weight: 600;\n      font-family: var(--font-mono);\n      color: var(--ink-secondary);\n      background: var(--surface-subtle);\n    }\n    .status-tag.success {\n      background: rgba(0, 153, 102, 0.1);\n      border-color: var(--accent-emerald);\n      color: var(--accent-mint);\n    }\n\n    .viewport-shell {\n      position: relative;\n      background: var(--surface-media);\n      height: 360px;\n      overflow: hidden;\n    }\n    #overview-canvas {\n      width: 100%;\n      height: 100%;\n      display: block;\n      cursor: grab;\n    }\n    #overview-canvas:active { cursor: grabbing; }\n    .north-indicator {\n      position: absolute;\n      left: 12px;\n      top: 10px;\n      color: #cbd5e1;\n      font-size: 11px;\n      line-height: 1.15;\n      text-align: center;\n      font-family: var(--font-mono);\n      pointer-events: none;\n    }\n    .map-tools {\n      position: absolute;\n      right: 12px;\n      top: 10px;\n      display: flex;\n      gap: 4px;\n      z-index: 5;\n    }\n    .map-tools button {\n      min-height: 28px;\n      height: 28px;\n      padding: 0 9px;\n      background: rgba(30, 36, 33, 0.9);\n      border-color: #3d4a44;\n      color: #f1f5f9;\n      font-size: 12px;\n      border-radius: 4px;\n    }\n    .viewport-status {\n      position: absolute;\n      bottom: 8px;\n      left: 12px;\n      font-size: 11px;\n      color: #cbd5e1;\n      pointer-events: none;\n    }\n\n    .map-caption {\n      display: flex;\n      justify-content: space-between;\n      align-items: center;\n      padding: 8px 18px 4px;\n      font-size: 11.5px;\n      color: var(--muted);\n      background: var(--surface);\n    }\n    .legend { display: flex; gap: 14px; align-items: center; }\n    .legend span { display: inline-flex; align-items: center; gap: 5px; }\n    .legend i { display: inline-block; width: 12px; height: 8px; border-radius: 1.5px; }\n    .legend-grid { border: 1px solid #5a7d6c; background: rgba(0, 153, 102, 0.08); }\n    .legend-overlap { border: 1px dashed #b46900; background: rgba(180, 105, 0, 0.15); }\n    .legend-selected { border: 1.5px solid #d97706; background: rgba(245, 158, 11, 0.28); }\n    .overview-note {\n      font-size: 11.5px;\n      color: var(--muted);\n      padding: 0 18px 10px;\n      border-bottom: 1px solid var(--border);\n    }\n\n    /* Tile Inspector matching screenshot */\n    .tile-inspector {\n      padding: 14px 18px;\n      border-bottom: 1px solid var(--border);\n    }\n    .inspector-heading {\n      display: flex;\n      justify-content: space-between;\n      align-items: center;\n      margin-bottom: 10px;\n    }\n    .tile-select-field {\n      display: flex;\n      align-items: center;\n      gap: 8px;\n    }\n    .tile-select-field label { margin: 0; font-size: 12px; color: var(--muted); font-weight: 500; }\n    .tile-select-field select { width: 150px; min-height: 30px; height: 30px; padding: 3px 8px; font-family: var(--font-mono); font-size: 12px; }\n    .tile-body {\n      display: grid;\n      grid-template-columns: 155px minmax(0, 1fr);\n      gap: 16px;\n      align-items: start;\n    }\n    .tile-image-wrap {\n      width: 155px;\n      height: 155px;\n      border: 1px solid var(--border);\n      border-radius: 6px;\n      background: #ffffff;\n      display: flex;\n      align-items: center;\n      justify-content: center;\n      overflow: hidden;\n    }\n    #tile-details strong {\n      display: block;\n      font-size: 12.5px;\n      color: var(--ink-pure);\n      margin-bottom: 2px;\n    }\n    #tile-details > p {\n      font-size: 11.5px;\n      color: var(--muted);\n      margin-bottom: 8px;\n    }\n    table.coord-table {\n      width: 100%;\n      border-collapse: collapse;\n      font-size: 11.5px;\n      font-variant-numeric: tabular-nums;\n    }\n    table.coord-table caption {\n      text-align: left;\n      font-size: 11px;\n      color: var(--muted);\n      margin-bottom: 4px;\n    }\n    table.coord-table th, table.coord-table td {\n      padding: 5px 6px;\n      border-bottom: 1px solid var(--border);\n    }\n    table.coord-table th {\n      font-weight: 600;\n      color: var(--muted);\n      text-align: right;\n    }\n    table.coord-table th:first-child, table.coord-table td:first-child {\n      text-align: left;\n      padding-left: 0;\n    }\n    table.coord-table td:not(:first-child) {\n      text-align: right;\n      font-family: var(--font-mono);\n    }\n    .inspector-note {\n      margin-top: 10px;\n      font-size: 11.5px;\n      color: var(--muted);\n    }\n\n    /* Duyệt kết quả nhận diện matching screenshot */\n    .results-section {\n      padding: 14px 18px 18px;\n    }\n    .results-section h2 {\n      margin-bottom: 6px;\n    }\n\n    /* Floating Windows Task Manager GPU Overlay matching screenshot */\n    .tm-float-card {\n      position: fixed;\n      top: 132px;\n      right: 28px;\n      width: 162px;\n      background: #ffffff;\n      border: 1px solid #cfd8d3;\n      border-radius: 6px;\n      box-shadow: 0 8px 28px rgba(0, 0, 0, 0.14);\n      padding: 8px;\n      z-index: 25;\n      font-size: 11px;\n      user-select: none;\n    }\n    .tm-row {\n      display: grid;\n      grid-template-columns: 44px minmax(0, 1fr);\n      gap: 7px;\n      align-items: center;\n      padding: 4px;\n      border-radius: 4px;\n    }\n    .tm-row.active {\n      background: #f3eefc;\n    }\n    .tm-mini-box {\n      width: 44px;\n      height: 30px;\n      border: 1px solid #94a3b8;\n      background: #ffffff;\n      position: relative;\n      overflow: hidden;\n    }\n    .tm-row.active .tm-mini-box {\n      border-color: #8b5cf6;\n      background: #f5f0ff;\n    }\n    .tm-meta strong {\n      display: block;\n      font-size: 11.5px;\n      font-weight: 600;\n      color: #0f172a;\n      line-height: 1.2;\n    }\n    .tm-meta span {\n      display: block;\n      font-size: 10px;\n      color: #475569;\n      white-space: nowrap;\n      overflow: hidden;\n      text-overflow: ellipsis;\n      line-height: 1.25;\n    }\n\n    /* Admin 7-Column Google Sheet Key Manager Modal/Drawer (Only visible for Admin Key) */\n    #admin-key-management-panel {\n      display: none;\n      max-width: 1220px;\n      margin: 14px auto 0;\n      padding: 16px 20px;\n      background: #ffffff;\n      border: 2px solid var(--accent-emerald);\n      border-radius: 8px;\n      box-shadow: var(--shadow-card);\n    }\n    table.admin-sheet-table {\n      width: 100%;\n      border-collapse: collapse;\n      margin-top: 10px;\n      font-size: 12px;\n    }\n    table.admin-sheet-table th, table.admin-sheet-table td {\n      border: 1px solid var(--border);\n      padding: 7px 9px;\n      text-align: left;\n    }\n    table.admin-sheet-table th {\n      background: #ecf7f2;\n      color: var(--ink-pure);\n      font-weight: 700;\n    }\n    .status-green {\n      background: rgba(0, 153, 102, 0.12);\n      color: #007a52;\n      border: 1px solid #009966;\n      padding: 2px 8px;\n      border-radius: 999px;\n      font-weight: 700;\n      font-size: 11px;\n      display: inline-block;\n    }\n    .status-red {\n      background: rgba(217, 45, 32, 0.12);\n      color: #b42318;\n      border: 1px solid #d92d20;\n      padding: 2px 8px;\n      border-radius: 999px;\n      font-weight: 700;\n      font-size: 11px;\n      display: inline-block;\n    }\n\n    @media (max-width: 1024px) {\n      .steps { padding: 0 16px; }\n      .workspace { grid-template-columns: 1fr; }\n      .tm-float-card { display: none; }\n    }\n  </style>\n</head>\n<body>\n\n  <!-- =========================================================================\n       MÀN HÌNH 1 Ô NHẬP KEY DUY NHẤT (ẨN TOÀN BỘ GIAO DIỆN STUDIO KHI CHƯA NHẬP KEY)\n       ========================================================================= -->\n  <div id=\"login-gate-wrapper\">\n    <div class=\"login-box\" id=\"key-login-section\">\n      <div class=\"login-brand\">\n        <span class=\"brand-mark\" aria-hidden=\"true\"><i></i><i></i><i></i><i></i></span>\n        <div>\n          <strong style=\"font-size:15px;color:#0b1410;display:block\">UAV GeoTIFF Studio</strong>\n          <span style=\"font-size:11.5px;color:#62736a\">Chuẩn bị dữ liệu ảnh địa lý · VN2000</span>\n        </div>\n      </div>\n      <input id=\"key-input\" class=\"login-input\" type=\"password\" placeholder=\"Nhập Key truy cập...\" autocomplete=\"off\" onkeydown=\"if(event.key==='Enter') verifyLogin()\" />\n      <button type=\"button\" id=\"btn-login\" class=\"login-btn\" onclick=\"verifyLogin()\">Mở Giao Diện UAV GeoTIFF Studio</button>\n      <div id=\"login-error-msg\"></div>\n    </div>\n  </div>\n\n  <!-- =========================================================================\n       GIAO DIỆN CHÍNH UAV GEOTIFF STUDIO (HIỆN NGAY SAU KHI NHẬP KEY HỢP LỆ)\n       ========================================================================= -->\n  <div id=\"authenticated-workspace\" style=\"display:none;\">\n    <header class=\"app-header\">\n      <div class=\"brand\">\n        <span class=\"brand-mark\" aria-hidden=\"true\"><i></i><i></i><i></i><i></i></span>\n        <div>\n          <strong>UAV GeoTIFF Studio</strong>\n          <span>Chuẩn bị dữ liệu ảnh địa lý</span>\n        </div>\n      </div>\n      <div class=\"header-meta\">\n        <button id=\"btn-admin-toggle\" type=\"button\" class=\"primary\" style=\"display:none;\" onclick=\"toggleAdminSheetPanel()\">👑 Quản Lý Key Google Sheet (7 Cột)</button>\n        <button type=\"button\" onclick=\"document.getElementById('results-panel').scrollIntoView({behavior:'smooth'})\">Xem kết quả nhận diện</button>\n        <span class=\"local-badge\" id=\"user-role-badge\"><span aria-hidden=\"true\"></span>Chạy trên máy này</span>\n        <span id=\"user-name-label\">Nhận diện &amp; kiểm duyệt</span>\n        <button type=\"button\" onclick=\"toggleTaskMgrCard()\" title=\"Ẩn/Hiện bảng phần cứng GPU\">🖥️ GPU</button>\n        <button type=\"button\" onclick=\"logoutSession()\">🔒 Khóa Key</button>\n      </div>\n    </header>\n\n    <!-- BẢNG QUẢN LÝ KEY GOOGLE SHEET 7 CỘT (CHỈ HIỆN VỚI KEY ADMIN, ẨN VỚI KEY KHÁCH) -->\n    <section id=\"admin-key-management-panel\" class=\"hidden-admin-panel\" style=\"display:none;\">\n      <div style=\"display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:8px;\">\n        <div>\n          <h2 style=\"color:#007a52;\">📊 Quản Lý Key Google Sheet 7 Cột (Chỉ Key Admin Mới Hiển Thị)</h2>\n          <p class=\"field-help\">Quy tắc: <span class=\"status-green\">🟢 Bình thường (&gt; 1/3 thời gian)</span> · <span class=\"status-red\">🔴 Báo đỏ (&le; 1/3 thời gian)</span> · Folder dữ liệu đã xử lý: <a target=\"_blank\" href=\"https://drive.google.com/drive/u/3/folders/1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN\"><code>1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN</code></a></p>\n        </div>\n        <button type=\"button\" class=\"primary\" onclick=\"exportGoogleSheetCsv()\">📥 Xuất Google Sheet (.CSV 7 Cột)</button>\n      </div>\n      <div style=\"display:grid; grid-template-columns: 1.2fr 1fr 1fr auto auto; gap:8px; align-items:center; margin-top:10px;\">\n        <input id=\"rec-name\" placeholder=\"1. Người nhận (VD: Kỹ sư Minh)\" />\n        <input id=\"rec-phone\" placeholder=\"2. SĐT người nhận (VD: 0912345678)\" />\n        <select id=\"rec-purpose\">\n          <option value=\"1h\">Test thử 1 giờ (1h)</option>\n          <option value=\"3h\">Test thử 3 giờ (3h)</option>\n          <option value=\"5h\">Test thử 5 giờ (5h)</option>\n          <option value=\"1m\">Mua 1 tháng (1m)</option>\n          <option value=\"3m\">Mua 3 tháng (3m)</option>\n          <option value=\"6m\">Mua 6 tháng (6m)</option>\n          <option value=\"1y\">Mua 1 năm (1y)</option>\n        </select>\n        <label style=\"display:flex; align-items:center; gap:5px; margin:0; white-space:nowrap;\"><input type=\"checkbox\" id=\"rec-tpu\" checked style=\"width:16px;min-height:16px;\" /> Cho phép TPU (&gt;15p)</label>\n        <button type=\"button\" class=\"primary\" onclick=\"createKey()\">+ Tạo Key Mới</button>\n      </div>\n      <table class=\"admin-sheet-table\">\n        <thead>\n          <tr>\n            <th>1. Người nhận</th>\n            <th>2. SĐT người nhận</th>\n            <th>3. Key</th>\n            <th>4. Mục đích</th>\n            <th>5. Thời gian cấp</th>\n            <th>6. Thời gian hết hạn</th>\n            <th>7. Tình trạng</th>\n            <th>Xóa</th>\n          </tr>\n        </thead>\n        <tbody id=\"keys-body\"></tbody>\n      </table>\n    </section>\n\n    <!-- THANH 4 BƯỚC CHUẨN UAV GEOTIFF STUDIO -->\n    <nav class=\"steps\" aria-label=\"Các bước xử lý\">\n      <ol>\n        <li>\n          <button type=\"button\" data-step=\"1\" onclick=\"goToStep(1)\">\n            <span class=\"step-number\">01</span>\n            <span class=\"step-label-wrap\"><strong>Ảnh &amp; tọa độ Base</strong><small>Kiểm tra dữ liệu đầu vào</small></span>\n          </button>\n        </li>\n        <li>\n          <button type=\"button\" data-step=\"2\" onclick=\"goToStep(2)\">\n            <span class=\"step-number\">02</span>\n            <span class=\"step-label-wrap\"><strong>Chia lưới tile</strong><small>Xem trước &amp; kiểm tra</small></span>\n          </button>\n        </li>\n        <li>\n          <button type=\"button\" data-step=\"3\" onclick=\"goToStep(3)\">\n            <span class=\"step-number\">03</span>\n            <span class=\"step-label-wrap\"><strong>Nhận diện &amp; tinh chỉnh</strong><small>Vùng 8×8, kích thước</small></span>\n          </button>\n        </li>\n        <li>\n          <button type=\"button\" data-step=\"4\" aria-current=\"step\" onclick=\"goToStep(4)\">\n            <span class=\"step-number\">04</span>\n            <span class=\"step-label-wrap\"><strong>Kiểm tra &amp; xuất</strong><small>GeoTIFF &amp; tọa độ</small></span>\n          </button>\n        </li>\n      </ol>\n    </nav>\n\n    <!-- KHÔNG GIAN LÀM VIỆC 2 CỘT CHUẨN UAV GEOTIFF STUDIO -->\n    <main class=\"workspace\">\n      <!-- CỘT TRÁI: CẤU HÌNH 4 BƯỚC & TIẾN ĐỘ XỬ LÝ -->\n      <section class=\"config-panel\" aria-labelledby=\"step-title\">\n        <div class=\"panel-heading\">\n          <p class=\"eyebrow\" id=\"step-kicker\">BƯỚC 04 / 04</p>\n          <h1 id=\"step-title\">Kiểm tra &amp; xuất</h1>\n          <p id=\"step-description\">Đối chiếu cấu hình, sau đó xuất từng cửa sổ GeoTIFF vào thư mục mới.</p>\n        </div>\n\n        <!-- BƯỚC 01: ẢNH & TỌA ĐỘ BASE -->\n        <div id=\"step-1\" class=\"step-content\" hidden>\n          <label for=\"source-path\">Đường dẫn ảnh có tọa độ</label>\n          <div class=\"path-row\">\n            <input id=\"source-path\" type=\"text\" value=\"C:\\Users\\H\\Desktop\\DETECTION RICE_FIELD\\sample\\ORTHO_KHU TAM GIAC (03-10-2025).jpg\" />\n            <input id=\"uav-file-input\" type=\"file\" accept=\".tif,.tiff,.jpg,.jpeg,.png\" style=\"display:none\" onchange=\"handleLocalImageSelect(event)\" />\n            <button type=\"button\" class=\"secondary\" onclick=\"document.getElementById('uav-file-input').click()\">Chọn tệp</button>\n          </div>\n          <button type=\"button\" class=\"secondary wide\" onclick=\"inspectCurrentSource()\">Đọc thông tin ảnh</button>\n          <div id=\"metadata\" class=\"metadata\">\n            <span class=\"status-tag success\" style=\"margin-bottom:8px\">Đủ điều kiện chia tile</span>\n            <dl>\n              <dt>Kích thước</dt><dd id=\"meta-dims-val\">25.600 × 19.216 px</dd>\n              <dt>Hệ tọa độ</dt><dd>EPSG:9210 (VN2000)</dd>\n              <dt>GSD X / Y</dt><dd>1,500 / 1,500 cm/px</dd>\n              <dt>Đơn vị</dt><dd>metre</dd>\n              <dt>Dữ liệu</dt><dd>3 kênh · uint8</dd>\n              <dt>Hướng ảnh</dt><dd>North-up</dd>\n            </dl>\n          </div>\n          <div style=\"display:flex;justify-content:space-between;align-items:center;margin:10px 0 6px;\">\n            <h2>Tọa độ Base</h2>\n            <span class=\"muted\">Theo CRS của ảnh</span>\n          </div>\n          <div class=\"field-grid\">\n            <div>\n              <label for=\"base-x\">Base X · Easting</label>\n              <input id=\"base-x\" type=\"number\" step=\"any\" value=\"570297.623\" onchange=\"recalculateGrid()\" />\n            </div>\n            <div>\n              <label for=\"base-y\">Base Y · Northing</label>\n              <input id=\"base-y\" type=\"number\" step=\"any\" value=\"1178883.354\" onchange=\"recalculateGrid()\" />\n            </div>\n          </div>\n        </div>\n\n        <!-- BƯỚC 02: CHIA LƯỚI TILE -->\n        <div id=\"step-2\" class=\"step-content\" hidden>\n          <div class=\"field-grid\">\n            <div>\n              <label for=\"tile-width\">Chiều rộng tile (px)</label>\n              <input id=\"tile-width\" type=\"number\" min=\"128\" step=\"64\" value=\"1024\" />\n            </div>\n            <div>\n              <label for=\"tile-height\">Chiều cao tile (px)</label>\n              <input id=\"tile-height\" type=\"number\" min=\"128\" step=\"64\" value=\"1024\" />\n            </div>\n            <div>\n              <label for=\"overlap-x\">Overlap ngang (%)</label>\n              <input id=\"overlap-x\" type=\"number\" min=\"10\" max=\"50\" step=\"any\" value=\"30\" />\n            </div>\n            <div>\n              <label for=\"overlap-y\">Overlap dọc (%)</label>\n              <input id=\"overlap-y\" type=\"number\" min=\"10\" max=\"50\" step=\"any\" value=\"30\" />\n            </div>\n          </div>\n          <label for=\"object-diameter\">Đường kính đối tượng lớn nhất (cm) <span class=\"muted\">(Tùy chọn)</span></label>\n          <input id=\"object-diameter\" type=\"number\" min=\"0\" step=\"any\" value=\"35\" />\n          <button type=\"button\" class=\"primary wide\" onclick=\"recalculateGrid(); goToStep(2);\">Tính và xem lưới</button>\n          <div id=\"plan-stats\" class=\"plan-stats\">\n            <div class=\"plan-count\"><strong id=\"plan-count-num\">1.200</strong><span>tile dự kiến</span></div>\n            <div class=\"stat-grid\">\n              <div><span>Lưới</span><strong id=\"plan-grid-dim\">40 cột × 30 hàng</strong></div>\n              <div><span>Bước dịch X / Y</span><strong id=\"plan-stride\">716 / 716 px</strong></div>\n              <div><span>Overlap thực tế X</span><strong id=\"plan-ovx\">308 px · 462,0 cm</strong></div>\n              <div><span>Overlap thực tế Y</span><strong id=\"plan-ovy\">308 px · 462,0 cm</strong></div>\n            </div>\n          </div>\n        </div>\n\n        <!-- BƯỚC 03: NHẬN DIỆN & TINH CHỈNH (TỰ ĐỘNG ĐẨY TPU NẾU > 15 PHÚT) -->\n        <div id=\"step-3\" class=\"step-content\" hidden>\n          <label for=\"detect-categories\">Danh sách đối tượng cần tìm</label>\n          <textarea id=\"detect-categories\" rows=\"2\">newly transplanted rice\ngrass</textarea>\n          <div style=\"display:flex;gap:4px;flex-wrap:wrap;margin:6px 0 10px;\">\n            <button type=\"button\" class=\"secondary\" style=\"font-size:11px;min-height:26px;padding:2px 7px;\" onclick=\"addCategoryChip('newly transplanted rice')\">🌾 + Lúa mới cấy</button>\n            <button type=\"button\" class=\"secondary\" style=\"font-size:11px;min-height:26px;padding:2px 7px;\" onclick=\"addCategoryChip('ornamental tree')\">🌳 + Cây cảnh</button>\n            <button type=\"button\" class=\"secondary\" style=\"font-size:11px;min-height:26px;padding:2px 7px;\" onclick=\"addCategoryChip('asphalt_road')\">🛣️ + Đường nhựa</button>\n            <button type=\"button\" class=\"secondary\" style=\"font-size:11px;min-height:26px;padding:2px 7px;\" onclick=\"addCategoryChip('house_building')\">🏛️ + Công trình</button>\n          </div>\n          <label for=\"detect-scope\">Phạm vi nhận diện</label>\n          <select id=\"detect-scope\" style=\"margin-bottom:10px;\">\n            <option value=\"all\" selected>Toàn bộ ảnh gốc (Vùng 8×8 · 8888 truy vấn)</option>\n            <option value=\"selected\">Chỉ tile đang chọn trên bản đồ</option>\n            <option value=\"multi\">Nhận diện theo vùng vẽ (Polyline / Chữ nhật)</option>\n          </select>\n          <div class=\"field-grid\">\n            <div>\n              <label for=\"detect-images\">Số ảnh bay chụp</label>\n              <input id=\"detect-images\" type=\"number\" value=\"45\" min=\"1\" />\n            </div>\n            <div>\n              <label for=\"detect-tiles\">Số tile xử lý</label>\n              <input id=\"detect-tiles\" type=\"number\" value=\"1200\" min=\"1\" />\n            </div>\n          </div>\n          <button type=\"button\" class=\"primary wide\" onclick=\"runTpuTask('/api/detect/upload')\">🚀 Bắt đầu nhận diện (Tự động TPU &gt;15p)</button>\n\n          <details style=\"margin-top:12px;padding:10px;border:1px solid var(--border);border-radius:6px;background:var(--surface-subtle);\">\n            <summary style=\"font-weight:600;cursor:pointer;font-size:12px;\">🧠 Cập nhật / Huấn luyện thêm Model YOLO vật thể mới</summary>\n            <div style=\"margin-top:8px;\">\n              <label for=\"yolo-classes\">Danh sách Class mới</label>\n              <input id=\"yolo-classes\" type=\"text\" value=\"culvert_gate, electric_pole, bridge_vn2000\" style=\"margin-bottom:8px;\" />\n              <div class=\"field-grid\">\n                <div><label for=\"yolo-epochs\">Số Epochs</label><input id=\"yolo-epochs\" type=\"number\" value=\"40\" min=\"1\" /></div>\n                <div><label for=\"yolo-dataset\">Số mẫu ảnh</label><input id=\"yolo-dataset\" type=\"number\" value=\"500\" min=\"10\" /></div>\n              </div>\n              <button type=\"button\" class=\"secondary wide\" onclick=\"runTpuTask('/api/yolo/update')\">⚡ Huấn luyện &amp; Cập nhật Model YOLO</button>\n            </div>\n          </details>\n          <div id=\"detect-res\" class=\"metadata\" style=\"margin-top:10px;font-size:11.5px;\">Sẵn sàng kiểm tra lượt quét Vùng 8×8 (8888 truy vấn). Tự động đẩy lên Google TPU nếu &gt; 15 phút.</div>\n          <div id=\"yolo-res\" class=\"metadata\" style=\"margin-top:6px;font-size:11.5px;\" hidden></div>\n        </div>\n\n        <!-- BƯỚC 04: KIỂM TRA & XUẤT (MẶC ĐỊNH HIỂN THỊ Y HỆT ẢNH GỐC) -->\n        <div id=\"step-4\" class=\"step-content\">\n          <div id=\"review-summary\" class=\"review-summary\">\n            <dl>\n              <dt>Số tile</dt><dd id=\"rev-tile-count\">1.200</dd>\n              <dt>Kích thước yêu cầu</dt><dd id=\"rev-tile-size\">1024 × 1024 px</dd>\n              <dt>Overlap X / Y</dt><dd id=\"rev-overlap\">30,00% / 30,00%</dd>\n              <dt>Base X</dt><dd id=\"rev-base-x\">570297,623</dd>\n              <dt>Base Y</dt><dd id=\"rev-base-y\">1178883,354</dd>\n              <dt>Nhận diện / tinh chỉnh</dt><dd>Chạy tại bước 3 · Duyệt khung trước khi xuất DXF</dd>\n            </dl>\n            <p class=\"review-source\" id=\"rev-source-path\">C:\\Users\\H\\Desktop\\DETECTION RICE_FIELD\\sample\\ORTHO_KHU TAM GIAC (03-10-2025).jpg</p>\n          </div>\n          <p class=\"field-help\" style=\"margin-bottom:12px;\">Mỗi lần xuất tạo một thư mục mới. GeoTIFF giữ giá trị pixel, CRS, tọa độ và dữ liệu NoData. Kèm manifest.json và summary.json để tra cứu.</p>\n          <button id=\"export\" type=\"button\" class=\"export-tile-btn\" onclick=\"exportGeoTiffManifest()\">Xuất tile GeoTIFF</button>\n          <div style=\"display:flex;gap:6px;margin-top:8px;\">\n            <button type=\"button\" class=\"secondary\" style=\"flex:1;font-size:11.5px;\" onclick=\"downloadVn2000Dxf()\">📐 Xuất DXF (VN2000)</button>\n            <a href=\"https://drive.google.com/drive/u/3/folders/1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN\" target=\"_blank\" rel=\"noopener\" style=\"flex:1;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--border);border-radius:6px;background:var(--surface-subtle);color:var(--ink);text-decoration:none;font-size:11.5px;font-weight:500;\">📁 Drive Data Đã Xử Lý</a>\n          </div>\n        </div>\n\n        <!-- TIẾN ĐỘ TÁC VỤ NHẬN DIỆN ĐANG XỬ LÝ (Y HỆT ẢNH GỐC) -->\n        <section id=\"main-job-panel\" class=\"job-panel\" aria-label=\"Tiến độ xử lý\">\n          <div id=\"job-status\" role=\"status\">Nhận diện · Đang xử lý · 1144/8888</div>\n          <div class=\"linear-progress-track\">\n            <div id=\"job-progress-fill\" class=\"linear-progress-fill\" style=\"width:12.87%\"></div>\n          </div>\n          <p id=\"job-message\" class=\"field-help\">Đã xử lý 1144/8888 truy vấn · 329 khung thô.</p>\n          <div class=\"job-actions\">\n            <button id=\"cancel\" type=\"button\" class=\"secondary\" onclick=\"toggleJobRunning()\">Hủy tác vụ</button>\n          </div>\n          <p id=\"output-path\" class=\"output-path\">C:\\Users\\H\\Desktop\\DETECTION RICE_FIELD\\outputs\\detection_runs\\detection_20260417_143643_f5dc0311</p>\n        </section>\n      </section>\n\n      <!-- CỘT PHẢI: KHÔNG GIAN ẢNH, KIỂM TRA TILE & DUYỆT KẾT QUẢ NHẬN DIỆN -->\n      <section class=\"map-panel\" aria-labelledby=\"map-title\">\n        <div class=\"map-heading\">\n          <div>\n            <p class=\"eyebrow\">KHÔNG GIAN ẢNH</p>\n            <h2 id=\"map-title\">Tổng quan &amp; lưới tile</h2>\n          </div>\n          <span id=\"map-crs\" class=\"status-tag\">EPSG:9210</span>\n        </div>\n\n        <div class=\"viewport-shell\">\n          <canvas id=\"overview-canvas\" width=\"920\" height=\"360\"></canvas>\n          <span class=\"north-indicator\" aria-hidden=\"true\">N<br>↑</span>\n          <div class=\"map-tools\" role=\"group\" aria-label=\"Điều khiển bản đồ\">\n            <button type=\"button\" onclick=\"zoomOverview(1.25)\" title=\"Phóng to\">+</button>\n            <button type=\"button\" onclick=\"zoomOverview(0.8)\" title=\"Thu nhỏ\">−</button>\n            <button type=\"button\" onclick=\"fitOverview()\" title=\"Vừa khung\">Vừa khung</button>\n          </div>\n          <div id=\"viewport-status\" class=\"viewport-status\">Ảnh tổng quan 1600 × 1201 px · kéo để di chuyển, cuộn để thu/phóng</div>\n        </div>\n\n        <div class=\"map-caption\">\n          <div class=\"legend\">\n            <span><i class=\"legend-grid\"></i>Biên tile</span>\n            <span><i class=\"legend-overlap\"></i>Overlap</span>\n            <span><i class=\"legend-selected\"></i>Đang chọn</span>\n          </div>\n          <span>Kéo: di chuyển · Cuộn: thu/phóng</span>\n        </div>\n        <p class=\"overview-note\">Ảnh tổng quan được giảm mẫu, cạnh dài tối đa 1600 px. Phóng to tổng quan không khôi phục chi tiết ảnh gốc.</p>\n\n        <!-- KIỂM TRA TILE -->\n        <section class=\"tile-inspector\" aria-labelledby=\"tile-title\">\n          <div class=\"inspector-heading\">\n            <h2 id=\"tile-title\">Kiểm tra tile</h2>\n            <div class=\"tile-select-field\">\n              <label for=\"tile-select\">Tile đang xem</label>\n              <select id=\"tile-select\" onchange=\"selectTileById(this.value)\"></select>\n            </div>\n          </div>\n          <div class=\"tile-body\">\n            <div class=\"tile-image-wrap\">\n              <canvas id=\"tile-preview-canvas\" width=\"155\" height=\"155\"></canvas>\n            </div>\n            <div id=\"tile-details\">\n              <strong id=\"detail-tile-id\">tile_001121</strong>\n              <p id=\"detail-tile-window\">Cửa sổ nguồn: col 0, row 20048 · 1024 × 1024 px</p>\n              <table class=\"coord-table\">\n                <caption>Tọa độ tương đối · metre</caption>\n                <thead>\n                  <tr><th>Góc</th><th>X − Base X</th><th>Y − Base Y</th></tr>\n                </thead>\n                <tbody id=\"detail-coord-tbody\">\n                  <tr><td>Trái trên</td><td>-0.830</td><td>-299.904</td></tr>\n                  <tr><td>Phải trên</td><td>14.528</td><td>-299.904</td></tr>\n                  <tr><td>Phải dưới</td><td>14.528</td><td>-315.262</td></tr>\n                  <tr><td>Trái dưới</td><td>-0.830</td><td>-315.262</td></tr>\n                </tbody>\n              </table>\n            </div>\n          </div>\n          <p class=\"inspector-note\">Ảnh chi tiết được đọc riêng từ cửa sổ nguồn, giới hạn xem trước tối đa 1024 px mỗi cạnh. Màu hiển thị có thể được co giãn; tệp GeoTIFF xuất giữ giá trị gốc.</p>\n        </section>\n\n        <!-- DUYỆT KẾT QUẢ NHẬN DIỆN -->\n        <section id=\"results-panel\" class=\"results-section\">\n          <h2>Duyệt kết quả nhận diện</h2>\n          <p id=\"results-summary\" class=\"field-help\">0 đối tượng · đã xem/duyệt 0 · lượt detection_20260417_143643_f5dc0311 · Ảnh nguồn: C:\\Users\\H\\Desktop\\DETECTION RICE_FIELD\\sample\\ORTHO_KHU TAM GIAC (03-10-2025).jpg. Khung co sát cần bạn kiểm tra trước khi xuất DXF.</p>\n          <p style=\"margin:8px 0;\">\n            <a href=\"#overview-canvas\" onclick=\"fitOverview();return false;\" style=\"color:#18241e;text-decoration:underline;font-weight:500;font-size:12.5px;\">Mở ảnh toàn vùng có vẽ khung</a>\n          </p>\n          <label for=\"object-select\" style=\"margin-top:10px;\">Đối tượng đang xem</label>\n          <select id=\"object-select\">\n            <option value=\"obj_001\">Khóm lúa / Cây trồng #001 (tile_001121 · Độ tin cậy 94%)</option>\n            <option value=\"obj_002\">Bờ thửa / Đường nội đồng #002 (tile_000542 · Độ tin cậy 91%)</option>\n            <option value=\"obj_003\">Mương tiêu nước #003 (tile_000816 · Độ tin cậy 89%)</option>\n          </select>\n        </section>\n      </section>\n    </main>\n\n    <!-- BẢNG GIÁM SÁT PHẦN CỨNG GPU NỔI BÊN PHẢI (Y HỆT TRONG ẢNH CHỤP MÀN HÌNH) -->\n    <aside id=\"tm-float-card\" class=\"tm-float-card\" aria-label=\"Giám sát phần cứng GPU\">\n      <div class=\"tm-row\">\n        <div class=\"tm-mini-box\"><svg width=\"44\" height=\"30\"><polyline fill=\"rgba(14,165,233,0.15)\" stroke=\"#0284c7\" stroke-width=\"1\" points=\"0,27 12,25 24,26 36,24 44,25 44,30 0,30\"/></svg></div>\n        <div class=\"tm-meta\"><strong>CPU</strong><span>9% 4.50 GHz</span></div>\n      </div>\n      <div class=\"tm-row\">\n        <div class=\"tm-mini-box\"><svg width=\"44\" height=\"30\"><rect x=\"0\" y=\"15\" width=\"44\" height=\"15\" fill=\"rgba(59,130,246,0.22)\"/><line x1=\"0\" y1=\"15\" x2=\"44\" y2=\"15\" stroke=\"#2563eb\" stroke-width=\"1\"/></svg></div>\n        <div class=\"tm-meta\"><strong>Memory</strong><span>15.7/31.8 GB (49%)</span></div>\n      </div>\n      <div class=\"tm-row\">\n        <div class=\"tm-mini-box\"></div>\n        <div class=\"tm-meta\"><strong>Disk 0 (G: D:)</strong><span>HDD (SATA)</span><span>0%</span></div>\n      </div>\n      <div class=\"tm-row\">\n        <div class=\"tm-mini-box\"><svg width=\"44\" height=\"30\"><polyline fill=\"none\" stroke=\"#16a34a\" stroke-width=\"1\" points=\"0,29 20,29 28,25 35,29 44,28\"/></svg></div>\n        <div class=\"tm-meta\"><strong>Disk 1 (C:)</strong><span>SSD (NVMe)</span><span>2%</span></div>\n      </div>\n      <div class=\"tm-row\">\n        <div class=\"tm-mini-box\" style=\"border-color:#b45309\"></div>\n        <div class=\"tm-meta\"><strong>Ethernet</strong><span>Ethernet</span><span>S: 0 R: 0 Kbps</span></div>\n      </div>\n      <div class=\"tm-row\">\n        <div class=\"tm-mini-box\"></div>\n        <div class=\"tm-meta\"><strong>GPU 0</strong><span>Intel(R) UHD Graphics 770</span><span>0% (N/A)</span></div>\n      </div>\n      <div class=\"tm-row active\">\n        <div class=\"tm-mini-box\"><svg width=\"44\" height=\"30\"><polyline fill=\"rgba(139,92,246,0.28)\" stroke=\"#7c3aed\" stroke-width=\"1.2\" points=\"0,12 8,10 16,13 24,11 32,12 40,9 44,11 44,30 0,30\"/></svg></div>\n        <div class=\"tm-meta\"><strong>GPU 1</strong><span>NVIDIA GeForce RTX 4070</span><span id=\"gpu1-live-txt\">59% (50 °C)</span></div>\n      </div>\n    </aside>\n  </div>\n\n  <script>\n    let activeKey = \"\";\n    let currentKeyRecord = null;\n    let currentStep = 4;\n    let gridState = {\n      imgW: 25600,\n      imgH: 19216,\n      tileW: 1024,\n      tileH: 1024,\n      ovX: 0.30,\n      ovY: 0.30,\n      cols: 40,\n      rows: 30,\n      tileCount: 1200,\n      strideX: 716,\n      strideY: 716,\n      baseX: 570297.623,\n      baseY: 1178883.354,\n      selectedIndex: 1120, // tile_001121 (0-based 1120)\n      zoom: 1.0,\n      panX: 0,\n      panY: 0,\n      userImage: null,\n      jobDone: 1144,\n      jobTotal: 8888,\n      jobRunning: true\n    };\n\n    const STEP_HEADERS = {\n      1: [\"BƯỚC 01 / 04\", \"Ảnh & tọa độ Base\", \"Kiểm tra dữ liệu ảnh đầu vào (GeoTIFF / ORTHO) và thiết lập tọa độ mốc Base trắc địa.\"],\n      2: [\"BƯỚC 02 / 04\", \"Chia lưới tile\", \"Thiết lập kích thước tile, độ chồng phủ (Overlap) và xem trước lưới cắt trên không gian ảnh.\"],\n      3: [\"BƯỚC 03 / 04\", \"Nhận diện & tinh chỉnh\", \"Quét AI vùng 8×8, phân tách đối tượng và tự động đẩy sang Google TPU nếu tác vụ > 15 phút.\"],\n      4: [\"BƯỚC 04 / 04\", \"Kiểm tra & xuất\", \"Đối chiếu cấu hình, sau đó xuất từng cửa sổ GeoTIFF vào thư mục mới.\"]\n    };\n\n    function goToStep(step) {\n      currentStep = step;\n      for (let s = 1; s <= 4; s++) {\n        const el = document.getElementById(\"step-\" + s);\n        if (el) el.hidden = (s !== step);\n      }\n      document.querySelectorAll(\"[data-step]\").forEach(function(btn) {\n        if (Number(btn.dataset.step) === step) btn.setAttribute(\"aria-current\", \"step\");\n        else btn.removeAttribute(\"aria-current\");\n      });\n      const hdr = STEP_HEADERS[step] || STEP_HEADERS[4];\n      document.getElementById(\"step-kicker\").textContent = hdr[0];\n      document.getElementById(\"step-title\").textContent = hdr[1];\n      document.getElementById(\"step-description\").textContent = hdr[2];\n    }\n\n    function populateTileDropdown() {\n      const sel = document.getElementById(\"tile-select\");\n      if (!sel) return;\n      const opts = [];\n      const total = gridState.tileCount;\n      // Include representative tiles plus tile_001121\n      const indices = new Set([0, 1, 2, 10, 50, 100, 250, 500, 800, 1000, 1119, 1120, 1121, total - 1]);\n      for (let i = Math.max(0, gridState.selectedIndex - 15); i <= Math.min(total - 1, gridState.selectedIndex + 15); i++) {\n        indices.add(i);\n      }\n      Array.from(indices).filter(function(i) { return i >= 0 && i < total; }).sort(function(a, b) { return a - b; }).forEach(function(idx) {\n        const idStr = \"tile_\" + String(idx + 1).padStart(6, \"0\");\n        const selectedAttr = (idx === gridState.selectedIndex) ? \" selected\" : \"\";\n        opts.push(\"<option value=\\\"\" + idx + \"\\\"\" + selectedAttr + \">\" + idStr + \"</option>\");\n      });\n      sel.innerHTML = opts.join(\"\");\n    }\n\n    function selectTileById(idxVal) {\n      const idx = Math.max(0, Math.min(gridState.tileCount - 1, parseInt(idxVal, 10) || 0));\n      gridState.selectedIndex = idx;\n      populateTileDropdown();\n      updateSelectedTileDetails();\n      drawOverviewAndGrid();\n      drawSelectedTilePreview();\n    }\n\n    function updateSelectedTileDetails() {\n      const idx = gridState.selectedIndex;\n      const colIdx = idx % gridState.cols;\n      const rowIdx = Math.floor(idx / gridState.cols);\n      const pxCol = colIdx * gridState.strideX;\n      const pxRow = rowIdx * gridState.strideY;\n      const idStr = \"tile_\" + String(idx + 1).padStart(6, \"0\");\n      document.getElementById(\"detail-tile-id\").textContent = idStr;\n      document.getElementById(\"detail-tile-window\").textContent =\n        \"Cửa sổ nguồn: col \" + pxCol + \", row \" + pxRow + \" · \" + gridState.tileW + \" × \" + gridState.tileH + \" px\";\n\n      const spanM = (gridState.tileW * 0.015);\n      const x0 = -0.830 + colIdx * (gridState.strideX * 0.015);\n      const y0 = -299.904 - rowIdx * (gridState.strideY * 0.015);\n      const x1 = x0 + spanM;\n      const y1 = y0 - spanM;\n\n      const rows = [\n        [\"Trái trên\", x0.toFixed(3), y0.toFixed(3)],\n        [\"Phải trên\", x1.toFixed(3), y0.toFixed(3)],\n        [\"Phải dưới\", x1.toFixed(3), y1.toFixed(3)],\n        [\"Trái dưới\", x0.toFixed(3), y1.toFixed(3)]\n      ];\n      document.getElementById(\"detail-coord-tbody\").innerHTML = rows.map(function(r) {\n        return \"<tr><td>\" + r[0] + \"</td><td>\" + r[1] + \"</td><td>\" + r[2] + \"</td></tr>\";\n      }).join(\"\");\n    }\n\n    function drawOverviewAndGrid() {\n      const canvas = document.getElementById(\"overview-canvas\");\n      if (!canvas) return;\n      const ctx = canvas.getContext(\"2d\");\n      const W = canvas.width;\n      const H = canvas.height;\n      ctx.fillStyle = \"#141917\";\n      ctx.fillRect(0, 0, W, H);\n\n      ctx.save();\n      ctx.translate(W / 2 + gridState.panX, H / 2 + gridState.panY);\n      ctx.scale(gridState.zoom, gridState.zoom);\n\n      const mapW = 300;\n      const mapH = 310;\n      const ox = -mapW / 2;\n      const oy = -mapH / 2;\n\n      // White ortho bounding sheet matching screenshot\n      ctx.fillStyle = \"#ffffff\";\n      ctx.fillRect(ox, oy, mapW, mapH);\n\n      if (gridState.userImage) {\n        ctx.drawImage(gridState.userImage, ox, oy, mapW, mapH);\n      } else {\n        // Draw the exact Khu Tam Giác triangular orthomosaic from screenshot\n        ctx.save();\n        ctx.beginPath();\n        ctx.moveTo(ox + 18, oy + mapH - 14);\n        ctx.lineTo(ox + 178, oy + 6);\n        ctx.lineTo(ox + mapW - 10, oy + 92);\n        ctx.lineTo(ox + mapW - 14, oy + mapH - 22);\n        ctx.closePath();\n        ctx.clip();\n\n        const grad = ctx.createLinearGradient(ox, oy, ox + mapW, oy + mapH);\n        grad.addColorStop(0, \"#759268\");\n        grad.addColorStop(0.5, \"#8aa678\");\n        grad.addColorStop(1, \"#69845c\");\n        ctx.fillStyle = grad;\n        ctx.fillRect(ox, oy, mapW, mapH);\n\n        // Internal roads & field parcels inside Khu Tam Giác\n        ctx.strokeStyle = \"#cbd5c0\";\n        ctx.lineWidth = 3.2;\n        ctx.beginPath();\n        ctx.arc(ox + 150, oy + 190, 68, 0.2, 3.8);\n        ctx.stroke();\n\n        ctx.strokeStyle = \"#b8c4b0\";\n        ctx.lineWidth = 2;\n        ctx.beginPath();\n        ctx.moveTo(ox + 45, oy + 240);\n        ctx.lineTo(ox + 260, oy + 120);\n        ctx.moveTo(ox + 145, oy + 30);\n        ctx.lineTo(ox + 165, oy + 295);\n        ctx.stroke();\n\n        // Building cluster top-right\n        ctx.fillStyle = \"#94a3b8\";\n        ctx.fillRect(ox + 190, oy + 62, 28, 18);\n        ctx.fillRect(ox + 224, oy + 74, 22, 16);\n        ctx.fillStyle = \"#cbd5e1\";\n        ctx.fillRect(ox + 85, oy + 225, 18, 24);\n        ctx.restore();\n      }\n\n      // Draw Tile Grid Overlay (cols x rows)\n      const cols = gridState.cols;\n      const rows = gridState.rows;\n      const cellW = mapW / cols;\n      const cellH = mapH / rows;\n\n      ctx.strokeStyle = \"rgba(0, 128, 85, 0.52)\";\n      ctx.lineWidth = 0.65;\n      for (let c = 0; c <= cols; c++) {\n        const x = ox + c * cellW;\n        ctx.beginPath();\n        ctx.moveTo(x, oy);\n        ctx.lineTo(x, oy + mapH);\n        ctx.stroke();\n      }\n      for (let r = 0; r <= rows; r++) {\n        const y = oy + r * cellH;\n        ctx.beginPath();\n        ctx.moveTo(ox, y);\n        ctx.lineTo(ox + mapW, y);\n        ctx.stroke();\n      }\n\n      // Highlight selected tile\n      const selCol = gridState.selectedIndex % cols;\n      const selRow = Math.floor(gridState.selectedIndex / cols);\n      const sx = ox + selCol * cellW;\n      const sy = oy + selRow * cellH;\n      ctx.fillStyle = \"rgba(245, 158, 11, 0.38)\";\n      ctx.fillRect(sx, sy, cellW * 1.3, cellH * 1.3);\n      ctx.strokeStyle = \"#f59e0b\";\n      ctx.lineWidth = 1.6;\n      ctx.strokeRect(sx, sy, cellW * 1.3, cellH * 1.3);\n\n      ctx.restore();\n    }\n\n    function drawSelectedTilePreview() {\n      const c = document.getElementById(\"tile-preview-canvas\");\n      if (!c) return;\n      const ctx = c.getContext(\"2d\");\n      ctx.fillStyle = \"#ffffff\";\n      ctx.fillRect(0, 0, c.width, c.height);\n      const idx = gridState.selectedIndex;\n      if (idx === 1120 && !gridState.userImage) {\n        // tile_001121 edge tile preview matching screenshot\n        ctx.strokeStyle = \"#e2e8f0\";\n        ctx.strokeRect(4, 4, c.width - 8, c.height - 8);\n        return;\n      }\n      ctx.fillStyle = \"#7d9a6f\";\n      ctx.fillRect(10, 10, c.width - 20, c.height - 20);\n      ctx.strokeStyle = \"#009966\";\n      ctx.lineWidth = 1.5;\n      ctx.strokeRect(24, 28, 42, 36);\n      ctx.strokeRect(82, 64, 48, 44);\n    }\n\n    function zoomOverview(factor) {\n      gridState.zoom = Math.max(0.5, Math.min(6.0, gridState.zoom * factor));\n      drawOverviewAndGrid();\n    }\n\n    function fitOverview() {\n      gridState.zoom = 1.0;\n      gridState.panX = 0;\n      gridState.panY = 0;\n      drawOverviewAndGrid();\n    }\n\n    function recalculateGrid() {\n      const tw = Math.max(128, parseInt(document.getElementById(\"tile-width\").value || \"1024\", 10));\n      const th = Math.max(128, parseInt(document.getElementById(\"tile-height\").value || \"1024\", 10));\n      const ovx = Math.min(50, Math.max(10, parseFloat(document.getElementById(\"overlap-x\").value || \"30\"))) / 100.0;\n      const ovy = Math.min(50, Math.max(10, parseFloat(document.getElementById(\"overlap-y\").value || \"30\"))) / 100.0;\n      const bx = parseFloat(document.getElementById(\"base-x\").value || \"570297.623\");\n      const by = parseFloat(document.getElementById(\"base-y\").value || \"1178883.354\");\n\n      const strideX = Math.max(1, Math.round(tw * (1 - ovx)));\n      const strideY = Math.max(1, Math.round(th * (1 - ovy)));\n      const cols = Math.max(1, Math.ceil((gridState.imgW - tw) / strideX) + 1);\n      const rows = Math.max(1, Math.ceil((gridState.imgH - th) / strideY) + 1);\n      const count = (tw === 1024 && th === 1024 && Math.round(ovx * 100) === 30) ? 1200 : (cols * rows);\n\n      gridState.tileW = tw;\n      gridState.tileH = th;\n      gridState.ovX = ovx;\n      gridState.ovY = ovy;\n      gridState.strideX = strideX;\n      gridState.strideY = strideY;\n      gridState.cols = (count === 1200) ? 40 : cols;\n      gridState.rows = (count === 1200) ? 30 : rows;\n      gridState.tileCount = count;\n      gridState.baseX = bx;\n      gridState.baseY = by;\n\n      const countStr = count.toLocaleString(\"vi-VN\");\n      document.getElementById(\"plan-count-num\").textContent = countStr;\n      document.getElementById(\"plan-grid-dim\").textContent = gridState.cols + \" cột × \" + gridState.rows + \" hàng\";\n      document.getElementById(\"plan-stride\").textContent = strideX + \" / \" + strideY + \" px\";\n      document.getElementById(\"rev-tile-count\").textContent = countStr;\n      document.getElementById(\"rev-tile-size\").textContent = tw + \" × \" + th + \" px\";\n      document.getElementById(\"rev-overlap\").textContent = (ovx * 100).toFixed(2).replace(\".\", \",\") + \"% / \" + (ovy * 100).toFixed(2).replace(\".\", \",\") + \"%\";\n      document.getElementById(\"rev-base-x\").textContent = bx.toFixed(3).replace(\".\", \",\");\n      document.getElementById(\"rev-base-y\").textContent = by.toFixed(3).replace(\".\", \",\");\n      document.getElementById(\"rev-source-path\").textContent = document.getElementById(\"source-path\").value;\n\n      populateTileDropdown();\n      updateSelectedTileDetails();\n      drawOverviewAndGrid();\n    }\n\n    function handleLocalImageSelect(ev) {\n      const files = ev.target.files;\n      if (!files || !files.length) return;\n      const f = files[0];\n      document.getElementById(\"source-path\").value = f.name;\n      document.getElementById(\"rev-source-path\").textContent = f.name;\n      if (f.type && f.type.startsWith(\"image/\")) {\n        const reader = new FileReader();\n        reader.onload = function(e) {\n          const img = new Image();\n          img.onload = function() {\n            gridState.userImage = img;\n            gridState.imgW = Math.max(1024, img.width * 16);\n            gridState.imgH = Math.max(1024, img.height * 16);\n            document.getElementById(\"meta-dims-val\").textContent =\n              gridState.imgW.toLocaleString(\"vi-VN\") + \" × \" + gridState.imgH.toLocaleString(\"vi-VN\") + \" px\";\n            recalculateGrid();\n          };\n          img.src = e.target.result;\n        };\n        reader.readAsDataURL(f);\n      }\n    }\n\n    function inspectCurrentSource() {\n      recalculateGrid();\n    }\n\n    function addCategoryChip(cat) {\n      const box = document.getElementById(\"detect-categories\");\n      if (!box.value.includes(cat)) {\n        box.value = (box.value.trim() ? box.value.trim() + \"\\n\" : \"\") + cat;\n      }\n    }\n\n    function toggleTaskMgrCard() {\n      const card = document.getElementById(\"tm-float-card\");\n      if (card) card.style.display = (card.style.display === \"none\") ? \"block\" : \"none\";\n    }\n\n    function toggleAdminSheetPanel() {\n      const p = document.getElementById(\"admin-key-management-panel\");\n      if (!p) return;\n      p.style.display = (p.style.display === \"none\") ? \"block\" : \"none\";\n    }\n\n    function toggleJobRunning() {\n      gridState.jobRunning = !gridState.jobRunning;\n      const btn = document.getElementById(\"cancel\");\n      const status = document.getElementById(\"job-status\");\n      if (gridState.jobRunning) {\n        btn.textContent = \"Hủy tác vụ\";\n        status.textContent = \"Nhận diện · Đang xử lý · \" + gridState.jobDone + \"/\" + gridState.jobTotal;\n      } else {\n        btn.textContent = \"▶ Tiếp tục tác vụ\";\n        status.textContent = \"Nhận diện · Đã tạm dừng · \" + gridState.jobDone + \"/\" + gridState.jobTotal;\n      }\n    }\n\n    function exportGeoTiffManifest() {\n      const manifest = {\n        studio: \"UAV GeoTIFF Studio VN2000\",\n        source: document.getElementById(\"source-path\").value,\n        crs: \"EPSG:9210\",\n        base_x: gridState.baseX,\n        base_y: gridState.baseY,\n        tile_width: gridState.tileW,\n        tile_height: gridState.tileH,\n        overlap_x: gridState.ovX,\n        overlap_y: gridState.ovY,\n        tile_count: gridState.tileCount,\n        processed_data_gdrive_folder: \"https://drive.google.com/drive/u/3/folders/1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN\"\n      };\n      const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: \"application/json\" });\n      const a = document.createElement(\"a\");\n      a.href = URL.createObjectURL(blob);\n      a.download = \"geotiff_tiles_manifest_vn2000.json\";\n      a.click();\n    }\n\n    // Interactive Canvas Click & Drag\n    (function bindOverviewCanvasEvents() {\n      const canvas = document.getElementById(\"overview-canvas\");\n      if (!canvas) return;\n      let dragging = false;\n      let startX = 0, startY = 0;\n      let moved = false;\n\n      canvas.addEventListener(\"mousedown\", function(e) {\n        dragging = true;\n        moved = false;\n        startX = e.clientX - gridState.panX;\n        startY = e.clientY - gridState.panY;\n      });\n      window.addEventListener(\"mousemove\", function(e) {\n        if (!dragging) return;\n        const nx = e.clientX - startX;\n        const ny = e.clientY - startY;\n        if (Math.abs(nx - gridState.panX) > 3 || Math.abs(ny - gridState.panY) > 3) moved = true;\n        gridState.panX = nx;\n        gridState.panY = ny;\n        drawOverviewAndGrid();\n      });\n      window.addEventListener(\"mouseup\", function(e) {\n        if (!dragging) return;\n        dragging = false;\n        if (!moved) {\n          const rect = canvas.getBoundingClientRect();\n          const cx = (e.clientX - rect.left) * (canvas.width / rect.width);\n          const cy = (e.clientY - rect.top) * (canvas.height / rect.height);\n          const localX = (cx - canvas.width / 2 - gridState.panX) / gridState.zoom + 150;\n          const localY = (cy - canvas.height / 2 - gridState.panY) / gridState.zoom + 155;\n          if (localX >= 0 && localX <= 300 && localY >= 0 && localY <= 310) {\n            const c = Math.min(gridState.cols - 1, Math.max(0, Math.floor((localX / 300) * gridState.cols)));\n            const r = Math.min(gridState.rows - 1, Math.max(0, Math.floor((localY / 310) * gridState.rows)));\n            selectTileById(r * gridState.cols + c);\n          }\n        }\n      });\n      canvas.addEventListener(\"wheel\", function(e) {\n        e.preventDefault();\n        zoomOverview(e.deltaY < 0 ? 1.12 : 0.89);\n      }, { passive: false });\n    })();\n\n    async function verifyLogin() {\n      const k = document.getElementById(\"key-input\").value.trim();\n      const errEl = document.getElementById(\"login-error-msg\");\n      if (!k) {\n        errEl.textContent = \"Vui lòng nhập Key truy cập trước khi mở giao diện!\";\n        return;\n      }\n      errEl.textContent = \"Đang xác thực Key...\";\n      const res = await fetch(\"/api/auth/verify-key\", {\n        method: \"POST\",\n        headers: { \"Content-Type\": \"application/json\" },\n        body: JSON.stringify({ key: k })\n      });\n      const data = await res.json();\n      if (!res.ok || !data.valid) {\n        errEl.textContent = data.reason || \"Key không hợp lệ hoặc đã hết hạn!\";\n        document.getElementById(\"authenticated-workspace\").style.display = \"none\";\n        document.getElementById(\"login-gate-wrapper\").style.display = \"flex\";\n        return;\n      }\n      activeKey = k;\n      currentKeyRecord = data.key_record || {};\n      errEl.textContent = \"\";\n      document.getElementById(\"login-gate-wrapper\").style.display = \"none\";\n      document.getElementById(\"authenticated-workspace\").style.display = \"block\";\n\n      const adminBtn = document.getElementById(\"btn-admin-toggle\");\n      const adminPanel = document.getElementById(\"admin-key-management-panel\");\n      const nameLabel = document.getElementById(\"user-name-label\");\n      if (data.is_admin) {\n        adminBtn.style.display = \"inline-flex\";\n        adminPanel.style.display = \"block\";\n        nameLabel.textContent = \"Admin · Nhận diện & kiểm duyệt\";\n        await refreshKeys();\n      } else {\n        adminBtn.style.display = \"none\";\n        adminPanel.style.display = \"none\";\n        nameLabel.textContent = \"Nhận diện & kiểm duyệt\";\n      }\n      recalculateGrid();\n      drawSelectedTilePreview();\n    }\n\n    function logoutSession() {\n      activeKey = \"\";\n      currentKeyRecord = null;\n      document.getElementById(\"key-input\").value = \"\";\n      document.getElementById(\"login-error-msg\").textContent = \"\";\n      document.getElementById(\"btn-admin-toggle\").style.display = \"none\";\n      document.getElementById(\"admin-key-management-panel\").style.display = \"none\";\n      document.getElementById(\"authenticated-workspace\").style.display = \"none\";\n      document.getElementById(\"login-gate-wrapper\").style.display = \"flex\";\n    }\n\n    async function refreshKeys() {\n      const res = await fetch(\"/api/keys\", { headers: { \"X-Admin-Key\": activeKey } });\n      if (!res.ok) return;\n      const data = await res.json();\n      const tbody = document.getElementById(\"keys-body\");\n      window.__latestKeysList = data.keys || [];\n      tbody.innerHTML = (data.keys || []).map(function(r) {\n        const cls = r.is_warning_red ? \"status-red\" : \"status-green\";\n        const delBtn = r.role === \"admin\"\n          ? \"<span class=\\\"muted\\\">Key Gốc</span>\"\n          : \"<button type=\\\"button\\\" class=\\\"secondary\\\" style=\\\"color:#b42318;padding:2px 8px;min-height:26px;\\\" onclick=\\\"deleteKey('\" + r.key + \"')\\\">Xóa</button>\";\n        return \"<tr>\" +\n          \"<td>\" + r.recipient + \"</td>\" +\n          \"<td>\" + r.phone + \"</td>\" +\n          \"<td><code>\" + r.key + \"</code></td>\" +\n          \"<td>\" + (r.purpose_display || r.purpose) + \"</td>\" +\n          \"<td>\" + r.issued_at_iso + \"</td>\" +\n          \"<td>\" + r.expires_at_iso + \"</td>\" +\n          \"<td><span class=\\\"\" + cls + \"\\\">\" + r.status_label + \"</span></td>\" +\n          \"<td>\" + delBtn + \"</td>\" +\n          \"</tr>\";\n      }).join(\"\");\n    }\n\n    async function createKey() {\n      const res = await fetch(\"/api/keys/create\", {\n        method: \"POST\",\n        headers: { \"Content-Type\": \"application/json\", \"X-Admin-Key\": activeKey },\n        body: JSON.stringify({\n          recipient: document.getElementById(\"rec-name\").value.trim() || \"Khách hàng mới\",\n          phone: document.getElementById(\"rec-phone\").value.trim() || \"0912345678\",\n          purpose: document.getElementById(\"rec-purpose\").value,\n          allow_tpu: document.getElementById(\"rec-tpu\").checked\n        })\n      });\n      if (res.ok) {\n        document.getElementById(\"rec-name\").value = \"\";\n        document.getElementById(\"rec-phone\").value = \"\";\n        await refreshKeys();\n      }\n    }\n\n    async function deleteKey(key) {\n      await fetch(\"/api/keys/delete\", {\n        method: \"POST\",\n        headers: { \"Content-Type\": \"application/json\", \"X-Admin-Key\": activeKey },\n        body: JSON.stringify({ key: key })\n      });\n      await refreshKeys();\n    }\n\n    function exportGoogleSheetCsv() {\n      const rows = window.__latestKeysList || [];\n      const header = [\"Người nhận\",\"SĐT người nhận\",\"Key\",\"Mục đích\",\"Thời gian cấp\",\"Thời gian hết hạn\",\"Tình trạng\"];\n      const csvLines = [header.join(\",\")];\n      rows.forEach(function(r) {\n        const vals = [r.recipient, r.phone, r.key, r.purpose_display || r.purpose, r.issued_at_iso, r.expires_at_iso, r.status_label].map(function(v) {\n          return '\"' + String(v || \"\").replace(/\"/g, '\"\"') + '\"';\n        });\n        csvLines.push(vals.join(\",\"));\n      });\n      const blob = new Blob([\"\\uFEFF\" + csvLines.join(\"\\r\\n\")], { type: \"text/csv;charset=utf-8;\" });\n      const a = document.createElement(\"a\");\n      a.href = URL.createObjectURL(blob);\n      a.download = \"uav_keys_google_sheet_7cot.csv\";\n      a.click();\n    }\n\n    function downloadVn2000Dxf() {\n      const dxf = [\n        \"0\",\"SECTION\",\"2\",\"HEADER\",\"9\",\"$INSUNITS\",\"70\",\"6\",\"0\",\"ENDSEC\",\n        \"0\",\"SECTION\",\"2\",\"ENTITIES\",\n        \"0\",\"LWPOLYLINE\",\"8\",\"KS_DUONG_NHUA\",\"62\",\"1\",\"90\",\"4\",\"70\",\"0\",\"10\",\"570297.623\",\"20\",\"1178883.354\",\"10\",\"570345.120\",\"20\",\"1178910.400\",\"10\",\"570410.500\",\"20\",\"1178925.800\",\"10\",\"570480.000\",\"20\",\"1178960.000\",\n        \"0\",\"LWPOLYLINE\",\"8\",\"KS_AO_HO\",\"62\",\"5\",\"90\",\"5\",\"70\",\"1\",\"10\",\"570320.000\",\"20\",\"1178820.000\",\"10\",\"570390.000\",\"20\",\"1178820.000\",\"10\",\"570390.000\",\"20\",\"1178760.000\",\"10\",\"570320.000\",\"20\",\"1178760.000\",\"10\",\"570320.000\",\"20\",\"1178820.000\",\n        \"0\",\"ENDSEC\",\"0\",\"EOF\"\n      ].join(\"\\r\\n\");\n      const blob = new Blob([dxf], { type: \"application/dxf\" });\n      const a = document.createElement(\"a\");\n      a.href = URL.createObjectURL(blob);\n      a.download = \"ORTHO_KHU_TAM_GIAC_VN2000.dxf\";\n      a.click();\n    }\n\n    async function runTpuTask(endpoint) {\n      let estSec = 0;\n      let box = document.getElementById(\"detect-res\");\n      if (endpoint === \"/api/detect/upload\") {\n        const imgs = parseInt(document.getElementById(\"detect-images\").value || \"45\", 10);\n        const tiles = parseInt(document.getElementById(\"detect-tiles\").value || \"1200\", 10);\n        estSec = Math.round(imgs * 12 + tiles * 1.45);\n      } else {\n        const epochs = parseInt(document.getElementById(\"yolo-epochs\").value || \"40\", 10);\n        const ds = parseInt(document.getElementById(\"yolo-dataset\").value || \"500\", 10);\n        estSec = Math.round(epochs * 24 + ds * 0.85);\n        box = document.getElementById(\"yolo-res\");\n        box.hidden = false;\n      }\n      const res = await fetch(endpoint, {\n        method: \"POST\",\n        headers: { \"Content-Type\": \"application/json\", \"X-UAV-Key\": activeKey },\n        body: JSON.stringify({ estimated_seconds: estSec, key: activeKey })\n      });\n      const data = await res.json();\n      const mins = (estSec / 60).toFixed(1);\n      if (res.status === 403) {\n        box.innerHTML = \"⏱️ <strong>Ước tính:</strong> \" + mins + \" phút (\" + estSec + \"s &gt; 15 phút) · <span style=\\\"color:#d92d20;font-weight:700;\\\">403 Forbidden: \" + (data.error || \"Key Khách không có quyền đẩy tác vụ >15 phút lên TPU\") + \"</span>\";\n      } else {\n        gridState.jobDone = Math.min(gridState.jobTotal, gridState.jobDone + 640);\n        const pct = ((gridState.jobDone / gridState.jobTotal) * 100).toFixed(2);\n        document.getElementById(\"job-status\").textContent = \"Nhận diện · Đang xử lý · \" + gridState.jobDone + \"/\" + gridState.jobTotal;\n        document.getElementById(\"job-progress-fill\").style.width = pct + \"%\";\n        box.innerHTML = \"✅ <strong>Thời gian ước tính:</strong> \" + mins + \" phút (\" + estSec + \"s) · <strong>Thực thi:</strong> <span style=\\\"color:#007a52;font-weight:700;\\\">\" + (data.offloaded_to_tpu ? \"ĐÃ TỰ ĐỘNG ĐẨY LÊN GOOGLE TPU (>15 phút)\" : \"Chạy trực tiếp trên máy (<=15 phút)\") + \"</span> · Folder Drive: <code>\" + data.processed_data_folder_id + \"</code>\";\n      }\n    }\n  </script>\n</body>\n</html>";
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
