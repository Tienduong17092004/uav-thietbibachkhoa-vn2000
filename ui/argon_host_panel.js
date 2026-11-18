// 🤖 Trung tâm Tự động hóa: Gemini 4 Argon CLI · Auto-Host Khi Bật Máy · GitHub
// Self-contained ES module for ui/webgpu.html (.control-column) and ui/index.html (.config-panel)

const PANEL_ID = "argon-host-control-panel";
const STYLE_ID = "argon-host-panel-styles";
const POLL_INTERVAL_MS = 2500;

const panelState = {
  sessionToken: "",
  argonRunning: false,
  argonPollTimer: null,
  autostartEnabled: false,
  lanUrl: "http://<LAN_IP>:8765",
  localUrl: "http://127.0.0.1:8765",
  mounted: false,
};

function injectPanelStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .argon-host-panel {
      background: linear-gradient(165deg, #0d1b28 0%, #09131d 100%);
      border: 1px solid rgba(16, 185, 129, 0.35);
      border-radius: 12px;
      padding: 14px;
      color: #e2e8f0;
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.35);
      font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
      margin-top: 12px;
    }
    .argon-host-panel * {
      box-sizing: border-box;
    }
    .argon-panel-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
      padding-bottom: 10px;
      margin-bottom: 10px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    }
    .argon-panel-kicker {
      display: inline-block;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 2px 7px;
      border-radius: 5px;
      background: rgba(16, 185, 129, 0.18);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.38);
      margin-bottom: 4px;
    }
    .argon-panel-title {
      margin: 0;
      font-size: 13.5px;
      font-weight: 700;
      line-height: 1.35;
      color: #f8fafc;
    }
    .argon-subcard {
      background: rgba(15, 29, 44, 0.88);
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 10px;
      padding: 11px 12px;
      margin-bottom: 10px;
    }
    .argon-subcard:last-child {
      margin-bottom: 0;
    }
    .argon-subcard-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
    .argon-subcard-title {
      margin: 0;
      font-size: 12.5px;
      font-weight: 700;
      color: #f1f5f9;
      line-height: 1.35;
    }
    .argon-badge {
      font-size: 10.5px;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 999px;
      white-space: nowrap;
      border: 1px solid rgba(148, 163, 184, 0.28);
      background: rgba(9, 20, 32, 0.9);
      color: #cbd5e1;
    }
    .argon-badge.ok {
      border-color: rgba(16, 185, 129, 0.5);
      color: #6ee7b7;
      background: rgba(16, 185, 129, 0.12);
    }
    .argon-badge.running {
      border-color: rgba(6, 182, 212, 0.55);
      color: #67e8f9;
      background: rgba(6, 182, 212, 0.15);
    }
    .argon-badge.warn {
      border-color: rgba(245, 158, 11, 0.5);
      color: #fcd34d;
      background: rgba(245, 158, 11, 0.12);
    }
    .argon-field-label {
      display: block;
      font-size: 11.2px;
      font-weight: 600;
      color: #cbd5e1;
      margin: 7px 0 4px;
    }
    .argon-input,
    .argon-select {
      width: 100%;
      min-height: 34px;
      padding: 6px 9px;
      border-radius: 7px;
      border: 1px solid rgba(148, 163, 184, 0.25);
      background: #07111a;
      color: #f8fafc;
      font-size: 12px;
      outline: none;
    }
    .argon-input:focus,
    .argon-select:focus {
      border-color: #10b981;
      box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.18);
    }
    .argon-row-2 {
      display: grid;
      grid-template-columns: 110px 1fr;
      gap: 8px;
      align-items: center;
      margin-top: 7px;
    }
    .argon-check-label {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 11.5px;
      font-weight: 500;
      color: #cbd5e1;
      cursor: pointer;
      margin: 8px 0 4px;
      user-select: none;
    }
    .argon-check-label input[type="checkbox"] {
      width: 15px;
      height: 15px;
      min-height: 15px;
      margin: 0;
      accent-color: #10b981;
      cursor: pointer;
    }
    .argon-btn-row {
      display: flex;
      gap: 7px;
      margin-top: 9px;
    }
    .argon-btn {
      min-height: 34px;
      padding: 7px 11px;
      border-radius: 7px;
      border: 1px solid rgba(148, 163, 184, 0.25);
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.14s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
    }
    .argon-btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .argon-btn-primary {
      flex: 1;
      background: linear-gradient(135deg, #10b981, #059669);
      border-color: #059669;
      color: #04130d;
    }
    .argon-btn-primary:hover:not(:disabled) {
      filter: brightness(1.08);
      color: #02100a;
    }
    .argon-btn-stop {
      background: rgba(239, 68, 68, 0.16);
      border-color: rgba(239, 68, 68, 0.45);
      color: #fca5a5;
    }
    .argon-btn-stop:hover:not(:disabled) {
      background: rgba(239, 68, 68, 0.28);
      color: #fecaca;
    }
    .argon-btn-secondary {
      width: 100%;
      background: rgba(15, 23, 42, 0.9);
      border-color: rgba(56, 189, 248, 0.35);
      color: #e0f2fe;
    }
    .argon-btn-secondary:hover:not(:disabled) {
      background: rgba(30, 41, 59, 0.95);
      border-color: #38bdf8;
      color: #ffffff;
    }
    .argon-log-box {
      margin-top: 8px;
      padding: 7px 9px;
      border-radius: 7px;
      background: #050b11;
      border: 1px solid rgba(16, 185, 129, 0.24);
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 11px;
      line-height: 1.45;
      color: #a7f3d0;
      max-height: 125px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .argon-kv-list {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 7px 9px;
      border-radius: 7px;
      background: rgba(7, 17, 26, 0.82);
      border: 1px solid rgba(148, 163, 184, 0.16);
      font-size: 11.4px;
      margin-bottom: 8px;
    }
    .argon-kv-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    .argon-kv-row code {
      color: #67e8f9;
      font-size: 11px;
      background: rgba(6, 182, 212, 0.1);
      padding: 1px 5px;
      border-radius: 4px;
    }
    .argon-note {
      margin: 7px 0 0;
      font-size: 11.2px;
      line-height: 1.42;
      color: #94a3b8;
      font-style: italic;
    }
  `;
  document.head.appendChild(style);
}

async function ensureSessionToken(forceRefresh = false) {
  if (!forceRefresh) {
    if (window.__sessionToken && typeof window.__sessionToken === "string") {
      panelState.sessionToken = window.__sessionToken;
      return panelState.sessionToken;
    }
    if (panelState.sessionToken) {
      return panelState.sessionToken;
    }
  }
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      if (data && typeof data.token === "string") {
        panelState.sessionToken = data.token;
        window.__sessionToken = data.token;
      }
    }
  } catch (_) {}
  return panelState.sessionToken;
}

async function panelGet(url) {
  const headers = {};
  const admInput = document.getElementById("adm-password-input");
  if (admInput && admInput.value.trim()) {
    headers["X-Admin-Password"] = admInput.value.trim();
  }
  const res = await fetch(url, { cache: "no-store", headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

async function panelPost(url, payload = {}) {
  let token = await ensureSessionToken(false);
  const buildHeaders = (tok) => {
    const h = {
      "Content-Type": "application/json",
      "X-Session-Token": tok || "",
    };
    const admInput = document.getElementById("adm-password-input");
    if (admInput && admInput.value.trim()) {
      h["X-Admin-Password"] = admInput.value.trim();
    }
    return h;
  };

  let res = await fetch(url, {
    method: "POST",
    headers: buildHeaders(token),
    body: JSON.stringify(payload || {}),
  });

  if (res.status === 403) {
    token = await ensureSessionToken(true);
    res = await fetch(url, {
      method: "POST",
      headers: buildHeaders(token),
      body: JSON.stringify(payload || {}),
    });
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Lỗi máy chủ (${res.status})`);
  }
  return data;
}

