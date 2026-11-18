// Zero-Install Browser WebGPU Survey Portal
// AES-256-GCM In-Memory ONNX Decryption + Local GeoTIFF Reader + 6-Class Corridor Vectorization + AutoCAD DXF

const CLASS_META = {
  1: { key: "asphalt_road", labelVi: "Đường nhựa", cadText: "D.NHUA", layer: "KS_DUONG_NHUA", aci: 1, linetype: "CONTINUOUS", centerline: true, hex: "#ef4444", rgb: [239, 68, 68] },
  2: { key: "concrete_road", labelVi: "Đường bê tông", cadText: "D.BE TONG", layer: "KS_DUONG_BETONG", aci: 7, linetype: "CONTINUOUS", centerline: true, hex: "#94a3b8", rgb: [148, 163, 184] },
  3: { key: "dirt_road", labelVi: "Đường đất", cadText: "D.DAT", layer: "KS_DUONG_DAT", aci: 30, linetype: "DASHED", centerline: false, hex: "#d97706", rgb: [217, 119, 6] },
  4: { key: "footpath", labelVi: "Đường đi bộ", cadText: "D.DI BO", layer: "KS_DUONG_DIBO", aci: 8, linetype: "DASHED", centerline: false, hex: "#a855f7", rgb: [168, 85, 247] },
  5: { key: "pond", labelVi: "Sông / Ao / Hồ", cadText: "AO", layer: "KS_AO_HO", aci: 5, linetype: "CONTINUOUS", centerline: false, hex: "#0ea5e9", rgb: [14, 165, 233] },
  6: { key: "masonry_ditch", labelVi: "Mương xây", cadText: "MUONG XAY", layer: "KS_MUONG_XAY", aci: 4, linetype: "CONTINUOUS", centerline: false, hex: "#06b6d4", rgb: [6, 182, 212] },
  7: { key: "house_building", labelVi: "Nhà / Công trình", cadText: "NHA", layer: "KS_NHA_CONGTRINH", aci: 2, linetype: "CONTINUOUS", centerline: false, hex: "#f59e0b", rgb: [245, 158, 11] },
  8: { key: "landscape_tree", labelVi: "Cây cảnh quan", cadText: "CAY XANH", layer: "KS_CAY_CANHQUAN", aci: 3, linetype: "CONTINUOUS", centerline: false, hex: "#10b981", rgb: [16, 185, 129] },
  9: { key: "newly_transplanted_rice", labelVi: "Lúa mới cấy", cadText: "LUA MOI CAY", layer: "KS_LUA_MOI_CAY", aci: 3, linetype: "CONTINUOUS", centerline: false, hex: "#22c55e", rgb: [34, 197, 94] },
  10: { key: "grass", labelVi: "Cỏ dại / Cỏ bờ", cadText: "CO DAI", layer: "KS_CO_DAI", aci: 30, linetype: "CONTINUOUS", centerline: false, hex: "#eab308", rgb: [234, 179, 8] },
  11: { key: "rice_partial_grass", labelVi: "Lúa lẫn cỏ", cadText: "LUA LAN CO", layer: "KS_LUA_LAN_CO", aci: 4, linetype: "CONTINUOUS", centerline: false, hex: "#14b8a6", rgb: [20, 184, 166] },
};

const KEY_TO_ID = Object.fromEntries(Object.entries(CLASS_META).map(([id, m]) => [m.key, Number(id)]));

function buildDefaultMylib2Blocks() {
  const makeCanopy = (lobes, innerCross = true) => {
    const ring = [];
    const total = lobes * 6;
    for (let i = 0; i <= total; i++) {
      const ang = (2 * Math.PI * i) / total;
      const rad = 0.8 + 0.2 * Math.abs(Math.cos(lobes * ang * 0.5));
      ring.push([Number((rad * Math.cos(ang)).toFixed(4)), Number((rad * Math.sin(ang)).toFixed(4))]);
    }
    const strokes = [ring];
    if (innerCross) {
      strokes.push([[-0.22, 0], [0.22, 0]], [[0, -0.22], [0, 0.22]]);
    }
    return { strokes };
  };
  return {
    Caytanbe: makeCanopy(6, true),
    Caydothi_cdt1: makeCanopy(8, true),
    Caytanto: makeCanopy(10, true),
    Caydoclap: makeCanopy(7, true),
    Caycanhquan_173e: makeCanopy(8, true),
  };
}

const TCVN_MAP_SCALE_SPECS = {
  500: {
    denom: 500,
    k: 1.0,
    label: "1:500",
    badgeText: "1:500 (k=1.0×) · Block ×1.0 · Cây 20×10m · Cỏ 10×5m · Cao độ 12.5m · Chữ 1.2m · ĐM 0.5m",
    treeGridM: [20, 10],
    grassGridM: [10, 5],
    spotGridM: 12.5,
    textHeightM: 1.2,
    contourIntervalM: 0.5,
  },
  1000: {
    denom: 1000,
    k: 2.0,
    label: "1:1000",
    badgeText: "1:1000 (k=2.0×) · Block ×2.0 · Cây 40×20m · Cỏ 20×10m · Cao độ 25m · Chữ 2.4m · ĐM 0.5m",
    treeGridM: [40, 20],
    grassGridM: [20, 10],
    spotGridM: 25.0,
    textHeightM: 2.4,
    contourIntervalM: 0.5,
  },
  2000: {
    denom: 2000,
    k: 4.0,
    label: "1:2000",
    badgeText: "1:2000 (k=4.0×) · Block ×4.0 · Cây 80×40m · Cỏ 40×20m · Cao độ 50m · Chữ 4.8m · ĐM 0.5m/1.0m",
    treeGridM: [80, 40],
    grassGridM: [40, 20],
    spotGridM: 50.0,
    textHeightM: 4.8,
    contourIntervalM: 0.5,
  },
  5000: {
    denom: 5000,
    k: 10.0,
    label: "1:5000",
    badgeText: "1:5000 (k=10.0×) · Block ×10.0 · Cây 200×100m · Cỏ 100×50m · Cao độ 125m · Chữ 12.0m · ĐM 1.0m",
    treeGridM: [200, 100],
    grassGridM: [100, 50],
    spotGridM: 125.0,
    textHeightM: 12.0,
    contourIntervalM: 1.0,
  },
};

function parseMapScaleDenominator(raw) {
  const s = String(raw || "500").trim();
  const m = s.match(/(?:1\s*[:/]\s*)?(\d{3,5})/);
  const val = m ? Number(m[1]) : Number(s);
  return TCVN_MAP_SCALE_SPECS[val] ? val : 500;
}

const state = {
  sessionToken: "",
  publicMode: false,
  adminPassword: "",
  gpuSupported: false,
  gpuLabel: "WASM SIMD CPU",
  deviceFingerprint: "",
  activeLicenseKey: "",
  activeModelInfo: null,
  ortSession: null,
  activeProvider: "wasm",
  bundle: { orthoFile: null, worldFile: null, prjFile: null, demFile: null },
  raster: null,
  maskCanvas: null,
  segMask: null,
  features: [],
  mapScale: 500,
  mylib2Blocks: buildDefaultMylib2Blocks(),
  view: { scale: 1, tx: 0, ty: 0, dragging: false, lastX: 0, lastY: 0 },
};

const el = (id) => document.getElementById(id);

function getMapScaleSpec() {
  const denom = parseMapScaleDenominator(el("mapScaleSelect")?.value || state.mapScale || 500);
  state.mapScale = denom;
  return TCVN_MAP_SCALE_SPECS[denom] || TCVN_MAP_SCALE_SPECS[500];
}

function updateTcvnScaleBadge() {
  const spec = getMapScaleSpec();
  const badge = el("tcvnScaleInfoBadge");
  if (badge) {
    badge.textContent = spec.badgeText;
  }
}

function setStatus(html, tone = "info") {
  const color = tone === "error" ? "#ef4444" : tone === "warn" ? "#f59e0b" : "#10b981";
  for (const id of ["portal-status", "gate-status"]) {
    const box = el(id);
    if (!box) continue;
    box.innerHTML = html;
    box.style.borderLeftColor = color;
  }
}

function unlockPortalWorkspace() {
  document.body.classList.remove("license-locked");
  el("license-gate-overlay")?.classList.add("hidden");
  requestAnimationFrame(() => {
    fitCanvasView();
    renderViewport();
  });
}

function base64ToUint8(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function apiGet(url) {
  const headers = {};
  if (state.adminPassword) headers["X-Admin-Password"] = state.adminPassword;
  const res = await fetch(url, { cache: "no-store", headers });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      if (err.error) msg = err.error;
    } catch (_) {}
    throw new Error(msg);
  }
  return res;
}

