# Awesome DESIGN.md — UAV GeoTIFF Studio & WebGPU 6-Class Terrain Survey Portal

> Built with the **Awesome DESIGN.md** specification (`skills/awesome-design-md-main`) and synchronized with [`ARCHITECTURE.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ARCHITECTURE.md).
> Every AI agent (`architecture-design-lead`, `ui-ux-specialist`) MUST read and update this file alongside `ARCHITECTURE.md` before modifying any UI component.

---

## 1. Visual Theme & Atmosphere

The **UAV GeoTIFF Studio & WebGPU Survey Portal** combines two precision-engineered surfaces tailored for photogrammetry and AutoCAD VN2000 topographic surveying:
1. **WebGPU Survey Portal & Automation Hub (`ui/webgpu.html`, `ui/argon_host_panel.js`) — Abyssal Carbon Cockpit**:
   - Built on deep carbon-slate surfaces (`#07090e` canvas, `#0f172a` containment cards) where 6-class topographic polylines (`PL`), elevation heatmaps (`DEM`), and live GPU/CLI telemetry glow with high-contrast clarity.
   - Uses a dual-signal accent system: **Emerald Signal Green (`#00d992` / `#10b981`)** for active runtime states (`Đang chạy cổng 8765`, `Đã xác thực License`) and **Survey Cyan (`#06b6d4` / `#38bdf8`)** for VN2000 coordinate readouts, Gemini 4 Argon CLI progress, and Graphify knowledge-graph navigation.
2. **5-Step Photogrammetry Workstation (`ui/index.html`, `ui/advanced.html`) — Daylight Engineering Studio (`☀️ Sáng` Default + `🌙 Tối` Toggle)**:
   - Defaults to high-contrast daylight paper (`#f8fafc` / `#ffffff`) with crisp `1px solid #cbd5e1` containment borders for outdoor/office CAD inspection on 24-inch full-bleed monitors.

---

## 2. Color Palette & Roles

### 2.1. Core Surface & Semantic Tokens
- **Abyss Slate Canvas** (`#07090e`): Primary background for the WebGPU Survey Portal and dark map viewport.
- **Carbon Panel Surface** (`#0f172a` / `#101010`): Contained control cards, Automation Hub sub-cards, and modal surfaces.
- **Daylight Workstation Surface** (`#f8fafc` / `#ffffff`): Default light-mode background for the 5-step Studio.
- **Warm Charcoal / Slate Containment Border** (`#3d3a39` / `rgba(148, 163, 184, 0.22)`): 1px structural border defining every card and toolbar without relying on heavy drop shadows.
- **Emerald Signal Green** (`#00d992` / `#10b981`): Active status badges, primary action highlights, and verified states.
- **Survey Telemetry Cyan** (`#06b6d4` / `#38bdf8`): Primary gradient CTA (`#0284c7 -> #06b6d4`), VN2000 coordinate tags, and Graphify links.
- **Warning Amber** (`#f59e0b`): Quota alerts, uncommitted Git changes, and pending states.
- **Danger Coral** (`#ef4444`): Emergency stop buttons (`⏹ Dừng`) and error alerts.

### 2.2. 8-Class VN2000 Topographic, Urban & Landscape Layer & AutoCAD `.DWG` Color Tokens (`9-Channel Tensor: 0=Background + 1..8`)
| Class ID (`Tensor Ch`) | Terrain / Urban Class | Vietnamese Label | AutoCAD `.DWG` Layer | Web UI Hex | AutoCAD ACI | Linetype & Geometry |
| :---: | :--- | :--- | :--- | :---: | :---: | :--- |
| `1` | `asphalt_road` | Đường ô tô / Đường nhựa | `KS_DUONG_NHUA` | `#ef4444` | `1` (Red) | `CONTINUOUS` · 2 edge `PL` + 1 centerline `PL` |
| `2` | `concrete_road` | Đường ô tô / Đường bê tông | `KS_DUONG_BETONG` | `#94a3b8` | `2` (Yellow) | `CONTINUOUS` · 2 edge `PL` + 1 centerline `PL` |
| `3` | `dirt_road` | Đường đi / Đường đất | `KS_DUONG_DAT` | `#d97706` | `30` (Orange) | `DASHED` · 2 dashed edge `PL` |
| `4` | `footpath` | Đường đi bộ / Vỉa hè | `KS_DUONG_DIBO` | `#a855f7` | `8` (Gray) | `DASHED` · 2 narrow edge `PL` (`< 1.9m`) |
| `5` | `pond` | Sông / Ao / Hồ | `KS_AO_HO` | `#0ea5e9` | `5` (Blue) | `CONTINUOUS` · Closed perimeter `PL` + taluy ticks |
| `6` | `masonry_ditch` | Mương xây / Kè kênh | `KS_MUONG_XAY` | `#06b6d4` | `4` (Cyan) | `CONTINUOUS` · 2 parallel wall `PL` |
| `7` | `house_building` | Nhà / Công trình | `Nha` / `Nha-2d` / `KS_NHA_CONGTRINH` | `#f59e0b` | `2` (Amber/Yellow) | `CONTINUOUS` · Closed regularized roof `PL` + label `NHÀ` / `ton` |
| `8` | `landscape_tree` | Cây cảnh quan / Vùng thực vật | `1.BK. THUC VAT` / `Thuvien` / `07-CAY XANH` / `CAY` / `Thuc_vat` / `Ranhgioi_thucvat` | `#10b981` | `3` (Emerald Green) | **Uniform 2D Grid `BLOCK INSERT` Array (`Mylib2` / `ACAD_KHU TAM GIAC.dwg`)** · Enclose vegetation zones with `Ranhgioi_thucvat` (`ACI 3`) `LWPOLYLINE` and fill the interior with a regular `(dx, dy)` 2D grid of standard blocks (`cumcay2`, `caylato`, `cothap` `.V.`, `cocao`, `cumcay1`, `hoa`, `cdt2`, `cbui13`), clipped cleanly against Roads, Water, Ditches, and Buildings |

### 2.2b. Standard `ACAD_KHU TAM GIAC.dwg` Topographic Survey Layers (`Bản vẽ #12`) & Multi-Scale TCVN Relayout Tokens (`Bản vẽ #13`)
- **Road & Sidewalk Layers**: `1.BK. DUONG CU-NHUA`, `Giao_thong`, `1.BK. VIA HE`, `1.BK. DUONG XE DAP`, `1.BK. CAU`, `1.BK. DEN DUONG` (`DEN1a`).
- **Hydrology & Canal Taluy Layers**: `1.BK. SONG+MUONG+RACH`, `Thuy_he`, and `1.BK. TALUY KENH` (alternating long/short perpendicular slope hachure `LINE` ticks + bank `LWPOLYLINE`).
- **Elevation Spot Grid & Contours (`DEM`)**: `Dot` (`POINT`) + `Cao độ` (`TEXT` formatted `%.2f`, e.g. `3.68`), `Đồng mức chính`, `Đồng mức phụ`, and `Nhãn ĐM` (`MTEXT`).
- **TCVN Map Scale Selector & Telemetry Badge (`1:500`, `1:1000`, `1:2000`, `1:5000` — TCVN 9398:2012 & TT 68/2015, 24/2018/TT-BTNMT)**:
  - Compact selector (`#map-scale-select` / `#terrain-scale-select`) styled with `Carbon Panel (#0f172a)` surface, `1px solid #06b6d4` border, and `monospace tabular-nums` options (`1:500 (Chi tiết k=1×)`, `1:1000 (k=2×)`, `1:2000 (k=4×)`, `1:5000 (k=10×)`).
  - Live TCVN specification badge (`#tcvn-scale-spec-badge`) displaying active grid spacing, spot elevation spacing (`15m / 30m / 60m / 150m`), contour interval (`0.5m / 1.0m / 2.0m`), and block scale factor (`1× / 2× / 4× / 10×`) in `Survey Telemetry Cyan (#38bdf8)` and `Emerald Signal Green (#00d992)` without increasing `.control-column` height beyond the zero-vertical-scroll budget.

### 2.3. 3-Class Multispectral Rice Field Stage 1 Agronomic Tokens (`Results_Stage 1`)
| Class ID | Agronomic Label (`Label_Color.txt`) | Vietnamese Label | RGB / Hex Token | AutoCAD `.DWG` Layer | Scientific Role |
| :--- | :--- | :--- | :---: | :--- | :--- |
| `rice_stage1` | `Newly transplanted rice` | Lúa mới cấy (`Stage 1`) | `RGB(250, 50, 83)` · `#fa3253` | `KS_LUA_MOI_CAY` | Pure newly transplanted rice stand |
| `grass_weed` | `Grass` | Cỏ dại xâm lấn | `RGB(51, 221, 255)` · `#33ddff` | `KS_CO_DAI` | Pure weed/grass patch requiring intervention |
| `rice_partial_grass` | `Newly transplanted rice + Partial Grass` | Lúa mới cấy lẫn cỏ | `RGB(255, 204, 51)` · `#ffcc33` | `KS_LUA_LAN_CO` | Mixed competition zone (`NDRE/ExG` transition) |

---

## 3. Typography Rules

| Role | Font Stack | Size | Weight | Line Height | Letter Spacing | Usage |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Workstation Title** | `system-ui, Inter, Segoe UI` | `18px–22px` | `700` | `1.15` | `-0.02em` | Top header & portal titles |
| **Card Heading** | `Inter, system-ui` | `13.5px–15px` | `700` | `1.25` | `-0.01em` | Control card headers |
| **Eyebrow / Kicker** | `system-ui, Inter` | `10.5px–11px` | `700` | `1.30` | `0.08em` | Uppercase section tags (`🛰️ TRUNG TÂM TỰ ĐỘNG HÓA`) |
| **Body / Control Label** | `Inter, system-ui` | `12px–13px` | `500–600` | `1.45` | `normal` | Form labels, checkboxes, buttons |
| **Coordinates & CLI Logs** | `SFMono-Regular, JetBrains Mono, Consolas` | `11.5px–12.5px` | `400–600` | `1.45` | `tabular-nums` | `X/Y/Z` coordinates, GSD, `agy.exe` logs, LAN URLs |

---

## 4. Layout & Component Stylings

- **Full-Screen License Key Gatekeeper (`#license-gate-overlay` & `body.gate-locked`)**:
  - Upon visiting any portal URL (`:8765/webgpu.html`, `:8766/index.html`, `:8766/advanced.html`), `body.gate-locked` hides the entire main application workspace (`header`, `main`, `.portal-header`, `.portal-grid`, canvas viewport) so **unauthenticated visitors CANNOT see the interface**.
  - Only the full-viewport `#license-gate-overlay` (`position: fixed; inset: 0; z-index: 99999; background: radial-gradient(circle at 50% 25%, #0f172a 0%, #07090e 75%);`) is visible, presenting a centered Carbon Panel authentication card (`max-width: 440px`, `1.5px solid #06b6d4`, monospace `tabular-nums` key input, model selector, primary CTA button, and an owner-only `🔐 Quản trị Key` password-protected modal trigger).
  - The main workspace only becomes visible after `/api/webgpu/auth` returns `ok: true`.
- **Full-Bleed 24-Inch Split-Pane Grid (`100vh Zero-Outer-Scroll GIS Cockpit`)**:
  - `html, body` locked to `height: 100vh; overflow: hidden; display: flex; flex-direction: column;` so there is **NEVER a double vertical scrollbar**.
  - `.portal-header` (`flex-shrink: 0`, compact `52px` height) + `.portal-grid` (`flex: 1; min-height: 0; overflow: hidden; grid-template-columns: 390px minmax(0, 1fr); gap: 12px; padding: 10px 12px;`).
  - Left Control Column (`.control-column`: `height: 100%; min-height: 0; overflow-y: auto;`): **Zero-Vertical-Scroll Constraint (`scrollHeight <= clientHeight`)** across standard display viewports (`1920x1080`, `1440x1080`, `1440x900`, `1366x768`, `1280x800`). To guarantee zero vertical scroll, all verbose explanatory paragraphs under step titles, `.hint` subtext blocks, and static tutorial banners (including *"Hãy bấm Bước 01 để xác thực Key & nạp mô hình mã hóa lên Card GPU."*) are eliminated; card padding is compacted (`padding: 8px 10px;`) and paired with the compact 2-column 8-class filter grid to keep the 3-step height budget strictly `<= 850px`.
  - Right Interactive Map/WebGPU Viewport (`.viewport-column`: `height: 100%; min-height: 0; display: flex; flex-direction: column; overflow: hidden;`) where `.canvas-stage` takes `flex: 1; min-height: 0` and `.summary-strip` (8-column telemetry bar) stays permanently docked at the bottom edge of the screen (`flex-shrink: 0`).
- **Border-Driven Elevation**:
  - Level 1 (Standard Card): `1px solid rgba(148, 163, 184, 0.18)` on `rgba(15, 23, 42, 0.88)` surface, `border-radius: 10px`.
  - Level 2 (Active / Highlighted Card): `1.5px solid #00d992` or `1.5px solid #06b6d4` with subtle ambient glow `0 10px 28px rgba(0, 0, 0, 0.35)`.
- **Buttons**:
  - Primary Action (`.argon-btn-primary` / `.btn-accent`): Gradient `linear-gradient(135deg, #0284c7, #06b6d4)` or Emerald `#10b981`, `border-radius: 8px`, `font-weight: 600`, `padding: 8px 12px`.
  - Secondary / Ghost Action: `rgba(30, 41, 59, 0.85)`, `1px solid rgba(148, 163, 184, 0.28)`, hover border shifts to `#38bdf8`.

---

## 5. Do's and Don'ts

### Do
- Use concise Vietnamese engineering terms (`ảnh` instead of `tile`, `Xuất các đường PL ra AutoCAD (.DWG)`).
- **Enforce concise functional microcopy**: Form labels, buttons, and empty states must communicate intent in minimal words without requiring supplementary `.hint` subtext or verbose instructional paragraphs.
- **Maintain zero-vertical-scroll layout on `.control-column`**: Ensure `scrollHeight <= clientHeight` on `ui/webgpu.html` across standard viewports (`1920x1080`, `1440x1080`, `1440x900`, `1366x768`, `1280x800`).
- **Preserve mandatory test string**: Ensure `ui/webgpu.html` retains the exact required title and test string: `"Cổng WebGPU Bình đồ Địa hình 6 Lớp"`.
- **Preserve mandatory professional domain icons**: Retain all 14 domain icons across HTML and JS sources: `"🛰️", "📡", "🧭", "📐", "⛰️", "🎯", "🌾", "🌱", "🌿", "🌳", "🖥️", "⚡", "🔬", "🎛️"`.
- **State-driven dynamic status element**: `#portal-status` remains in the DOM for runtime toast/alert messages via `setStatus()`, but starts empty/hidden with no initial static tutorial banner.
- Always render coordinates (`X = Easting`, `Y = Northing`, `Z = DEM`), ports (`8765`), and file paths in `monospace` with `tabular-nums`.
- **Keep all new UI controls grouped inside structured sub-cards** with a status badge (`Sẵn sàng`, `⚡ Đang chạy`, `✅ Hoàn tất`).
- **Provide a 1-Click Live Portal Launcher (`MO_WEB_NHAN_DIEN_NGAY.html` & `LINK_TRUY_CAP_WEB.txt`)** styled with the same Abyssal Carbon (`#07090e`) & Emerald/Cyan (`#00d992` / `#06b6d4`) tokens so secondary users opening the permanent Google Drive link can launch Port `8765` (`WebGPU 9 Lớp`) or Port `8766` (`Trạm 5 Bước`) with a single click.
- **Enforce Clean-Sync & Strict Project-Folder Containment on Google Drive (`Bản vẽ #10`)**: All project files MUST be stored strictly inside the dedicated project folder `CODE_DATA / UAV_GeoTIFF_WebGPU_Survey_VN2000` (`1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV`)—never leave loose project files in the root `CODE_DATA` folder (`1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D`), and automatically prune stale/duplicate File IDs on every update.
- **Display Gemini 4 Argon Model Approval & 5ha < 5-Min SLA Telemetry (`Bản vẽ #11`)**: Render Direct 9-Class training & model review badges (`✅ Đã duyệt bởi Gemini 4 Argon`, `5.17 ha -> .DWG: ~6–11s (< 5 phút)`, `Chưng cất: Tạm hoãn`) using `Emerald Signal Green (#00d992)` and `monospace tabular-nums` inside the Owner Automation Hub and training logs.
- Update `ARCHITECTURE.md` and `DESIGN.md` via `architecture-design-lead` **before** writing any UI or backend code.

### Don't
- **Never use forbidden emojis** in `ui/index.html`, `ui/advanced.html`, or `ui/advanced.js` (strictly prohibited: `"🙈", "🔮", "✨", "❓", "💡"`). Help buttons must use ASCII `?` (`>?</button>`).
- **Never add verbose explanatory paragraphs** under step titles, inside `.hint` subtext blocks, inside `.empty-card` / `.empty-note` containers, or as static tutorial banners (including *"Hãy bấm Bước 01 để xác thực Key & nạp mô hình mã hóa lên Card GPU."*). All control cards must present concise functional UI only.
- **Never allow `.control-column` to exceed viewport height** causing vertical scrollbars on standard viewports (`scrollHeight > clientHeight`).
- Never show the CAD Polyline drawing toolbar unless the user selects *"Chỉ các vùng được chọn"*.
- Never start coding a feature before its architecture diagram and design tokens are signed off in `ARCHITECTURE.md`.
- **Never expose Owner/Developer Administration Panels to End-Users on `/webgpu.html`**: By default, `/webgpu.html` MUST render ONLY the clean **3-Step UAV Survey Workflow** (`Bước 01: Xác thực License Key & Chọn Mô hình`, `Bước 02: Tải Ảnh UAV & DEM`, `Bước 03: Chạy Suy luận WebGPU & Xuất CAD`). All internal host/developer panels (`Tự động mở Cổng Web Host`, `Git Push / Lưu CODE_DATA Drive`, `Đồ thị Tri thức Graphify`, `Vòng lặp Gemini 4 Argon`, `Quản trị & Cấp phát Mã Key`) MUST remain strictly hidden (`display: none`) unless explicitly unlocked by the software owner via `?admin=1` + Admin Password.
- **Never show a Stop/Cancel Button (`⏹ Dừng` / `Hủy`) when a process is not running (`State-Driven Action Visibility`)**: Any Stop/Cancel button (`#argonStopBtn`, `#cancelJobBtn`, `#stopBtn`) MUST default to `display: none` when the task status is `Sẵn sàng` / `Idle` / `Hoàn tất` (`running === false`) and ONLY become visible (`display: inline-flex`) while `running === true`. Append cache-busting query strings (`?v=20261109_2`) when updating UI scripts so browsers immediately load the latest state logic.