function buildPanelMarkup() {
  return `
    <div class="argon-panel-header">
      <div>
        <span class="argon-panel-kicker">🛰️ TỰ ĐỘNG HÓA</span>
        <h2 class="argon-panel-title">🤖 Tự động hóa: Argon CLI &amp; Dịch vụ Máy chủ</h2>
      </div>
    </div>

    <!-- CARD A: GEMINI 4 ARGON CLI LOOP -->
    <div class="argon-subcard" id="argon-card-a">
      <div class="argon-subcard-head">
        <h3 class="argon-subcard-title">🤖 Vòng lặp Gemini 4 Argon (<code>agy.exe</code>)</h3>
        <span id="argon-status-badge" class="argon-badge">Sẵn sàng</span>
      </div>

      <label class="argon-field-label" for="argon-model-select">Mô hình thị giác Gemini 4 Argon CLI</label>
      <select id="argon-model-select" class="argon-select">
        <option value="gemini-4-argon-high" selected>gemini-4-argon-high (Độ chính xác cao)</option>
        <option value="gemini-4-argon-medium">gemini-4-argon-medium</option>
        <option value="gemini-4-argon-low">gemini-4-argon-low</option>
        <option value="gemini-3.8-flash-high">gemini-3.8-flash-high</option>
      </select>

      <label class="argon-field-label" for="argon-tiles-dir">Thư mục ảnh cắt ô</label>
      <input
        id="argon-tiles-dir"
        class="argon-input"
        type="text"
        placeholder="Mặc định: outputs/tiles"
        autocomplete="off"
      >

      <div class="argon-row-2">
        <div>
          <label class="argon-field-label" for="argon-max-tiles" style="margin-top:0">Số ô tối đa</label>
          <input id="argon-max-tiles" class="argon-input" type="number" min="1" max="5000" step="1" value="20">
        </div>
        <label class="argon-check-label" for="argon-auto-train" style="margin-top:16px">
          <input id="argon-auto-train" type="checkbox" checked>
          <span>Tự huấn luyện sau gán nhãn</span>
        </label>
      </div>

      <div class="argon-btn-row">
        <button type="button" id="btn-argon-start" class="argon-btn argon-btn-primary">
          🚀 Chạy Vòng lặp Gemini 4 Argon
        </button>
        <button type="button" id="btn-argon-stop" class="argon-btn argon-btn-stop" style="display:none" hidden disabled>
          ⏹ Dừng
        </button>
      </div>

      <div id="argon-log-readout" class="argon-log-box">Chưa khởi chạy vòng lặp.</div>
    </div>

    <!-- CARD B: AUTO-BOOT PORT 8765 -->
    <div class="argon-subcard" id="argon-card-b">
      <div class="argon-subcard-head">
        <h3 class="argon-subcard-title">🌐 Tự động mở Web Host (Port 8765)</h3>
        <span id="host-autostart-badge" class="argon-badge ok">Đang chạy cổng 8765</span>
      </div>

      <div class="argon-kv-list">
        <div class="argon-kv-row">
          <span>Trạng thái dịch vụ:</span>
          <strong id="host-status-text" style="color:#6ee7b7">Đang chạy cổng 8765 · Khởi động cùng Windows</strong>
        </div>
        <div class="argon-kv-row">
          <span>Địa chỉ mạng LAN:</span>
          <code id="host-lan-url">http://&lt;LAN_IP&gt;:8765</code>
        </div>
        <div class="argon-kv-row">
          <span>Địa chỉ máy cục bộ (Local):</span>
          <code id="host-local-url">http://127.0.0.1:8765</code>
        </div>
      </div>

      <button type="button" id="btn-host-toggle-autostart" class="argon-btn argon-btn-secondary">
        ⚡ Bật / Tắt Tự khởi động cùng Windows
      </button>

      <p class="argon-note">Web Host tự động chạy ngầm ở cổng 8765 khi bật máy tính.</p>
    </div>

    <!-- CARD C: GITHUB PUSH -->
    <div class="argon-subcard" id="argon-card-c">
      <div class="argon-subcard-head">
        <h3 class="argon-subcard-title">🐙 Đồng bộ GitHub &amp; Drive</h3>
        <span id="git-branch-badge" class="argon-badge">git status</span>
      </div>

      <div class="argon-kv-list">
        <div class="argon-kv-row">
          <span>Trạng thái Git hiện tại:</span>
          <strong id="git-status-summary" style="color:#cbd5e1">Đang kiểm tra trạng thái Git…</strong>
        </div>
      </div>

      <label class="argon-field-label" for="gdrive-project-name">Tên Project Google Drive (CODE_DATA)</label>
      <input
        id="gdrive-project-name"
        class="argon-input"
        type="text"
        value="UAV_GeoTIFF_WebGPU_Survey_VN2000"
        placeholder="Nhập tên riêng cho từng Project (VD: UAV_Waterpoint_KhuTamGiac)"
        autocomplete="off"
      >

      <label class="argon-field-label" for="git-remote-url">Remote URL GitHub / Google Drive</label>
      <input
        id="git-remote-url"
        class="argon-input"
        type="text"
        placeholder="https://github.com/ten-cua-ban/uav-geotiff-webgpu.git"
        autocomplete="off"
      >

      <div class="argon-btn-row">
        <button type="button" id="btn-gdrive-sync" class="argon-btn argon-btn-primary">
          ☁️ Lưu Project vào CODE_DATA (Drive)
        </button>
        <button type="button" id="btn-git-push" class="argon-btn argon-btn-secondary">
          🐙 Commit &amp; Đẩy lên GitHub
        </button>
      </div>

      <div id="git-push-readout" class="argon-log-box" style="max-height:90px">Sẵn sàng đồng bộ.</div>
    </div>

    <!-- CARD D: GRAPHIFY KNOWLEDGE GRAPH -->
    <div class="argon-subcard" id="argon-card-d">
      <div class="argon-subcard-head">
        <h3 class="argon-subcard-title">🕸️ Đồ thị Tri thức <code>Graphify</code></h3>
        <span id="graphify-badge" class="argon-badge ok">1,166 nodes · 47.7× token</span>
      </div>

      <div class="argon-kv-list">
        <div class="argon-kv-row">
          <span>Cấu trúc AST &amp; Ngữ nghĩa:</span>
          <strong id="graphify-summary-text" style="color:#6ee7b7">1,166 nodes · 3,229 edges · 45 communities · Giảm 47.7× token</strong>
        </div>
      </div>

      <div class="argon-btn-row">
        <a href="/graph.html" target="_blank" rel="noopener" class="argon-btn argon-btn-primary" style="text-decoration:none;text-align:center">
          🕸️ Mở Đồ thị (graph.html)
        </a>
        <a href="/callflow.html" target="_blank" rel="noopener" class="argon-btn argon-btn-secondary" style="text-decoration:none;text-align:center">
          📊 Sơ đồ Luồng gọi (callflow)
        </a>
        <a href="/ARCHITECTURE.md" target="_blank" rel="noopener" class="argon-btn argon-btn-secondary" style="text-decoration:none;text-align:center">
          📐 Bản vẽ ARCHITECTURE.md
        </a>
      </div>

      <div class="argon-btn-row" style="margin-top:6px">
        <input id="graphify-query-input" class="argon-input" type="text" placeholder="Truy vấn nhanh đồ thị (VD: ProjectService, terrain_dwg_file, gemini_argon_loop)" value="ProjectService">
        <button type="button" id="btn-graphify-query" class="argon-btn argon-btn-secondary" style="flex:0 0 auto">
          🔍 Truy vấn
        </button>
        <button type="button" id="btn-graphify-rebuild" class="argon-btn argon-btn-secondary" style="flex:0 0 auto">
          🔄 Cập nhật
        </button>
      </div>

      <div id="graphify-readout" class="argon-log-box" style="max-height:95px">Sẵn sàng truy vấn đồ thị.</div>
    </div>
  `;
}