async function apiPost(url, payload) {
  const headers = {
    "Content-Type": "application/json",
    "X-Session-Token": state.sessionToken,
  };
  if (state.adminPassword) headers["X-Admin-Password"] = state.adminPassword;
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(payload || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Lỗi máy chủ (${res.status})`);
  }
  return data;
}

function getOrCreateDeviceFingerprint(gpuInfoStr) {
  let seed = localStorage.getItem("uav_webgpu_device_seed");
  if (!seed) {
    const arr = new Uint8Array(12);
    window.crypto.getRandomValues(arr);
    seed = Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem("uav_webgpu_device_seed", seed);
  }
  const hw = [
    seed,
    navigator.hardwareConcurrency || 4,
    screen.width + "x" + screen.height,
    gpuInfoStr || "generic-gpu",
  ].join("|");
  return hw;
}

async function probeClientGpu() {
  const badge = el("gpu-adapter-badge");
  const gateBadge = el("gate-gpu-badge");
  const setBadges = (txt) => {
    if (badge) badge.textContent = txt;
    if (gateBadge) gateBadge.textContent = txt;
  };
  if (window.ort && window.ort.env && window.ort.env.wasm) {
    window.ort.env.wasm.wasmPaths = "/vendor/ort/";
    if (!window.crossOriginIsolated) {
      window.ort.env.wasm.numThreads = 1;
    }
  }
  if (!navigator.gpu) {
    state.gpuSupported = false;
    state.gpuLabel = "WebAssembly SIMD (Trình duyệt chưa bật WebGPU)";
    setBadges("🟡 WebAssembly SIMD (CPU)");
    state.deviceFingerprint = getOrCreateDeviceFingerprint(state.gpuLabel);
    return;
  }
  try {
    const adapter = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter) {
      throw new Error("No WebGPU adapter");
    }
    let info = adapter.info || {};
    if (!info.vendor && typeof adapter.requestAdapterInfo === "function") {
      try {
        info = await adapter.requestAdapterInfo();
      } catch (_) {}
    }
    const desc = [info.description, info.vendor, info.architecture]
      .filter(Boolean)
      .join(" · ")
      .trim() || "Card Đồ Họa Rời / Tích hợp DirectX12-Vulkan";
    state.gpuSupported = true;
    state.gpuLabel = desc;
    setBadges(`🟢 WebGPU Sẵn sàng · ${desc}`);
  } catch (_) {
    state.gpuSupported = false;
    state.gpuLabel = "WebAssembly SIMD Fallback";
    setBadges("🟡 WebAssembly SIMD (CPU)");
  }
  state.deviceFingerprint = getOrCreateDeviceFingerprint(state.gpuLabel);
}

function updateLicenseTelemetry(lic, deviceId, epLabel, cryptoLabel) {
  el("auth-telemetry").classList.remove("hidden");
  el("tele-owner").textContent = `${lic.owner} (${lic.plan})`;
  if (deviceId) el("tele-device").textContent = `${deviceId} (${lic.active_devices_count}/${lic.max_devices} máy)`;
  if (epLabel) el("tele-ep").textContent = epLabel;
  if (cryptoLabel) el("tele-crypto").textContent = cryptoLabel;

  const rem = Number(lic.quota_ha_remaining || 0);
  const tot = Math.max(0.01, Number(lic.quota_ha_total || 1));
  el("tele-quota-text").textContent = `${rem.toFixed(2)} / ${tot.toFixed(0)} ha`;
  const pct = Math.max(0, Math.min(100, (rem / tot) * 100));
  el("tele-quota-fill").style.width = `${pct.toFixed(1)}%`;
}

function populateModelSelect(models) {
  if (!Array.isArray(models)) return;
  for (const selId of ["model-select", "gate-model-select"]) {
    const sel = el(selId);
    if (!sel) continue;
    const currentVal = sel.value || "terrain_seg";
    sel.innerHTML = "";
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.disabled = !m.ready;
      const displayTitle =
        m.id === "terrain_seg" || m.id === "terrain_9classes"
          ? "🧠 Model 9 Lớp (Huấn luyện chuẩn ACAD_KHU TAM GIAC.dwg + Mylib2 Block Grid + TCVN Scale)"
          : m.title;
      opt.textContent = m.ready ? `${displayTitle} [${m.size_mb} MB]` : `${displayTitle} (Chưa xuất ONNX)`;
      sel.appendChild(opt);
    }
    if ([...sel.options].some((o) => o.value === currentVal && !o.disabled)) {
      sel.value = currentVal;
    }
  }
}

async function refreshAdminLicenses(throwOnAuthError = false) {
  if (state.publicMode && !state.adminPassword && !throwOnAuthError) return;
  try {
    const res = await apiGet("/api/webgpu/licenses");
    const data = await res.json();
    populateModelSelect(data.available_models);

    const listEl = el("adm-license-list");
    if (!listEl) return;
    listEl.innerHTML = "";
    for (const item of data.licenses || []) {
      const div = document.createElement("div");
      div.className = "adm-item";
      const stBadge = item.status === "active" ? "🟢 Active" : "🔴 Khóa";
      div.innerHTML = `
        <div class="adm-item-top">
          <span>${item.key}</span>
          <span>${stBadge}</span>
        </div>
        <div>${item.owner} · Còn <strong>${item.quota_ha_remaining}</strong>/${item.quota_ha_total} ha · Thiết bị: ${item.active_devices_count}/${item.max_devices}</div>
        <div class="adm-actions">
          <button type="button" class="btn-xs" data-use-key="${item.key}">Dùng Key</button>
          <button type="button" class="btn-xs" data-act="reset_devices" data-key="${item.key}">Reset Máy</button>
          ${
            item.status === "active"
              ? `<button type="button" class="btn-xs" data-act="revoke" data-key="${item.key}">Khóa Key</button>`
              : `<button type="button" class="btn-xs" data-act="activate" data-key="${item.key}">Mở lại</button>`
          }
        </div>
      `;
      listEl.appendChild(div);
    }
  } catch (err) {
    if (throwOnAuthError) throw err;
  }
}

async function authenticateAndLoadEncryptedModel() {
  const btn = el("btn-auth-load");
  const key = (el("license-key-input").value || "").trim();
  const modelId = el("model-select").value || "terrain_seg";
  if (!key) {
    setStatus("Vui lòng nhập License Key.", "error");
    return;
  }

  btn.disabled = true;
  const t0 = performance.now();
  try {
    setStatus("🔐 Đang xác thực Key &amp; cấp phiên giải mã…");
    const auth = await apiPost("/api/webgpu/auth", {
      license_key: key,
      device_fingerprint: state.deviceFingerprint,
      gpu_label: state.gpuLabel,
      model_id: modelId,
    });

    setStatus("📥 Đang nạp &amp; giải mã mô hình trong RAM…");
    const streamRes = await apiGet(`/api/webgpu/model-stream?lease=${encodeURIComponent(auth.crypto.lease_token)}`);
    const cipherBuf = await streamRes.arrayBuffer();

    const rawKey = base64ToUint8(auth.crypto.key_b64);
    const iv = base64ToUint8(auth.crypto.iv_b64);
    const cryptoKey = await window.crypto.subtle.importKey("raw", rawKey, { name: "AES-GCM" }, false, ["decrypt"]);
    rawKey.fill(0); // Xóa khóa AES khỏi mảng tạm ngay sau khi nạp vào WebCrypto

    const plainBuf = await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, cryptoKey, cipherBuf);
    const plainBytes = new Uint8Array(plainBuf);

    setStatus("⚙️ Đang nạp mô hình vào GPU…");
    let session = null;
    let usedProvider = "wasm";
    if (state.gpuSupported) {
      try {
        session = await window.ort.InferenceSession.create(plainBytes, {
          executionProviders: ["webgpu", "wasm"],
          graphOptimizationLevel: "all",
        });
        usedProvider = "webgpu";
      } catch (_) {
        session = null;
      }
    }
    if (!session) {
      session = await window.ort.InferenceSession.create(plainBytes, {
        executionProviders: ["wasm"],
        graphOptimizationLevel: "all",
      });
      usedProvider = "wasm";
    }
    plainBytes.fill(0); // Xóa bản rõ ONNX trong mảng byte sau khi nạp vào VRAM/ORT

    state.ortSession = session;
    state.activeProvider = usedProvider;
    state.activeLicenseKey = auth.license.key;
    state.activeModelInfo = auth.model;
    try {
      sessionStorage.setItem("uav_verified_license_key", auth.license.key);
    } catch (_) {}

    const elapsedMs = Math.round(performance.now() - t0);
    const epText = usedProvider === "webgpu" ? `WEBGPU (${state.gpuLabel})` : "WASM SIMD (CPU)";
    updateLicenseTelemetry(
      auth.license,
      auth.device_id,
      epText,
      `AES-256-GCM RAM (${(auth.crypto.encrypted_bytes / 1024).toFixed(0)} KB · ${elapsedMs} ms)`
    );
    updateRunButtonState();
    await refreshAdminLicenses();
    unlockPortalWorkspace();
    setStatus(
      `✅ Đã nạp mô hình <strong>${auth.model.title}</strong> (${epText} · ${elapsedMs} ms).`
    );
  } catch (err) {
    setStatus(`❌ Lỗi xác thực / nạp mô hình: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

function updateRunButtonState() {
  el("btn-run-webgpu").disabled = !(state.ortSession && state.raster);
}

// ============================================================================
// BỘ ĐỌC ĐA TỆP KHẢO SÁT: ORTHO (.JPG + .JGW + .PRJ) + DEM (.TIF) & GEOTIFF
// ============================================================================

function parsePrjWkt(wktText) {
  const txt = String(wktText || "").trim();
  if (!txt) return { crsName: "Tọa độ phẳng (Mét)", unitFactor: 1.0, isProjected: true };
  const projMatch = txt.match(/PROJCS\s*\[\s*"([^"]+)"/i);
  const geogMatch = txt.match(/GEOGCS\s*\[\s*"([^"]+)"/i);
  const isProjected = Boolean(projMatch) || !/UNIT\s*\[\s*"Degree"/i.test(txt);
  const crsName = projMatch?.[1] || geogMatch?.[1] || "VN2000 / Projected";
  const unitFactor = isProjected ? 1.0 : 111320.0;
  return { crsName, unitFactor, isProjected };
}

function parseWorldFileText(rawText) {
  const nums = String(rawText || "")
    .trim()
    .split(/[\r\n]+/)
    .map((line) => Number(line.trim().replace(",", ".")))
    .filter((v) => Number.isFinite(v));
  if (nums.length < 6) {
    throw new Error("Tệp World File (.jgw/.tfw/.wld) phải có đủ 6 dòng thông số tọa độ Affine.");
  }
  const [A, D, B, E, C, F] = nums;
  // C, F trong chuẩn .jgw là tâm pixel (0,0) -> đổi về góc trên-trái (0,0) khớp GDAL / AutoCAD
  const cornerX = C - 0.5 * A - 0.5 * B;
  const cornerY = F - 0.5 * D - 0.5 * E;
  return { A, D, B, E, cornerX, cornerY };
}

async function readJpegDimensionsFast(blob) {
  // Đọc kích thước gốc (origW x origH) từ header nhị phân SOF0..SOFCF chỉ với 2 MB đầu (không tốn RAM cho ảnh 300+ MB)
  try {
    const headBuf = await blob.slice(0, Math.min(blob.size, 2 * 1024 * 1024)).arrayBuffer();
    const dv = new DataView(headBuf);
    if (dv.byteLength > 12 && dv.getUint16(0) === 0xffd8) {
      let off = 2;
      while (off + 9 < dv.byteLength) {
        if (dv.getUint8(off) !== 0xff) {
          off++;
          continue;
        }
        while (off < dv.byteLength && dv.getUint8(off) === 0xff) off++;
        if (off + 7 >= dv.byteLength) break;
        const marker = dv.getUint8(off++);
        if (marker === 0xd8 || marker === 0xd9 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0x01) {
          continue;
        }
        const segLen = dv.getUint16(off);
        const isSof =
          (marker >= 0xc0 && marker <= 0xc3) ||
          (marker >= 0xc5 && marker <= 0xc7) ||
          (marker >= 0xc9 && marker <= 0xcb) ||
          (marker >= 0xcd && marker <= 0xcf);
        if (isSof) {
          const height = dv.getUint16(off + 3);
          const width = dv.getUint16(off + 5);
          if (width > 0 && height > 0) return { width, height };
        }
        if (segLen < 2) break;
        off += segLen;
      }
    }
  } catch (_) {}
  const bmp = await createImageBitmap(blob);
  const dims = { width: bmp.width, height: bmp.height };
  bmp.close();
  return dims;
}

function updateBundleChecklistUI() {
  const box = el("bundle-checklist");
  if (!box) return;
  const { orthoFile, worldFile, prjFile, demFile } = state.bundle;
  if (!orthoFile && !worldFile && !prjFile && !demFile) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");

  const setPill = (id, labelHtml, cls) => {
    const node = el(id);
    if (!node) return;
    node.className = `bundle-pill ${cls || ""}`.trim();
    const sp = node.querySelector("span");
    if (sp) sp.innerHTML = labelHtml;
  };

  if (orthoFile) {
    setPill("bdl-ortho", `${orthoFile.name} ✓`, "ok");
  } else {
    setPill("bdl-ortho", "Chưa chọn ORTHO (.jpg / .tif RGB) ⚠️", "warn");
  }

  const isOrthoJpg = orthoFile && /\.(jpe?g|png)$/i.test(orthoFile.name || "");
  if (worldFile) {
    setPill("bdl-world", `${worldFile.name} ✓`, "ok");
  } else if (isOrthoJpg) {
    setPill("bdl-world", "Chưa gắn .jgw (Hãy chọn kèm .jgw!) ⚠️", "warn");
  } else {
    setPill("bdl-world", orthoFile ? "Đọc trực tiếp từ GeoTIFF ✓" : "Chưa có", orthoFile ? "ok" : "");
  }

  if (prjFile) {
    setPill("bdl-prj", `${prjFile.name} ✓`, "ok");
  } else {
    setPill("bdl-prj", orthoFile ? "Hệ phẳng Mét (VN2000/UTM)" : "Chưa có", "");
  }

  if (demFile) {
    setPill("bdl-dem", `${demFile.name} ✓`, "ok");
  } else {
    setPill("bdl-dem", "Chưa gắn (Tùy chọn)", "");
  }
}

function boxSmooth2D(grid, validMask, w, h, radius) {
  const r = Math.max(4, Math.min(128, radius | 0));
  const tmp = new Float64Array(w * h);
  const tmpCnt = new Uint32Array(w * h);
  const out = new Float32Array(w * h);
  const prefS = new Float64Array(Math.max(w, h) + 1);
  const prefC = new Uint32Array(Math.max(w, h) + 1);

  // Lượt ngang O(W * H) bằng mảng cộng dồn (Prefix Sum)
  for (let y = 0; y < h; y++) {
    const row = y * w;
    prefS[0] = 0;
    prefC[0] = 0;
    for (let x = 0; x < w; x++) {
      const ok = validMask[row + x] ? 1 : 0;
      prefS[x + 1] = prefS[x] + (ok ? grid[row + x] : 0);
      prefC[x + 1] = prefC[x] + ok;
    }
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - r);
      const x1 = Math.min(w - 1, x + r) + 1;
      tmp[row + x] = prefS[x1] - prefS[x0];
      tmpCnt[row + x] = prefC[x1] - prefC[x0];
    }
  }
  // Lượt dọc O(W * H)
  for (let x = 0; x < w; x++) {
    prefS[0] = 0;
    prefC[0] = 0;
    for (let y = 0; y < h; y++) {
      prefS[y + 1] = prefS[y] + tmp[y * w + x];
      prefC[y + 1] = prefC[y] + tmpCnt[y * w + x];
    }
    for (let y = 0; y < h; y++) {
      const y0 = Math.max(0, y - r);
      const y1 = Math.min(h - 1, y + r) + 1;
      const c = prefC[y1] - prefC[y0];
      out[y * w + x] = c > 0 ? (prefS[y1] - prefS[y0]) / c : 0;
    }
  }
  return out;
}

async function loadAlignedDemGrid(demBlob, orthoMeta) {
  if (!window.GeoTIFF || !demBlob) return null;
  const tiff = await window.GeoTIFF.fromBlob(demBlob);
  const baseImg = await tiff.getImage(0);
  const demOrigW = baseImg.getWidth();
  const demOrigH = baseImg.getHeight();

  let demOriginX = orthoMeta.cornerX;
  let demOriginY = orthoMeta.cornerY;
  let demResX = orthoMeta.origGsdM;
  let demResY = -orthoMeta.origGsdM;
  try {
    const orig = baseImg.getOrigin();
    if (Array.isArray(orig) && Number.isFinite(orig[0]) && Number.isFinite(orig[1])) {
      demOriginX = orig[0] * orthoMeta.unitFactor;
      demOriginY = orig[1] * orthoMeta.unitFactor;
    }
    const res = baseImg.getResolution();
    if (Array.isArray(res) && Number.isFinite(res[0]) && Math.abs(res[0]) > 1e-9) {
      demResX = Math.abs(res[0]) * orthoMeta.unitFactor;
      demResY = (res[1] < 0 ? res[1] : -Math.abs(res[1] || res[0])) * orthoMeta.unitFactor;
    }
  } catch (_) {}

  // Chọn mức Overview tối ưu nếu tệp DEM lớn (800+ MB) có sẵn kim tự tháp ảnh
  const imgCount = await tiff.getImageCount();
  let readImg = baseImg;
  for (let i = 1; i < imgCount; i++) {
    try {
      const cand = await tiff.getImage(i);
      if (cand.getWidth() >= 384 && cand.getWidth() < readImg.getWidth()) {
        readImg = cand;
      }
    } catch (_) {}
  }

  const rw = readImg.getWidth();
  const rh = readImg.getHeight();
  const gridW = Math.min(512, rw);
  const gridH = Math.min(512, rh);
  let demBuf = null;

  if (rw * rh <= 28_000_000) {
    // Đọc trực tiếp từ mức overview nhỏ gọn
    const ras = await readImg.readRasters({ width: gridW, height: gridH, interleave: true, samples: [0] });
    demBuf = Float32Array.from(ras);
  } else {
    // Tệp DEM đơn lớp dung lượng rất lớn (> 200 MB, không có overview): đọc thưa từng dòng quét (scanline) để không tràn RAM
    demBuf = new Float32Array(gridW * gridH);
    for (let gy = 0; gy < gridH; gy++) {
      const srcRow = Math.min(rh - 1, Math.floor((gy * rh) / gridH));
      const rowRas = await readImg.readRasters({
        window: [0, srcRow, rw, srcRow + 1],
        width: gridW,
        height: 1,
        interleave: true,
        samples: [0],
      });
      for (let gx = 0; gx < gridW; gx++) {
        demBuf[gy * gridW + gx] = rowRas[gx];
      }
    }
  }

  // Nội suy cao độ DEM khớp chính xác theo tọa độ phẳng VN2000 (mapX, mapY) của từng điểm lưới ORTHO
  const { anaW, anaH, origW, origH, affA, affB, affD, affE, cornerX, cornerY, anaGsdM } = orthoMeta;
  const demSpanX = demOrigW * demResX;
  const demSpanY = demOrigH * demResY; // âm

  const demZ = new Float32Array(anaW * anaH);
  const validMask = new Uint8Array(anaW * anaH);
  let minZ = Infinity;
  let maxZ = -Infinity;
  let validCount = 0;

  for (let py = 0; py < anaH; py++) {
    const gy = py * (origH / anaH);
    for (let px = 0; px < anaW; px++) {
      const gx = px * (origW / anaW);
      const mapX = cornerX + gx * affA + gy * affB;
      const mapY = cornerY + gx * affD + gy * affE;

      const u = (mapX - demOriginX) / (demSpanX || 1);
      const v = (mapY - demOriginY) / (demSpanY || -1);
      const idx = py * anaW + px;

      if (u >= 0 && u <= 1 && v >= 0 && v <= 1) {
        const dx = Math.min(gridW - 1, Math.max(0, Math.round(u * (gridW - 1))));
        const dy = Math.min(gridH - 1, Math.max(0, Math.round(v * (gridH - 1))));
        const z = demBuf[dy * gridW + dx];
        if (Number.isFinite(z) && z > -200 && z < 8500) {
          demZ[idx] = z;
          validMask[idx] = 1;
          validCount++;
          if (z < minZ) minZ = z;
          if (z > maxZ) maxZ = z;
          continue;
        }
      }
      demZ[idx] = NaN;
    }
  }

  if (validCount < 32) return null;
  // Bán kính nền địa hình cục bộ ~8.5m (cửa sổ ~17m) để toàn bộ mái tôn / tán cây 3m-12m có demRel dương rõ rệt
  const smoothRadius = Math.max(12, Math.min(120, Math.round(8.5 / Math.max(0.03, anaGsdM))));
  const localBaseZ = boxSmooth2D(demZ, validMask, anaW, anaH, smoothRadius);
  const demRel = new Float32Array(anaW * anaH);
  for (let i = 0; i < anaW * anaH; i++) {
    demRel[i] = validMask[i] ? demZ[i] - localBaseZ[i] : 0;
  }
  return { demZ, demRel, validMask, minZ, maxZ };
}

async function ingestSurveyFiles(rawFiles) {
  const files = Array.from(rawFiles || []).filter(Boolean);
  if (!files.length) return;

  const worldCandidates = [];
  const prjCandidates = [];
  const fileDepth = (f) => String(f.webkitRelativePath || f.name || "").split("/").length;
  const stemOf = (name) => String(name || "").replace(/\.[^.]+$/, "").trim().toLowerCase();

  // Lượt 1: Nhận diện tệp ảnh màu ORTHO (.jpg/.png/.tif RGB) và tệp cao độ DEM (.tif 1 kênh)
  for (const f of files) {
    const name = f.name || "";
    const lower = name.toLowerCase();
    if (/\.(jgw|tfw|pgw|wld|jpw)$/i.test(lower)) {
      worldCandidates.push(f);
    } else if (/\.prj$/i.test(lower)) {
      prjCandidates.push(f);
    } else if (/\.(jpe?g|png)$/i.test(lower)) {
      const cur = state.bundle.orthoFile;
      const curIsOrtho = cur && /ortho/i.test(cur.name || "");
      const candIsOrtho = /ortho/i.test(name);
      if (
        !cur ||
        !/\.(jpe?g|png)$/i.test(cur.name || "") ||
        (candIsOrtho && !curIsOrtho) ||
        (candIsOrtho === curIsOrtho && fileDepth(f) <= fileDepth(cur) && (f.size || 0) >= (cur.size || 0))
      ) {
        state.bundle.orthoFile = f;
      }
    } else if (/\.tiff?$/i.test(lower)) {
      let isDem = /(^|[\s_.-])(dem|dsm|dtm)([\s_.-]|$)/i.test(name);
      if (!isDem && window.GeoTIFF) {
        try {
          const t = await window.GeoTIFF.fromBlob(f);
          const img0 = await t.getImage(0);
          if (img0.getSamplesPerPixel() === 1) isDem = true;
        } catch (_) {}
      }
      if (isDem) {
        if (!state.bundle.demFile || (f.size || 0) >= (state.bundle.demFile.size || 0)) {
          state.bundle.demFile = f;
        }
      } else if (!state.bundle.orthoFile || /ortho/i.test(name) || (f.size || 0) >= (state.bundle.orthoFile.size || 0)) {
        state.bundle.orthoFile = f;
      }
    }
  }

  // Lượt 2: Ghép chính xác tệp .jgw/.tfw và .prj trùng tên với tệp ORTHO
  const orthoStem = state.bundle.orthoFile ? stemOf(state.bundle.orthoFile.name) : "";
  if (worldCandidates.length) {
    worldCandidates.sort((a, b) => {
      const aMatch = orthoStem && stemOf(a.name) === orthoStem ? 0 : /ortho/i.test(a.name) ? 1 : 2;
      const bMatch = orthoStem && stemOf(b.name) === orthoStem ? 0 : /ortho/i.test(b.name) ? 1 : 2;
      return aMatch - bMatch || fileDepth(a) - fileDepth(b);
    });
    state.bundle.worldFile = worldCandidates[0];
  }
  if (prjCandidates.length) {
    prjCandidates.sort((a, b) => {
      const aMatch = orthoStem && stemOf(a.name) === orthoStem ? 0 : /ortho/i.test(a.name) ? 1 : 2;
      const bMatch = orthoStem && stemOf(b.name) === orthoStem ? 0 : /ortho/i.test(b.name) ? 1 : 2;
      return aMatch - bMatch || fileDepth(a) - fileDepth(b);
    });
    state.bundle.prjFile = prjCandidates[0];
  }

  updateBundleChecklistUI();

  if (!state.bundle.orthoFile) {
    if (state.bundle.demFile) {
      setStatus(
        `⛰️ Đã nạp DEM <strong>${state.bundle.demFile.name}</strong>. Hãy chọn thêm ảnh ORTHO RGB.`,
        "warn"
      );
    } else {
      setStatus(
        `📎 Đã nhận tệp phụ trợ. Cần thêm ảnh ORTHO RGB.`,
        "warn"
      );
    }
    return;
  }

  await buildRasterFromCurrentBundle();
}

async function buildRasterFromCurrentBundle() {
  const { orthoFile, worldFile, prjFile, demFile } = state.bundle;
  if (!orthoFile) return;

  const isJpgOrPng = /\.(jpe?g|png)$/i.test(orthoFile.name || "");
  const prjInfo = prjFile ? parsePrjWkt(await prjFile.text()) : { crsName: "VN2000 / Hệ phẳng (Mét)", unitFactor: 1.0, isProjected: true };
  let unitFactor = prjInfo.unitFactor;

  let origW = 1024;
  let origH = 1024;
  let anaW = 1024;
  let anaH = 1024;
  let rgbData = null;
  let rgbCanvas = null;

  let affA = 0.05;
  let affD = 0.0;
  let affB = 0.0;
  let affE = -0.05;
  let cornerX = 584100.0;
  let cornerY = 1040200.0;
  let hasTrueGeoref = false;

  if (isJpgOrPng) {
    setStatus(`🖼️ Đang nạp <strong>${orthoFile.name}</strong> (${((orthoFile.size || 0) / (1024 * 1024)).toFixed(1)} MB)…`);
    const dims = await readJpegDimensionsFast(orthoFile);
    origW = dims.width;
    origH = dims.height;

    const maxSide = 1280;
    const downScale = Math.max(1.0, Math.max(origW, origH) / maxSide);
    anaW = Math.max(64, Math.round(origW / downScale));
    anaH = Math.max(64, Math.round(origH / downScale));

    let bmp = null;
    try {
      bmp = await createImageBitmap(orthoFile, { resizeWidth: anaW, resizeHeight: anaH, resizeQuality: "high" });
    } catch (_) {
      bmp = await createImageBitmap(orthoFile);
    }
    rgbCanvas = document.createElement("canvas");
    rgbCanvas.width = anaW;
    rgbCanvas.height = anaH;
    const cctx = rgbCanvas.getContext("2d", { willReadFrequently: true });
    cctx.drawImage(bmp, 0, 0, anaW, anaH);
    bmp.close();

    const imgData = cctx.getImageData(0, 0, anaW, anaH).data;
    rgbData = new Uint8Array(anaW * anaH * 3);
    for (let p = 0; p < anaW * anaH; p++) {
      rgbData[p * 3] = imgData[p * 4];
      rgbData[p * 3 + 1] = imgData[p * 4 + 1];
      rgbData[p * 3 + 2] = imgData[p * 4 + 2];
    }

    if (worldFile) {
      const wf = parseWorldFileText(await worldFile.text());
      if (!prjFile && Math.abs(wf.A) < 0.0005) unitFactor = 111320.0;
      affA = wf.A * unitFactor;
      affD = wf.D * unitFactor;
      affB = wf.B * unitFactor;
      affE = wf.E * unitFactor;
      cornerX = wf.cornerX * unitFactor;
      cornerY = wf.cornerY * unitFactor;
      hasTrueGeoref = true;
    } else if (demFile && window.GeoTIFF) {
      // Nếu người dùng mới chọn ORTHO.jpg + DEM.tif mà quên tick .jgw, tạm mượn khung tọa độ từ DEM.tif và nhắc gắn thêm .jgw
      try {
        const dt = await window.GeoTIFF.fromBlob(demFile);
        const dImg = await dt.getImage(0);
        const dOrig = dImg.getOrigin();
        const dRes = dImg.getResolution();
        if (Array.isArray(dOrig) && Array.isArray(dRes)) {
          cornerX = dOrig[0] * unitFactor;
          cornerY = dOrig[1] * unitFactor;
          affA = ((dImg.getWidth() * Math.abs(dRes[0])) / origW) * unitFactor;
          affE = -((dImg.getHeight() * Math.abs(dRes[1] || dRes[0])) / origH) * unitFactor;
        }
      } catch (_) {}
    }
  } else {
    // RGB GeoTIFF (.tif / .tiff)
    if (!window.GeoTIFF) throw new Error("Chưa nạp được thư viện geotiff.js");
    setStatus(`📂 Đang đọc GeoTIFF <strong>${orthoFile.name}</strong>…`);
    const tiff = await window.GeoTIFF.fromBlob(orthoFile);
    const baseImage = await tiff.getImage(0);
    origW = baseImage.getWidth();
    origH = baseImage.getHeight();

    try {
      const orig = baseImage.getOrigin();
      const res = baseImage.getResolution();
      if (Array.isArray(orig) && Number.isFinite(orig[0]) && Number.isFinite(orig[1])) {
        if (!prjFile && Array.isArray(res) && Math.abs(res[0]) < 0.0005) unitFactor = 111320.0;
        cornerX = orig[0] * unitFactor;
        cornerY = orig[1] * unitFactor;
        hasTrueGeoref = true;
      }
      if (Array.isArray(res) && Number.isFinite(res[0]) && Math.abs(res[0]) > 1e-9) {
        affA = Math.abs(res[0]) * unitFactor;
        affE = (res[1] < 0 ? res[1] : -Math.abs(res[1] || res[0])) * unitFactor;
      }
    } catch (_) {}

    if (worldFile) {
      const wf = parseWorldFileText(await worldFile.text());
      affA = wf.A * unitFactor;
      affD = wf.D * unitFactor;
      affB = wf.B * unitFactor;
      affE = wf.E * unitFactor;
      cornerX = wf.cornerX * unitFactor;
      cornerY = wf.cornerY * unitFactor;
      hasTrueGeoref = true;
    }

    const maxSide = 1280;
    const downScale = Math.max(1.0, Math.max(origW, origH) / maxSide);
    anaW = Math.max(64, Math.round(origW / downScale));
    anaH = Math.max(64, Math.round(origH / downScale));

    // Ưu tiên đọc từ mức pyramid overview gần anaW nhất để tránh giải nén hàng GB
    const imgCount = await tiff.getImageCount();
    let readImage = baseImage;
    for (let i = 1; i < imgCount; i++) {
      try {
        const cand = await tiff.getImage(i);
        if (cand.getWidth() >= anaW && cand.getWidth() < readImage.getWidth()) {
          readImage = cand;
        }
      } catch (_) {}
    }

    const samplesCount = readImage.getSamplesPerPixel();
    const sampleIndices = samplesCount >= 3 ? [0, 1, 2] : [0];
    const rasters = await readImage.readRasters({
      width: anaW,
      height: anaH,
      interleave: true,
      samples: sampleIndices,
    });

    rgbData = new Uint8Array(anaW * anaH * 3);
    const rgba = new Uint8ClampedArray(anaW * anaH * 4);
    const isUint8 = rasters instanceof Uint8Array || rasters instanceof Uint8ClampedArray;
    let minV = Infinity;
    let maxV = -Infinity;
    if (!isUint8) {
      for (let i = 0; i < rasters.length; i += 13) {
        const v = rasters[i];
        if (Number.isFinite(v) && v > 0) {
          if (v < minV) minV = v;
          if (v > maxV) maxV = v;
        }
      }
      if (!Number.isFinite(minV) || maxV <= minV) {
        minV = 0;
        maxV = 255;
      }
    }
    const stride = sampleIndices.length;
    for (let p = 0; p < anaW * anaH; p++) {
      let r = stride >= 3 ? rasters[p * 3] : rasters[p];
      let g = stride >= 3 ? rasters[p * 3 + 1] : rasters[p];
      let b = stride >= 3 ? rasters[p * 3 + 2] : rasters[p];
      if (!isUint8) {
        const span = maxV - minV || 1;
        r = Math.max(0, Math.min(255, ((r - minV) / span) * 255));
        g = Math.max(0, Math.min(255, ((g - minV) / span) * 255));
        b = Math.max(0, Math.min(255, ((b - minV) / span) * 255));
      }
      rgbData[p * 3] = r;
      rgbData[p * 3 + 1] = g;
      rgbData[p * 3 + 2] = b;
      rgba[p * 4] = r;
      rgba[p * 4 + 1] = g;
      rgba[p * 4 + 2] = b;
      rgba[p * 4 + 3] = r === 0 && g === 0 && b === 0 ? 0 : 255;
    }
    rgbCanvas = document.createElement("canvas");
    rgbCanvas.width = anaW;
    rgbCanvas.height = anaH;
    rgbCanvas.getContext("2d").putImageData(new ImageData(rgba, anaW, anaH), 0, 0);
  }

  const origGsdX = Math.hypot(affA, affD);
  const origGsdY = Math.hypot(affB, affE);
  const origGsdM = Math.max(0.005, (origGsdX + origGsdY) * 0.5);
  const anaGsdM = origGsdM * (origW / anaW);
  const areaHa = Math.max(0.005, (origW * origGsdX * (origH * origGsdY)) / 10000.0);

  // Tính khung bao tọa độ thực từ 4 góc ảnh (kể cả khi ảnh có góc xoay trong .jgw)
  const cornersMap = [
    [cornerX, cornerY],
    [cornerX + origW * affA, cornerY + origW * affD],
    [cornerX + origW * affA + origH * affB, cornerY + origW * affD + origH * affE],
    [cornerX + origH * affB, cornerY + origH * affE],
  ];
  const minMapX = Math.min(...cornersMap.map((c) => c[0]));
  const minMapY = Math.min(...cornersMap.map((c) => c[1]));
  el("base-x-input").value = Math.round(minMapX * 100) / 100;
  el("base-y-input").value = Math.round(minMapY * 100) / 100;

  const rasterObj = {
    fileName: orthoFile.name || "uav_ortho.tif",
    origW,
    origH,
    anaW,
    anaH,
    rgbData,
    rgbCanvas,
    affA,
    affB,
    affD,
    affE,
    cornerX,
    cornerY,
    unitFactor,
    crsName: prjInfo.crsName,
    hasTrueGeoref,
    origGsdM,
    anaGsdM,
    areaHa,
    demGrid: null,
  };

  if (demFile) {
    try {
      setStatus(`⛰️ Đang đồng bộ cao độ DEM <strong>${demFile.name}</strong>…`);
      rasterObj.demGrid = await loadAlignedDemGrid(demFile, rasterObj);
    } catch (_) {
      rasterObj.demGrid = null;
    }
  }

  state.raster = rasterObj;
  state.maskCanvas = null;
  state.segMask = null;
  state.features = [];
  el("btn-download-dxf").disabled = true;
  el("btn-download-geojson").disabled = true;

  const sizeMb = ((orthoFile.size || 0) / (1024 * 1024)).toFixed(1);
  const partsLoaded = [orthoFile.name, worldFile?.name, prjFile?.name, demFile?.name].filter(Boolean).join(" + ");
  el("local-file-label").textContent = `${partsLoaded} · ${sizeMb} MB (0 Byte Upload)`;
  el("raster-meta-box").classList.remove("hidden");
  if (el("meta-model")) {
    el("meta-model").textContent =
      "🧠 Model 9 Lớp (Huấn luyện chuẩn ACAD_KHU TAM GIAC.dwg + Mylib2 Block Grid + TCVN Scale)";
  }
  el("meta-dims").textContent = `${origW} × ${origH} px (lưới GPU ${anaW} × ${anaH})`;
  el("meta-gsd").textContent = `${(origGsdM * 100).toFixed(2)} cm/px · ${prjInfo.crsName}`;
  if (el("meta-dem")) {
    el("meta-dem").textContent = rasterObj.demGrid
      ? `${demFile.name} (Z: ${rasterObj.demGrid.minZ.toFixed(2)}m → ${rasterObj.demGrid.maxZ.toFixed(2)}m)`
      : demFile
      ? `${demFile.name} (Khác vùng tọa độ)`
      : "Chưa gắn DEM (Chạy RGB + Hình thái học)";
  }
  el("meta-area").textContent = `${areaHa.toFixed(3)} ha`;
  el("canvas-empty-overlay").classList.add("hidden");

  fitCanvasView();
  renderViewport();
  updateRunButtonState();
  updateSummaryCounts();

  const trainedModelTag =
    "<strong>🧠 Model 9 Lớp (Huấn luyện chuẩn <code>ACAD_KHU TAM GIAC.dwg</code> + Mylib2 Block Grid + TCVN Scale)</strong>";
  if (isJpgOrPng && !worldFile) {
    setStatus(
      `⚠️ Đã nạp <strong>${orthoFile.name}</strong> (thiếu .jgw định vị tọa độ) · Sẵn sàng áp dụng ${trainedModelTag}.`,
      "warn"
    );
  } else {
    const demNote = rasterObj.demGrid ? ` + ghép DEM <strong>${demFile.name}</strong>` : "";
    setStatus(
      state.ortSession
        ? `✅ Đã nạp <strong>${orthoFile.name}</strong>${demNote} · ${trainedModelTag} sẵn sàng nhận diện &amp; dàn bản vẽ tự động!`
        : `✅ Đã nạp <strong>${orthoFile.name}</strong>${demNote} · ${trainedModelTag} (Hãy xác thực Key ở Bước 01).`
    );
  }
}

async function decodeGeoTiffBlob(blob, fileName) {
  const pseudoFile = new File([blob], fileName, { type: "image/tiff" });
  state.bundle = { orthoFile: pseudoFile, worldFile: null, prjFile: null, demFile: null };
  updateBundleChecklistUI();
  await buildRasterFromCurrentBundle();
}

// ============================================================================
// THUẬT TOÁN HÌNH HỌC & VECTOR HÓA BÌNH ĐỒ TRÊN TRÌNH DUYỆT (CLIENT-SIDE JS)
// ============================================================================

function morphDilate(bin, w, h, r) {
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - r);
    const y1 = Math.min(h - 1, y + r);
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - r);
      const x1 = Math.min(w - 1, x + r);
      let hit = 0;
      for (let yy = y0; yy <= y1 && !hit; yy++) {
        const rowOff = yy * w;
        for (let xx = x0; xx <= x1; xx++) {
          if (bin[rowOff + xx]) {
            hit = 1;
            break;
          }
        }
      }
      out[y * w + x] = hit;
    }
  }
  return out;
}