function renderArgonStatus(data) {
  const badge = document.getElementById("argon-status-badge");
  const readout = document.getElementById("argon-log-readout");
  const startBtn = document.getElementById("btn-argon-start");
  const stopBtn = document.getElementById("btn-argon-stop");
  if (!badge || !readout) return;

  const isRunning = Boolean(
    data?.running ||
      data?.status === "running" ||
      data?.state === "running"
  );
  panelState.argonRunning = isRunning;

  if (startBtn) {
    startBtn.disabled = isRunning;
    startBtn.innerHTML = isRunning
      ? "⏳ Đang chạy Vòng lặp Gemini 4 Argon…"
      : "🚀 Chạy Vòng lặp Gemini 4 Argon";
  }
  if (stopBtn) {
    stopBtn.hidden = !isRunning;
    stopBtn.disabled = !isRunning;
    stopBtn.style.display = isRunning ? "inline-flex" : "none";
  }

  const processed = data?.processed ?? data?.done ?? data?.labeled_count ?? 0;
  const total = data?.total ?? data?.max_tiles ?? 0;
  const modelName = data?.model || "gemini-4-argon-high";

  if (isRunning) {
    badge.className = "argon-badge running";
    badge.textContent = total > 0 ? `⚡ Đang chạy (${processed}/${total})` : "⚡ Đang chạy";
  } else if (data?.status === "error" || data?.error) {
    badge.className = "argon-badge warn";
    badge.textContent = "⚠️ Cảnh báo";
  } else if (data?.status === "completed" || data?.status === "done") {
    badge.className = "argon-badge ok";
    badge.textContent = "✅ Hoàn tất";
  } else {
    badge.className = "argon-badge";
    badge.textContent = "Sẵn sàng";
  }

  const lines = [];
  if (data?.message || data?.summary) {
    lines.push(`[${modelName}] ${data.message || data.summary}`);
  } else if (isRunning) {
    lines.push(`[${modelName}] Đang chạy vòng lặp gán nhãn & huấn luyện (${processed}/${total} ô)…`);
  }

  const rawLogs = data?.logs ?? data?.log_lines ?? data?.recent_logs ?? data?.output;
  if (Array.isArray(rawLogs) && rawLogs.length > 0) {
    lines.push(...rawLogs.slice(-18).map((l) => String(l)));
  } else if (typeof rawLogs === "string" && rawLogs.trim()) {
    lines.push(rawLogs.trim());
  }

  if (lines.length > 0) {
    readout.textContent = lines.join("\n");
    readout.scrollTop = readout.scrollHeight;
  }
}

function scheduleArgonPoll() {
  if (panelState.argonPollTimer) {
    clearTimeout(panelState.argonPollTimer);
    panelState.argonPollTimer = null;
  }
  if (!panelState.argonRunning) return;
  panelState.argonPollTimer = setTimeout(async () => {
    try {
      const st = await panelGet("/api/argon/status");
      renderArgonStatus(st);
    } catch (_) {}
    if (panelState.argonRunning) {
      scheduleArgonPoll();
    }
  }, POLL_INTERVAL_MS);
}

async function refreshArgonStatus() {
  try {
    const st = await panelGet("/api/argon/status");
    renderArgonStatus(st);
    if (panelState.argonRunning) {
      scheduleArgonPoll();
    }
  } catch (_) {}
}

function renderHostStatus(data) {
  const badge = document.getElementById("host-autostart-badge");
  const statusText = document.getElementById("host-status-text");
  const lanEl = document.getElementById("host-lan-url");
  const localEl = document.getElementById("host-local-url");
  if (!badge || !statusText) return;

  const autostart = Boolean(
    data?.enabled ??
      data?.autostart_enabled ??
      data?.autostart ??
      data?.registered ??
      data?.startup_enabled ??
      false
  );
  panelState.autostartEnabled = autostart;

  const port = data?.port || 8765;
  const lanIp = data?.lan_ip || "<LAN_IP>";
  const lanUrl = data?.lan_url || `http://${lanIp}:${port}`;
  const localUrl = data?.local_url || `http://127.0.0.1:${port}`;

  if (lanEl) lanEl.textContent = lanUrl;
  if (localEl) localEl.textContent = localUrl;

  if (autostart) {
    badge.className = "argon-badge ok";
    badge.textContent = "Đã đăng ký khởi động cùng Windows";
    statusText.textContent = `Đang chạy cổng ${port} · Đã đăng ký khởi động cùng Windows`;
    statusText.style.color = "#6ee7b7";
  } else {
    badge.className = "argon-badge";
    badge.textContent = `Đang chạy cổng ${port}`;
    statusText.textContent = `Đang chạy cổng ${port} · Chưa bật tự khởi động cùng Windows`;
    statusText.style.color = "#cbd5e1";
  }
}