function morphErode(bin, w, h, r) {
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - r);
    const y1 = Math.min(h - 1, y + r);
    for (let x = 0; x < w; x++) {
      if (!bin[y * w + x]) continue;
      const x0 = Math.max(0, x - r);
      const x1 = Math.min(w - 1, x + r);
      let ok = 1;
      for (let yy = y0; yy <= y1 && ok; yy++) {
        const rowOff = yy * w;
        for (let xx = x0; xx <= x1; xx++) {
          if (!bin[rowOff + xx]) {
            ok = 0;
            break;
          }
        }
      }
      out[y * w + x] = ok;
    }
  }
  return out;
}

function morphClose(bin, w, h, r) {
  return morphErode(morphDilate(bin, w, h, r), w, h, r);
}

function chamferDistanceTransform(bin, w, h) {
  const INF = 1e6;
  const dist = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) dist[i] = bin[i] ? INF : 0;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = y * w + x;
      if (!dist[idx]) continue;
      let d = dist[idx];
      if (x > 0) d = Math.min(d, dist[idx - 1] + 1.0);
      if (y > 0) {
        d = Math.min(d, dist[idx - w] + 1.0);
        if (x > 0) d = Math.min(d, dist[idx - w - 1] + 1.4142);
        if (x + 1 < w) d = Math.min(d, dist[idx - w + 1] + 1.4142);
      }
      dist[idx] = d;
    }
  }
  for (let y = h - 1; y >= 0; y--) {
    for (let x = w - 1; x >= 0; x--) {
      const idx = y * w + x;
      if (!dist[idx]) continue;
      let d = dist[idx];
      if (x + 1 < w) d = Math.min(d, dist[idx + 1] + 1.0);
      if (y + 1 < h) {
        d = Math.min(d, dist[idx + w] + 1.0);
        if (x + 1 < w) d = Math.min(d, dist[idx + w + 1] + 1.4142);
        if (x > 0) d = Math.min(d, dist[idx + w - 1] + 1.4142);
      }
      dist[idx] = d;
    }
  }
  return dist;
}