async function refreshHostStatus() {
  try {
    const st = await panelGet("/api/host/status");
    renderHostStatus(st);
  } catch (_) {
    // Fallback if server exposes host status inside /api/state
    try {
      const stateData = await panelGet("/api/state");
      if (stateData?.host_status) {
        renderHostStatus(stateData.host_status);
      }
    } catch (_) {}
  }
}

function renderGitStatus(data) {
  const badge = document.getElementById("git-branch-badge");
  const summaryEl = document.getElementById("git-status-summary");
  const remoteInput = document.getElementById("git-remote-url");
  if (!summaryEl) return;

  const branch = data?.branch || "main";
  const dirtyCount =
    data?.dirty_count ??
    data?.changed_files_count ??
    data?.modified_count ??
    (Array.isArray(data?.changed_files) ? data.changed_files.length : null);

  if (badge) {
    badge.textContent = `🌿 ${branch}`;
    badge.className = dirtyCount && dirtyCount > 0 ? "argon-badge warn" : "argon-badge ok";
  }

  const commit = data?.last_commit || data?.commit || data?.head || "";

  if (data?.error) {
    summaryEl.textContent = data.error;
  } else if (data?.status_text || data?.summary) {
    summaryEl.textContent = data.status_text || data.summary;
  } else if (commit || dirtyCount !== null) {
    const countLabel = dirtyCount !== null ? `${dirtyCount} tệp thay đổi` : "Sẵn sàng";
    summaryEl.textContent = commit ? `${commit} · ${countLabel}` : countLabel;
  } else {
    summaryEl.textContent = "Kho Git sẵn sàng commit & push";
  }

  const remoteUrl = data?.remote_url || data?.origin || "";
  if (remoteInput && remoteUrl && !remoteInput.value.trim()) {
    remoteInput.value = remoteUrl;
  }
}

async function refreshGitStatus() {
  try {
    const st = await panelGet("/api/git/status");
    renderGitStatus(st);
  } catch (err) {
    const summaryEl = document.getElementById("git-status-summary");
    if (summaryEl) {
      summaryEl.textContent = `Sẵn sàng cấu hình Git (${err.message})`;
    }
  }
}

function bindPanelEvents() {
  const startBtn = document.getElementById("btn-argon-start");
  const stopBtn = document.getElementById("btn-argon-stop");
  const toggleHostBtn = document.getElementById("btn-host-toggle-autostart");
  const gitPushBtn = document.getElementById("btn-git-push");
  const gdriveSyncBtn = document.getElementById("btn-gdrive-sync");
  const graphifyQueryBtn = document.getElementById("btn-graphify-query");
  const graphifyRebuildBtn = document.getElementById("btn-graphify-rebuild");

  graphifyQueryBtn?.addEventListener("click", async () => {
    const q = (document.getElementById("graphify-query-input")?.value || "").trim() || "ProjectService";
    const readout = document.getElementById("graphify-readout");
    graphifyQueryBtn.disabled = true;
    if (readout) readout.textContent = `🔍 Đang truy vấn đồ thị Graphify cho: "${q}"…`;
    try {
      const res = await panelPost("/api/graphify/query", { query: q });
      if (readout) readout.textContent = res.output || "Đã hoàn tất truy vấn.";
    } catch (err) {
      if (readout) readout.textContent = `❌ Lỗi truy vấn Graphify: ${err.message}`;
    } finally {
      graphifyQueryBtn.disabled = false;
    }
  });

  graphifyRebuildBtn?.addEventListener("click", async () => {
    const readout = document.getElementById("graphify-readout");
    const sumEl = document.getElementById("graphify-summary-text");
    graphifyRebuildBtn.disabled = true;
    if (readout) readout.textContent = "🔄 Đang quét lại AST Tree-sitter & cập nhật graph.html, callflow.html, GRAPH_REPORT.md…";
    try {
      const res = await panelPost("/api/graphify/rebuild", {});
      if (sumEl && res.summary) sumEl.textContent = res.summary;
      if (readout) readout.textContent = res.message || "✅ Đã cập nhật Graphify!";
    } catch (err) {
      if (readout) readout.textContent = `❌ Lỗi cập nhật Graphify: ${err.message}`;
    } finally {
      graphifyRebuildBtn.disabled = false;
    }
  });

  gdriveSyncBtn?.addEventListener("click", async () => {
    const readout = document.getElementById("git-push-readout");
    const projName = (document.getElementById("gdrive-project-name")?.value || "").trim() || "UAV_GeoTIFF_WebGPU_Survey_VN2000";
    gdriveSyncBtn.disabled = true;
    if (readout) {
      readout.textContent = `☁️ Đang tạo/cập nhật thư mục Project '${projName}' trong Google Drive CODE_DATA (1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D)…`;
    }
    try {
      const res = await panelPost("/api/gdrive/sync", {
        project_name: projName,
        parent_folder_id: "1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D",
      });
      if (readout) {
        readout.textContent = res.message || `✅ Đã đẩy Project '${projName}' lên Google Drive CODE_DATA!`;
      }
    } catch (err) {
      if (readout) {
        readout.textContent = `❌ Lỗi đồng bộ Google Drive: ${err.message}`;
      }
    } finally {
      gdriveSyncBtn.disabled = false;
    }
  });

  startBtn?.addEventListener("click", async () => {
    const model = document.getElementById("argon-model-select")?.value || "gemini-4-argon-high";
    const tilesDir = (document.getElementById("argon-tiles-dir")?.value || "").trim();
    const maxTiles = Math.max(1, Number(document.getElementById("argon-max-tiles")?.value || 20));
    const autoTrain = Boolean(document.getElementById("argon-auto-train")?.checked);
    const readout = document.getElementById("argon-log-readout");

    startBtn.disabled = true;
    if (readout) {
      readout.textContent = `🚀 Đang khởi chạy vòng lặp ${model} qua agy.exe CLI (tối đa ${maxTiles} ô)…`;
    }
    try {
      const res = await panelPost("/api/argon/start", {
        model,
        tiles_dir: tilesDir || null,
        input_dir: tilesDir || null,
        max_tiles: maxTiles,
        auto_train: autoTrain,
        auto_train_after: autoTrain,
      });
      if (res.error && res.ok === false) {
        throw new Error(res.error);
      }
      renderArgonStatus({ ...res, running: res.running ?? true, model });
      panelState.argonRunning = Boolean(res.running ?? true);
      scheduleArgonPoll();
    } catch (err) {
      startBtn.disabled = false;
      startBtn.innerHTML = "🚀 Chạy Vòng lặp Gemini 4 Argon";
      if (stopBtn) {
        stopBtn.hidden = true;
        stopBtn.disabled = true;
        stopBtn.style.display = "none";
      }
      if (readout) {
        readout.textContent = `❌ Không thể khởi chạy vòng lặp Gemini 4 Argon: ${err.message}`;
      }
    }
  });

  stopBtn?.addEventListener("click", async () => {
    const readout = document.getElementById("argon-log-readout");
    try {
      const res = await panelPost("/api/argon/stop", {});
      panelState.argonRunning = false;
      if (panelState.argonPollTimer) {
        clearTimeout(panelState.argonPollTimer);
        panelState.argonPollTimer = null;
      }
      renderArgonStatus({ ...res, running: false, status: "stopped" });
    } catch (err) {
      if (readout) {
        readout.textContent = `❌ Lỗi khi dừng vòng lặp: ${err.message}`;
      }
    }
  });

  toggleHostBtn?.addEventListener("click", async () => {
    toggleHostBtn.disabled = true;
    const nextState = !panelState.autostartEnabled;
    try {
      const res = await panelPost("/api/host/toggle-autostart", {
        enabled: nextState,
        enable: nextState,
        port: 8765,
        action: "toggle",
      });
      if (res.error && res.ok === false) {
        throw new Error(res.error);
      }
      renderHostStatus(res);
    } catch (err) {
      const statusText = document.getElementById("host-status-text");
      if (statusText) {
        statusText.textContent = `⚠️ Không thể đổi trạng thái tự khởi động: ${err.message}`;
      }
    } finally {
      toggleHostBtn.disabled = false;
    }
  });

  gitPushBtn?.addEventListener("click", async () => {
    const remoteUrl = (document.getElementById("git-remote-url")?.value || "").trim();
    const readout = document.getElementById("git-push-readout");
    gitPushBtn.disabled = true;
    if (readout) {
      readout.textContent = "🐙 Đang thực hiện git add, commit và git push lên GitHub…";
    }
    try {
      const res = await panelPost("/api/git/push", {
        remote_url: remoteUrl,
        commit_message: "Update UAV GeoTIFF WebGPU & Gemini 4 Argon pipeline",
      });
      if (res.git_status) {
        renderGitStatus(res.git_status);
      } else {
        await refreshGitStatus();
      }
      const parts = [];
      if (res.message) parts.push(res.message);
      if (res.instructions_vi) parts.push(res.instructions_vi);
      if (res.output && !res.pushed) parts.push(res.output);
      if (readout) {
        readout.textContent =
          parts.join("\n") || "✅ Đã commit & đẩy dự án lên GitHub thành công!";
      }
    } catch (err) {
      if (readout) {
        readout.textContent = `❌ Lỗi git push: ${err.message}`;
      }
    } finally {
      gitPushBtn.disabled = false;
    }
  });
}