function connectedComponents(bin, w, h, minArea) {
  const labels = new Int32Array(w * h);
  const comps = [];
  const q = new Int32Array(w * h);
  let nextLbl = 0;

  for (let i = 0; i < w * h; i++) {
    if (!bin[i] || labels[i]) continue;
    nextLbl++;
    let head = 0;
    let tail = 0;
    q[tail++] = i;
    labels[i] = nextLbl;
    const pixels = [];
    let minX = w, minY = h, maxX = 0, maxY = 0;

    while (head < tail) {
      const cur = q[head++];
      pixels.push(cur);
      const cx = cur % w;
      const cy = (cur / w) | 0;
      if (cx < minX) minX = cx;
      if (cx > maxX) maxX = cx;
      if (cy < minY) minY = cy;
      if (cy > maxY) maxY = cy;

      for (let dy = -1; dy <= 1; dy++) {
        const ny = cy + dy;
        if (ny < 0 || ny >= h) continue;
        for (let dx = -1; dx <= 1; dx++) {
          if (!dx && !dy) continue;
          const nx = cx + dx;
          if (nx < 0 || nx >= w) continue;
          const ni = ny * w + nx;
          if (bin[ni] && !labels[ni]) {
            labels[ni] = nextLbl;
            q[tail++] = ni;
          }
        }
      }
    }
    if (pixels.length >= minArea) {
      comps.push({ id: nextLbl, pixels, minX, minY, maxX, maxY });
    }
  }
  return comps;
}

function zhangSuenThinning(subBin, sw, sh, maxIter = 55) {
  const img = new Uint8Array(subBin);
  const toClear = [];
  for (let iter = 0; iter < maxIter; iter++) {
    let changed = false;
    for (let step = 0; step < 2; step++) {
      toClear.length = 0;
      for (let y = 1; y < sh - 1; y++) {
        for (let x = 1; x < sw - 1; x++) {
          const idx = y * sw + x;
          if (!img[idx]) continue;
          const p2 = img[idx - sw];
          const p3 = img[idx - sw + 1];
          const p4 = img[idx + 1];
          const p5 = img[idx + sw + 1];
          const p6 = img[idx + sw];
          const p7 = img[idx + sw - 1];
          const p8 = img[idx - 1];
          const p9 = img[idx - sw - 1];

          const B = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9;
          if (B < 2 || B > 6) continue;
          const A =
            (!p2 && p3 ? 1 : 0) +
            (!p3 && p4 ? 1 : 0) +
            (!p4 && p5 ? 1 : 0) +
            (!p5 && p6 ? 1 : 0) +
            (!p6 && p7 ? 1 : 0) +
            (!p7 && p8 ? 1 : 0) +
            (!p8 && p9 ? 1 : 0) +
            (!p9 && p2 ? 1 : 0);
          if (A !== 1) continue;
          if (step === 0) {
            if (p2 * p4 * p6 !== 0 || p4 * p6 * p8 !== 0) continue;
          } else {
            if (p2 * p4 * p8 !== 0 || p2 * p6 * p8 !== 0) continue;
          }
          toClear.push(idx);
        }
      }
      if (toClear.length > 0) {
        changed = true;
        for (let k = 0; k < toClear.length; k++) img[toClear[k]] = 0;
      }
    }
    if (!changed) break;
  }
  return img;
}

function traceSkeletonPolylines(skel, sw, sh, offsetX, offsetY, minLen) {
  const visited = new Uint8Array(sw * sh);
  const deg = new Uint8Array(sw * sh);
  const pts = [];

  for (let y = 1; y < sh - 1; y++) {
    for (let x = 1; x < sw - 1; x++) {
      const idx = y * sw + x;
      if (!skel[idx]) continue;
      let d = 0;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          if ((dx || dy) && skel[(y + dy) * sw + (x + dx)]) d++;
        }
      }
      deg[idx] = d;
      pts.push(idx);
    }
  }
  // Ưu tiên xuất phát từ điểm đầu mút (deg === 1)
  pts.sort((a, b) => (deg[a] === 1 ? 0 : 1) - (deg[b] === 1 ? 0 : 1));

  const paths = [];
  for (const startIdx of pts) {
    if (visited[startIdx]) continue;
    const chain = [];
    let cur = startIdx;
    while (cur !== -1 && !visited[cur]) {
      visited[cur] = 1;
      const cx = cur % sw;
      const cy = (cur / sw) | 0;
      chain.push([cx + offsetX - 1, cy + offsetY - 1]);
      let next = -1;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          if (!dx && !dy) continue;
          const ni = (cy + dy) * sw + (cx + dx);
          if (skel[ni] && !visited[ni]) {
            next = ni;
            if ( dx === 0 || dy === 0 ) break;
          }
        }
        if (next !== -1 && ((next % sw) === cx || ((next / sw) | 0) === cy)) break;
      }
      cur = next;
    }
    if (chain.length >= minLen) paths.push(chain);
  }
  return paths;
}

function traceClosedBoundary(subBin, sw, sh, offsetX, offsetY) {
  let startX = -1, startY = -1;
  for (let y = 1; y < sh - 1 && startY === -1; y++) {
    for (let x = 1; x < sw - 1; x++) {
      if (subBin[y * sw + x]) {
        startX = x;
        startY = y;
        break;
      }
    }
  }
  if (startX === -1) return [];
  // Moore-Neighbor boundary tracing
  const dirs = [
    [1, 0], [1, 1], [0, 1], [-1, 1],
    [-1, 0], [-1, -1], [0, -1], [1, -1],
  ];
  const contour = [];
  let cx = startX, cy = startY;
  let backDir = 4;
  const maxSteps = sw * sh * 2;
  for (let step = 0; step < maxSteps; step++) {
    contour.push([cx + offsetX - 1, cy + offsetY - 1]);
    let found = false;
    for (let k = 1; k <= 8; k++) {
      const dIdx = (backDir + k) & 7;
      const nx = cx + dirs[dIdx][0];
      const ny = cy + dirs[dIdx][1];
      if (nx >= 0 && nx < sw && ny >= 0 && ny < sh && subBin[ny * sw + nx]) {
        cx = nx;
        cy = ny;
        backDir = (dIdx + 4) & 7;
        found = true;
        break;
      }
    }
    if (!found || (cx === startX && cy === startY && contour.length > 4)) break;
  }
  return contour;
}

function simplifyRDP(pts, eps) {
  if (pts.length <= 2) return pts.slice();
  let maxDist = 0;
  let idx = 0;
  const [x1, y1] = pts[0];
  const [x2, y2] = pts[pts.length - 1];
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;

  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i];
    let d;
    if (lenSq < 1e-9) {
      d = Math.hypot(px - x1, py - y1);
    } else {
      const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lenSq));
      d = Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
    }
    if (d > maxDist) {
      maxDist = d;
      idx = i;
    }
  }
  if (maxDist > eps) {
    const left = simplifyRDP(pts.slice(0, idx + 1), eps);
    const right = simplifyRDP(pts.slice(idx), eps);
    return left.slice(0, -1).concat(right);
  }
  return [pts[0], pts[pts.length - 1]];
}

function chaikinSmooth(pts, closed = false) {
  if (pts.length < 3) return pts;
  const out = [];
  if (!closed) out.push(pts[0]);
  const n = closed ? pts.length : pts.length - 1;
  for (let i = 0; i < n; i++) {
    const p0 = pts[i];
    const p1 = pts[(i + 1) % pts.length];
    out.push([0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]]);
    out.push([0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]]);
  }
  if (!closed) out.push(pts[pts.length - 1]);
  return out;
}

function offsetPolylinePair(pts, halfWidth) {
  if (pts.length < 2) return [pts, pts];
  const normals = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const dx = pts[i + 1][0] - pts[i][0];
    const dy = pts[i + 1][1] - pts[i][1];
    const len = Math.hypot(dx, dy) || 1;
    normals.push([-dy / len, dx / len]);
  }
  const left = [];
  const right = [];
  for (let i = 0; i < pts.length; i++) {
    let nx, ny;
    if (i === 0) {
      [nx, ny] = normals[0];
    } else if (i === pts.length - 1) {
      [nx, ny] = normals[normals.length - 1];
    } else {
      nx = (normals[i - 1][0] + normals[i][0]) * 0.5;
      ny = (normals[i - 1][1] + normals[i][1]) * 0.5;
      const nl = Math.hypot(nx, ny) || 1;
      nx /= nl;
      ny /= nl;
    }
    const hasZ = pts[i].length >= 3 && Number.isFinite(pts[i][2]);
    if (hasZ) {
      left.push([pts[i][0] + nx * halfWidth, pts[i][1] + ny * halfWidth, pts[i][2]]);
      right.push([pts[i][0] - nx * halfWidth, pts[i][1] - ny * halfWidth, pts[i][2]]);
    } else {
      left.push([pts[i][0] + nx * halfWidth, pts[i][1] + ny * halfWidth]);
      right.push([pts[i][0] - nx * halfWidth, pts[i][1] - ny * halfWidth]);
    }
  }
  return [left, right];
}

function medianValue(arr) {
  if (!arr.length) return 1;
  const sorted = Float32Array.from(arr).sort();
  return sorted[(sorted.length / 2) | 0];
}

// ============================================================================
// CHẠY SUY LUẬN TILED 512x512 TRÊN WEBGPU & HẬU XỬ LÝ 6 LỚP ĐỊA HÌNH
// ============================================================================

async function runClientWebGpuSegmentation() {
  if (!state.ortSession || !state.raster) return;
  const btn = el("btn-run-webgpu");
  btn.disabled = true;

  try {
    const { anaW, anaH, rgbData, anaGsdM, areaHa, demGrid } = state.raster;
    const demRel = demGrid?.demRel || null;
    const demValid = demGrid?.validMask || null;
    const baseX = Number(el("base-x-input").value || 0);
    const baseY = Number(el("base-y-input").value || 0);

    const enabledKeys = new Set(
      [...document.querySelectorAll("#terrain-class-checklist input[type='checkbox']:checked")].map((c) => c.value)
    );

    const tileSize = Number(state.activeModelInfo?.input_size || 512);
    const stride = tileSize - 64;
    const xs = [];
    const ys = [];
    for (let x = 0; x < anaW; x += stride) {
      xs.push(Math.min(x, Math.max(0, anaW - tileSize)));
      if (x + tileSize >= anaW) break;
    }
    for (let y = 0; y < anaH; y += stride) {
      ys.push(Math.min(y, Math.max(0, anaH - tileSize)));
      if (y + tileSize >= anaH) break;
    }

    const totalTiles = xs.length * ys.length;
    const segMask = new Uint8Array(anaW * anaH);
    const rawYoloBoxes = [];
    const isYoloTask = state.activeModelInfo?.task === "yolo_detection";
    const inputName = state.ortSession.inputNames[0];
    const outputName = state.ortSession.outputNames[0];

    let doneTiles = 0;
    const tStart = performance.now();

    for (const ty of ys) {
      for (const tx of xs) {
        doneTiles++;
        setStatus(
          `⚡ Card GPU (<strong>${state.activeProvider.toUpperCase()}</strong>) đang quét ô lưới <strong>${doneTiles}/${totalTiles}</strong> (${tileSize}×${tileSize} px)…`
        );
        await new Promise((r) => requestAnimationFrame(r));

        const tensorData = new Float32Array(3 * tileSize * tileSize);
        const plane = tileSize * tileSize;
        for (let py = 0; py < tileSize; py++) {
          const sy = Math.min(anaH - 1, ty + py);
          for (let px = 0; px < tileSize; px++) {
            const sx = Math.min(anaW - 1, tx + px);
            const srcIdx = (sy * anaW + sx) * 3;
            const dstIdx = py * tileSize + px;
            tensorData[dstIdx] = rgbData[srcIdx] / 255.0;
            tensorData[plane + dstIdx] = rgbData[srcIdx + 1] / 255.0;
            tensorData[2 * plane + dstIdx] = rgbData[srcIdx + 2] / 255.0;
          }
        }

        const inputTensor = new window.ort.Tensor("float32", tensorData, [1, 3, tileSize, tileSize]);
        const outputs = await state.ortSession.run({ [inputName]: inputTensor });
        const logits = outputs[outputName].data;
        const dims = outputs[outputName].dims; // [1, 9, 512, 512] (segmentation) hoặc [1, 4+C, N] (yolo_detection)

        if (dims.length === 4 && dims[1] >= 7) {
          const numC = dims[1];
          const copyW = Math.min(tileSize, anaW - tx);
          const copyH = Math.min(tileSize, anaH - ty);
          for (let py = 0; py < copyH; py++) {
            for (let px = 0; px < copyW; px++) {
              const pIdx = py * tileSize + px;
              const gx = tx + px;
              const gy = ty + py;
              const gIdx = gy * anaW + gx;
              const r = rgbData[gIdx * 3];
              const g = rgbData[gIdx * 3 + 1];
              const b = rgbData[gIdx * 3 + 2];

              const exg = 2 * g - r - b;
              const isVeg = exg > 22 && g > r + 10 && g > b + 16;
              if (r === 0 && g === 0 && b === 0) {
                segMask[gIdx] = 0;
                continue;
              }

              let dRel = 0;
              const hasDemAtPx = Boolean(demRel && demValid && demValid[gIdx]);
              if (hasDemAtPx) {
                dRel = demRel[gIdx];
              }

              // Nếu điểm ảnh thuộc tán thực vật: xét Cây cảnh quan (Class 8) hoặc Nền cỏ (Class 0)
              if (isVeg) {
                if (numC >= 9 && enabledKeys.has("landscape_tree")) {
                  const v0 = logits[pIdx];
                  const v8 = logits[8 * plane + pIdx] + (hasDemAtPx && dRel > 0.65 ? 1.55 : 0.0);
                  segMask[gIdx] = v8 > v0 + 0.25 ? 8 : 0;
                } else {
                  segMask[gIdx] = 0;
                }
                continue;
              }

              // Nếu điểm ảnh không phải thực vật và cao > 1.45m trong DEM (hoặc mái ngói đỏ / tôn xanh) -> Nhà / Công trình (Class 7)
              const isRoofColor = (r > 152 && r > g + 28 && g > b + 12) || (b > 138 && b > r + 28 && b > g + 14);
              if ((hasDemAtPx && dRel > 1.45) || isRoofColor) {
                if (numC >= 8 && enabledKeys.has("house_building")) {
                  segMask[gIdx] = 7;
                } else {
                  segMask[gIdx] = 0;
                }
                continue;
              }

              let bestC = 0;
              let bestVal = logits[pIdx];
              for (let c = 1; c < numC; c++) {
                if (c === 8) continue;
                let val = logits[c * plane + pIdx];
                if (hasDemAtPx) {
                  if (c === 5 && dRel < -0.22) val += 1.15; // Vùng trũng -> ưu tiên Sông / Ao / Hồ
                  else if (c === 6 && dRel < -0.10) val += 0.95; // Lòng rãnh thấp -> ưu tiên Mương xây
                  else if (c === 7 && dRel > 1.15) val += 1.45; // Mái nhà cao -> ưu tiên Nhà
                  else if (c >= 1 && c <= 4 && dRel < -0.35) val -= 0.75;
                }
                if (val > bestVal) {
                  bestVal = val;
                  bestC = c;
                }
              }
              if (bestC > 0 && !enabledKeys.has(CLASS_META[bestC]?.key)) {
                bestC = 0;
              }
              segMask[gIdx] = bestC;
            }
          }
        } else if (dims.length === 3 && dims[1] >= 5) {
          // Giải mã đầu ra YOLO11 ONNX: [1, 4 + numClasses, numAnchors]
          const numChannels = dims[1];
          const numAnchors = dims[2];
          const numClasses = numChannels - 4;
          for (let a = 0; a < numAnchors; a++) {
            let bestCls = 0;
            let bestScore = 0;
            for (let c = 0; c < numClasses; c++) {
              const sc = logits[(4 + c) * numAnchors + a];
              if (sc > bestScore) {
                bestScore = sc;
                bestCls = c;
              }
            }
            if (bestScore < 0.28) continue;
            const cx = logits[0 * numAnchors + a];
            const cy = logits[1 * numAnchors + a];
            const bw = logits[2 * numAnchors + a];
            const bh = logits[3 * numAnchors + a];
            if (bw < 2 || bh < 2) continue;
            const x1 = Math.max(0, Math.min(anaW - 1, tx + cx - bw * 0.5));
            const y1 = Math.max(0, Math.min(anaH - 1, ty + cy - bh * 0.5));
            const x2 = Math.max(0, Math.min(anaW, tx + cx + bw * 0.5));
            const y2 = Math.max(0, Math.min(anaH, ty + cy + bh * 0.5));
            if (x2 - x1 >= 2 && y2 - y1 >= 2) {
              rawYoloBoxes.push({ x1, y1, x2, y2, cls: bestCls, score: bestScore });
            }
          }
        }
      }
    }

    const gpuElapsedMs = Math.round(performance.now() - tStart);
    const msPerTile = Math.round(gpuElapsedMs / Math.max(1, totalTiles));

    setStatus("📐 Đang trích xuất Vector CAD…");
    await new Promise((r) => setTimeout(r, 15));

    let features = [];
    if (isYoloTask || rawYoloBoxes.length > 0) {
      rawYoloBoxes.sort((a, b) => b.score - a.score);
      const kept = [];
      for (const cand of rawYoloBoxes) {
        let suppressed = false;
        const areaA = (cand.x2 - cand.x1) * (cand.y2 - cand.y1);
        for (const k of kept) {
          if (k.cls !== cand.cls) continue;
          const ix1 = Math.max(cand.x1, k.x1);
          const iy1 = Math.max(cand.y1, k.y1);
          const ix2 = Math.min(cand.x2, k.x2);
          const iy2 = Math.min(cand.y2, k.y2);
          if (ix2 > ix1 && iy2 > iy1) {
            const inter = (ix2 - ix1) * (iy2 - iy1);
            const areaB = (k.x2 - k.x1) * (k.y2 - k.y1);
            if (inter / (areaA + areaB - inter) > 0.45) {
              suppressed = true;
              break;
            }
          }
        }
        if (!suppressed) kept.push(cand);
      }
      for (const box of kept) {
        const classId = 9 + (box.cls % 3);
        const meta = CLASS_META[classId] || CLASS_META[9];
        const polyPx = [
          [box.x1, box.y1],
          [box.x2, box.y1],
          [box.x2, box.y2],
          [box.x1, box.y2],
        ];
        const polyRel = polyPx.map(([x, y]) => anaPxToVn2000Rel(x, y, baseX, baseY));
        const areaM2 = Math.round((box.x2 - box.x1) * (box.y2 - box.y1) * anaGsdM * anaGsdM * 100) / 100;
        const iy0 = Math.max(0, Math.floor(box.y1));
        const iy1 = Math.min(anaH - 1, Math.floor(box.y2));
        const ix0 = Math.max(0, Math.floor(box.x1));
        const ix1 = Math.min(anaW - 1, Math.floor(box.x2));
        for (let yy = iy0; yy <= iy1; yy++) {
          for (let xx = ix0; xx <= ix1; xx++) {
            segMask[yy * anaW + xx] = classId;
          }
        }
        // Quy tắc bắt buộc cho Vùng thực vật (landscape_tree / grass / newly_transplanted_rice):
        // - Cây đơn lẻ (< 25 m²): đặt 1 Block tại tâm tán
        // - Vùng thực vật (>= 25 m²): xuất đường bao Ranhgioi_thucvat + rải Block ĐỀU theo lưới thẳng hàng ngang - dọc
        if (areaM2 < 25.0) {
          const cx = (box.x1 + box.x2) * 0.5;
          const cy = (box.y1 + box.y2) * 0.5;
          const rM = Math.max(0.85, Math.min(2.8, Math.sqrt(areaM2 / Math.PI)));
          features.push({
            id: `yolo_${features.length + 1}`,
            classId,
            classKey: meta.key,
            geometry: "BLOCK",
            placementMode: "single_crown",
            blockName: rM < 1.5 ? "Caytanbe" : "Caydothi_cdt1",
            sourceBlock: classId === 10 ? "cothap" : "cdt2",
            sourceLayer: classId === 10 ? "1.BK. THUC VAT" : "07-CAY XANH",
            radiusPx: Math.round((rM / anaGsdM) * 100) / 100,
            radiusM: Math.round(rM * 100) / 100,
            areaM2,
            score: Math.round(box.score * 1000) / 1000,
            centerPx: [cx, cy],
            centerRel: anaPxToVn2000Rel(cx, cy, baseX, baseY),
          });
        } else {
          const isGrassZone = classId === 10 || classId === 9;
          const stepM = areaM2 >= 220 ? (isGrassZone ? 5.0 : 10.0) : Math.max(2.5, Math.min(8.0, Math.sqrt(areaM2) / 3.0));
          const stepPx = Math.max(4, stepM / anaGsdM);
          const marginPx = Math.min(1.5 / anaGsdM, Math.min(box.x2 - box.x1, box.y2 - box.y1) * 0.2);
          let firstInZone = true;
          let rIdx = 0;
          for (let gy = box.y1 + marginPx; gy <= box.y2 - marginPx; gy += stepPx, rIdx++) {
            let cIdx = 0;
            for (let gx = box.x1 + marginPx; gx <= box.x2 - marginPx; gx += stepPx, cIdx++) {
              const pat = (rIdx + cIdx) % 3;
              const srcBlk = isGrassZone ? (pat === 0 ? "cothap" : pat === 1 ? "cocao" : "cumcay1") : (pat === 2 ? "caylato" : "cumcay2");
              const blkName = srcBlk === "cothap" || srcBlk === "cocao" ? "Caytanbe" : "Caydothi_cdt1";
              const rM = isGrassZone ? 1.2 : 1.8;
              const item = {
                id: `yolo_${features.length + 1}`,
                classId,
                classKey: meta.key,
                geometry: "BLOCK",
                placementMode: "uniform_grid",
                gridStepM: [Math.round(stepM * 10) / 10, Math.round(stepM * 10) / 10],
                blockName: blkName,
                sourceBlock: srcBlk,
                sourceLayer: isGrassZone ? "1.BK. THUC VAT" : "Thuc_vat",
                radiusPx: Math.round((rM / anaGsdM) * 100) / 100,
                radiusM: rM,
                areaM2,
                score: Math.round(box.score * 1000) / 1000,
                centerPx: [gx, gy],
                centerRel: anaPxToVn2000Rel(gx, gy, baseX, baseY),
              };
              if (firstInZone) {
                item.zoneBoundaryPx = polyPx;
                item.zoneBoundaryRel = polyRel;
                firstInZone = false;
              }
              features.push(item);
            }
          }
        }
      }
    } else {
      features = vectorizeSegmentationMask(segMask, anaW, anaH, anaGsdM, baseX, baseY, enabledKeys);
    }
    state.segMask = segMask;
    state.features = features;
    buildMaskOverlayCanvas(segMask, anaW, anaH);

    // Trừ hạn mức diện tích trên License Key
    if (state.activeLicenseKey) {
      try {
        const updatedLic = await apiPost("/api/webgpu/quota", {
          license_key: state.activeLicenseKey,
          area_ha: areaHa,
        });
        updateLicenseTelemetry(updatedLic, null, null, null);
      } catch (_) {}
      await refreshAdminLicenses();
    }

    el("perf-readout").textContent = `${state.activeProvider.toUpperCase()} · ${msPerTile} ms/tile · ${features.length} địa vật`;
    if (el("btn-download-dwg")) el("btn-download-dwg").disabled = features.length === 0;
    el("btn-download-dxf").disabled = features.length === 0;
    el("btn-download-geojson").disabled = features.length === 0;
    updateSummaryCounts();
    renderViewport();

    setStatus(
      `✅ Hoàn tất (${gpuElapsedMs} ms): <strong>${features.length} đối tượng PL</strong>.`
    );
  } catch (err) {
    setStatus(`❌ Lỗi khi chạy WebGPU: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

function sampleDemZAtAnaPx(px, py) {
  const dg = state.raster?.demGrid;
  if (!dg || !dg.demZ || !dg.validMask) return 0.0;
  const { anaW, anaH } = state.raster;
  const ix = Math.min(anaW - 1, Math.max(0, Math.round(px)));
  const iy = Math.min(anaH - 1, Math.max(0, Math.round(py)));
  const idx = iy * anaW + ix;
  if (dg.validMask[idx] && Number.isFinite(dg.demZ[idx])) {
    return Math.round(dg.demZ[idx] * 1000) / 1000;
  }
  return 0.0;
}

function anaPxToVn2000Rel(px, py, baseX, baseY) {
  const { affA, affB, affD, affE, cornerX, cornerY, origW, origH, anaW, anaH } = state.raster;
  const gx = px * (origW / anaW);
  const gy = py * (origH / anaH);
  const mapX = cornerX + gx * affA + gy * affB;
  const mapY = cornerY + gx * affD + gy * affE;
  return [
    Math.round((mapX - baseX) * 1000) / 1000,
    Math.round((mapY - baseY) * 1000) / 1000,
    sampleDemZAtAnaPx(px, py),
  ];
}

function vectorizeSegmentationMask(segMask, w, h, gsdM, baseX, baseY, enabledKeys) {
  const features = [];

  // 1. Xử lý Ao / Hồ (Class 5) -> Đa giác khép kín + ký hiệu bờ Taluy
  const pondBin = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) if (segMask[i] === 5) pondBin[i] = 1;
  const pondClosed = morphClose(pondBin, w, h, 2);
  const minPondPx = Math.max(25, Math.round(6.0 / (gsdM * gsdM)));
  const pondComps = connectedComponents(pondClosed, w, h, minPondPx);
  const confirmedPond = new Uint8Array(w * h);

  for (const comp of pondComps) {
    const sw = comp.maxX - comp.minX + 3;
    const sh = comp.maxY - comp.minY + 3;
    const sub = new Uint8Array(sw * sh);
    for (const p of comp.pixels) {
      const x = (p % w) - comp.minX + 1;
      const y = ((p / w) | 0) - comp.minY + 1;
      sub[y * sw + x] = 1;
    }
    const dist = chamferDistanceTransform(sub, sw, sh);
    let maxR = 0;
    for (let i = 0; i < dist.length; i++) if (dist[i] > maxR) maxR = dist[i];
    // Tỷ số thon dài = Diện tích / (2 * maxR)^2 (~0.79 với ao tròn, ~1.6 với ao bầu dục, >6 với tuyến đường dài)
    const aspectElong = comp.pixels.length / Math.max(1, 4.0 * maxR * maxR);
    if (aspectElong > 4.8 || maxR * gsdM < 0.9) continue;

    for (const p of comp.pixels) confirmedPond[p] = 1;
    if (!enabledKeys.has("pond")) continue;

    const rawContour = traceClosedBoundary(sub, sw, sh, comp.minX, comp.minY);
    if (rawContour.length < 6) continue;
    const simp = simplifyRDP(rawContour, Math.max(1.4, 0.16 / gsdM));
    const smooth = chaikinSmooth(simp, true);
    const areaM2 = Math.round(comp.pixels.length * gsdM * gsdM * 10) / 10;

    features.push({
      id: `terrain_${features.length + 1}`,
      classId: 5,
      classKey: "pond",
      geometry: "POLYGON",
      areaM2,
      polygonPx: smooth,
      polygonRel: smooth.map(([x, y]) => anaPxToVn2000Rel(x, y, baseX, baseY)),
    });
  }

  // 1b. Xử lý Nhà / Công trình (Class 7) -> Đa giác khép kín
  if (enabledKeys.has("house_building")) {
    const polyBin = new Uint8Array(w * h);
    for (let i = 0; i < w * h; i++) if (segMask[i] === 7) polyBin[i] = 1;
    const polyClosed = morphClose(polyBin, w, h, 2);
    const minPx = Math.max(12, Math.round(5.0 / (gsdM * gsdM)));
    const polyComps = connectedComponents(polyClosed, w, h, minPx);
    polyComps.sort((a, b) => b.pixels.length - a.pixels.length);

    for (const comp of polyComps.slice(0, 80)) {
      const sw = comp.maxX - comp.minX + 3;
      const sh = comp.maxY - comp.minY + 3;
      const sub = new Uint8Array(sw * sh);
      for (const p of comp.pixels) {
        const x = (p % w) - comp.minX + 1;
        const y = ((p / w) | 0) - comp.minY + 1;
        sub[y * sw + x] = 1;
      }
      const rawContour = traceClosedBoundary(sub, sw, sh, comp.minX, comp.minY);
      if (rawContour.length < 4) continue;
      const outPts = simplifyRDP(rawContour, Math.max(1.2, 0.16 / gsdM));
      if (outPts.length < 3) continue;
      const areaM2 = Math.round(comp.pixels.length * gsdM * gsdM * 10) / 10;
      features.push({
        id: `terrain_${features.length + 1}`,
        classId: 7,
        classKey: "house_building",
        geometry: "POLYGON",
        areaM2,
        polygonPx: outPts,
        polygonRel: outPts.map(([x, y]) => anaPxToVn2000Rel(x, y, baseX, baseY)),
      });
    }
  }

  // 1c. Xử lý Cây cảnh quan & Vùng thực vật (Class 8):
  // - Cây đơn lẻ độc lập (< 25 m²): đặt 1 Block tại tâm tán cây
  // - Vùng thực vật / Thảm cây xanh / Bãi cỏ (>= 25 m²):
  //   a) Xuất đường bao ranh giới vùng thực vật LWPOLYLINE trên layer Ranhgioi_thucvat (ACI 3, linetype RGTV)
  //   b) Rải Block ĐỀU theo lưới thẳng hàng ngang - dọc (Uniform 2D Grid) bên trong vùng thực vật
  if (enabledKeys.has("landscape_tree")) {
    const treeBin = new Uint8Array(w * h);
    for (let i = 0; i < w * h; i++) {
      if (segMask[i] === 8 && !confirmedPond[i]) treeBin[i] = 1;
    }
    const treeClosed = morphClose(treeBin, w, h, 1);
    const minTreePx = Math.max(10, Math.round(1.5 / (gsdM * gsdM)));
    const treeComps = connectedComponents(treeClosed, w, h, minTreePx);
    treeComps.sort((a, b) => b.pixels.length - a.pixels.length);
    const scaleSpec = getMapScaleSpec();
    const kScale = scaleSpec.k;

    for (const comp of treeComps.slice(0, 150)) {
      if (comp.pixels.length > w * h * 0.45) continue;
      const sw = comp.maxX - comp.minX + 3;
      const sh = comp.maxY - comp.minY + 3;
      const sub = new Uint8Array(sw * sh);
      for (const p of comp.pixels) {
        const x = (p % w) - comp.minX + 1;
        const y = ((p / w) | 0) - comp.minY + 1;
        sub[y * sw + x] = 1;
      }
      const dist = chamferDistanceTransform(sub, sw, sh);
      let maxD = 0;
      let bestSx = (sw / 2) | 0;
      let bestSy = (sh / 2) | 0;
      for (let sy = 1; sy < sh - 1; sy++) {
        for (let sx = 1; sx < sw - 1; sx++) {
          const dVal = dist[sy * sw + sx];
          if (dVal > maxD) {
            maxD = dVal;
            bestSx = sx;
            bestSy = sy;
          }
        }
      }
      if (maxD * gsdM < 0.35) continue;
      const compAreaM2 = Math.round(comp.pixels.length * gsdM * gsdM * 10) / 10;

      // Case 1: Cây đơn lẻ độc lập (< 25 m²) -> đặt 1 Block tại tâm tán (phóng to theo hệ số k = M / 500)
      if (compAreaM2 < 25.0) {
        const gx = comp.minX + bestSx - 1;
        const gy = comp.minY + bestSy - 1;
        const eqRM = Math.sqrt(compAreaM2 / Math.PI);
        const baseRM = Math.max(0.85, Math.min(3.2, Math.min(eqRM, maxD * gsdM * 1.25)));
        const rM = baseRM * kScale;
        const rPx = rM / gsdM;
        const blkName = baseRM < 1.5 ? "Caytanbe" : baseRM > 2.6 ? "Caytanto" : "Caydothi_cdt1";
        features.push({
          id: `terrain_${features.length + 1}`,
          classId: 8,
          classKey: "landscape_tree",
          geometry: "BLOCK",
          placementMode: "single_crown",
          blockName: blkName,
          sourceBlock: baseRM < 1.8 ? "cdt2" : "caylato",
          sourceLayer: "07-CAY XANH",
          baseRadiusPx: Math.round((baseRM / gsdM) * 100) / 100,
          baseRadiusM: Math.round(baseRM * 100) / 100,
          scaledAtK: kScale,
          radiusPx: Math.round(rPx * 100) / 100,
          radiusM: Math.round(rM * 100) / 100,
          areaM2: compAreaM2,
          centerPx: [gx, gy],
          centerRel: anaPxToVn2000Rel(gx, gy, baseX, baseY),
        });
        continue;
      }

      // Case 2: Vùng thực vật (>= 25 m²) -> Ranhgioi_thucvat + Rải Block ĐỀU theo lưới chuẩn TCVN (nhân hệ số k = M / 500)
      let zoneBoundaryPx = null;
      let zoneBoundaryRel = null;
      const rawContour = traceClosedBoundary(sub, sw, sh, comp.minX, comp.minY);
      if (rawContour.length >= 4) {
        const simpV = simplifyRDP(rawContour, Math.max(1.2, 0.22 / gsdM));
        const smoothV = simpV.length >= 4 ? chaikinSmooth(simpV, true) : simpV;
        if (smoothV.length >= 3) {
          zoneBoundaryPx = smoothV;
          zoneBoundaryRel = smoothV.map(([x, y]) => anaPxToVn2000Rel(x, y, baseX, baseY));
        }
      }

      let isTallGrove = true;
      const dg = state.raster?.demGrid;
      if (dg && dg.demRel && dg.validMask) {
        let sumZ = 0;
        let cntZ = 0;
        for (const p of comp.pixels) {
          if (dg.validMask[p]) {
            sumZ += dg.demRel[p];
            cntZ++;
          }
        }
        if (cntZ > 0 && sumZ / cntZ < 0.85) isTallGrove = false;
      }

      const marginPx = Math.min(Math.max(1.0, 1.5 / gsdM), Math.max(1.0, maxD * 0.35));
      const baseStepM = compAreaM2 >= 220.0 ? (isTallGrove ? 10.0 : 5.0) : Math.max(2.5, Math.min(8.0, Math.sqrt(compAreaM2) / 3.0));
      const stepM = baseStepM * kScale;
      const stepPx = Math.max(4.0, stepM / gsdM);
      const startGx = Math.ceil(comp.minX / stepPx) * stepPx;
      const startGy = Math.ceil(comp.minY / stepPx) * stepPx;

      const gridPts = [];
      let rIdx = 0;
      for (let gy = startGy; gy <= comp.maxY; gy += stepPx, rIdx++) {
        let cIdx = 0;
        for (let gx = startGx; gx <= comp.maxX; gx += stepPx, cIdx++) {
          const sx = Math.round(gx) - comp.minX + 1;
          const sy = Math.round(gy) - comp.minY + 1;
          if (sx >= 1 && sx < sw - 1 && sy >= 1 && sy < sh - 1 && dist[sy * sw + sx] >= marginPx) {
            const gIdx = Math.min(h - 1, Math.max(0, Math.round(gy))) * w + Math.min(w - 1, Math.max(0, Math.round(gx)));
            if (!confirmedPond[gIdx] && (segMask[gIdx] === 8 || segMask[gIdx] === 0)) {
              gridPts.push({ rIdx, cIdx, gx: Math.round(gx * 10) / 10, gy: Math.round(gy * 10) / 10 });
            }
          }
        }
      }
      if (gridPts.length === 0) {
        gridPts.push({ rIdx: 0, cIdx: 0, gx: comp.minX + bestSx - 1, gy: comp.minY + bestSy - 1 });
      }

      gridPts.slice(0, 220).forEach((pt, idxG) => {
        const pat = (pt.rIdx + pt.cIdx) % 4;
        let blkName = "Caydothi_cdt1";
        let srcBlk = "cumcay2";
        let srcLyr = "Thuc_vat";
        let baseRM = 1.8;
        if (isTallGrove) {
          if (pat === 0) {
            srcBlk = "cumcay2";
            baseRM = 1.8;
          } else if (pat === 1) {
            srcBlk = "caylato";
            baseRM = 1.9;
          } else if (pat === 2) {
            blkName = "Caytanbe";
            srcBlk = "cothap";
            baseRM = 1.2;
          } else {
            blkName = "Caytanbe";
            srcBlk = "hoa";
            baseRM = 1.15;
          }
        } else {
          srcLyr = "1.BK. THUC VAT";
          if (pat === 0) {
            blkName = "Caytanbe";
            srcBlk = "cothap";
            baseRM = 1.1;
          } else if (pat === 1) {
            blkName = "Caytanbe";
            srcBlk = "cocao";
            baseRM = 1.2;
          } else if (pat === 2) {
            blkName = "Caytanbe";
            srcBlk = "hoa";
            baseRM = 1.1;
          } else {
            blkName = "Caydothi_cdt1";
            srcBlk = "cumcay2";
            baseRM = 1.5;
          }
        }
        const rM = baseRM * kScale;
        const rPx = rM / gsdM;
        const featObj = {
          id: `terrain_${features.length + 1}`,
          classId: 8,
          classKey: "landscape_tree",
          geometry: "BLOCK",
          placementMode: "uniform_grid",
          gridStepM: [Math.round(stepM * 10) / 10, Math.round(stepM * 10) / 10],
          gridRC: [pt.rIdx, pt.cIdx],
          blockName: blkName,
          sourceBlock: srcBlk,
          sourceLayer: srcLyr,
          baseRadiusPx: Math.round((baseRM / gsdM) * 100) / 100,
          baseRadiusM: Math.round(baseRM * 100) / 100,
          scaledAtK: kScale,
          radiusPx: Math.round(rPx * 100) / 100,
          radiusM: Math.round(rM * 100) / 100,
          areaM2: compAreaM2,
          centerPx: [pt.gx, pt.gy],
          centerRel: anaPxToVn2000Rel(pt.gx, pt.gy, baseX, baseY),
        };
        if (idxG === 0 && zoneBoundaryPx && zoneBoundaryRel) {
          featObj.zoneBoundaryPx = zoneBoundaryPx;
          featObj.zoneBoundaryRel = zoneBoundaryRel;
        }
        features.push(featObj);
      });
    }
  }

  // 2. Xử lý các tuyến hành lang: Mương xây (6) và Đường giao thông (1, 2, 3, 4)
  for (const clsId of [6, 1, 2, 3, 4]) {
    const rawBin = new Uint8Array(w * h);
    for (let i = 0; i < w * h; i++) {
      if (segMask[i] === clsId && !confirmedPond[i]) rawBin[i] = 1;
    }
    const closed = morphClose(rawBin, w, h, clsId === 6 ? 2 : 3);
    const minLenPx = Math.max(12, Math.round(3.0 / gsdM));
    const comps = connectedComponents(closed, w, h, minLenPx * 3);

    for (const comp of comps) {
      const sw = comp.maxX - comp.minX + 3;
      const sh = comp.maxY - comp.minY + 3;
      const sub = new Uint8Array(sw * sh);
      for (const p of comp.pixels) {
        const x = (p % w) - comp.minX + 1;
        const y = ((p / w) | 0) - comp.minY + 1;
        sub[y * sw + x] = 1;
      }
      const dist = chamferDistanceTransform(sub, sw, sh);
      const skel = zhangSuenThinning(sub, sw, sh);
      const skelRadii = [];
      for (let i = 0; i < skel.length; i++) {
        if (skel[i] && dist[i] > 0) skelRadii.push(dist[i]);
      }
      if (skelRadii.length < minLenPx) continue;

      const medHalfPx = medianValue(skelRadii);
      const measuredWidthM = 2.0 * medHalfPx * gsdM;
      const elong = skelRadii.length / Math.max(1.0, 2.0 * medHalfPx);
      if (elong < 1.8) continue;

      let finalId = clsId;
      let finalWidthM = measuredWidthM;
      if (clsId !== 6) {
        if (measuredWidthM < 1.9) {
          finalId = 4; // Đường hẹp < 1.9m -> Đường đi bộ
          finalWidthM = Math.max(0.65, Math.min(1.85, measuredWidthM));
        } else if (clsId === 4) {
          finalId = 3;
          finalWidthM = Math.max(1.95, measuredWidthM);
        }
      } else {
        finalWidthM = Math.max(0.5, Math.min(2.6, measuredWidthM));
      }

      const finalMeta = CLASS_META[finalId];
      if (!enabledKeys.has(finalMeta.key)) continue;

      const paths = traceSkeletonPolylines(skel, sw, sh, comp.minX, comp.minY, minLenPx);
      for (const rawPath of paths) {
        const simp = simplifyRDP(rawPath, Math.max(1.6, 0.22 / gsdM));
        const smooth = simp.length >= 3 ? chaikinSmooth(simp, false) : simp;
        if (smooth.length < 2) continue;

        const halfPx = (finalWidthM * 0.5) / gsdM;
        const [leftPx, rightPx] = offsetPolylinePair(smooth, halfPx);
        const centerRel = smooth.map(([x, y]) => anaPxToVn2000Rel(x, y, baseX, baseY));
        const [leftRel, rightRel] = offsetPolylinePair(centerRel, finalWidthM * 0.5);

        let lenM = 0;
        for (let i = 0; i < centerRel.length - 1; i++) {
          lenM += Math.hypot(centerRel[i + 1][0] - centerRel[i][0], centerRel[i + 1][1] - centerRel[i][1]);
        }
        if (lenM < 2.5) continue;

        features.push({
          id: `terrain_${features.length + 1}`,
          classId: finalId,
          classKey: finalMeta.key,
          geometry: "CORRIDOR",
          widthM: Math.round(finalWidthM * 100) / 100,
          lengthM: Math.round(lenM * 100) / 100,
          centerPx: smooth,
          leftPx,
          rightPx,
          centerRel,
          leftRel,
          rightRel,
        });
      }
    }
  }
  return features;
}

function buildMaskOverlayCanvas(segMask, w, h) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const img = new ImageData(w, h);
  for (let i = 0; i < w * h; i++) {
    const cid = segMask[i];
    if (!cid || !CLASS_META[cid]) continue;
    const [r, g, b] = CLASS_META[cid].rgb;
    img.data[i * 4] = r;
    img.data[i * 4 + 1] = g;
    img.data[i * 4 + 2] = b;
    img.data[i * 4 + 3] = 225;
  }
  c.getContext("2d").putImageData(img, 0, 0);
  state.maskCanvas = c;
}

function updateSummaryCounts() {
  const counts = {
    asphalt_road: 0,
    concrete_road: 0,
    dirt_road: 0,
    footpath: 0,
    pond: 0,
    masonry_ditch: 0,
    house_building: 0,
    landscape_tree: 0,
  };
  for (const f of state.features) {
    if (counts[f.classKey] !== undefined) counts[f.classKey]++;
  }
  for (const [k, v] of Object.entries(counts)) {
    const node = el(`cnt-${k}`);
    if (node) node.textContent = String(v);
  }
}

// ============================================================================
// HIỂN THỊ BẢN ĐỒ CANVAS TƯƠNG TÁC (ZOOM / PAN / VECTOR 2 MÉP + TIM ĐƯỜNG)
// ============================================================================

function fitCanvasView() {
  const canvas = el("webgpu-canvas");
  const stage = el("canvas-stage");
  if (!canvas || !stage || !state.raster) return;
  const rect = stage.getBoundingClientRect();
  canvas.width = Math.max(400, Math.floor(rect.width));
  canvas.height = Math.max(360, Math.floor(rect.height));

  const pad = 24;
  const sx = (canvas.width - pad * 2) / state.raster.anaW;
  const sy = (canvas.height - pad * 2) / state.raster.anaH;
  state.view.scale = Math.min(sx, sy);
  state.view.tx = (canvas.width - state.raster.anaW * state.view.scale) * 0.5;
  state.view.ty = (canvas.height - state.raster.anaH * state.view.scale) * 0.5;
}

function drawPolylinePath(ctx, pts, closed = false) {
  if (!pts || pts.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  if (closed) ctx.closePath();
  ctx.stroke();
}

function drawCadVegetationPattern(ctx, f, inv, kScale = 1.0) {
  const meta = CLASS_META[f.classId] || CLASS_META[8];
  ctx.save();
  if (Array.isArray(f.zoneBoundaryPx) && f.zoneBoundaryPx.length >= 3) {
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = 1.9 * inv;
    ctx.setLineDash([7 * inv * Math.min(2.5, Math.sqrt(kScale)), 4 * inv * Math.min(2.5, Math.sqrt(kScale))]);
    drawPolylinePath(ctx, f.zoneBoundaryPx, true);
  }
  ctx.strokeStyle = meta.hex;
  ctx.lineWidth = 1.65 * inv;
  ctx.setLineDash([]);
  const [cx, cy] = f.centerPx;
  const baseRPx = f.baseRadiusPx || (f.radiusPx ? f.radiusPx / (f.scaledAtK || 1.0) : 8);
  const symRadius = Math.max(4 * inv, baseRPx * kScale);
  if (f.sourceBlock === "cothap" || f.sourceBlock === "cocao") {
    const hB = f.sourceBlock === "cocao" ? symRadius * 0.58 : symRadius * 0.42;
    ctx.beginPath();
    ctx.moveTo(cx - symRadius * 0.32, cy - hB);
    ctx.lineTo(cx, cy);
    ctx.lineTo(cx + symRadius * 0.32, cy - hB);
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx, cy - hB * 1.15);
    ctx.stroke();
  } else if (f.sourceBlock === "hoa") {
    const pR = symRadius * 0.42;
    ctx.beginPath();
    ctx.arc(cx, cy, pR * 0.45, 0, Math.PI * 2);
    for (let a = 0; a < 5; a++) {
      const ang = (a * Math.PI * 2) / 5;
      const px = cx + Math.cos(ang) * pR;
      const py = cy + Math.sin(ang) * pR;
      ctx.moveTo(px + pR * 0.35, py);
      ctx.arc(px, py, pR * 0.35, 0, Math.PI * 2);
    }
    ctx.stroke();
  } else {
    const blkDef = state.mylib2Blocks?.[f.blockName] || state.mylib2Blocks?.Caydothi_cdt1;
    if (blkDef && Array.isArray(blkDef.strokes)) {
      for (const st of blkDef.strokes) {
        if (!st || st.length < 2) continue;
        ctx.beginPath();
        ctx.moveTo(cx + st[0][0] * symRadius, cy - st[0][1] * symRadius);
        for (let i = 1; i < st.length; i++) {
          ctx.lineTo(cx + st[i][0] * symRadius, cy - st[i][1] * symRadius);
        }
        ctx.stroke();
      }
    }
  }
  ctx.restore();
}

function renderViewport() {
  const canvas = el("webgpu-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!state.raster) return;
  const { scale, tx, ty } = state.view;
  const scaleSpec = getMapScaleSpec();
  const kScale = scaleSpec.k;
  ctx.save();
  ctx.translate(tx, ty);
  ctx.scale(scale, scale);

  if (el("toggle-rgb").checked && state.raster.rgbCanvas) {
    ctx.drawImage(state.raster.rgbCanvas, 0, 0);
  }
  if (el("toggle-mask").checked && state.maskCanvas) {
    ctx.save();
    ctx.globalAlpha = Number(el("mask-opacity").value || 0.42);
    ctx.drawImage(state.maskCanvas, 0, 0);
    ctx.restore();
  }

  if (el("toggle-vectors").checked && state.features.length > 0) {
    const inv = 1 / Math.max(0.15, scale);
    for (const f of state.features) {
      const meta = CLASS_META[f.classId];
      if (!meta) continue;

      if (f.geometry === "BLOCK") {
        drawCadVegetationPattern(ctx, f, inv, kScale);
      } else if (f.geometry === "POLYGON") {
        ctx.save();
        ctx.strokeStyle = meta.hex;
        ctx.lineWidth = 2.2 * inv;
        ctx.setLineDash([]);
        drawPolylinePath(ctx, f.polygonPx, true);

        const poly = f.polygonPx;
        let cx = 0, cy = 0;
        for (const p of poly) { cx += p[0]; cy += p[1]; }
        cx /= poly.length;
        cy /= poly.length;

        if (f.classId === 5) {
          // Vẽ vạch răng lược bờ Taluy hướng vào tâm sông/ao (giãn khoảng cách & chiều dài theo hệ số k = M / 500)
          const step = Math.max(1, Math.floor((poly.length / 12) * Math.sqrt(kScale)));
          const tickLen = 7 * inv * Math.min(2.2, Math.sqrt(kScale));
          ctx.beginPath();
          for (let i = 0; i < poly.length; i += step) {
            const p = poly[i];
            const vx = cx - p[0], vy = cy - p[1];
            const vl = Math.hypot(vx, vy) || 1;
            ctx.moveTo(p[0], p[1]);
            ctx.lineTo(p[0] + (vx / vl) * tickLen, p[1] + (vy / vl) * tickLen);
          }
          ctx.stroke();
        }

        ctx.fillStyle = "#e0f2fe";
        const fontPx = Math.max(10, Math.round(12 * inv * Math.min(1.6, Math.pow(kScale, 0.22))));
        ctx.font = `bold ${fontPx}px sans-serif`;
        ctx.fillText(`${meta.cadText} (${f.areaM2}m²)`, cx - 22 * inv, cy);
        ctx.restore();
      } else {
        ctx.save();
        ctx.strokeStyle = meta.hex;
        ctx.lineWidth = 2.0 * inv;
        ctx.setLineDash(meta.linetype === "DASHED" ? [7 * inv, 5 * inv] : []);
        drawPolylinePath(ctx, f.leftPx, false);
        drawPolylinePath(ctx, f.rightPx, false);

        if (meta.centerline) {
          ctx.strokeStyle = "#facc15";
          ctx.lineWidth = 1.3 * inv;
          ctx.setLineDash([10 * inv, 4 * inv, 2 * inv, 4 * inv]);
          drawPolylinePath(ctx, f.centerPx, false);
        }

        const mid = f.centerPx[(f.centerPx.length / 2) | 0];
        if (mid) {
          ctx.fillStyle = "#f8fafc";
          const fontPx = Math.max(9, Math.round(11 * inv * Math.min(1.6, Math.pow(kScale, 0.22))));
          ctx.font = `bold ${fontPx}px sans-serif`;
          ctx.fillText(`${meta.labelVi} (B=${f.widthM}m)`, mid[0] + 4 * inv, mid[1] - 4 * inv);
        }
        ctx.restore();
      }
    }

    // Vẽ lưới điểm độ cao chuẩn TCVN (giãn theo hệ số k = M / 500: 12.5m * k) khi có DEM
    const dg = state.raster?.demGrid;
    if (dg && dg.demRel && dg.validMask) {
      const gsdM = Math.max(0.03, state.raster.gsdM * state.raster.scaleFactor);
      const elevStepPx = Math.max(28, Math.round((scaleSpec.elevGridM || 12.5 * kScale) / gsdM));
      ctx.save();
      ctx.fillStyle = "#fde047";
      ctx.strokeStyle = "#fde047";
      ctx.lineWidth = 1.2 * inv;
      const fontPx = Math.max(9, Math.round(10 * inv * Math.min(1.5, Math.pow(kScale, 0.2))));
      ctx.font = `600 ${fontPx}px monospace`;
      for (let gy = Math.round(elevStepPx * 0.5); gy < state.raster.anaH - 8; gy += elevStepPx) {
        for (let gx = Math.round(elevStepPx * 0.5); gx < state.raster.anaW - 8; gx += elevStepPx) {
          const idx = gy * state.raster.anaW + gx;
          if (!dg.validMask[idx]) continue;
          const zVal = dg.demRel[idx];
          if (!Number.isFinite(zVal)) continue;
          const crossR = 2.6 * inv * Math.min(1.8, Math.sqrt(kScale));
          ctx.beginPath();
          ctx.moveTo(gx - crossR, gy);
          ctx.lineTo(gx + crossR, gy);
          ctx.moveTo(gx, gy - crossR);
          ctx.lineTo(gx, gy + crossR);
          ctx.stroke();
          ctx.fillText(zVal.toFixed(2), gx + 4 * inv, gy - 3 * inv);
        }
      }
      ctx.restore();
    }
  }
  ctx.restore();
}

function render() {
  renderViewport();
}

// ============================================================================
// XUẤT BẢN VẼ AUTOCAD VN2000 (.DXF) & GEOJSON NGAY TRÊN TRÌNH DUYỆT
// ============================================================================

function buildAutoCadDxf(features, plOnly = false) {
  const lines = [];
  const push = (...items) => {
    for (const it of items) lines.push(String(it));
  };

  push(0, "SECTION", 2, "HEADER", 9, "$ACADVER", 1, "AC1009", 9, "$INSUNITS", 70, 6, 0, "ENDSEC");

  // TABLES: LTYPE & LAYER
  push(0, "SECTION", 2, "TABLES");
  push(0, "TABLE", 2, "LTYPE", 70, 4);
  push(0, "LTYPE", 2, "CONTINUOUS", 70, 0, 3, "Solid line", 72, 65, 73, 0, 40, "0.0");
  push(0, "LTYPE", 2, "DASHED", 70, 0, 3, "Dashed __ __", 72, 65, 73, 2, 40, "0.75", 49, "0.5", 49, "-0.25");
  push(0, "LTYPE", 2, "CENTER", 70, 0, 3, "Center ____ _ ____", 72, 65, 73, 4, 40, "1.2", 49, "0.7", 49, "-0.15", 49, "0.2", 49, "-0.15");
  push(0, "LTYPE", 2, "RGTV", 70, 0, 3, "Ranh gioi thuc vat _ . _", 72, 65, 73, 2, 40, "0.5", 49, "0.3", 49, "-0.2");
  push(0, "ENDTAB");

  const layerDefs = [
    ...Object.values(CLASS_META).map((m) => ({ name: m.layer, aci: m.aci, lt: m.linetype })),
    { name: "KS_TIM_DUONG", aci: 2, lt: "CENTER" },
    { name: "Ranhgioi_thucvat", aci: 3, lt: "RGTV" },
    { name: "Thuc_vat", aci: 92, lt: "CONTINUOUS" },
    { name: "1.BK. THUC VAT", aci: 94, lt: "CONTINUOUS" },
    { name: "07-CAY XANH", aci: 3, lt: "CONTINUOUS" },
    ...(plOnly ? [] : [{ name: "KS_GHI_CHU", aci: 7, lt: "CONTINUOUS" }]),
  ];
  push(0, "TABLE", 2, "LAYER", 70, layerDefs.length + 1);
  push(0, "LAYER", 2, "0", 70, 0, 62, 7, 6, "CONTINUOUS");
  for (const lyr of layerDefs) {
    push(0, "LAYER", 2, lyr.name, 70, 0, 62, lyr.aci, 6, lyr.lt);
  }
  push(0, "ENDTAB", 0, "ENDSEC");

  // BLOCKS: Thư viện Block chuẩn Mylib2 (C:\Block\Mylib2)
  push(0, "SECTION", 2, "BLOCKS");
  const blocksDict = state.mylib2Blocks || buildDefaultMylib2Blocks();
  for (const [bname, binfo] of Object.entries(blocksDict)) {
    push(0, "BLOCK", 8, "0", 2, bname, 70, 0, 10, "0.0", 20, "0.0", 30, "0.0", 3, bname);
    for (const st of binfo.strokes || []) {
      if (!st || st.length < 2) continue;
      if (st.length === 2) {
        push(
          0, "LINE", 8, "0", 62, 3,
          10, Number(st[0][0]).toFixed(4), 20, Number(st[0][1]).toFixed(4), 30, "0.0",
          11, Number(st[1][0]).toFixed(4), 21, Number(st[1][1]).toFixed(4), 31, "0.0"
        );
      } else {
        const closed = Math.hypot(st[0][0] - st[st.length - 1][0], st[0][1] - st[st.length - 1][1]) < 1e-3 ? 1 : 0;
        push(0, "POLYLINE", 8, "0", 62, 3, 66, 1, 70, closed);
        for (const pt of st) {
          push(0, "VERTEX", 8, "0", 10, Number(pt[0]).toFixed(4), 20, Number(pt[1]).toFixed(4), 30, "0.0");
        }
        push(0, "SEQEND", 8, "0");
      }
    }
    push(0, "ENDBLK", 8, "0");
  }
  push(0, "ENDSEC");

  // ENTITIES
  push(0, "SECTION", 2, "ENTITIES");

  const writePolyline = (pts, layer, aci, lt, closed) => {
    if (!pts || pts.length < 2) return;
    push(0, "POLYLINE", 8, layer, 6, lt, 62, aci, 66, 1, 70, closed ? 1 : 0);
    for (const pt of pts) {
      const x = pt[0];
      const y = pt[1];
      const z = Number.isFinite(pt[2]) ? pt[2] : 0.0;
      push(0, "VERTEX", 8, layer, 10, x.toFixed(3), 20, y.toFixed(3), 30, z.toFixed(3));
    }
    push(0, "SEQEND", 8, layer);
  };

  const writeLine = (x1, y1, x2, y2, z, layer, aci) => {
    const zStr = (Number.isFinite(z) ? z : 0.0).toFixed(3);
    push(0, "LINE", 8, layer, 62, aci, 10, x1.toFixed(3), 20, y1.toFixed(3), 30, zStr, 11, x2.toFixed(3), 21, y2.toFixed(3), 31, zStr);
  };

  const writeText = (txt, x, y, z, height, rotDeg, layer, aci) => {
    const zStr = (Number.isFinite(z) ? z : 0.0).toFixed(3);
    push(0, "TEXT", 8, layer, 62, aci, 10, x.toFixed(3), 20, y.toFixed(3), 30, zStr, 40, height.toFixed(2), 1, txt, 50, rotDeg.toFixed(1));
  };

  const scaleSpec = getMapScaleSpec();
  const kScale = scaleSpec.k;

  for (const f of features) {
    const m = CLASS_META[f.classId];
    if (!m) continue;
    if (f.geometry === "BLOCK") {
      if (Array.isArray(f.zoneBoundaryRel) && f.zoneBoundaryRel.length >= 3) {
        writePolyline(f.zoneBoundaryRel, "Ranhgioi_thucvat", 3, "RGTV", true);
      }
      const c = f.centerRel || [0, 0, 0];
      const cx = (Number.isFinite(c[0]) ? c[0] : 0).toFixed(3);
      const cy = (Number.isFinite(c[1]) ? c[1] : 0).toFixed(3);
      const cz = (Number.isFinite(c[2]) ? c[2] : 0).toFixed(3);
      const baseRM = Number.isFinite(f.baseRadiusM)
        ? f.baseRadiusM
        : Number.isFinite(f.radiusM)
        ? f.radiusM / (f.scaledAtK || 1.0)
        : 1.5;
      const rScale = (baseRM * kScale).toFixed(3);
      const bname = f.blockName || "Caydothi_cdt1";
      push(
        0, "INSERT",
        8, m.layer,
        2, bname,
        62, m.aci,
        10, cx,
        20, cy,
        30, cz,
        41, rScale,
        42, rScale,
        43, rScale,
        50, "0.0"
      );
    } else if (f.geometry === "POLYGON") {
      const poly = f.polygonRel;
      writePolyline(poly, m.layer, m.aci, m.linetype, true);
      if (!plOnly) {
        let cx = 0, cy = 0, cz = 0;
        for (const p of poly) {
          cx += p[0];
          cy += p[1];
          cz += Number.isFinite(p[2]) ? p[2] : 0;
        }
        cx /= poly.length;
        cy /= poly.length;
        cz /= poly.length;
        if (f.classId === 5) {
          const step = Math.max(1, Math.floor((poly.length / 12) * Math.sqrt(kScale)));
          const tickM = 0.35 * kScale;
          for (let i = 0; i < poly.length; i += step) {
            const p = poly[i];
            const vx = cx - p[0], vy = cy - p[1];
            const vl = Math.hypot(vx, vy) || 1;
            writeLine(p[0], p[1], p[0] + (vx / vl) * tickM, p[1] + (vy / vl) * tickM, p[2], m.layer, m.aci);
          }
        }
        writeText(`${m.cadText} (${f.areaM2} m2)`, cx, cy, cz, 0.65 * kScale, 0.0, "KS_GHI_CHU", m.aci);
      }
    } else {
      writePolyline(f.leftRel, m.layer, m.aci, m.linetype, false);
      writePolyline(f.rightRel, m.layer, m.aci, m.linetype, false);
      if (m.centerline) {
        writePolyline(f.centerRel, "KS_TIM_DUONG", 2, "CENTER", false);
      }
      if (!plOnly) {
        const midIdx = (f.centerRel.length / 2) | 0;
        const pa = f.centerRel[Math.max(0, midIdx - 1)];
        const pb = f.centerRel[Math.min(f.centerRel.length - 1, midIdx)];
        let ang = (Math.atan2(pb[1] - pa[1], pb[0] - pa[0]) * 180) / Math.PI;
        if (ang > 90) ang -= 180;
        if (ang < -90) ang += 180;
        const tx = (pa[0] + pb[0]) * 0.5;
        const ty = (pa[1] + pb[1]) * 0.5;
        const tz = ((Number.isFinite(pa[2]) ? pa[2] : 0) + (Number.isFinite(pb[2]) ? pb[2] : 0)) * 0.5;
        const th = Math.max(0.35 * kScale, Math.min(scaleSpec.textHeightM, f.widthM * 0.25 * kScale));
        writeText(`${m.cadText} (B=${f.widthM}m)`, tx, ty, tz, th, ang, "KS_GHI_CHU", m.aci);
      }
    }
  }

  push(0, "ENDSEC", 0, "EOF");
  return lines.join("\r\n");
}

function triggerDownload(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

// ============================================================================
// KHỞI ĐỘNG SỰ KIỆN GIAO DIỆN
// ============================================================================

async function bootPortal() {
  try {
    const blkRes = await fetch("/mylib2_blocks.json", { cache: "force-cache" });
    if (blkRes.ok) {
      const blkJson = await blkRes.json();
      const blkMap = blkJson?.blocks || blkJson;
      if (blkMap && typeof blkMap === "object") {
        state.mylib2Blocks = { ...state.mylib2Blocks, ...blkMap };
      }
    }
  } catch (_) {}

  try {
    const stRes = await apiGet("/api/state");
    const stData = await stRes.json();
    state.sessionToken = stData.token || "";
    state.publicMode = Boolean(stData.public_mode);
    if (Array.isArray(stData.available_models)) {
      populateModelSelect(stData.available_models);
    }
  } catch (_) {}

  const isAdminUrl = (() => {
    try {
      const p = new URLSearchParams(window.location.search || "");
      return p.get("admin") === "1" || p.get("owner") === "1";
    } catch (_) {
      return false;
    }
  })();

  if (isAdminUrl) {
    el("admin-key-drawer")?.classList.remove("hidden");
    el("dwg-trainer-box")?.classList.remove("hidden");
  }

  if (state.publicMode && !isAdminUrl) {
    // Chế độ Web Công khai cho khách hàng: ẩn hoàn toàn link máy trạm, Key mẫu, bảng Admin & bộ huấn luyện
    el("workstation-back-link")?.classList.add("hidden");
    el("quick-keys-row")?.classList.add("hidden");
    el("admin-key-drawer")?.classList.add("hidden");
    el("dwg-trainer-box")?.classList.add("hidden");
    if (el("license-key-input")) el("license-key-input").value = "";
  } else if (state.publicMode && isAdminUrl) {
    el("workstation-back-link")?.classList.add("hidden");
    el("admin-unlock-box")?.classList.remove("hidden");
    el("admin-protected-content")?.classList.add("hidden");
  }

  await probeClientGpu();
  await refreshAdminLicenses();

  // Mở khóa Bảng Quản trị trên Web công khai bằng Mật khẩu Admin
  const tryUnlockAdmin = async () => {
    const pwd = (el("adm-password-input")?.value || el("gate-adm-password-input")?.value || "").trim();
    if (!pwd) {
      setStatus("Vui lòng nhập mật khẩu Quản trị.", "warn");
      return;
    }
    state.adminPassword = pwd;
    try {
      await refreshAdminLicenses(true);
      el("admin-key-drawer")?.classList.remove("hidden");
      if (el("admin-key-drawer")) el("admin-key-drawer").open = true;
      el("quick-keys-row")?.classList.remove("hidden");
      el("admin-protected-content")?.classList.remove("hidden");
      el("admin-unlock-box")?.classList.add("hidden");
      el("dwg-trainer-box")?.classList.remove("hidden");
      try {
        sessionStorage.setItem("uav_verified_license_key", "ADMIN_UNLOCKED");
      } catch (_) {}
      if (!state.ortSession) {
        if (el("license-key-input") && !el("license-key-input").value.trim()) {
          el("license-key-input").value = "UAV-WEBGPU-2026-PRO";
        }
        try {
          await authenticateAndLoadEncryptedModel();
        } catch (_) {}
      }
      unlockPortalWorkspace();
      window.dispatchEvent(new CustomEvent("uav-admin-unlocked"));
      setStatus("🛡️ Đã xác thực Quản trị viên &amp; nạp mô hình GPU.");
    } catch (err) {
      state.adminPassword = "";
      setStatus(`❌ Mật khẩu Quản trị viên không đúng (${err.message}).`, "error");
    }
  };
  el("btn-adm-unlock")?.addEventListener("click", tryUnlockAdmin);
  el("adm-password-input")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      tryUnlockAdmin();
    }
  });
  el("btn-gate-adm-unlock")?.addEventListener("click", tryUnlockAdmin);
  el("gate-adm-password-input")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      tryUnlockAdmin();
    }
  });

  const runGateAuth = async () => {
    const gateKey = (el("gate-license-key-input")?.value || "").trim();
    if (!gateKey) {
      setStatus("❌ Vui lòng nhập mã License Key để mở khóa giao diện.", "error");
      el("gate-license-key-input")?.focus();
      return;
    }
    if (el("license-key-input")) el("license-key-input").value = gateKey;
    if (el("gate-model-select") && el("model-select")) {
      el("model-select").value = el("gate-model-select").value;
    }
    const gateBtn = el("btn-gate-auth");
    if (gateBtn) gateBtn.disabled = true;
    try {
      await authenticateAndLoadEncryptedModel();
    } finally {
      if (gateBtn) gateBtn.disabled = false;
    }
  };
  el("btn-gate-auth")?.addEventListener("click", runGateAuth);
  el("gate-license-key-input")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      runGateAuth();
    }
  });

  // Chọn nhanh Key mẫu
  document.querySelectorAll("[data-sample-key]").forEach((btn) => {
    btn.addEventListener("click", () => {
      el("license-key-input").value = btn.dataset.sampleKey;
    });
  });

  el("btn-auth-load").addEventListener("click", authenticateAndLoadEncryptedModel);

  // Quản trị viên tạo / khóa / reset Key
  el("btn-adm-create").addEventListener("click", async () => {
    try {
      const created = await apiPost("/api/webgpu/license/create", {
        owner: el("adm-owner").value,
        quota_ha: Number(el("adm-quota").value || 200),
        max_devices: Number(el("adm-devices").value || 2),
      });
      el("license-key-input").value = created.key;
      await refreshAdminLicenses();
      setStatus(`🛡️ Đã cấp mã License Key mới: <strong>${created.key}</strong> (${created.quota_ha_total} ha).`);
    } catch (err) {
      setStatus(`❌ ${err.message}`, "error");
    }
  });

  el("adm-license-list").addEventListener("click", async (ev) => {
    const target = ev.target.closest("button");
    if (!target) return;
    if (target.dataset.useKey) {
      el("license-key-input").value = target.dataset.useKey;
      return;
    }
    if (target.dataset.act && target.dataset.key) {
      try {
        await apiPost("/api/webgpu/license/action", {
          key: target.dataset.key,
          action: target.dataset.act,
        });
        await refreshAdminLicenses();
        setStatus(`🛡️ Đã cập nhật trạng thái Key <strong>${target.dataset.key}</strong>.`);
      } catch (err) {
        setStatus(`❌ ${err.message}`, "error");
      }
    }
  });

  // Chọn nhiều tệp khảo sát (ORTHO.jpg + .jgw + .prj + DEM.tif) hoặc 1 tệp GeoTIFF RGB
  el("local-tiff-input").addEventListener("change", async (ev) => {
    const files = ev.target.files;
    if (!files || !files.length) return;
    try {
      await ingestSurveyFiles(files);
    } catch (err) {
      setStatus(`❌ Không đọc được bộ tệp khảo sát: ${err.message}`, "error");
    } finally {
      ev.target.value = "";
    }
  });

  // Chọn cả thư mục khảo sát (tự ghép ORTHO.jpg + .jgw + .prj + DEM.tif)
  const folderInput = el("local-folder-input");
  if (folderInput) {
    folderInput.addEventListener("change", async (ev) => {
      const files = ev.target.files;
      if (!files || !files.length) return;
      try {
        await ingestSurveyFiles(files);
      } catch (err) {
        setStatus(`❌ Không đọc được thư mục khảo sát: ${err.message}`, "error");
      } finally {
        ev.target.value = "";
      }
    });
  }

  // Làm mới bộ tệp khảo sát đang nạp
  const clearBtn = el("btn-clear-bundle");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      state.bundle = { orthoFile: null, worldFile: null, prjFile: null, demFile: null };
      state.raster = null;
      state.maskCanvas = null;
      state.segMask = null;
      state.features = [];
      updateBundleChecklistUI();
      el("raster-meta-box").classList.add("hidden");
      el("canvas-empty-overlay").classList.remove("hidden");
      el("local-file-label").textContent =
        ".JPG + .JGW + .PRJ + DEM.TIF hoặc GeoTIFF";
      if (el("btn-download-dwg")) el("btn-download-dwg").disabled = true;
      el("btn-download-dxf").disabled = true;
      el("btn-download-geojson").disabled = true;
      updateRunButtonState();
      updateSummaryCounts();
      renderViewport();
      setStatus("↺ Đã làm mới bộ tệp.");
    });
  }

  const dropzone = el("tiff-dropzone");
  dropzone.addEventListener("dragover", (ev) => {
    ev.preventDefault();
    dropzone.style.borderColor = "#10b981";
  });
  dropzone.addEventListener("dragleave", () => {
    dropzone.style.borderColor = "";
  });
  dropzone.addEventListener("drop", async (ev) => {
    ev.preventDefault();
    dropzone.style.borderColor = "";
    const files = ev.dataTransfer?.files;
    if (!files || !files.length) return;
    try {
      await ingestSurveyFiles(files);
    } catch (err) {
      setStatus(`❌ Không đọc được bộ tệp kéo-thả: ${err.message}`, "error");
    }
  });

  // Nạp ảnh GeoTIFF Mẫu 6 Lớp
  el("btn-load-demo-tiff").addEventListener("click", async () => {
    const btn = el("btn-load-demo-tiff");
    btn.disabled = true;
    try {
      const res = await apiGet("/api/webgpu/demo-geotiff");
      const blob = await res.blob();
      await decodeGeoTiffBlob(blob, "uav_demo_6_lop_dia_hinh_VN2000.tif");
    } catch (err) {
      setStatus(`❌ Lỗi tạo ảnh GeoTIFF mẫu: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  });

  el("btn-run-webgpu").addEventListener("click", runClientWebGpuSegmentation);

  // Chọn tỉ lệ bản đồ chuẩn TCVN (1:500, 1:1000, 1:2000, 1:5000) & tự động dàn lại bản vẽ trên Canvas
  updateTcvnScaleBadge(state.mapScale);
  const mapScaleSelectEl = el("mapScaleSelect") || el("advMapScaleSelect");
  if (mapScaleSelectEl) {
    mapScaleSelectEl.addEventListener("change", (ev) => {
      state.mapScale = parseMapScaleDenominator(ev.target.value);
      const spec = updateTcvnScaleBadge(state.mapScale);
      if (state.segMask && state.raster) {
        state.features = vectorizeSegmentationMask(state.segMask, state.raster.anaW, state.raster.anaH);
        updateSummaryCounts();
      }
      renderViewport();
      setStatus(`📐 Đã dàn lại bản vẽ theo tỉ lệ TCVN ${spec.ratioLabel} (hệ số k = ×${spec.k.toFixed(1)}).`);
    });
  }

  el("btn-train-dwg")?.addEventListener("click", async () => {
    const btn = el("btn-train-dwg");
    const folder = window.prompt(
      "Nhập đường dẫn thư mục chứa các bản vẽ .DWG + ảnh ORTHO (.JPG + .JGW) để huấn luyện (Để trống để huấn luyện từ thư mục Waterpoint_10.3.26 mặc định):",
      "D:\\LUUTRU VIEC N\\ACAD\\Waterpoint_10.3.26"
    );
    if (folder === null) return;
    btn.disabled = true;
    try {
      setStatus("🎓 Đang trích xuất PL và huấn luyện trên GPU…");
      const roots = folder.trim() ? [folder.trim()] : [];
      const meta = await apiPost("/api/terrain/train-dwg", { survey_roots: roots, steps: 160 });
      const zones = (meta.real_dwg_zones_trained || []).map((z) => z.dwg_file).join(", ");
      if (el("dwg-train-summary")) {
        el("dwg-train-summary").innerHTML = `🎓 <strong>Đã huấn luyện trên ${meta.real_dwg_zones_count || 0} bản vẽ .DWG</strong> (${zones || "Waterpoint"}) · Độ chính xác: <strong>${Math.round((meta.val_pixel_accuracy || 0) * 100)}%</strong>`;
      }
      setStatus(`✅ Huấn luyện hoàn tất (${meta.real_dwg_zones_count || 0} bản vẽ DWG).`);
    } catch (err) {
      setStatus(`❌ Lỗi huấn luyện .DWG: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  });

  el("btn-download-dwg")?.addEventListener("click", async () => {
    if (!state.features.length) return;
    const btn = el("btn-download-dwg");
    const plOnly = Boolean(el("toggle-pl-only")?.checked);
    const mapScale = parseMapScaleDenominator(el("mapScaleSelect")?.value || state.mapScale);
    state.mapScale = mapScale;
    const dxf = buildAutoCadDxf(state.features, plOnly);
    btn.disabled = true;
    try {
      setStatus(`📐 Đang xuất bản vẽ DWG (tỉ lệ 1:${mapScale})…`);
      const headers = { "Content-Type": "application/json" };
      if (state.sessionToken) headers["X-Session-Token"] = state.sessionToken;
      const res = await fetch(`/api/terrain/dwg?map_scale=${mapScale}`, {
        method: "POST",
        headers,
        body: JSON.stringify({ dxf_content: dxf, map_scale: mapScale }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${res.status}`);
      }
      const dwgBlob = await res.blob();
      triggerDownload(dwgBlob, `binh_do_PL_VN2000_1_${mapScale}.dwg`, "application/acad");
      setStatus(`✅ Đã xuất ${state.features.length} đối tượng PL (DWG VN2000 1:${mapScale}).`);
    } catch (err) {
      triggerDownload(dxf, `binh_do_PL_VN2000_1_${mapScale}.dxf`, "application/dxf");
      setStatus(`⚠️ Không kết xuất được .DWG (${err.message}); đã tải .DXF thay thế.`, "warn");
    } finally {
      btn.disabled = false;
    }
  });

  el("btn-download-dxf").addEventListener("click", () => {
    if (!state.features.length) return;
    const plOnly = Boolean(el("toggle-pl-only")?.checked);
    const mapScale = parseMapScaleDenominator(el("mapScaleSelect")?.value || state.mapScale);
    state.mapScale = mapScale;
    const dxf = buildAutoCadDxf(state.features, plOnly);
    triggerDownload(dxf, `binh_do_PL_VN2000_1_${mapScale}.dxf`, "application/dxf");
  });

  el("btn-download-geojson").addEventListener("click", () => {
    if (!state.features.length) return;
    const geojson = {
      type: "FeatureCollection",
      features: state.features.map((f) => ({
        type: "Feature",
        properties: {
          id: f.id,
          class_key: f.classKey,
          label_vi: CLASS_META[f.classId]?.labelVi,
          layer: CLASS_META[f.classId]?.layer,
          width_m: f.widthM || null,
          length_m: f.lengthM || null,
          area_m2: f.areaM2 || null,
        },
        geometry:
          f.geometry === "BLOCK"
            ? { type: "Point", coordinates: f.centerRel }
            : f.geometry === "POLYGON"
            ? { type: "Polygon", coordinates: [[...f.polygonRel, f.polygonRel[0]]] }
            : { type: "LineString", coordinates: f.centerRel },
      })),
    };
    triggerDownload(JSON.stringify(geojson, null, 2), "binh_do_webgpu_VN2000.geojson", "application/geo+json");
  });

  // Điều khiển Canvas
  for (const id of ["toggle-rgb", "toggle-mask", "mask-opacity", "toggle-vectors"]) {
    el(id).addEventListener("input", renderViewport);
  }
  el("btn-zoom-fit").addEventListener("click", () => {
    fitCanvasView();
    renderViewport();
  });

  const stage = el("canvas-stage");
  stage.addEventListener(
    "wheel",
    (ev) => {
      if (!state.raster) return;
      ev.preventDefault();
      const rect = stage.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      const factor = ev.deltaY < 0 ? 1.15 : 0.87;
      const nextScale = Math.max(0.15, Math.min(18, state.view.scale * factor));
      state.view.tx = mx - ((mx - state.view.tx) / state.view.scale) * nextScale;
      state.view.ty = my - ((my - state.view.ty) / state.view.scale) * nextScale;
      state.view.scale = nextScale;
      renderViewport();
    },
    { passive: false }
  );

  stage.addEventListener("mousedown", (ev) => {
    state.view.dragging = true;
    state.view.lastX = ev.clientX;
    state.view.lastY = ev.clientY;
  });
  window.addEventListener("mousemove", (ev) => {
    if (!state.view.dragging) return;
    state.view.tx += ev.clientX - state.view.lastX;
    state.view.ty += ev.clientY - state.view.lastY;
    state.view.lastX = ev.clientX;
    state.view.lastY = ev.clientY;
    renderViewport();
  });
  window.addEventListener("mouseup", () => {
    state.view.dragging = false;
  });
  window.addEventListener("resize", () => {
    if (state.raster) {
      fitCanvasView();
      renderViewport();
    }
  });
}

bootPortal();