export async function mountArgonHostPanel(customContainer = null) {
  if (document.getElementById(PANEL_ID)) {
    return document.getElementById(PANEL_ID);
  }

  injectPanelStyles();

  const target =
    (typeof customContainer === "string"
      ? document.querySelector(customContainer)
      : customContainer) ||
    document.querySelector(".control-column") ||
    document.querySelector(".config-panel") ||
    document.querySelector("main") ||
    document.body;

  if (!target) return null;

  const section = document.createElement("section");
  section.id = PANEL_ID;
  section.className = "card argon-host-panel";
  section.setAttribute(
    "aria-label",
    "Trung tâm Tự động hóa: Gemini 4 Argon CLI, Auto-Host Khi Bật Máy, GitHub"
  );
  section.innerHTML = buildPanelMarkup();

  const stepNavFooter = target.querySelector(":scope > footer.step-navigation");
  if (stepNavFooter) {
    target.insertBefore(section, stepNavFooter);
  } else {
    target.appendChild(section);
  }

  panelState.mounted = true;
  bindPanelEvents();

  await ensureSessionToken(false);
  await Promise.allSettled([
    refreshArgonStatus(),
    refreshHostStatus(),
    refreshGitStatus(),
  ]);

  return section;
}

export const initArgonHostPanel = mountArgonHostPanel;
export default mountArgonHostPanel;

function shouldMountAdminAutomationPanel() {
  if (typeof window === "undefined") return false;
  if (window.__UAV_ADMIN_UNLOCKED === true) return true;
  try {
    const params = new URLSearchParams(window.location.search || "");
    return params.get("admin") === "1" || params.get("owner") === "1";
  } catch (_) {
    return false;
  }
}

function mountWorkstationLicenseGateIfNeeded() {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  // Skip on webgpu.html (which has its own built-in #license-gate-overlay) or headless Playwright runner
  if (document.getElementById("license-gate-overlay") || navigator.webdriver === true) return;
  try {
    if (sessionStorage.getItem("uav_verified_license_key")) return;
  } catch (_) {}

  document.body.classList.add("ws-license-locked");
  const gateStyle = document.createElement("style");
  gateStyle.id = "ws-license-gate-styles";
  gateStyle.textContent = `
    body.ws-license-locked > header,
    body.ws-license-locked > nav,
    body.ws-license-locked > main,
    body.ws-license-locked > footer {
      visibility: hidden !important;
      opacity: 0 !important;
      pointer-events: none !important;
      user-select: none !important;
    }
    #ws-license-gate-overlay {
      position: fixed;
      inset: 0;
      z-index: 99999;
      background: radial-gradient(circle at 50% 20%, #0f293a 0%, #060d14 70%);
      display: grid;
      place-items: center;
      padding: 20px;
      font-family: "Inter", "Segoe UI", system-ui, sans-serif;
      color: #e2e8f0;
    }
    #ws-license-gate-overlay.hidden {
      display: none !important;
    }
    .ws-gate-card {
      width: min(430px, 94vw);
      background: rgba(18, 36, 54, 0.96);
      border: 1px solid rgba(16, 185, 129, 0.45);
      border-radius: 14px;
      padding: 22px 20px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.75);
    }
    .ws-gate-input {
      width: 100%;
      padding: 10px 12px;
      border-radius: 8px;
      border: 1px solid rgba(148, 163, 184, 0.3);
      background: #091520;
      color: #f8fafc;
      font-size: 13px;
    }
    .ws-gate-btn {
      width: 100%;
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid rgba(16, 185, 129, 0.55);
      background: linear-gradient(135deg, #10b981, #059669);
      color: #04130e;
      font-weight: 700;
      font-size: 13px;
      cursor: pointer;
    }
    .ws-gate-status {
      font-size: 12px;
      padding: 8px 10px;
      border-radius: 7px;
      background: rgba(9, 21, 32, 0.9);
      border-left: 3px solid #10b981;
    }
  `;
  document.head.appendChild(gateStyle);

  const overlay = document.createElement("div");
  overlay.id = "ws-license-gate-overlay";
  overlay.innerHTML = `
    <div class="ws-gate-card" role="dialog" aria-modal="true">
      <div style="display:flex;align-items:center;gap:12px">
        <div style="width:36px;height:36px;border-radius:8px;background:rgba(16,185,129,0.2);border:1px solid rgba(16,185,129,0.45);display:grid;place-items:center;font-size:18px">🔐</div>
        <div>
          <div style="font-size:10px;font-weight:700;color:#10b981;letter-spacing:0.08em">BẢO MẬT TRẠM NHẬN DIỆN · LICENSE GATE</div>
          <h2 style="margin:2px 0 0;font-size:17px;color:#f8fafc">Xác thực License Key</h2>
        </div>
      </div>
      <label for="ws-gate-key-input" style="font-size:12px;font-weight:600;color:#cbd5e1">Mã License Key</label>
      <input id="ws-gate-key-input" class="ws-gate-input" type="text" placeholder="Nhập mã License Key để mở giao diện…" autocomplete="off">
      <button type="button" id="ws-gate-submit" class="ws-gate-btn">🔑 Xác thực Key &amp; Mở Giao diện</button>
      <div id="ws-gate-status" class="ws-gate-status">Vui lòng nhập mã License Key hợp lệ để hiển thị giao diện.</div>
    </div>
  `;
  document.body.prepend(overlay);

  const keyIn = overlay.querySelector("#ws-gate-key-input");
  const btn = overlay.querySelector("#ws-gate-submit");
  const st = overlay.querySelector("#ws-gate-status");

  const submitWsKey = async () => {
    const key = (keyIn.value || "").trim();
    if (!key) {
      st.textContent = "❌ Vui lòng nhập mã License Key.";
      st.style.borderLeftColor = "#ef4444";
      return;
    }
    btn.disabled = true;
    st.textContent = "🔐 Đang kiểm tra License Key…";
    st.style.borderLeftColor = "#10b981";
    try {
      const tok = await ensureSessionToken(false);
      const res = await fetch("/api/webgpu/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Session-Token": tok || "" },
        body: JSON.stringify({
          license_key: key,
          device_fingerprint: "workstation-browser|" + (navigator.hardwareConcurrency || 4),
          gpu_label: "Workstation Browser",
          model_id: "terrain_seg",
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      try {
        sessionStorage.setItem("uav_verified_license_key", data.license?.key || key);
      } catch (_) {}
      document.body.classList.remove("ws-license-locked");
      overlay.classList.add("hidden");
    } catch (err) {
      st.textContent = `❌ ${err.message}`;
      st.style.borderLeftColor = "#ef4444";
    } finally {
      btn.disabled = false;
    }
  };
  btn.addEventListener("click", submitWsKey);
  keyIn.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      submitWsKey();
    }
  });
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const tryAutoMount = () => {
    mountWorkstationLicenseGateIfNeeded();
    if (shouldMountAdminAutomationPanel()) {
      mountArgonHostPanel();
    }
  };
  window.addEventListener("uav-admin-unlocked", () => {
    window.__UAV_ADMIN_UNLOCKED = true;
    mountArgonHostPanel();
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tryAutoMount);
  } else {
    tryAutoMount();
  }
}
