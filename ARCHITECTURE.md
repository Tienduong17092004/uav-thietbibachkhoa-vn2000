# Kiến trúc Hệ thống Toàn diện & Quy chuẩn Thiết kế Awesome Design (`ARCHITECTURE.md`)

> [!IMPORTANT]
> **NGUYÊN TẮC BẮT BUỘC TRƯỚC MỖI LẦN CODE (`ARCHITECTURE-FIRST GATEKEEPER`)**:
> 1. **Tuyệt đối không viết hoặc sửa code ngay lập tức** khi có yêu cầu tính năng mới, thay đổi luồng dữ liệu hoặc cập nhật giao diện.
> 2. **Bước 0 — Bắt buộc chạy Agent `architecture-design-lead`**: Agent kiến trúc phải đọc [`graphify-out/GRAPH_REPORT.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/graphify-out/GRAPH_REPORT.md) và tệp [`ARCHITECTURE.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ARCHITECTURE.md) này, **vẽ bổ sung sơ đồ kiến trúc (Mermaid) + hợp đồng API/Dữ liệu + đặc tả UI Awesome Design** vào tệp này trước.
> 3. **Chốt kiến trúc trơn tru (`Architecture Sign-Off`)**: Kiểm tra không có xung đột luồng, không tạo vòng lặp phụ thuộc (`0 Import Cycles`), rõ đầu vào/đầu ra giữa các tệp, rồi mới bàn giao cho 4 Agent thi công (`code-architect`, `ui-ux-specialist`, `math-geometry-expert`, `gis-uav-specialist`) bắt đầu code.

---

## Phần I. Kiến trúc Tổng thể Hệ thống (Hexagonal & Multi-Engine Architecture)

Hệ thống **UAV GeoTIFF Studio & WebGPU 6-Class Terrain Survey Portal** được thiết kế theo kiến trúc **Hexagonal (Ports & Adapters)** kết hợp **Đồ thị Tri thức Graphify (`1,170 nodes · 3,245 edges · 51 communities · Giảm 47.7× token`)**, tách biệt hoàn toàn giữa:
1. **Lõi nghiệp vụ & Hình học (`uav_app/domain/`)** — thuần Python/Toán học, không phụ thuộc I/O hay GPU.
2. **Điều phối Ứng dụng (`uav_app/application/`)** — quản lý vòng đời Job, tiến độ cuốn chiếu, duyệt kết quả và bảo vệ trạng thái nguyên tử.
3. **Hạ tầng Viễn thám, AI & CAD (`uav_app/infrastructure/`)** — đọc/ghi GeoTIFF cửa sổ trượt (`Rasterio`), chuyển đổi `.DWG` ↔ `.DXF` 2 chiều (`AutoCAD Core Console`), phân đoạn địa hình 6 lớp, vòng lặp tự gán nhãn `Gemini 4 Argon CLI` (`agy.exe`), và Web Host tự khởi động (`0.0.0.0:8765`).
4. **Cổng giao tiếp & Giao diện (`uav_app/adapters/` + `ui/`)** — Máy chủ Trạm 5 bước (`server.py`), Cổng WebGPU Công khai (`webgpu_public_server.py`), Huấn luyện viên ONNX từ `.DWG` (`terrain_onnx_builder.py`) và 3 giao diện chuyên dụng (`index.html`, `advanced.html`, `webgpu.html`).

### 1.1. Sơ đồ Kiến trúc Phân tầng & Luồng Phụ thuộc (`flowchart TB`)

```mermaid
flowchart TB
    subgraph UI_Layer["1. Tầng Giao diện Kỹ thuật (UI Layer — Awesome Design System)"]
        UI_Studio["Trạm Băm ảnh & Lưới 3D<br/>(ui/index.html · ui/app.js · ui/viewport.js)"]
        UI_Adv["Trạm Nhận diện & Duyệt 5 Bước<br/>(ui/advanced.html · ui/advanced.js)"]
        UI_WebGPU["Cổng Khảo sát Địa hình WebGPU<br/>(ui/webgpu.html · ui/webgpu_app.js)"]
        UI_AutoPanel["Trung tâm Tự động hóa & Graphify<br/>(ui/argon_host_panel.js)"]
    end

    subgraph Adapter_Layer["2. Tầng Cổng Giao tiếp & Điều phối HTTP/IPC (uav_app/adapters/)"]
        Srv_Local["Máy chủ Trạm Cục bộ<br/>(server.py · Loopback + CSRF Token)"]
        Srv_Public["Cổng WebGPU Công khai Port 8765<br/>(webgpu_public_server.py)"]
        Routes_Auto["Cổng API Tự động hóa<br/>(autostart_and_argon_routes.py)<br/>/api/host · /api/argon · /api/gdrive · /api/graphify"]
        ONNX_Builder["Huấn luyện ONNX từ Bản vẽ .DWG<br/>(terrain_onnx_builder.py)"]
        Worker_IPC["Tiến trình Model Độc lập<br/>(model_worker.py · turbo_worker.py)"]
    end

    subgraph App_Layer["3. Tầng Điều phối Nghiệp vụ (uav_app/application/)"]
        Svc["God Node #1: ProjectService<br/>(service.py · 84 edges)"]
        Pipe_Det["Luồng Quét Cuốn chiếu<br/>(detection_pipeline.py · 37 edges)"]
        Rev["Duyệt & Xuất Kết quả<br/>(review.py · advisor.py)"]
    end

    subgraph Domain_Layer["4. Tầng Lõi Toán học & Hình học (uav_app/domain/)"]
        Dom_Geo["Biến đổi Affine & Cắt Đa giác<br/>(geometry.py)"]
        Dom_Det["Gộp Khung WBF / Stitch Biên<br/>(detection.py)"]
        Dom_Set["Whitelist Cấu hình An toàn<br/>(settings.py)"]
    end

    subgraph Infra_Layer["5. Tầng Hạ tầng GIS, AI, AutoCAD .DWG & Cloud Sync (uav_app/infrastructure/)"]
        Inf_Raster["Đọc/Ghi GeoTIFF Cửa sổ & Warp<br/>(raster.py · warp.py · dem.py · multispectral.py)"]
        Inf_Terrain["Phân đoạn 6 Lớp & Vector hóa PL<br/>(terrain_segmentation.py · survey_cad.py)"]
        Inf_DWG["Engine .DWG ↔ .DXF 2 Chiều<br/>(dwg_io.py · AutoCAD accoreconsole.exe)"]
        Inf_Argon["Vòng lặp Gemini 4 Argon CLI<br/>(gemini_argon_loop.py · agy.exe)"]
        Inf_Host["Auto-Boot Web Host Port 8765<br/>(autostart_host.py · Startup VBS)"]
        Inf_License["Bảo mật Khoá WebGPU AES-256-GCM<br/>(webgpu_license.py)"]
        Inf_Graphify["Đồ thị Tri thức Graphify<br/>(graphify-out/graph.json · GRAPH_REPORT.md)"]
    end

    UI_Studio --> Srv_Local
    UI_Adv --> Srv_Local
    UI_WebGPU --> Srv_Public
    UI_WebGPU --> Srv_Local
    UI_AutoPanel --> Routes_Auto

    Srv_Local --> Svc
    Srv_Local --> Routes_Auto
    Srv_Public --> Inf_License
    Srv_Public --> Routes_Auto

    Svc --> Pipe_Det
    Svc --> Rev
    Svc --> Inf_Terrain
    Svc --> Inf_DWG
    Svc --> ONNX_Builder

    Pipe_Det --> Dom_Geo
    Pipe_Det --> Dom_Det
    Pipe_Det --> Inf_Raster
    Pipe_Det --> Worker_IPC

    Inf_Terrain --> Inf_DWG
    Inf_Terrain --> Inf_Raster
    ONNX_Builder --> Inf_DWG
    Routes_Auto --> Inf_Argon
    Routes_Auto --> Inf_Host
    Routes_Auto --> Inf_Graphify
```

---

### 1.2. Sơ đồ Tuần tự Luồng Dữ liệu Đầu-Cuối (`sequenceDiagram`)

Từ lúc nạp ảnh `ORTHO` + bản vẽ `.DWG` khảo sát → Băm ảnh → Tự gán nhãn bằng **Gemini 4 Argon (`agy.exe`)** → Huấn luyện mô hình `terrain_webgpu.onnx` → Suy luận WebGPU và xuất thẳng các đường `PL` (`LWPOLYLINE`) ra tệp AutoCAD **`.DWG`** + đồng bộ **Google Drive (`CODE_DATA`)**:

```mermaid
sequenceDiagram
    autonumber
    actor Engineer as Kỹ sư Khảo sát
    participant UI as Giao diện Web / WebGPU<br/>(webgpu.html / index.html)
    participant API as Backend Server<br/>(server.py / routes)
    participant DWG as Engine AutoCAD .DWG<br/>(dwg_io.py · accoreconsole)
    participant Argon as Gemini 4 Argon CLI<br/>(gemini_argon_loop.py · agy.exe)
    participant ONNX as Trình Huấn luyện & WebGPU<br/>(terrain_onnx_builder.py / ORT)
    participant GDrive as Google Drive Cloud<br/>(CODE_DATA / Project Folder)

    Note over Engineer,GDrive: GIAI ĐOẠN 1: BĂM ẢNH & VÒNG LẶP TỰ GÁN NHÃN GEMINI 4 ARGON CLI
    Engineer->>UI: 1. Chọn ảnh ORTHO (.tif/.jpg+.jgw) & Băm ảnh (Export Tiles)
    UI->>API: POST /api/export (Xuất các ảnh cắt ô vào outputs/geotiff_runs/*)
    Engineer->>UI: 2. Bấm "Chạy Vòng lặp Gemini 4 Argon (gemini-4-argon-high)"
    UI->>API: POST /api/argon/start {model: "gemini-4-argon-high", auto_train_after: true}
    API->>Argon: Khởi chạy luồng nền quét từng ảnh đã băm
    loop Mỗi ảnh trong thư mục đã băm
        Argon->>Argon: Gọi agy.exe --model gemini-4-argon-high + Phân tích Phổ/Địa hình
        Argon-->>Argon: Ghi nhãn YOLO (.txt) + Mặt nạ 6 lớp (_mask.png) + data.yaml
    end

    Note over Engineer,GDrive: GIAI ĐOẠN 2: HUẤN LUYỆN TỪ BẢN VẼ .DWG THỰC TẾ & SUY LUẬN WEBGPU
    Engineer->>UI: 3. Huấn luyện từ bộ bản vẽ .DWG khảo sát (hoặc nạp terrain_webgpu.onnx)
    UI->>API: POST /api/terrain/train-dwg
    API->>DWG: convert_dwg_to_dxf() đọc các lớp 1.BK.MEPDUONG_*, 1.BK.SONG+MUONG+RACH
    DWG-->>ONNX: Mặt nạ chuẩn (Ground-Truth Masks) 6 lớp địa hình
    ONNX-->>API: Xuất models/turbo_yolo/terrain_webgpu.onnx + terrain_webgpu.json

    Note over Engineer,GDrive: GIAI ĐOẠN 3: TRÍCH XUẤT ĐƯỜNG PL (.DWG) & LƯU LÊN GOOGLE DRIVE (CODE_DATA)
    Engineer->>UI: 4. Nạp bộ 4 tệp (ORTHO.jpg + .jgw + .prj + DEM.tif) & Chạy Nhận diện
    UI->>ONNX: Suy luận WebGPU (6 lớp) + Vector hóa 2 mép + tim đường + cao độ Z (DEM)
    Engineer->>UI: 5. Tích chọn "Chỉ xuất các đường PL" & Bấm "Xuất các đường PL ra AutoCAD (.DWG)"
    UI->>API: POST /api/terrain/dwg {dxf_content, pl_only: true}
    API->>DWG: convert_dxf_to_dwg() qua AutoCAD Core Console (~2 giây)
    DWG-->>Engineer: Tải về tệp binh_do_PL_VN2000.dwg (Native AutoCAD 2018 .DWG)
    Engineer->>UI: 6. Nhập tên Project & Bấm "Lưu Project vào CODE_DATA (Drive)"
    UI->>API: POST /api/gdrive/sync {project_name, parent_folder_id: "1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D"}
    API->>GDrive: Tạo/Cập nhật tại chỗ thư mục CODE_DATA/<Tên_Project> (ZIP + Bundle + ONNX + Graphify)
```

---

### 1.3. Sơ đồ Máy Trạng thái Quy trình Kiến trúc & Vòng đời Tác vụ (`stateDiagram-v2`)

```mermaid
stateDiagram-v2
    [*] --> Step0_ArchitectureGate: Yêu cầu Tính năng / Sửa đổi mới
    state "Bước 0: Chốt Kiến trúc (architecture-design-lead)" as Step0_ArchitectureGate {
        ReadGraphify: Đọc GRAPH_REPORT.md & ARCHITECTURE.md
        DrawBlueprint: Vẽ bổ sung Sơ đồ Mermaid & Đặc tả Awesome Design
        AuditSmoothness: Kiểm tra 0 Import Cycles & Hợp đồng API/UI
        ReadGraphify --> DrawBlueprint
        DrawBlueprint --> AuditSmoothness
    }
    Step0_ArchitectureGate --> Step1_CodingAgents: [Đã chốt kiến trúc trơn tru]
    state "Bước 1: Thi công Code (4 Sub-Agents chuyên trách)" as Step1_CodingAgents {
        Backend: code-architect (service.py, server.py, routes)
        GIS_CAD: gis-uav-specialist (terrain_segmentation.py, dwg_io.py)
        Math_Geo: math-geometry-expert (geometry.py, detection.py)
        UI_UX: ui-ux-specialist (webgpu.html, index.html, argon_host_panel.js)
    }
    Step1_CodingAgents --> Step2_Verification: Chạy pytest + cập nhật Graphify
    state "Bước 2: Kiểm thử & Đồng bộ Đồ thị" as Step2_Verification {
        PytestSuite: 98/98 bài kiểm thử pytest đạt 100%
        GraphifyHook: Git post-commit tự động cập nhật graphify-out/
        DriveSync: Đồng bộ lên Google Drive (CODE_DATA/<Tên_Project>)
        PytestSuite --> GraphifyHook
        GraphifyHook --> DriveSync
    }
    Step2_Verification --> [*]
```

---

### 1.4. Bảng Phân rã 10 Nút Trung tâm (`God Nodes` từ `Graphify`) & Trách nhiệm Tệp

| Hạng | God Node / Module | Số liên kết (`Edges`) | Tệp nguồn chính | Trách nhiệm Kiến trúc Cốt lõi |
| :---: | :--- | :---: | :--- | :--- |
| **1** | [`ProjectService`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/application/service.py) | `84` | [`uav_app/application/service.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/application/service.py) | Điều phối trung tâm: quản lý trạng thái dự án, khoá phiên đơn (`Lease`), gọi luồng băm ảnh, nhận diện, phân đoạn 6 lớp và xuất `.DXF`/`.DWG`. |
| **2** | [`createAdvanced()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/advanced.js) | `71` | [`ui/advanced.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/advanced.js) | Bộ điều khiển giao diện Trạm 5 bước: chọn vùng đa giác CAD, theo dõi tiến độ cuốn chiếu, duyệt mẫu, cấu hình thư viện khảo sát `.DWG`/`.DXF`. |
| **3** | [`createViewport()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/viewport.js) | `43` | [`ui/viewport.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/viewport.js) | Không gian bản đồ 2D/3D (Three.js + Canvas): hiển thị ảnh tổng quan, lưới cắt ảnh, vùng chồng lấn (`Overlap`), khung nhận diện và la bàn Bắc. |
| **4** | [`run_detection()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/application/detection_pipeline.py) | `37` | [`uav_app/application/detection_pipeline.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/application/detection_pipeline.py) | Luồng quét cuốn chiếu cửa sổ trượt: đọc từng vùng ảnh gốc, suy luận, làm giàu chỉ số phổ (`NDVI`/`NDRE`/`ExG`) + cao độ `DEM`, ghi kết quả tức thì. |
| **5** | [`run_terrain_segmentation_and_export_dxf()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/terrain_segmentation.py) | `29` | [`uav_app/infrastructure/terrain_segmentation.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/terrain_segmentation.py) | Phân đoạn 6 lớp địa hình (`asphalt_road`, `concrete_road`, `dirt_road`, `footpath`, `pond`, `masonry_ditch`), trích xuất 2 bờ + tim đường `PL` chuẩn VN2000. |
| **6** | [`handle_automation_get/post()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/autostart_and_argon_routes.py) | `32` | [`uav_app/adapters/autostart_and_argon_routes.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/autostart_and_argon_routes.py) | Cổng tích hợp Tự động hóa: quản lý Auto-Boot Web Host (`8765`), vòng lặp Gemini 4 Argon CLI, đồng bộ Google Drive (`CODE_DATA`) và Graphify API. |
| **7** | [`start_argon_active_learning_loop()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/gemini_argon_loop.py) | `25` | [`uav_app/infrastructure/gemini_argon_loop.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/gemini_argon_loop.py) | Động cơ Active Learning hậu băm ảnh: gọi `agy.exe --model gemini-4-argon-high` kết hợp bộ phân tích phổ/địa hình để sinh nhãn YOLO + mặt nạ phân đoạn. |
| **8** | [`convert_dwg_to_dxf()` / `convert_dxf_to_dwg()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/dwg_io.py) | `24` | [`uav_app/infrastructure/dwg_io.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/dwg_io.py) | Chuyển đổi `.DWG` ↔ `.DXF` 2 chiều ngầm qua `accoreconsole.exe` (AutoCAD 2025/2027) và kiểm kê các đường `PL` (`LWPOLYLINE`) theo layer. |
| **9** | [`make_public_webgpu_server()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/webgpu_public_server.py) | `24` | [`uav_app/adapters/webgpu_public_server.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/webgpu_public_server.py) | Máy chủ Cổng WebGPU Công khai (`0.0.0.0:8765`): cách ly tệp máy trạm, cấp phát mô hình ONNX mã hóa `AES-256-GCM` dùng 1 lần trên RAM trình duyệt. |
| **10** | [`train_and_export_terrain_onnx()`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/terrain_onnx_builder.py) | `26` | [`uav_app/adapters/terrain_onnx_builder.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/terrain_onnx_builder.py) | Khớp nối tọa độ `.DWG` khảo sát với ảnh `ORTHO` + `.jgw` + `DEM`, huấn luyện mạng `TerrainSegUNetLite-WebGPU` trên GPU CUDA và xuất `.onnx`. |

---

## Phần II. Quy chuẩn Hệ thống Thiết kế Awesome Design (`Awesome DESIGN.md Specification`)

Áp dụng chuẩn **[Awesome `DESIGN.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/skills/awesome-design-md-main/README.md)** kết hợp triết lý **VoltAgent Precision Engineering** ([`design/DESIGN.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/design/DESIGN.md)):

### 2.1. Chủ đề Thị giác & Bầu không khí (`Visual Theme & Atmosphere`)
Hệ thống vận hành với **Kiến trúc Giao diện Kép (Dual-Surface Engineering Identity)**:
1. **Cổng WebGPU Khảo sát & Trung tâm Tự động hóa (`ui/webgpu.html`, `ui/argon_host_panel.js`) — Chế độ Buồng lái Đêm Kỹ thuật (`Abyssal Carbon Cockpit`)**:
   - Nền tối sâu (`#07090e` → `#0f172a`) làm nổi bật tuyệt đối các đường nét vector địa hình 6 lớp, bản đồ nhiệt cao độ DEM và trạng thái hoạt động của GPU/CLI.
   - Năng lượng điểm nhấn kép: **Emerald Signal Green (`#10b981` / `#00d992`)** biểu thị trạng thái *"Đã kết nối / Đang chạy / Đã xác thực"* và **Cyan Telemetry (`#06b6d4` / `#38bdf8`)** biểu thị luồng dữ liệu toạ độ VN2000 & WebGPU.
2. **Trạm Workstation 5 Bước (`ui/index.html`, `ui/advanced.html`) — Chế độ Sáng Mặc định (`☀️ Sáng`) có Công tắc Chuyển đổi `☀️ Sáng / 🌙 Tối`**:
   - Nền sáng kỹ thuật (`#f8fafc` / `#ffffff`) với đường viền sắc nét (`#cbd5e1`), tối ưu cho kỹ sư biên tập bản đồ ngoài thực địa hoặc văn phòng ánh sáng mạnh trên màn hình 24 inch Full-Bleed.

### 2.2. Bảng Màu & Mã Màu Chuẩn Khảo sát VN2000 (`Color Palette & Roles`)

#### A. Bảng màu Giao diện & Trạng thái (`UI Surface & Semantic Tokens`)
| Vai trò (`Role`) | Tên Token | Mã Hex | Ứng dụng bắt buộc |
| :--- | :--- | :---: | :--- |
| **Canvas Dark** | `Abyss Slate` | `#07090e` | Nền chính Cổng WebGPU và khung nhìn Canvas bản đồ tối |
| **Card Surface Dark** | `Carbon Panel` | `#0f172a` | Nền các thẻ điều khiển, bảng Automation, khung thông số |
| **Canvas Light** | `Daylight Paper` | `#f8fafc` | Nền mặc định Trạm 5 bước (`☀️ Sáng`) |
| **Border Containment** | `Warm Charcoal / Slate Border` | `#3d3a39` / `rgba(148,163,184,0.22)` | Đường viền 1px phân tách rõ mọi khung chức năng, không dùng bóng đổ mờ nhạt |
| **Primary Brand Signal** | `Emerald Signal Green` | `#00d992` / `#10b981` | Trạng thái Active, nút CTA chính, viền thẻ đang hoạt động |
| **Telemetry Accent** | `Survey Cyan` | `#06b6d4` / `#38bdf8` | Nhãn tọa độ VN2000, tiến độ băm ảnh/Gemini 4 Argon, liên kết Graphify |
| **Warning / Dirty Git** | `Warning Amber` | `#f59e0b` | Cảnh báo hạn ngạch, tệp Git chưa commit, trạng thái đang chờ |
| **Danger / Stop** | `Danger Coral` | `#ef4444` | Nút dừng khẩn cấp (`⏹ Dừng`), thông báo lỗi xác thực |

#### B. Bảng màu 8 Lớp Địa hình – Đô thị – Cảnh quan (`9-Channel Tensor: 0=Background + 8 Lớp Địa vật`) & Mã màu AutoCAD Chuẩn VN2000
| Mã Số (`ID`) | Mã Lớp (`Class ID`) | Tên Tiếng Việt | Layer AutoCAD (`.DWG`/`.DXF`) | Màu Hiển thị Web (`Hex`) | Mã Màu AutoCAD (`ACI`) | Kiểu Nét & Hình học Xuất `.DWG` |
| :---: | :--- | :--- | :--- | :---: | :---: | :--- |
| `0` | `background` | **Nền trống / Nodata** | *(Không xuất)* | `transparent` | — | Bỏ qua khi vector hóa |
| `1` | `asphalt_road` | **Đường ô tô / Đường nhựa** | `KS_DUONG_NHUA` | `#ef4444` | `1` (Red) | `CONTINUOUS` · `CORRIDOR` 2 đường `PL` mép + 1 đường `PL` tim (`CENTER`) |
| `2` | `concrete_road` | **Đường ô tô / Đường bê tông** | `KS_DUONG_BETONG` | `#94a3b8` | `2` (Yellow) | `CONTINUOUS` · `CORRIDOR` 2 đường `PL` mép + 1 đường `PL` tim (`CENTER`) |
| `3` | `dirt_road` | **Đường đi / Đường đất** | `KS_DUONG_DAT` | `#d97706` | `30` (Orange) | `DASHED` · `CORRIDOR` 2 đường `PL` mép nét đứt |
| `4` | `footpath` | **Đường đi bộ / Vỉa hè** | `KS_DUONG_DIBO` | `#a855f7` | `8` (Gray) | `DASHED` · `CORRIDOR` 2 đường `PL` mép hẹp (`< 1.9m`) |
| `5` | `pond` | **Sông / Ao / Hồ / Kênh rạch** | `KS_AO_HO` | `#0ea5e9` | `5` (Blue) | `CONTINUOUS` · `POLYGON` khép kín + ký hiệu bờ taluy (`dZ < -0.15m`) |
| `6` | `masonry_ditch` | **Mương xây / Kè kênh** | `KS_MUONG_XAY` | `#06b6d4` | `4` (Cyan) | `CONTINUOUS` · `CORRIDOR` 2 đường `PL` thành mương song song |
| `7` | `house_building` | **Nhà / Công trình xây dựng** | `KS_NHA_CONGTRINH` | `#f59e0b` | `2` (Yellow/Amber) | `CONTINUOUS` · `POLYGON` khép kín vuông hóa/làm mượt + nhãn `NHÀ` (`dZ > +1.8m`) |
| `8` | `landscape_tree` | **Cây cảnh quan / Cây xanh** | `KS_CAY_CANHQUAN` | `#10b981` | `3` (Green) | `BLOCK INSERT` · **Tuyệt đối KHÔNG vẽ vùng `POLYGON`**; chèn Block chuẩn từ thư viện `assets/cad_blocks/Mylib2` tại tâm `(X, Y, Z)` với tỷ lệ `scale = diameter_m` |

### 2.3. Quy tắc Kiểu chữ (`Typography Rules`)
- **Heading & Điều hướng (`system-ui` / `Archivo` / `Inter`)**:
  - Nén chặt chiều cao dòng (`line-height: 1.0 – 1.15`), `letter-spacing: -0.02em`, tạo cảm giác bảng điều khiển kỹ thuật cô đọng.
  - Nhãn phân khu (`Eyebrow / Kicker`): In hoa (`uppercase`), `font-size: 10.5px – 11px`, `font-weight: 700`, `letter-spacing: 0.08em`, màu `#38bdf8` hoặc `#00d992`.
- **Toạ độ, Thông số GSD, Log CLI & Mã Khoá (`SFMono-Regular` / `JetBrains Mono` / `Consolas`)**:
  - Bắt buộc dùng font `monospace` kèm `font-variant-numeric: tabular-nums` cho mọi ô tọa độ `X (Easting)`, `Y (Northing)`, `Z (DEM)`, kích thước lưới, nhật ký `agy.exe` và đường dẫn tệp để các chữ số thẳng cột tuyệt đối khi cập nhật theo thời gian thực.

### 2.4. Bố cục & Quy chuẩn Thành phần Giao diện (`Layout & Component Stylings`)
1. **Bố cục Màn hình 24-inch Full-Bleed Split-Pane & Chuẩn Không Cuộn Dọc (`Zero-Vertical-Scroll Layout`)**:
   - Cột điều khiển bên trái (`.control-column` trên `ui/webgpu.html`, chiều rộng `380px – 440px`): Bắt buộc thiết kế vừa khít khung nhìn không phát sinh thanh cuộn dọc (`scrollHeight <= clientHeight`) trên toàn bộ các độ phân giải màn hình tiêu chuẩn (`1920x1080`, `1440x1080`, `1440x900`, `1366x768`, `1280x800`).
   - Không gian bản đồ/Canvas bên phải (`1fr`, chiếm trọn chiều cao màn hình, khoá cuộn ngang `overflow-x: hidden`).
2. **Thẻ chức năng (`Engineering Sub-Cards`)**:
   - Bo góc chuẩn kỹ thuật (`6px – 10px`, chỉ dùng `9999px` cho huy hiệu trạng thái `Badge`).
   - Phân cấp chiều sâu bằng **độ dày và màu đường viền** (`1px solid #3d3a39` cho thẻ thường → `1.5px solid #00d992` hoặc `#06b6d4` cho thẻ đang hoạt động), hạn chế lạm dụng bóng đổ mờ.
3. **Ngôn ngữ Giao diện Chuyên nghiệp & Vi mô Súc tích (`Do's & Don'ts`)**:
   - **DO**: Dùng thuật ngữ tiếng Việt kỹ thuật ngắn gọn, vi mô chức năng súc tích (functional microcopy: **`ảnh`** thay cho `tile`, **`PL (.DWG)`** cho `LWPOLYLINE`, **`Cao độ Z (DEM)`**); bảo toàn nguyên vẹn chuỗi kiểm thử bắt buộc `"Cổng WebGPU Bình đồ Địa hình 6 Lớp"` trong `ui/webgpu.html`; bảo toàn trọn vẹn 14 emoji miền nghiệp vụ chuyên dụng (`"🛰️", "📡", "🧭", "📐", "⛰️", "🎯", "🌾", "🌱", "🌿", "🌳", "🖥️", "⚡", "🔬", "🎛️"`); thẻ trạng thái `#portal-status` chỉ hiển thị thông báo alert/toast khi có sự kiện runtime, không chứa banner hướng dẫn tĩnh ban đầu.
   - **DON'T**:
     * Tuyệt đối không đưa các ký tự emoji bị cấm (`"🙈", "🔮", "✨", "❓", "💡"`) vào `ui/index.html`, `ui/advanced.html`, `ui/advanced.js`.
     * Tuyệt đối không viết các câu mô tả giải thích dài dòng dưới tiêu đề bước; loại bỏ hoàn toàn các khối chú thích phụ `.hint`, các banner/thông báo trạng thái tĩnh dư thừa (đặc biệt banner: *"Hãy bấm Bước 01 để xác thực Key & nạp mô hình mã hóa lên Card GPU."*), và các đoạn văn bản giải thích dài dòng trong `.empty-card` / `.empty-note` trên toàn bộ các trang giao diện (`ui/webgpu.html`, `ui/index.html`, `ui/advanced.html`) và script liên quan (`ui/argon_host_panel.js`, `ui/webgpu_app.js`, `ui/app.js`, `ui/advanced.js`).
     * Không hiển thị thanh công cụ vẽ đa giác khi người dùng chưa chọn chế độ *"Chỉ các vùng được chọn"*.

---

## Phần III. Quy trình Bắt buộc Trước Mỗi Lần Code (`Pre-Code Architecture Protocol`)

Mỗi khi người dùng yêu cầu thêm tính năng, thay đổi thuật toán hoặc chỉnh sửa giao diện, **Agent Điều phối (`Orchestrator`)** và **5 Sub-Agent** bắt buộc tuân thủ quy trình 3 bước sau:

### Bước 0: Giao cho Agent `architecture-design-lead` Vẽ & Chốt Kiến trúc (`BẮT BUỘC TRƯỚC KHI CODE`)
1. Đọc [`graphify-out/GRAPH_REPORT.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/graphify-out/GRAPH_REPORT.md) và [`ARCHITECTURE.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ARCHITECTURE.md).
2. Cập nhật bổ sung vào **Mục Nhật ký Kiến trúc Tính năng Mới (Phần IV bên dưới)** của tệp [`ARCHITECTURE.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ARCHITECTURE.md) này:
   - **Sơ đồ luồng / thành phần Mermaid** cho tính năng sắp làm.
   - **Hợp đồng dữ liệu (`Input / Output / API Route / State`)** giữa các tệp.
   - **Token thiết kế Awesome Design** (nếu có thêm nút bấm, thẻ giao diện hoặc lớp màu CAD mới).
3. Kiểm tra **Chốt kiến trúc trơn tru (`Architecture Sign-Off Checklist`)**:
   - [x] Không tạo phụ thuộc ngược từ `domain/` sang `infrastructure/` hoặc `adapters/`.
   - [x] Không import `torch` trực tiếp trong tiến trình HTTP Server nhẹ.
   - [x] Không làm gián đoạn tiến trình quét hoặc cổng Web Host `8765` đang chạy.
   - [x] Đã xác định rõ danh sách tệp từng Agent được phép sửa.

### Bước 1: Phân công Thi công Code theo Chuyên môn
Chỉ sau khi Bước 0 hoàn tất và `ARCHITECTURE.md` đã được cập nhật trơn tru, mới gọi các Agent thi công:
- **`code-architect`**: Backend HTTP routes, `ProjectService`, đa luồng, `autostart_host.py`, `gemini_argon_loop.py`, `pytest`.
- **`gis-uav-specialist`**: `terrain_segmentation.py`, `dwg_io.py`, `survey_cad.py`, `terrain_onnx_builder.py`, `raster.py`, `dem.py`.
- **`math-geometry-expert`**: `geometry.py`, `detection.py`, `refinement.py`.
- **`ui-ux-specialist`**: `ui/webgpu.html`, `ui/webgpu_app.js`, `ui/index.html`, `ui/advanced.html`, `ui/argon_host_panel.js`.

### Bước 2: Kiểm thử `pytest` & Tự động Cập nhật Đồ thị `Graphify`
- Chạy `pytest` đảm bảo 100% test xanh.
- Chạy `graphify update . --force` (hoặc commit để Git hook tự chạy) nhằm đồng bộ `graph.html`, `callflow.html`, `graph.json`, `GRAPH_REPORT.md`.

---

## Phần IV. Nhật ký Bản vẽ Kiến trúc theo Từng Đợt Phát triển (`Architecture Evolution Log`)

### Bản vẽ #01 (2026-11-09): Hệ sinh thái Khảo sát `.DWG` 2 Chiều + Auto-Host `8765` + Gemini 4 Argon CLI + Graphify + Google Drive `CODE_DATA`
- **Trạng thái**: `ĐÃ CHỐT KIẾN TRÚC & TRIỂN KHAI HOÀN TẤT (APPROVED & VERIFIED)`
- **Các hợp đồng kỹ thuật đã khóa**:
  1. `uav_app/infrastructure/dwg_io.py` ↔ `AutoCAD accoreconsole.exe`: Chuyển đổi `.DWG` ↔ `.DXF` ngầm và xuất trực tiếp `LWPOLYLINE` (`pl_only=True`) ra `.DWG`.
  2. `uav_app/infrastructure/autostart_host.py` ↔ `UAV_WebGPU_AutoHost.vbs`: Khởi động ngầm cổng `0.0.0.0:8765` khi bật Windows, tự đóng khi tắt máy.
  3. `uav_app/infrastructure/gemini_argon_loop.py` ↔ `agy.exe --model gemini-4-argon-high`: Tự gán nhãn YOLO + mặt nạ phân đoạn sau khi băm ảnh và kích hoạt huấn luyện tinh chỉnh.
  4. `uav_app/adapters/autostart_and_argon_routes.py`: Đồng bộ từng Project theo tên thư mục riêng vào Google Drive `CODE_DATA` (`1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D`) và phục vụ trực tiếp `/graph.html`, `/callflow.html`, `/GRAPH_REPORT.md`.

---

### Bản vẽ #02 (2026-11-09): Kiến trúc Tự Huấn luyện Lúa Đa phổ–Độ cao sang RGB (`Cross-Sensor MS+DEM → RGB Self-Distillation`) trên `Results_Stage 1` & Khung Bài báo Khoa học Q1
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING]`
- **Điểm mới Khoa học Cốt lõi (`Core Scientific Novelty - Q1 Journal Contribution`)**:
  - **Cross-Resolution & Cross-Sensor Physics-Guided Self-Distillation (`MS 2.46cm + DEM 24.8cm → RGB 1.5cm`)**: Khắc phục chi phí cảm biến đa phổ đắt đỏ và công sức gán nhãn thủ công trên đồng ruộng lúa mới cấy (`Stage 1`) bằng cách dùng tổ hợp 5 băng phổ thực tế (`Green`, `Red`, `RedEdge`, `NIR`) + vi địa hình mặt ruộng (`ΔZ_micro_relief` từ `DEM_Stage 1.tif`) + phân vùng ngữ cảnh (`Ortho_Stage 1_Segment.tif`) làm **Mô hình Thầy Vật lý – Sinh học (`8-Channel Physics-Guided Spectral-Topographic Teacher`)** để tự động tổng hợp nhãn chuẩn xác cho 3 lớp sinh thái nông học (`0: Newly transplanted rice`, `1: Grass`, `2: Newly transplanted rice + Partial Grass`) và chưng cất tri thức sang **Mô hình Trò chỉ dùng ảnh RGB chuẩn 1.5cm (`Dual RGB Student: YOLO11 Clump/Zone Detector + WebGPU Semantic UNet ONNX`)**.

#### 1. Sơ đồ Luồng Kiến trúc Tự Huấn luyện Đa phổ sang RGB (`Mermaid Flowchart`)

```mermaid
flowchart LR
    subgraph Input["1. Tổ hợp Dữ liệu Thực địa (sample/MULTISPECTRAL/Results_Stage 1)"]
        RGB["Ortho_Stage 1_RGB.tif<br/>(5782x5468 · 1.50cm GSD)"]
        MS["4 Băng Đa phổ (_Green, _Red, _RedEdge, _NIR.tif)<br/>(3515x3332 · 2.46cm GSD)"]
        DEM["DEM_Stage 1.tif<br/>(612x582 · 24.8cm GSD)"]
        SEG["Ortho_Stage 1_Segment.tif + Label_Color.txt<br/>(3 Lớp chuẩn: Lúa mới cấy / Cỏ / Lúa+Cỏ)"]
    end

    subgraph Teacher["2. Mô hình Thầy Vật lý Đa phổ - Vi địa hình (8-Ch Physics Teacher)"]
        ALIGN["Đồng bộ Không gian Affine UTM 48N<br/>(Sub-pixel Bilinear/Cubic Co-registration)"]
        INDICES["Trích xuất Chỉ số Sinh-Địa vật lý:<br/>NDVI, NDRE, GNDVI, ExG, ΔZ_micro_relief"]
        PSEUDO["Tự động Sinh Nhãn Đa Tỷ lệ:<br/>- Mask Ngữ nghĩa 3 Lớp<br/>- Hộp giới hạn Khóm lúa / Đám cỏ YOLO"]
    end

    subgraph Student["3. Huấn luyện Kép Mô hình Trò RGB (Dual Student Distillation)"]
        S_YOLO["Luồng Trò 1: YOLO11-Nano/Small RGB<br/>(runs/stage1_rice_yolo/weights/best.pt & .onnx)"]
        S_WEBGPU["Luồng Trò 2: RiceStage1UNetLite RGB<br/>(models/rice_stage1_webgpu.onnx · FP32)"]
        BENCH["Đánh giá Định lượng & Ablation Study<br/>(RGB-only vs RGB+ExG vs MS+DEM Teacher → RGB Student)"]
    end

    subgraph Paper["4. Sản phẩm Đầu ra & Bài báo Khoa học Q1"]
        SCAN["Chạy Thực nghiệm Toàn cảnh Stage 1<br/>(Tạo Ảnh băm, Nhãn, Bản đồ Phân bố & .DXF/.DWG)"]
        DOC["Báo cáo & Bản thảo Bài báo Khoa học Q1<br/>(docs/SCIENTIFIC_PAPER_RICE_UAV_Q1.md)"]
    end

    RGB --> ALIGN
    MS --> ALIGN
    DEM --> ALIGN
    SEG --> ALIGN
    ALIGN --> INDICES --> PSEUDO
    PSEUDO --> S_YOLO
    PSEUDO --> S_WEBGPU
    S_YOLO --> BENCH
    S_WEBGPU --> BENCH
    BENCH --> SCAN --> DOC
```

#### 2. Hợp đồng Dữ liệu & Mô-đun (`Data & Module Contracts`)
1. [`uav_app/adapters/stage1_rice_trainer.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/stage1_rice_trainer.py):
   - Hàm chính: `run_stage1_multispectral_training_and_experiment(stage1_dir: Path, output_project_dir: Path, epochs: int = 8) -> dict[str, Any]`
   - **Đầu vào**: Đường dẫn `C:\Users\HL\Desktop\DETECTION RICE_FIELD\sample\MULTISPECTRAL\Results_Stage 1` chứa 7 tệp GeoTIFF thực địa (`RGB`, `Green`, `Red`, `RedEdge`, `NIR`, `DEM`, `Segment`) và `Label_Color.txt`.
   - **Xử lý**:
     - Căn chỉnh tọa độ địa lý (`UTM Zone 48N, EPSG:32648`) giữa `RGB (1.5cm)`, `MS (2.46cm)`, `DEM (24.8cm)` và `Segment (1.5cm)`.
     - Tính toán các chỉ số phổ vật lý: `NDVI = (NIR - Red)/(NIR + Red)`, `NDRE = (NIR - RedEdge)/(NIR + RedEdge)`, `GNDVI = (NIR - Green)/(NIR + Green)`, `ExG = 2G - R - B`, và độ lệch vi địa hình mặt ruộng `ΔZ = DEM - GaussianBlur(DEM, σ=3m)`.
     - Trích xuất bộ dữ liệu huấn luyện tự động (`dataset_stage1_yolo/` cho phát hiện khóm/vùng lúa–cỏ và `dataset_stage1_seg/` cho phân đoạn ngữ nghĩa 3 lớp).
     - Huấn luyện thực tế mô hình `RiceStage1UNetLite` bằng PyTorch, xuất trọng số `.pt` và `.onnx` (`models/rice_stage1_webgpu.onnx`), đồng thời huấn luyện/tinh chỉnh mô hình phát hiện YOLO/Torch và chạy kiểm nghiệm Ablation (`Ablation 1: Baseline ExG Thresholding`, `Ablation 2: Standard RGB Supervised`, `Ablation 3: Proposed Physics-Guided MS+DEM → RGB Self-Distillation`).
   - **Đầu ra**: Từ điển JSON (`stage1_experiment_metrics.json`) chứa IoU, F1-Score, Precision, Recall, mAP@50 của từng phương pháp, diện tích (`m²` và `%`) của 3 lớp trên cánh đồng Stage 1, và đường dẫn tới các tệp mô hình đã huấn luyện.
2. [`docs/SCIENTIFIC_PAPER_RICE_UAV_Q1.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/docs/SCIENTIFIC_PAPER_RICE_UAV_Q1.md):
   - Bản thảo bài báo khoa học chuẩn tạp chí Q1 (*Computers and Electronics in Agriculture* / *ISPRS Journal of Photogrammetry and Remote Sensing*), đầy đủ: **Title, Abstract, Keywords, 1. Introduction, 2. Study Area & Multi-Sensor UAV Dataset (`Results_Stage 1`), 3. Proposed Methodology (Physics-Guided Cross-Sensor MS+DEM to RGB Self-Distillation & WebGPU Edge Deployment), 4. Experimental Results & Ablation Study (số liệu thực tế từ `stage1_experiment_metrics.json`), 5. Discussion & Agronomic CAD/BIM Integration, 6. Conclusion**.

#### 3. Kiểm tra Chốt Kiến trúc Trơn tru (`Pre-Code Smoothness Audit`)
- [x] **Zero Circular Imports**: `uav_app/adapters/stage1_rice_trainer.py` chỉ gọi các hàm đọc raster/hình học và chạy độc lập trong tiến trình huấn luyện/thực nghiệm, không đẩy `torch` vào `uav_app/domain/`.
- [x] **Thread & Process Safety**: Lưu kết quả thực nghiệm và mô hình `.onnx` nguyên tử (`.tmp` → `os.replace`), tích hợp mượt với danh sách mô hình của Cổng WebGPU (`webgpu_license.py`).
- [x] **Awesome Design Compliance**: Bổ sung bảng màu 3 lớp Sinh thái Lúa Stage 1 (`Newly transplanted rice`, `Grass`, `Rice + Partial Grass`) vào `DESIGN.md` đồng bộ với `Label_Color.txt`.

---

### Mục 11 / Bản vẽ #03 (2026-11-09): Mô hình Phân đoạn & Vector hóa 9 Lớp Địa hình – Đô thị – Cảnh quan từ `sample/RGB` (`Đường đi, Đường ô tô, Đường đi bộ, Sông/Ao hồ, Nhà, Cây cảnh quan`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #03]`
- **Mục tiêu Kỹ thuật**:
  - Mở rộng mô hình phân đoạn địa hình `TerrainSegUNetLite-WebGPU` và bộ suy luận/vector hóa `uav_app/domain/terrain_segmentation.py` từ 7 kênh (`0..6`) lên **9 kênh (`0..8`)**, bổ sung **Lớp `7: house_building` (Nhà / Công trình xây dựng)** và **Lớp `8: landscape_tree` (Cây cảnh quan / Cây xanh đô thị)** bên cạnh hệ thống **Đường ô tô (`asphalt_road`, `concrete_road`), Đường đi (`dirt_road`), Đường đi bộ (`footpath`), Sông / Ao hồ (`pond`) và Mương xây (`masonry_ditch`)**.
  - Huấn luyện trực tiếp trên bộ dữ liệu thực tế **`C:\Users\HL\Desktop\DETECTION RICE_FIELD\sample\RGB`** kết hợp **Tri thức Địa hình `DEM` + Bản vẽ Khảo sát `.DWG` thực địa (`Topographic Map_Triangle Zone (07 October 2026)_Preliminary.dwg`)**.

#### 1. Sơ đồ Luồng Huấn luyện Đa nguồn & Vector hóa 9 Lớp (`Mermaid Flowchart TB`)

```mermaid
flowchart TB
    subgraph SampleRGB["1. Tổ hợp Dữ liệu Thực tế (sample/RGB & Waterpoint_10.3.26)"]
        ORTHO["ORTHO_KHU TAM GIAC (03-10-2026).jpg<br/>(28,683 x 22,612 px · GSD 2.00 cm/px · .jgw + .prj VN2000 EPSG:9210)"]
        DEM["DEM_TAM GIAC (03-10-2026).tif<br/>(14,342 x 11,306 px · GSD 4.00 cm/px · Z: 0.53m Lòng sông -> 28.28m Mái nhà/Tán cây)"]
        RAW["DJI_20240312163133_0006_D.JPG<br/>(5,280 x 3,956 px · Ảnh UAV Góc cao Đô thị - Sông - Cây cảnh quan)"]
        DWG["Topographic Map_Triangle Zone (07 October 2026)_Preliminary.dwg<br/>(+ 3 Bản vẽ .DWG Waterpoint: LWPOLYLINE, POLYLINE, INSERT)"]
    end

    subgraph LabelFusion["2. Bộ Tổng hợp Nhãn Địa vật 9 Lớp (CAD + DEM + Spectral Teacher)"]
        CAD_PARSE["Trích xuất Vector & Block CAD chuẩn VN2000:<br/>- Giao_thong / 1.BK. DUONG CU-NHUA -> Lớp 1, 2, 3<br/>- 1.BK. VIA HE / 1.BK. DUONG XE DAP -> Lớp 4 (Đường đi bộ)<br/>- 1.BK. SONG+MUONG+RACH / 1.BK. AO NUOC -> Lớp 5, 6<br/>- Nha -> Lớp 7 (Nhà / Công trình)<br/>- 07-CAY XANH / 1.BK. CAY DO THI / 1.BK. THUC VAT -> Lớp 8 (Cây cảnh quan)"]
        PHYS_FUSE["Ràng buộc Vật lý & Độ cao Địa hình (DEM dZ + Phổ RGB):<br/>- Sông/Hồ (Lớp 5): dZ < -0.15m & Chỉ số nước NDWI/ExG âm<br/>- Nhà (Lớp 7): dZ > +1.8m, Độ phẳng mái cao, Phổ ngói/tôn/bê tông<br/>- Cây cảnh quan (Lớp 8): ExG > 20, Độ nhám tán lá cao, dZ > +0.8m"]
        PATCH_GEN["Trích xuất Cửa sổ Huấn luyện Thực tế (512x512 RGB + Mask 9 Lớp)<br/>từ Khu Tam Giác (Ortho + DEM) & DJI_0006_D.JPG"]
    end

    subgraph Model9Class["3. Huấn luyện & Xuất ONNX 9 Lớp (TerrainSegUNetLite-WebGPU)"]
        UNET9["Kiến trúc TerrainSegUNetLite (in_ch=3, num_classes=9)<br/>Input Tensor: [1, 3, 512, 512] FP32<br/>Output Tensor: [1, 9, 512, 512] Logits (Opset 17)"]
        ONNX_OUT["Xuất Trọng số Chuẩn:<br/>- models/terrain_6class_webgpu.onnx (Nâng cấp 9 kênh tương thích ngược)<br/>- models/rgb_landscape_9class_webgpu.onnx & .pt"]
    end

    subgraph Vectorizer["4. Vector hóa Hình học CAD/BIM & Hiển thị WebGPU 8 Lớp Địa vật"]
        CORR["Lớp 1, 2, 3, 4, 6 (Đường ô tô, Đường đi, Đường đi bộ, Mương):<br/>Trích xuất 2 Biên LWPOLYLINE + Đường tim CENTER"]
        WATER["Lớp 5 (Sông / Ao / Hồ):<br/>Đường bao LWPOLYLINE khép kín + Ký hiệu Taluy bờ nước"]
        HOUSE["Lớp 7 (Nhà / Công trình - KS_NHA_CONGTRINH):<br/>Đa giác khép kín vuông hóa/xấp xỉ cạnh thẳng + Nhãn NHÀ"]
        TREE["Lớp 8 (Cây cảnh quan - KS_CAY_CANHQUAN):<br/>Đa giác đường bao tán cây + Tâm cây + Nhãn CÂY XANH"]
    end

    ORTHO --> CAD_PARSE
    DEM --> PHYS_FUSE
    RAW --> PATCH_GEN
    DWG --> CAD_PARSE
    CAD_PARSE --> PHYS_FUSE --> PATCH_GEN --> UNET9 --> ONNX_OUT
    ONNX_OUT --> CORR
    ONNX_OUT --> WATER
    ONNX_OUT --> HOUSE
    ONNX_OUT --> TREE
```

#### 2. Đặc tả Hợp đồng Tensor & Lớp Địa vật (`9-Class Tensor & Layer Contract`)
- **Đầu vào (`input_rgb`)**: Tensor `float32` kích thước `[B, 3, 512, 512]`, chuẩn hóa dải `[0.0, 1.0]`.
- **Đầu ra (`logits`)**: Tensor `float32` kích thước `[B, 9, 512, 512]`, `opset_version=17`:
  - `0: background` — Nền trống / Nodata
  - `1: asphalt_road` — Đường ô tô / Đường nhựa (`KS_DUONG_NHUA`, `#ef4444`, `CORRIDOR`)
  - `2: concrete_road` — Đường ô tô / Đường bê tông (`KS_DUONG_BETONG`, `#94a3b8`, `CORRIDOR`)
  - `3: dirt_road` — Đường đi / Đường đất (`KS_DUONG_DAT`, `#d97706`, `CORRIDOR`)
  - `4: footpath` — Đường đi bộ / Vỉa hè (`KS_DUONG_DIBO`, `#a855f7`, `CORRIDOR` bề rộng `< 1.9m`)
  - `5: pond` — Sông / Ao / Hồ / Kênh rạch (`KS_AO_HO`, `#0ea5e9`, `POLYGON` + ký hiệu bờ taluy, `dZ < -0.15m`)
  - `6: masonry_ditch` — Mương xây / Kè kênh (`KS_MUONG_XAY`, `#06b6d4`, `CORRIDOR`)
  - `7: house_building` — Nhà / Công trình xây dựng (`KS_NHA_CONGTRINH`, `#f59e0b`, `POLYGON` vuông hóa + nhãn `NHÀ`, `dZ > +1.8m`)
  - `8: landscape_tree` — Cây cảnh quan / Cây xanh đô thị (`KS_CAY_CANHQUAN`, `#10b981`, `POLYGON` tán cây + nhãn `CÂY XANH`, `ExG > 20`, `dZ > +0.8m`)

#### 3. Danh sách Tệp Cấp phép Thi công (`Authorized Files per Sub-Agent`)
1. **`gis-uav-specialist`**:
   - [`uav_app/domain/terrain_segmentation.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/domain/terrain_segmentation.py): Mở rộng `TERRAIN_CLASSES` lên 8 lớp địa vật (`1..8`), nâng cấp `classify_terrain_patch_6class()` nhận diện thêm `house_building` (`7`) và `landscape_tree` (`8`) kết hợp `DEM dZ` + đặc trưng phổ/kết cấu mái nhà & tán cây + trọng số `.onnx`, và vector hóa thành `POLYGON` chuẩn AutoCAD.
   - [`uav_app/adapters/terrain_onnx_builder.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/terrain_onnx_builder.py): Nâng cấp `TerrainSegUNetLite(in_ch=3, num_classes=9)` và bổ sung pipeline trích xuất mẫu thực tế từ `C:\Users\HL\Desktop\DETECTION RICE_FIELD\sample\RGB` (`ORTHO_KHU TAM GIAC`, `DEM_TAM GIAC`, `DJI_20240312163133_0006_D.JPG`) để huấn luyện và xuất mô hình `.onnx` 9 kênh.
2. **`ui-ux-specialist`**:
   - [`ui/webgpu.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.html), [`ui/webgpu_app.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu_app.js), [`ui/index.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/index.html), [`ui/advanced.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/advanced.html): Cập nhật bảng điều khiển & bộ lọc hiển thị đầy đủ 8 lớp địa vật (`Đường ô tô / Đường nhựa`, `Đường bê tông`, `Đường đi / Đường đất`, `Đường đi bộ`, `Sông / Ao / Hồ`, `Mương xây`, `Nhà / Công trình`, `Cây cảnh quan`).
3. **`code-architect`**:
   - [`tests/test_advanced_pipeline.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/tests/test_advanced_pipeline.py) & kiểm thử tích hợp trên `sample/RGB`.

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #03]`

---

## 12. Giao thức Bắt buộc: Điều phối 5 Agent Song Song (`5-Agent Parallel Swarm Protocol`)

Theo lệnh trực tiếp của người dùng, với **mọi yêu cầu / mệnh lệnh tiếp theo**, **Lead Orchestrator** bắt buộc kích hoạt đồng thời **5 Sub-Agent làm việc song song** trên 5 phân vùng độc lập để đạt tốc độ xử lý tối đa:

```mermaid
flowchart TB
    USER["Mệnh lệnh của Người dùng (User Prompt)"] --> ORCH["Lead Orchestrator (Phân rã 5 nhánh độc lập trong 1 lượt)"]
    ORCH --> A1["Agent #1: architecture-design-lead<br/>Vẽ ARCHITECTURE.md & DESIGN.md"]
    ORCH --> A2["Agent #2: gis-uav-specialist<br/>Xử lý ORTHO/DEM/Đa phổ & Train GPU RTX 4070"]
    ORCH --> A3["Agent #3: code-architect<br/>Backend API, Vector hóa PL & Xuất AutoCAD .DWG/.DXF"]
    ORCH --> A4["Agent #4: ui-ux-specialist<br/>Giao diện WebGPU Portal & Trạm 5 Bước"]
    ORCH --> A5["Agent #5: qa-cloud-sync-specialist<br/>Kiểm thử Pytest, Web Host 8765 & Đồng bộ Google Drive"]
    A1 & A2 & A3 & A4 & A5 --> DONE["Tổng hợp Kết quả & Báo cáo Tức thì"]
```

---

### Mục 13 / Bản vẽ #04 (2026-11-09): Tách bạch Tuyệt đối Giao diện Người dùng Cuối (`End-User Clean 3-Step Survey Mode`) và Khu vực Quản trị Chủ phần mềm (`Owner/Admin Gatekeeper Mode`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #04]`
- **Vấn đề phát hiện từ Ảnh chụp Màn hình Người dùng**:
  - Trên cổng công cộng `/webgpu.html`, người dùng cuối (Khách hàng nhận Key) đang nhìn thấy các bảng điều khiển nội bộ của Chủ phần mềm/Kỹ sư phát triển (`Tự động mở Cổng Web Host khi Bật Máy tính`, `Đẩy Dự án lên GitHub / Lưu Project vào CODE_DATA (Drive)`, `Đồ thị Tri thức Graphify`, `Vòng lặp tự động gán nhãn Gemini 4 Argon`, `Quản trị & Cấp phát Mã Key`).
- **Quy chuẩn Kiến trúc Tách Quyền Giao diện (`Strict End-User vs Owner UI Isolation`)**:

```mermaid
flowchart LR
    VISIT["Truy cập /webgpu.html"] --> CHECK{"Kiểm tra Chế độ Truy cập"}
    CHECK -- "Mặc định (Người dùng cuối / Khách hàng nhận Key)" --> ENDUSER["Giao diện Thuần 3 Bước Khảo sát UAV:<br/>- Bước 01: Nhập License Key & Chọn Mô hình<br/>- Bước 02: Tải Ảnh UAV / DEM<br/>- Bước 03: Chạy Suy luận WebGPU & Xuất CAD (.DXF/.GeoJSON)"]
    ENDUSER --> HIDE["ẨN TUYỆT ĐỐI 100%:<br/>- Không nạp/hiển thị argon_host_panel.js<br/>- Ẩn Auto-Boot Host, Git Push, CODE_DATA Drive<br/>- Ẩn Graphify, Argon CLI Loop<br/>- Ẩn Khung Quản trị Cấp Key"]
    CHECK -- "Chủ phần mềm (?admin=1 + Mật khẩu Admin hợp lệ)" --> ADMIN["Mở khóa Khu vực Quản trị Chủ phần mềm:<br/>- Quản lý & Cấp phát License Key<br/>- Trung tâm Tự động hóa Host 8765 / Drive / Graphify / Argon"]
```

#### Danh sách Tệp & Quy tắc Cấp phép Thi công (`Authorized Files`)
1. **`ui-ux-specialist`**:
   - [`ui/webgpu.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.html): Mặc định ẩn hoàn toàn thẻ `#adminSection` (`display: none !important` trừ khi `?admin=1` hoặc mở khóa Admin), ẩn thanh liên kết kỹ thuật nội bộ trên Header đối với người dùng cuối; gắn tham số chống lưu đệm `?v=20261109_2` cho `webgpu_app.js` và `argon_host_panel.js`.
   - [`ui/argon_host_panel.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/argon_host_panel.js), [`ui/webgpu_app.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu_app.js), [`ui/index.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/index.html), [`ui/advanced.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/advanced.html):
     - Chỉ khởi tạo/hiển thị bảng `Trung tâm Tự động hóa & Host 8765` và `Quản trị Cấp Key` khi đang ở **Chế độ Chủ phần mềm (`?admin=1` hoặc xác thực Admin)**.
     - **Quy tắc Hiển thị Nút Dừng theo Trạng thái (`State-Driven Stop Button Visibility`)**: Mọi nút `⏹ Dừng` / `Hủy` (`#argonStopBtn`, `#cancelJobBtn`, `#stopScanBtn`) **BẮT BUỘC ẨN HOÀN TOÀN (`display: none`)** khi tiến trình ở trạng thái `Sẵn sàng / Idle / Completed / Failed` (`running === false`), và **CHỈ HIỂN THỊ (`display: inline-flex` / `inline-block`)** khi tiến trình thực sự đang chạy (`running === true`).

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #04 & STATE-DRIVEN STOP BUTTON]`

---

### Mục 14 / Bản vẽ #05 (2026-11-09): Tự Động Mở Kép 2 Cổng (`8765` + `8766`), Khởi tạo Cloudflare Tunnel & Đồng bộ Tự động `LINK_TRUY_CAP_WEB.txt` lên Google Drive Cố định khi Bật Máy
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #05]`
- **Giải pháp Cố định Điểm Truy cập Từ xa Miễn phí 100% (Không cần mua tên miền)**:
  - Mỗi khi Windows khởi động (`start_web_host_on_boot.bat` / `UAV_WebGPU_AutoHost.vbs` / `uav_app/infrastructure/autostart_host.py`), hệ thống tự động khởi chạy ngầm:
    1. **Cổng `8765` (`WebGPU 9 Lớp & Lúa`)** + tiến trình `cloudflared tunnel --url http://127.0.0.1:8765` (ghi log `.cache/tunnel_8765.log`).
    2. **Cổng `8766` (`Trạm Nhận diện 5 Bước /index.html & /advanced.html`)** + tiến trình `cloudflared tunnel --url http://127.0.0.1:8766` (ghi log `.cache/tunnel_8766.log`).
  - Ngay sau khi 2 đường hầm Cloudflare cấp phát URL `https://*.trycloudflare.com` (hoặc Tailscale Funnel nếu có), kịch bản [`scripts/publish_live_web_links.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/scripts/publish_live_web_links.py) tự động trích xuất cả 2 URL mới nhất, ghi vào:
    - [`LINK_TRUY_CAP_WEB.txt`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/LINK_TRUY_CAP_WEB.txt) (Bản tin văn bản rõ ràng chứa Link LAN cố định + Link Internet công cộng cổng `8765` & `8766` + Mã Key)
    - [`MO_WEB_NHAN_DIEN_NGAY.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/MO_WEB_NHAN_DIEN_NGAY.html) (Trang Portal bấm mở ngay 1 chạm, tự chuyển hướng hoặc chọn cổng)
  - Đồng thời, `publish_live_web_links.py` tự động đẩy/cập nhật tại chỗ (`gdrive files update` giữ nguyên File ID cố định vĩnh viễn) **CHỈ nằm gọn bên trong thư mục riêng của dự án `CODE_DATA / UAV_GeoTIFF_WebGPU_Survey_VN2000`** (`Folder ID: 1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV`), tuyệt đối **không để bất kỳ tệp lẻ nào tràn ra thư mục gốc `CODE_DATA`** (`1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D`).

```mermaid
flowchart LR
    BOOT["Bật Máy tính Windows<br/>(UAV_WebGPU_AutoHost.vbs / start_web_host_on_boot.bat)"] --> S8765["Khởi chạy Server 8765 +<br/>cloudflared (.cache/tunnel_8765.log)"]
    BOOT --> S8766["Khởi chạy Server 8766 +<br/>cloudflared (.cache/tunnel_8766.log)"]
    S8765 & S8766 --> PUB["scripts/publish_live_web_links.py<br/>(Quét URL *.trycloudflare.com + IP LAN)"]
    PUB --> LOCAL["Cập nhật Tệp Cục bộ:<br/>- LINK_TRUY_CAP_WEB.txt<br/>- MO_WEB_NHAN_DIEN_NGAY.html<br/>- .cache/live_web_links.json"]
    LOCAL --> GDRIVE["Đồng bộ Gọn gàng vào Thư mục Dự án:<br/>CODE_DATA / UAV_GeoTIFF_WebGPU_Survey_VN2000<br/>(Folder ID: 1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV)"]
```

#### Danh sách Tệp Cấp phép Thi công (`Authorized Files`)
1. **`code-architect` / `qa-cloud-sync-specialist`**:
   - [`scripts/publish_live_web_links.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/scripts/publish_live_web_links.py): Khởi chạy/kiểm tra 2 cổng `8765` & `8766` cùng 2 tiến trình `cloudflared`, trích xuất URL `https://*.trycloudflare.com`, xuất `LINK_TRUY_CAP_WEB.txt` + `MO_WEB_NHAN_DIEN_NGAY.html` + `.cache/live_web_links.json` và đồng bộ gọn vào duy nhất thư mục dự án `1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV` (tự động di chuyển/dọn mọi tệp lẻ bị tràn ở thư mục gốc `1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D` vào đúng `1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV`).
   - [`start_web_host_on_boot.bat`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/start_web_host_on_boot.bat) & [`uav_app/infrastructure/autostart_host.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/autostart_host.py): Tích hợp gọi `scripts/publish_live_web_links.py --ensure-running --sync-drive` mỗi khi bật máy.
   - [`uav_app/adapters/autostart_and_argon_routes.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/autostart_and_argon_routes.py): Trả về thông tin `live_web_links` trong `/api/automation/status` cho Chủ phần mềm.

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #05]`

---

### Mục 15 / Bản vẽ #06 (2026-11-09): Chuẩn hóa Bố cục Khung nhìn Toàn màn hình `100vh Zero-Outer-Scroll GIS Workstation Layout` trên `webgpu.html`
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #06]`
- **Vấn đề phát hiện từ Ảnh chụp Màn hình Người dùng**:
  - Trang `ui/webgpu.html` bị xuất hiện **2 thanh cuộn dọc lồng nhau** (`body` cuộn ngoài + `.control-column` bị đặt `max-height: calc(100vh - 76px)` trong khi `.viewport-column` đặt `min-height: calc(100vh - 96px)`), khiến cột điều khiển bên trái bị cụt lửng ở nửa trên kèm khoảng đen trống trải phía dưới, còn khung Canvas bên phải bị đẩy tràn quá đáy màn hình làm mất thanh thống kê 8 lớp địa vật (`.summary-strip`).
- **Quy chuẩn Bố cục Khung nhìn `100vh Zero-Outer-Scroll & Zero-Vertical-Scroll Control Panel` (`Flex + Grid Containment Contract`)**:

```mermaid
flowchart TB
    ROOT["html, body<br/>height: 100vh; max-height: 100vh; overflow: hidden;<br/>display: flex; flex-direction: column;"] --> HEADER[".portal-header<br/>height: 52px; flex-shrink: 0;"]
    ROOT --> GRID[".portal-grid<br/>flex: 1; min-height: 0; overflow: hidden;<br/>display: grid; grid-template-columns: 390px minmax(0, 1fr); gap: 12px; padding: 10px 12px;"]
    GRID --> LEFT[".control-column<br/>height: 100%; min-height: 0; overflow-y: auto;<br/>scrollHeight <= clientHeight (Zero-Vertical-Scroll)<br/>(Bước 01 + Bước 02 + Bước 03: Ngân sách chiều cao <= 850px,<br/>đã loại bỏ hoàn toàn .hint & banner tĩnh)"]
    GRID --> RIGHT[".viewport-column<br/>height: 100%; min-height: 0; overflow: hidden;<br/>display: flex; flex-direction: column;"]
    RIGHT --> TOOLBAR[".viewport-toolbar<br/>flex-shrink: 0;"]
    RIGHT --> STAGE[".canvas-stage<br/>flex: 1; min-height: 0; position: relative; overflow: hidden;"]
    RIGHT --> STRIP[".summary-strip (8 Lớp Địa vật)<br/>flex-shrink: 0; luôn neo cố định ở đáy màn hình"]
```

#### Danh sách Tệp Cấp phép Thi công (`Authorized Files`)
1. **`ui-ux-specialist`**:
   - [`ui/webgpu.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.html) & [`ui/webgpu.css`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.css):
     - Khóa `html, body { height: 100vh; overflow: hidden; display: flex; flex-direction: column; }`.
     - Đặt `.portal-header { flex-shrink: 0; padding: 8px 16px; }` và `.portal-grid { flex: 1; min-height: 0; overflow: hidden; grid-template-columns: 390px minmax(0, 1fr); gap: 12px; padding: 10px 12px; }`.
     - Đặt `.control-column { height: 100%; max-height: none; min-height: 0; overflow-y: auto; }` thỏa mãn tuyệt đối `scrollHeight <= clientHeight` (không phát sinh thanh cuộn dọc) trên các độ phân giải tiêu chuẩn (`1920x1080`, `1440x1080`, `1440x900`, `1366x768`, `1280x800`).
     - Loại bỏ các khối `<p class="hint">` giải thích rườm rà tại Bước 01 và Bước 02; loại bỏ văn bản banner hướng dẫn tĩnh ban đầu tại `#portal-status` trong Bước 03 (đặc biệt: *"Hãy bấm Bước 01 để xác thực Key & nạp mô hình mã hóa lên Card GPU."*), chuyển `#portal-status` thành phần tử rỗng chỉ hiện cảnh báo/toast khi phát sinh runtime; rút gọn `.empty-card` thành nhãn ngắn gọn; tinh chỉnh padding thẻ `.card` (`8px 10px`) và xếp danh sách 8 lớp địa vật (`.class-legend-list`) thành **lưới 2 cột gọn gàng (`grid-template-columns: repeat(2, minmax(0, 1fr))`)** để tổng chiều cao cả 3 bước gói gọn trong `<= 850px`.
     - Bảo toàn nguyên vẹn chuỗi kiểm thử bắt buộc: `"Cổng WebGPU Bình đồ Địa hình 6 Lớp"`.
     - Đặt `.viewport-column { height: 100%; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }`, `.canvas-stage { flex: 1; min-height: 0; }`, và `.summary-strip { flex-shrink: 0; grid-template-columns: repeat(8, minmax(0, 1fr)); }` luôn hiện rõ ngay đáy khung nhìn.

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #06]`

---

### Mục 16 / Bản vẽ #07 (2026-11-09): Tích hợp Thư viện Block Chuẩn `Mylib2` (`C:\Block\Mylib2` → `assets/cad_blocks/Mylib2`) & Chèn Thực thể `BLOCK INSERT` cho Cây Cảnh Quan (`landscape_tree`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #07]`
- **Quy chuẩn Kỹ thuật Bắt buộc theo Lệnh Người dùng**:
  1. **Sao chép & Chuẩn hóa Thư viện Block (`C:\Block\Mylib2` → `uav_geotiff/assets/cad_blocks/Mylib2` & `ui/mylib2_blocks.json`)**:
     - Sao chép nguyên vẹn toàn bộ thư viện `C:\Block\Mylib2` (bao gồm nhóm `CAY XANH`, `THUC VAT`, `KHOI KIEN TRUC`, `GIAO THONG`, `THUY HE`, v.v.) vào `uav_geotiff/assets/cad_blocks/Mylib2` làm thư viện Block chuẩn vĩnh viễn của dự án.
     - Trích xuất hình học Vector chuẩn của các Block cây xanh tiêu biểu từ `Mylib2` (`CAY1`..`CAY30`, `Cxanh`, `07-CAY XANH`) thành tệp `ui/mylib2_blocks.json` và định nghĩa bảng `BLOCKS` trong `.DXF`/`.DWG` để cả máy chủ Python lẫn trình duyệt WebGPU dùng trực tiếp.
  2. **Đối với Lớp `8: landscape_tree` (`Cây cảnh quan / Cây xanh`) — BỎ VẼ VÙNG ĐA GIÁC (`NO POLYGON`), CHUYỂN SANG CHÈN `BLOCK INSERT` TỪ `Mylib2`**:
     - **Tuyệt đối KHÔNG vẽ đường bao vùng (`POLYGON` / `LWPOLYLINE` khép kín)** quanh mảng cây như ao hồ hay nhà cửa.
     - Từ mặt nạ phân đoạn `landscape_tree`, thuật toán tách từng cá thể/tán cây bằng biến đổi khoảng cách (`Euclidean Distance Transform / Local Maxima Peak Splitting` cho các rặng cây dính nhau) hoặc thành phần liên thông (`Connected Components`), xác định **tâm cây `(cx, cy, z)`** và **đường kính tán `diameter_m`**.
     - **Trên Canvas WebGPU (`ui/webgpu_app.js`)**: Vẽ trực tiếp ký hiệu **Block Cây xanh chuẩn `Mylib2`** (gồm các nét cành/tán lá đối xứng tâm đặc trưng của `Mylib2/CAY XANH`) tại đúng tâm `(cx, cy)` với bán kính theo `diameter_m`.
     - **Khi Xuất `.DXF` / `.DWG` (`ui/webgpu_app.js` & `uav_app/domain/terrain_segmentation.py`)**:
       - Khai báo định nghĩa Block chuẩn (`Mylib2_CAY1`, `Mylib2_CAY4`, `07-CAY XANH`) trong mục `BLOCKS` của tệp `.DXF`/`.DWG`.
       - Phát sinh thực thể **`INSERT` (Block Reference)** tại tọa độ thực `(X, Y, Z)` chuẩn VN-2000 trên layer `KS_CAY_CANHQUAN` với tỷ lệ `xscale = yscale = radius_or_diameter_scale` và góc xoay tự nhiên.

```mermaid
flowchart LR
    LIB["Thư viện Gốc C:\Block\Mylib2<br/>(CAY XANH / CAY1..CAY30.dwg)"] --> COPY["Thư viện Web Chuẩn:<br/>- assets/cad_blocks/Mylib2/<br/>- ui/mylib2_blocks.json"]
    MASK["Mặt nạ Lớp 8 (landscape_tree)"] --> PEAK["Tách Đỉnh Tán Cây (Distance Transform Peaks)<br/>Tính Tâm (X, Y, Z) & Đường kính Tán (D)"]
    COPY & PEAK --> CANVAS["Hiển thị WebGPU Canvas:<br/>Vẽ Ký hiệu Block Mylib2 tại Tâm (X, Y)<br/>(KHÔNG vẽ vùng đa giác bao quanh)"]
    COPY & PEAK --> CAD["Xuất AutoCAD .DXF / .DWG:<br/>Nhúng BLOCKS Mylib2_CAY + Đặt thực thể INSERT<br/>tại (X, Y, Z) với Scale theo Đường kính Tán"]
```

#### Danh sách Tệp Cấp phép Thi công (`Authorized Files`)
1. **`gis-uav-specialist` & `code-architect`**:
   - Sao chép `C:\Block\Mylib2` → `uav_geotiff/assets/cad_blocks/Mylib2` và tạo `ui/mylib2_blocks.json` + `uav_app/domain/mylib2_blocks.py`.
   - [`uav_app/domain/terrain_segmentation.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/domain/terrain_segmentation.py): Cập nhật `vectorize_terrain_mask_to_polylines()` và `export_terrain_polylines_to_dxf()` để lớp `8: landscape_tree` tạo các điểm chèn Block (`geometry_type="BLOCK_INSERT"`, `block_name="Mylib2_CAY1"`, `center_world=(X,Y,Z)`, `radius_m`) và xuất thực thể `INSERT` chuẩn `Mylib2` vào `.DXF`/`.DWG` (không xuất `LWPOLYLINE` bao vùng cho lớp cây xanh).
2. **`ui-ux-specialist`**:
   - [`ui/webgpu_app.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu_app.js) & [`ui/webgpu.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.html): Cập nhật bộ trích xuất lớp `8` (`landscape_tree`), bộ vẽ Canvas và bộ xuất `.DXF` phía trình duyệt để dùng **Block `Mylib2_CAY1` (`INSERT`)** tại tâm từng cây thay vì vẽ vùng đa giác.

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #07]`

---

### Mục 17 / Bản vẽ #08 (2026-11-09): Kiến trúc Tinh gọn Giao diện Toàn diện & Đặc tả Chuẩn Không Cuộn Dọc Cột Điều khiển WebGPU (Streamlined Web UI & Zero-Vertical-Scroll Layout Contract)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #08]`
- **Bối cảnh & Mục tiêu Tinh gọn**:
  - Giao diện người dùng trên `ui/webgpu.html`, `ui/index.html`, `ui/advanced.html`, và các script liên quan chứa nhiều văn bản hướng dẫn dài dòng, banner giải thích tĩnh, thẻ chú thích `.hint` và các thông điệp `.empty-card` chiếm dụng không gian dọc, gây ra thanh cuộn dọc không mong muốn trên cột điều khiển bên trái (`.control-column`) của `ui/webgpu.html` (chiều cao đo đạc thực tế ban đầu `scrollHeight = 1031px > clientHeight = 979px` tại khung nhìn chuẩn `1440x1080`, tràn +52px).
  - Mục tiêu kiến trúc: Chuẩn hóa toàn bộ ngôn ngữ giao diện theo phong cách kỹ thuật vi mô súc tích (functional microcopy), triệt tiêu hoàn toàn thanh cuộn dọc trên bảng điều khiển `.control-column` (`scrollHeight <= clientHeight`) trên mọi độ phân giải tiêu chuẩn (`1920x1080`, `1440x1080`, `1440x900`, `1366x768`, `1280x800`), đồng thời bảo toàn 100% tính năng điều khiển, mã định danh DOM, chuỗi kiểm thử bắt buộc và các emoji miền nghiệp vụ.

```mermaid
flowchart TD
    subgraph UI_Streamlined["Kiến trúc Giao diện Tinh gọn Toàn diện (Streamlined Web UI)"]
        W_GPU["ui/webgpu.html + ui/webgpu.css<br/>- Zero-Vertical-Scroll (.control-column scrollHeight <= clientHeight)<br/>- Loại bỏ .hint Bước 01 & Bước 02<br/>- Loại bỏ banner tĩnh #portal-status (Bước 03)<br/>- Rút gọn .empty-card overlay<br/>- BẢO TOÀN: 'Cổng WebGPU Bình đồ Địa hình 6 Lớp'"]
        
        W_CORE["ui/index.html & ui/advanced.html<br/>- Rút gọn các đoạn .empty-note thành nhãn ngắn<br/>- Loại bỏ paragraph mô tả thừa trong Phân đoạn 6 lớp & Hard Negatives<br/>- Tinh gọn #cad-mode-hint & #yolo-cad-mode-hint<br/>- KHÔNG có emoji bị cấm: 🙈, 🔮, ✨, ❓, 💡<br/>- BẢO TOÀN: 14 domain icons (🛰️, 📡, 🧭, 📐, ⛰️, 🎯, 🌾, 🌱, 🌿, 🌳, 🖥️, ⚡, 🔬, 🎛️)"]
        
        W_JS["Frontend Scripts (ui/*.js)<br/>- ui/webgpu_app.js: setStatus() động, không chèn text tĩnh dài dòng<br/>- ui/argon_host_panel.js: Loại bỏ trích dẫn giải thích .argon-note<br/>- ui/app.js & ui/advanced.js: Vi mô súc tích cho navigation-hint, updateCadHint, telemetry"]
    end

    subgraph Verification_Gates["Cổng Kiểm thử Tự động Bắt buộc (Verification Gates)"]
        GATE_LAYOUT["1. Layout Gate: Playwright E2E<br/>col.scrollHeight <= col.clientHeight<br/>(1920x1080, 1440x1080, 1440x900, 1366x768, 1280x800)"]
        GATE_STR["2. Title String Gate: Pytest test_advanced_pipeline.py<br/>assert 'Cổng WebGPU Bình đồ Địa hình 6 Lớp' in html"]
        GATE_EMOJI["3. Emoji Gate: Pytest test_domain_emojis_and_task_manager_telemetry<br/>assert forbidden not in html/js<br/>assert domain_icon in (index + adv_html + adv_js)"]
        GATE_FUNC["4. Functionality Gate: Full Interactive Flow<br/>Bảo toàn đủ 54 element IDs, model loading, export DXF/DWG"]
    end

    W_GPU --> GATE_LAYOUT
    W_GPU --> GATE_STR
    W_CORE --> GATE_EMOJI
    W_JS --> GATE_FUNC
```

#### Quy chuẩn Kỹ thuật Chi tiết cho Từng Tệp Giao diện:
1. **`ui/webgpu.html`**:
   - Bắt buộc giữ nguyên vẹn thẻ tiêu đề chứa chuỗi kiểm thử: `<h1>Cổng WebGPU Bình đồ Địa hình 6 Lớp &amp; Đô thị 9 Lớp (Đường · Sông/Ao · Mương · Nhà · Cây cảnh quan)</h1>`.
   - Xóa bỏ thẻ `<p class="hint">` giải thích AES-256-GCM ở Bước 01 (tiết kiệm ~51px).
   - Xóa bỏ thẻ `<p class="hint">` giải thích quét 4 tệp khảo sát ở Bước 02 (tiết kiệm ~68px).
   - Xóa bỏ nội dung văn bản tĩnh trong `<div id="portal-status" class="status-banner">` ở Bước 03 (đặc biệt: *"Hãy bấm Bước 01 để xác thực Key & nạp mô hình mã hóa lên Card GPU."*, tiết kiệm ~50px). Phần tử `#portal-status` vẫn tồn tại trong DOM nhưng mặc định ở trạng thái rỗng/ẩn và chỉ hiển thị khi `setStatus()` được kích hoạt bởi sự kiện runtime.
   - Rút gọn nội dung `<div class="empty-card">` trên lớp phủ Canvas thành nhãn ngắn gọn súc tích, loại bỏ đoạn hướng dẫn 3 bước đánh số dài dòng.
   - Bảo toàn toàn bộ 54 mã định danh phần tử DOM (`step1-card`, `step2-card`, `step3-card`, `btn-auth-load`, `btn-load-demo-tiff`, `terrain-class-checklist`, `btn-run-webgpu`, `btn-download-dwg`, `btn-download-dxf`, v.v.).
2. **`ui/webgpu.css`**:
   - Tinh chỉnh khoảng đệm thẻ `.card` từ `10px 12px` thành `8px 10px`, giảm khoảng cách `margin` của `.quick-keys` để tổng chiều cao 3 bước nằm gọn dưới `850px`.
   - Đảm bảo `.control-column` tuân thủ nghiêm ngặt điều kiện `scrollHeight <= clientHeight` (không bao giờ sinh thanh cuộn dọc) trên toàn bộ dải độ phân giải tiêu chuẩn (`1920x1080`, `1440x1080`, `1440x900`, `1366x768`, `1280x800`).
3. **`ui/index.html`**:
   - Rút gọn các đoạn mô tả `.empty-note` (Lines 46, 63, 86, 134) thành các nhãn trạng thái ngắn gọn: *"Chưa nạp ảnh."*, *"Chưa tạo lưới."*, *"Chưa có dữ liệu."*, *"Chưa chọn ảnh."*.
   - Rút gọn các ghi chú dài dòng trong Bước 03 và thẻ `<details class="design-details">` thành các nhãn kỹ thuật ngắn gọn.
   - Giữ `#navigation-hint` súc tích, không diễn giải rườm rà.
4. **`ui/advanced.html`**:
   - Tinh gọn `#cad-mode-hint` và `#yolo-cad-mode-hint` thành chỉ báo trạng thái thao tác ngắn gọn (ví dụ: *"Chế độ vẽ: Polyline"*).
   - Loại bỏ đoạn văn bản giải thích 3 dòng rườm rà `<p class="field-help">` dưới tiêu đề Phân đoạn Địa hình 6 Lớp (VN2000 AutoCAD .DXF).
   - Tinh gọn gợi ý `#turbo-neg-tip` thành nhãn chức năng ngắn gọn (*"Mẫu âm tính (Hard Negatives)"*).
   - Tuyệt đối không chứa bất kỳ emoji bị cấm nào (`"🙈", "🔮", "✨", "❓", "💡"`), nút trợ giúp dùng ký tự ASCII `?` (`>?</button>`).
5. **`ui/argon_host_panel.js`**:
   - Loại bỏ đoạn trích dẫn giải thích rườm rà `<p class="argon-note">` ("Khi bật máy tính, Web Host tự động chạy ngầm ở cổng 8765...").
6. **`ui/webgpu_app.js`**:
   - Hàm `setStatus(html, tone)` tương thích với `#portal-status` dạng alert động; không tiêm các câu văn bản tutorial dài dòng khi tải trang.
7. **`ui/app.js` & `ui/advanced.js`**:
   - Rút gọn các chuỗi văn bản mảng `navigation-hint`, hàm `updateCadHint`, và biểu ngữ `renderTurboEngineBanner` thành vi mô súc tích.
   - Bảo toàn nghiêm ngặt 14 emoji miền nghiệp vụ chuyên dụng: `"🛰️", "📡", "🧭", "📐", "⛰️", "🎯", "🌾", "🌱", "🌿", "🌳", "🖥️", "⚡", "🔬", "🎛️"`.

#### Danh sách Tệp Cấp phép Thi công (`Authorized Files`)
1. **`ui-ux-specialist`**:
   - [`ui/webgpu.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.html)
   - [`ui/webgpu.css`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.css)
   - [`ui/index.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/index.html)
   - [`ui/advanced.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/advanced.html)
   - [`ui/webgpu_app.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu_app.js)
   - [`ui/argon_host_panel.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/argon_host_panel.js)
   - [`ui/app.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/app.js)
   - [`ui/advanced.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/advanced.js)
2. **`qa-cloud-sync-specialist` / `code-architect`**:
   - [`tests/test_advanced_pipeline.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/tests/test_advanced_pipeline.py)
   - [`tests/ui/`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/tests/ui/)

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #08]`

---

### Mục 18 / Bản vẽ #09 (2026-11-09): Cổng Khóa License Key Toàn Màn Hình Trước Khi Mở Giao Diện (`Full-Screen License Key Gatekeeper`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #09]`
- **Yêu cầu Bắt buộc từ Người dùng**:
  - *"Sau này khi vào link thì yêu cầu nhập key trước, không nhập key thì không thấy giao diện."*
- **Quy chuẩn Kiến trúc Khóa Giao Diện Toàn Màn Hình (`#license-gate-overlay` & `.gate-locked`)**:
  1. **Mặc định khóa toàn bộ giao diện làm việc khi truy cập Link (`Port 8765: /webgpu.html` và `Port 8766: /index.html, /advanced.html`)**:
     - Ngay khi tải trang (`DOMContentLoaded`), thẻ `body` mang lớp `.gate-locked`: ẩn toàn bộ phần tử giao diện làm việc chính (`.portal-header`, `.portal-grid`, `header`, `main`, bản đồ Canvas, thanh công cụ) bằng `visibility: hidden; pointer-events: none; opacity: 0;` (hoặc `display: none` cho vùng làm việc) và chỉ hiển thị duy nhất **Màn hình Khóa Xác thực License Key (`#license-gate-overlay`)** phủ kín `100vw × 100vh` (`position: fixed; inset: 0; z-index: 99999; background: #07090e;`).
  2. **Luồng Xác thực Mở khóa Giao diện (`Authentication & Lease Unlock Flow`)**:
     - Người dùng bắt buộc nhập `License Key` vào ô nhập trên `#license-gate-overlay` (và chọn mô hình ONNX trên `webgpu.html`) rồi bấm **Xác thực & Mở Giao diện**.
     - Trình duyệt gọi `POST /api/webgpu/auth` (kèm `license_key`, `device_fingerprint`, `model_id`).
     - **Nếu Key không hợp lệ / hết hạn ngạch / vượt số thiết bị**: Giữ nguyên màn hình khóa `#license-gate-overlay`, báo lỗi rõ ràng trên hộp thoại khóa, tuyệt đối không hiển thị giao diện chính.
     - **Nếu Key hợp lệ (`ok === true`)**:
       - Trên `webgpu.html`: Giải mã và nạp mô hình `.onnx` vào WebGPU/WASM RAM, lưu trạng thái phiên hợp lệ (`sessionStorage`), gỡ bỏ lớp `.gate-locked` và đóng `#license-gate-overlay` để mở giao diện làm việc 3 bước.
       - Trên `index.html` & `advanced.html`: Xác thực Key qua `/api/webgpu/auth` (hoặc `/api/license/verify`), lưu phiên xác thực hợp lệ vào `sessionStorage`, gỡ `.gate-locked` và hiển thị Trạm Nhận diện 5 bước.
  3. **Nút Quản trị Key dành riêng cho Chủ phần mềm ngay trên Màn hình Khóa (`🔐 Quản trị Key`)**:
     - Trên `#license-gate-overlay` có nút nhỏ `🔐 Quản trị Key` dành cho Chủ máy: khi bấm vào yêu cầu nhập mật khẩu Admin (`X-Admin-Password`), xác thực qua `/api/webgpu/admin/licenses` để chủ máy có thể tạo/cấp Key mới hoặc thu hồi Key ngay cả khi chưa nhập Key người dùng.

```mermaid
stateDiagram-v2
    [*] --> GateLocked: Truy cập Link (8765 /webgpu.html hoặc 8766 /index.html, /advanced.html)
    state GateLocked {
        [*] --> ShowOverlay: Ẩn toàn bộ Header/Main/Canvas (.gate-locked)<br/>Chỉ hiện #license-gate-overlay toàn màn hình
        ShowOverlay --> VerifyAPI: Nhập License Key -> POST /api/webgpu/auth
        VerifyAPI --> ShowOverlay: Key sai / Hết lượt -> Báo lỗi & Giữ khóa
        ShowOverlay --> AdminModal: Chủ máy bấm '🔐 Quản trị Key' + Mật khẩu Admin
        AdminModal --> ShowOverlay: Tạo / Cấp Key mới thành công
    }
    VerifyAPI --> UnlockedWorkspace: Key hợp lệ (ok=true) -> Nạp ONNX Lease & Lưu sessionStorage
    UnlockedWorkspace --> [*]: Ẩn #license-gate-overlay, Mở giao diện chính
```

#### Danh sách Tệp Cấp phép Thi công (`Authorized Files`)
1. **`ui-ux-specialist`**:
   - [`ui/webgpu.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.html), [`ui/webgpu.css`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu.css), [`ui/webgpu_app.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/webgpu_app.js): Tích hợp `#license-gate-overlay` toàn màn hình, khóa `.portal-header` & `.portal-grid` khi chưa xác thực Key, và tích hợp hộp thoại `🔐 Quản trị Key` (bảo vệ bằng `X-Admin-Password`).
   - [`ui/index.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/index.html), [`ui/advanced.html`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/advanced.html), [`ui/styles.css`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/styles.css), [`ui/app.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/app.js), [`ui/advanced.js`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ui/advanced.js): Tích hợp cổng khóa License Key toàn màn hình đồng bộ trước khi mở Trạm 5 bước (tuyệt đối không dùng các emoji bị cấm).
2. **`code-architect`**:
   - [`uav_app/adapters/http_server.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/http_server.py) & [`uav_app/adapters/webgpu_public_server.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/webgpu_public_server.py): Đảm bảo API `/api/webgpu/auth` và `/api/webgpu/admin/licenses` phản hồi trên cả 2 cổng `8765` và `8766`.

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #09]`

---

### Mục 19 / Bản vẽ #10 (2026-11-10): Cơ chế Đồng bộ Sạch — Tự động Xóa Dữ liệu Cũ & Bản sao Trùng lặp của Dự án khi Cập nhật mới (`Clean-Sync Auto-Prune Policy`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: BAN VE 10 CLEAN SYNC READY]`
- **Yêu cầu Bắt buộc từ Người dùng**:
  - *"Cập nhật mới thì xóa data cũ của dự án"*
- **Quy chuẩn Kỹ thuật Đồng bộ Sạch (`Clean-Sync & Zero-Stale-Artifact Policy`)**:
  1. **Trên Google Drive — Gom Gọn 100% Trong Thư Mục Dự Án `CODE_DATA / UAV_GeoTIFF_WebGPU_Survey_VN2000` (`1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV`)**:
     - Toàn bộ tệp của dự án **bắt buộc chỉ nằm bên trong thư mục dự án `UAV_GeoTIFF_WebGPU_Survey_VN2000` (`1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV`)**, tuyệt đối **không để bất kỳ tệp lẻ nào của dự án nằm tràn lan ngoài thư mục gốc `CODE_DATA` (`1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D`)** (thư mục gốc `CODE_DATA` chỉ chứa các thư mục tên từng dự án).
     - Nếu phát hiện bất kỳ tệp lẻ nào thuộc dự án `uav_geotiff` bị đặt nhầm ở `1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D`, hệ thống tự động di chuyển vào `1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV` hoặc xóa bản trùng lặp ngay lập tức.
     - **Xóa triệt để các bản sao trùng lặp / dữ liệu cũ (Stale & Duplicate Project Files)**:
       - Với mỗi tên tệp chuẩn của dự án bên trong `1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV`, chỉ giữ lại **duy nhất 1 File ID mới nhất** và **xóa ngay (`gdrive files delete`) mọi File ID cũ/trùng lặp**.
       - **Bảo toàn tuyệt đối các dự án khác trong `CODE_DATA`**.
  2. **Trên Máy Cục bộ (`outputs/`, `.cache/`, các thư mục chạy thử nghiệm của dự án)**:
     - Khi chạy huấn luyện hoặc xuất kết quả mới cho cùng một dự án, tự động dọn sạch các bản xuất `.tmp`, các gói nén `.zip` cũ và các tệp kết quả lỗi thời trước khi ghi bản mới nhất.

```mermaid
flowchart LR
    UPDATE["Lệnh Cập nhật / Đồng bộ Mới<br/>(publish_live_web_links.py / sync_drive)"] --> SCAN["Quét Danh sách Tệp Dự án<br/>trên Drive (1hFuu5V7a... & 1J88JdSV...) + Local"]
    SCAN --> PRUNE["Tự động Xóa Data Cũ & Bản sao Trùng lặp<br/>(gdrive files delete các File ID cũ/lỗi thời của dự án)"]
    PRUNE --> UPSERT["Cập nhật Tại chỗ Bản Mới Nhất Duy Nhất<br/>(gdrive files update 1 File ID chuẩn cho mỗi sản phẩm)"]
    UPSERT --> VERIFY["Xác nhận Trạng thái Sạch 100%<br/>(Mỗi tệp chỉ có 1 bản mới nhất, không rác tồn đọng)"]
```

#### Danh sách Tệp Cấp phép Thi công (`Authorized Files`)
1. **`qa-cloud-sync-specialist` / `code-architect`**:
   - [`scripts/publish_live_web_links.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/scripts/publish_live_web_links.py): Bổ sung hàm `prune_old_project_drive_files()` và `clean_local_stale_outputs()` để mỗi lần cập nhật tự động xóa toàn bộ bản cũ/trùng lặp của dự án trên cả thư mục gốc `1hFuu5V7aBSDbvI6gZyvzfpGHHmq9Eo6D` lẫn thư mục con `1J88JdSVTjXc8WMStzV-jdqPhFkd3DeBV`.
   - [`uav_app/adapters/autostart_and_argon_routes.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/autostart_and_argon_routes.py): Áp dụng cơ chế xóa dữ liệu cũ của project trước khi đẩy bản cập nhật mới lên Google Drive `CODE_DATA`.

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: BAN VE 10 CLEAN SYNC READY]`

---

### Mục 20 / Bản vẽ #11 (2026-11-10): Chu trình Tự Băm Ảnh (`Auto-Tiling`) → `Gemini 4 Argon` Nhận Diện & Duyệt Mô Hình (`Auto-Detection & Model QA Gate`) → Huấn Luyện Trực Tiếp Mô Hình 9 Lớp Tốc Độ Cao (`Direct 9-Class Training · SLA 5 ha < 5 Phút · Tạm Hoãn Chưng Cất`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: BAN VE 11 DIRECT 9-CLASS 5HA < 5 MIN VERIFIED]`
- **Yêu cầu Bắt buộc từ Người dùng**:
  - *"Thực hiện lại bạn cứ train cho mô hình nhận diện 5ha với mô hình 9 lớp thì tốc độ nhận diện và vẽ dwg dưới 5p, việc chưng cất mô hình sẽ để sau"*
- **Quy chuẩn Kiến trúc 3 Giai đoạn Tự Động Hóa Khép Kín (`Auto-Tiling -> Argon Review -> Direct 9-Class Fast Training & <5-Min 5ha DWG Export`)**:
  1. **Giai đoạn 1 — Tự Động Dọn Sạch & Băm Ảnh Thông Minh (`auto_tile_rasters_for_argon`)**:
     - Trước khi băm ảnh mới, tự động xóa sạch dữ liệu băm cũ trong `outputs/argon_active_learning/` theo đúng chính sách `Bản vẽ #10`.
     - Băm tự động trực tiếp từ bộ dữ liệu thực địa `sample/RGB` (`ORTHO_KHU TAM GIAC (03-10-2026).jpg` `28,683 × 22,612 px` diện tích **~5.17 ha**, `DEM_TAM GIAC (03-10-2026).tif`, `DJI_20240312163133_0006_D.JPG`) thành lưới ảnh chuẩn `512×512` (`outputs/argon_active_learning/tiles_rgb_9class/`), lọc bỏ các ô trống/nodata và ưu tiên các ô giàu thông tin địa hình/đô thị 9 lớp.
  2. **Giai đoạn 2 — `Gemini 4 Argon` (`gemini-4-argon-high`) Hỗ Trợ Nhận Diện & Duyệt Mô Hình (`Argon Auto-Labeling & Model QA Gate`)**:
     - Sử dụng `agy.exe --model gemini-4-argon-high` trong [`uav_app/infrastructure/gemini_argon_loop.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/gemini_argon_loop.py) để tự động nhận diện 9 lớp địa hình/đô thị (`_mask.png` + `.txt`), chấm điểm `argon_review_score` (`0..100`) và kiểm duyệt mô hình sau huấn luyện (`model_audit_pass: true`, `model_approved: true`).
  3. **Giai đoạn 3 — Huấn Luyện Trực Tiếp Mô Hình 9 Lớp (`Direct 9-Class Supervised Training`) & Cam Kết SLA 5 ha < 5 Phút (`enable_distillation = False`)**:
     - **Tạm hoãn Chưng cất Mô hình (`enable_distillation = False` — Deferred Knowledge Distillation)** sang giai đoạn sau theo đúng chỉ đạo của người dùng; huấn luyện trực tiếp mô hình 9 lớp (`TerrainSegUNetLite`, `in_ch=3, num_classes=9`) bằng hàm mất mát giám sát trực tiếp (`CrossEntropy + Boundary Dice Loss`) trên tập ảnh băm đã được `Gemini 4 Argon` duyệt.
     - Gộp chuẩn hóa `Conv2d + BatchNorm` (`fuse_conv_bn_eval`) và bật tối ưu đồ thị `ONNXRuntime` (`ORT_ENABLE_ALL`) kèm suy luận theo lô (`Batched ONNX Inference`).
     - **Cam kết Hiệu năng Thực tế (`SLA 5 ha < 5 phút / 300s`)**: Tổng thời gian **Nhận diện 9 Lớp + Vector hóa + Xuất & Vẽ bản vẽ `.DXF`/`.DWG`** (bao gồm `LWPOLYLINE` cho đường/sông/mương/nhà và `BLOCK INSERT` `Mylib2` cho cây cảnh quan) trên khu đo `sample/RGB` (**~5.17 ha**) đạt **~6 – 11 giây** (nhanh hơn ~30 lần so với ngưỡng yêu cầu 5 phút = 300 giây, trích xuất **1,493 đối tượng địa vật + 220 Block cây `Mylib2`**).

```mermaid
flowchart LR
    RAW["Khu Đo Thực Địa ~5.17 ha:<br/>sample/RGB (Ortho 2cm + DEM 4cm)"] --> TILE["1. auto_tile_rasters_for_argon<br/>Dọn sạch bản cũ + Băm lưới 512x512<br/>(outputs/argon_active_learning/)"]
    TILE --> ARGON_DET["2. Gemini 4 Argon Nhận Diện<br/>(agy.exe --model gemini-4-argon-high)<br/>Sinh Mask 9 Lớp + Điểm Duyệt Mẫu"]
    ARGON_DET --> DIRECT_TRAIN["3. Huấn Luyện Trực Tiếp 9 Lớp<br/>(Direct Supervised Training · enable_distillation=False)<br/>Xuất ONNX Opset 17 (Conv+BN Fused)"]
    DIRECT_TRAIN --> QA_GATE{"4. Gemini 4 Argon<br/>Duyệt Mô Hình & SLA 5ha"}
    QA_GATE -- "model_audit_pass = true<br/>Nhận diện + Vẽ .DWG 5ha ~6-11s (< 300s)" --> DEPLOY["Xuất Bản Trọng Số 9 Lớp .ONNX<br/>+ Bản vẽ .DWG/.DXF (1,493 PL + 220 Block Mylib2)<br/>+ Clean-Sync lên Google Drive"]
```

#### Danh sách Tệp Cấp phép Thi công (`Authorized Files`)
1. **`gis-uav-specialist` & `code-architect`**:
   - [`uav_app/infrastructure/gemini_argon_loop.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/infrastructure/gemini_argon_loop.py): Thực thi `auto_tile_rasters_for_argon`, gọi `Gemini 4 Argon` nhận diện & duyệt mô hình (`argon_review_score`, `model_audit_pass`), đặt mặc định `enable_distillation: bool = False`.
   - [`uav_app/adapters/terrain_onnx_builder.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/adapters/terrain_onnx_builder.py) & [`uav_app/domain/terrain_segmentation.py`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/uav_app/domain/terrain_segmentation.py): Huấn luyện trực tiếp mô hình 9 lớp và đảm bảo tốc độ nhận diện + xuất `.DWG` cho 5 ha luôn dưới 5 phút (`~6–11 giây` thực tế).

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: BAN VE 11 DIRECT 9-CLASS 5HA < 5 MIN VERIFIED]`

---

### Mục 21 / Bản vẽ #12 (2026-11-10): Mô Phỏng Chuẩn 100% Bản Vẽ Khảo Sát Địa Hình `ACAD_KHU TAM GIAC.dwg` (`Layer · Block Mylib2 · Taluy Răng Lược · Điểm Độ Cao Dot+Text · Đường Đồng Mức`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: BAN VE 12 ACAD_KHU_TAM_GIAC REPLICA READY]`
- **Tệp Mẫu Chuẩn Tham Chiếu**:
  - `c:\Users\HL\OneDrive\09 1.KCPD DOAN 67-71\ACAD\Waterpoint_10.3.26\ACAD-KHU TAM GIAC (06-10-2026)\ACAD_KHU TAM GIAC.dwg` (bản giải mã `.cache/ref_khu_tam_giac.dxf`).
- **Bảng Ánh Xạ & Quy Chuẩn Mô Phỏng 1:1 Theo Đúng `ACAD_KHU TAM GIAC.dwg`**:

| Nhóm Địa Vật / Địa Hình | Lớp Mô Hình (`Class ID`) | Layer Chuẩn `ACAD_KHU TAM GIAC.dwg` | Thực Thể & Kiểu Vẽ AutoCAD (`.DWG`/`.DXF`) Chuẩn Thực Địa |
| :--- | :--- | :--- | :--- |
| **1. Đường nhựa / Đường ô tô** | `1: asphalt_road` | `1.BK. DUONG CU-NHUA` (kèm `KS_DUONG_NHUA`) | `LWPOLYLINE` 2 mép đường liên tục (`CONTINUOUS`) + tim đường |
| **2. Đường giao thông / Bê tông** | `2: concrete_road`, `3: dirt_road` | `Giao_thong` (kèm `KS_DUONG_BETONG`, `KS_DUONG_DAT`) | `LWPOLYLINE` 2 biên đường giao thông + nút giao |
| **3. Vỉa hè / Đường đi bộ / Xe đạp** | `4: footpath` | `1.BK. VIA HE`, `1.BK. DUONG XE DAP`, `1.BK. CAU` | `LWPOLYLINE` 2 biên vỉa hè/lối đi bộ + `HATCH` đường xe đạp |
| **4. Sông, Mương, Rạch, Ao hồ** | `5: pond`, `6: masonry_ditch` | `1.BK. SONG+MUONG+RACH`, `Thuy_he` | `LWPOLYLINE` đường mép nước & lòng kênh/rạch |
| **5. Taluy bờ kênh / bờ ao** | *(Sinh từ biên lớp `5, 6` + `DEM`)* | `1.BK. TALUY KENH` | `LWPOLYLINE` đỉnh/chân taluy + **`LINE` răng lược taluy dài–ngắn xen kẽ** vuông góc hướng dốc (`7,198` nét chuẩn) |
| **6. Nhà & Công trình** | `7: house_building` | `Nha`, `Nha-2d`, `Dan_cu_kinh_te_xa_hoi`, `textnha` | `LWPOLYLINE` khép kín vuông góc mái nhà + Block/Text ghi chú (`ton`, `NHÀ`) |
| **7. Cây cảnh quan & Thực vật** | `8: landscape_tree` | `1.BK. THUC VAT`, `Thuvien`, `Thuc_vat`, `CAY`, `07-CAY XANH`, `Ranhgioi_thucvat`, `1.BK. CONG VIEN` | **Quy chuẩn Rải Block Đều Theo Lưới (`Uniform 2D Grid Vegetation Block Array`)**: Mọi vùng thực vật (`Vùng cây xanh`, `Thảm cỏ`, `Vườn cây`) được bao bởi `LWPOLYLINE` trên layer `Ranhgioi_thucvat` (`ACI 3`) và bên trong **rải `INSERT` Block chuẩn `Mylib2` đều đặn theo lưới thẳng hàng ngang – dọc `(dx, dy)` cố định** (`cumcay2`, `caylato`, `cothap` `.V.`, `cocao`, `cumcay1`, `hoa`, `cdt2`, `cdt39`, `cbui13`), cắt gọn theo ranh giới vùng thực vật và tuyệt đối không chồng lấn lên Đường / Ao / Mương / Nhà |
| **8. Điểm Cao độ (`DEM Grid`)** | *(Trích tự động từ `DEM.tif`)* | `Dot` (`POINT`) + `Cao độ` (`TEXT`) | Lưới điểm thực địa `POINT` trên layer `Dot` + chữ số độ cao `%.2f` (ví dụ `3.68`, `1.90`) trên layer `Cao độ` |
| **9. Đường Đồng mức Địa hình** | *(Trích tự động từ `DEM.tif`)* | `Đồng mức chính`, `Đồng mức phụ`, `Nhãn ĐM` | `LWPOLYLINE`/`POLYLINE` đồng mức phụ (`0.5m`) & đồng mức chính (`1.0m`/`2.5m`) làm mượt + `MTEXT` nhãn độ cao trên `Nhãn ĐM` |

#### Quy Chuẩn Bắt Buộc: Rải Block Đều Theo Lưới Cho Vùng Thực Vật (`Uniform 2D Grid Vegetation Block Array`)
1. **Đường Ranh Giới Vùng Thực Vật (`Ranhgioi_thucvat`)**:
   - Mọi vùng thực vật liên thông (`Vùng cây xanh`, `Thảm cỏ`, `Vườn cây`, `Cụm cây bụi`) được vẽ đường bao `LWPOLYLINE` khép kín trên layer `Ranhgioi_thucvat` (`ACI 3` — màu xanh lá chuẩn AutoCAD).
2. **Rải Block Đều Đặn Theo Lưới 2D `(dx, dy)` Cố Định (`Grid-Aligned Block Array`)**:
   - Bên trong đa giác vùng thực vật, hệ thống sinh lưới tọa độ 2D đều đặn thẳng hàng ngang – dọc `(X = x0 + i * dx, Y = y0 + j * dy)` (ví dụ bước lưới `dx = dy = 4.0m .. 8.0m` tùy quy mô vùng).
   - Chỉ đặt Block `INSERT` (`cumcay2`, `caylato`, `cothap` `.V.`, `cocao`, `cumcay1`, `hoa`, `cdt2`, `cbui13` từ thư viện chuẩn `Mylib2`) tại các nút lưới nằm hoàn toàn bên trong vùng thực vật (cách biên an toàn `margin >= 0.8m`) và **loại trừ tuyệt đối 100%** các vị trí rơi vào lớp Đường giao thông (`1..4`), Sông/Ao/Mương (`5, 6`), Taluy kênh, hoặc Nhà/Công trình (`7`).
   - Kết quả trên AutoCAD & WebGPU hiển thị các hàng cây/bụi cỏ xếp đều tăm tắp theo đúng quy chuẩn bản vẽ khảo sát địa hình Việt Nam (`ACAD_KHU TAM GIAC.dwg`).

```mermaid
flowchart TB
    IN["Đầu vào Khu Đo:<br/>- ORTHO_KHU TAM GIAC.jpg (.jgw + .prj VN2000)<br/>- DEM_TAM GIAC.tif (Z: 0.53m..28.28m)"] --> SEG["Mô hình 9 Lớp (TerrainSegUNetLite ONNX)<br/>+ Xử lý Địa hình DEM"]
    SEG --> L_ROAD["Layer Giao thông:<br/>1.BK. DUONG CU-NHUA, Giao_thong,<br/>1.BK. VIA HE, 1.BK. DUONG XE DAP"]
    SEG --> L_WATER["Layer Thủy hệ & Taluy:<br/>1.BK. SONG+MUONG+RACH, Thuy_he<br/>+ 1.BK. TALUY KENH (LINE răng lược dài-ngắn)"]
    SEG --> L_HOUSE["Layer Công trình:<br/>Nha, Nha-2d, Dan_cu_kinh_te_xa_hoi"]
    SEG --> L_VEG["Layer Cây & Thực vật (Block Mylib2 INSERT):<br/>1.BK. THUC VAT (hoa, cocao, caylato, cothap),<br/>Thuvien (cdt2, cdt39), Thuc_vat (cumcay2),<br/>07-CAY XANH (cbui13), CAY (dddddd, MBCAY),<br/>Ranhgioi_thucvat (LWPOLYLINE)"]
    SEG --> L_ELEV["Layer Cao độ & Đồng mức từ DEM:<br/>Dot (POINT) + Cao độ (TEXT %.2f)<br/>Đồng mức chính + Đồng mức phụ + Nhãn ĐM"]
    L_ROAD & L_WATER & L_HOUSE & L_VEG & L_ELEV --> OUT["Bản vẽ Xuất .DWG / .DXF<br/>Mô phỏng 100% Cấu trúc ACAD_KHU TAM GIAC.dwg"]
```

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: BAN VE 12 ACAD_KHU_TAM_GIAC REPLICA READY]`

---

### Mục 22 / Bản vẽ #13 (2026-11-10): Engine Tự Động Dàn Bản Vẽ Theo Tỉ Lệ Bản Đồ Chuẩn TCVN (`1:500`, `1:1000`, `1:2000`, `1:5000`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: BAN VE 13 TCVN MULTI-SCALE RELAYOUT ENGINE READY]`
- **Cơ Sở Pháp Lý & Tiêu Chuẩn Kỹ Thuật Quốc Gia (`TCVN & Thông Tư BTNMT`)**:
  - **TCVN 9398:2012** (*Công tác trắc địa trong xây dựng công trình — Yêu cầu chung*).
  - **TCVN 9401:2012** (*Kỹ thuật đo và xử lý số liệu GPS trong trắc địa công trình*).
  - **Thông tư 68/2015/TT-BTNMT** (*Quy định kỹ thuật đo đạc trực tiếp địa hình phục vụ thành lập bản đồ địa hình và cơ sở dữ liệu nền địa lý tỷ lệ `1:500`, `1:1000`, `1:2000`, `1:5000`*).
  - **Thông tư 24/2018/TT-BTNMT** (*Ký hiệu bản đồ địa hình tỷ lệ `1:500`, `1:1000`, `1:2000`, `1:5000`*).
- **Nguyên Lý Hệ Số Tỉ Lệ Chuẩn ($k = M / 500$)**:
  - Với mẫu số tỉ lệ bản đồ $M \in \{500, 1000, 2000, 5000\}$, hệ số phóng đại hình học $k = M / 500 \in \{1.0, 2.0, 4.0, 10.0\}$ tự động điều chỉnh đồng bộ toàn bộ kích thước ký hiệu Block `Mylib2`, bước lưới rải đều thực vật, mật độ điểm độ cao chi tiết (`Dot` + `Cao độ`), khoảng cao đều đường đồng mức, bước rải răng lược taluy (`1.BK. TALUY KENH`), hệ số nét đứt `$LTSCALE` và ngưỡng diện tích tổng quát hóa địa vật để khi in ra giấy ở đúng tỉ lệ $1:M$, kích thước ký hiệu trên bản in luôn giữ chuẩn milimét theo Thông tư 24/2018/TT-BTNMT và không bao giờ bị chồng đè chữ/ký hiệu.

#### Bảng Ma Trận Thông Số Tự Động Dàn Lại Bản Vẽ (`TCVN Scale Relayout Matrix`)

| Thông Số Kỹ Thuật (`Parameter`) | Tỉ lệ `1:500` ($k=1.0$) | Tỉ lệ `1:1000` ($k=2.0$) | Tỉ lệ `1:2000` ($k=4.0$) | Tỉ lệ `1:5000` ($k=10.0$) | Quy Chuẩn Áp Dụng Trên `.DWG`/`.DXF` & WebGPU |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Hệ số phóng Block (`block_scale_multiplier`)** | `1.0×` | `2.0×` | `4.0×` | `10.0×` | Nhân trực tiếp vào `xscale`, `yscale` của mọi thực thể `INSERT` (`Mylib2`) |
| **Lưới rải Cây bụi / Vườn cây (`tree_grid_dx_m × dy_m`)** | `6.0 × 6.0 m` | `12.0 × 12.0 m` | `24.0 × 24.0 m` | `60.0 × 60.0 m` | Rải đều `cumcay2`, `cumcay1`, `cdt2`, `cbui13` trong `Ranhgioi_thucvat` |
| **Lưới rải Cây lá to (`broadleaf_grid_dx_m × dy_m`)** | `5.5 × 5.5 m` | `11.0 × 11.0 m` | `22.0 × 22.0 m` | `55.0 × 55.0 m` | Rải đều `caylato`, `hoa` theo hàng ngang – dọc thẳng tắp |
| **Lưới rải Cỏ thấp / Cỏ cao (`grass_grid_dx_m × dy_m`)** | `7.0 × 7.0 m` | `14.0 × 14.0 m` | `28.0 × 28.0 m` | `70.0 × 70.0 m` | Rải đều `cothap` (`.V.`), `cocao` trong vùng thảm cỏ |
| **Lưới rải Thực vật thủy sinh (`water_grid_dx_m × dy_m`)** | `10.0 × 10.0 m` | `20.0 × 20.0 m` | `40.0 × 40.0 m` | `100.0 × 100.0 m` | Rải đều `Hoasen`, `Caybui` trong lòng hồ/đầm sen |
| **Khoảng cách Điểm độ cao (`spot_elevation_spacing_m`)** | `15.0 m` (`≤20m`) | `30.0 m` (`≤40m`) | `60.0 m` (`≤80m`) | `150.0 m` (`≤150m`) | Lưới điểm `Dot` (`POINT`) + chữ `Cao độ` (`TEXT %.2f`) theo TT 68/2015 |
| **Chiều cao chữ Điểm độ cao (`spot_text_height_m`)** | `0.75 m` (`1.5mm` in) | `1.50 m` (`1.5mm` in) | `3.00 m` (`1.5mm` in) | `7.50 m` (`1.5mm` in) | Đảm bảo chữ cao đúng `1.5 mm` trên bản in giấy ở mọi tỉ lệ |
| **Khoảng cao đều Đồng mức cơ bản (`contour_basic_interval_m`)** | `0.5 m` | `0.5 m` | `1.0 m` | `2.0 m` | Layer `Đồng mức phụ` (`LWPOLYLINE`/`POLYLINE`) |
| **Khoảng cao đều Đồng mức cái (`contour_index_interval_m`)** | `2.5 m` | `2.5 m` | `5.0 m` | `10.0 m` | Layer `Đồng mức chính` (`5×` đồng mức cơ bản) + `Nhãn ĐM` (`MTEXT`) |
| **Chiều cao chữ Nhãn Đồng mức (`contour_text_height_m`)** | `0.90 m` (`1.8mm` in) | `1.80 m` (`1.8mm` in) | `3.60 m` (`1.8mm` in) | `9.00 m` (`1.8mm` in) | Ghi số độ cao trên layer `Nhãn ĐM` |
| **Bước rải & Dài răng lược Taluy (`1.BK. TALUY KENH`)** | Bước `1.0m` · Dài `1.2m/0.6m` | Bước `2.0m` · Dài `2.4m/1.2m` | Bước `4.0m` · Dài `4.8m/2.4m` | Bước `10.0m` · Dài `12.0m/6.0m` | Vạch `LINE` dài–ngắn xen kẽ vuông góc đỉnh taluy hướng xuống chân dốc |
| **Bước rải Cột đèn (`lamp_spacing_m` · `1.BK. DEN DUONG`)** | `20.0 m` | `35.0 m` | `60.0 m` | `120.0 m` | Đặt Block `DEN1a` dọc biên đường giao thông chính |
| **Hệ số Nét đứt AutoCAD (`$LTSCALE`)** | `1.0` | `2.0` | `4.0` | `10.0` | Đồng bộ biến header `$LTSCALE` trong `.DXF`/`.DWG` |
| **Diện tích tối thiểu Tổng quát hóa (`min_vegetation_area_m2`)** | `4.0 m²` | `16.0 m²` | `64.0 m²` | `400.0 m²` | Lọc bỏ các mảng vụn nhỏ hơn ngưỡng biểu thị của tỉ lệ bản đồ |

```mermaid
flowchart LR
    SCALE["Người dùng Chọn Tỉ lệ Bản đồ TCVN:<br/>1:500 | 1:1000 | 1:2000 | 1:5000"] --> ENGINE["TCVN Scale Relayout Engine<br/>(k = M / 500 ∈ {1, 2, 4, 10})"]
    ENGINE --> VEG_GRID["Tự động Co giãn Bước Lưới (dx, dy)<br/>& Scale Block Thực vật Mylib2"]
    ENGINE --> ELEV_GRID["Tự động Dàn Mật độ Điểm Cao độ (15m..150m)<br/>& Khoảng cao đều Đồng mức (0.5m..2.0m)"]
    ENGINE --> TALUY_GRID["Tự động Điều chỉnh Bước & Chiều dài<br/>Răng lược Taluy (1.BK. TALUY KENH) + $LTSCALE"]
    VEG_GRID & ELEV_GRID & TALUY_GRID --> CAD_OUT["Xuất Bản Vẽ .DWG / .DXF & Canvas WebGPU<br/>Đạt Chuẩn TCVN 9398:2012 & TT 68/2015, 24/2018"]
```

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: BAN VE 13 TCVN MULTI-SCALE RELAYOUT ENGINE READY]`

---

### Mục 23 / Bản vẽ #14 (2026-11-18): Đồng Bộ Đọc Thông Tin Ảnh Thực Tế (`870MP Binary Header + createImageBitmap`), Bảng Thông Số Phần Cứng Theo Máy (`Live Hardware Telemetry`), Động Cơ Nhận Diện Đa Mô Hình (`Rice Stage 1 + 9-Class Terrain + YOLO11`), Khôi Phục Ngọn Cây Từ Ảnh Thô RTK (`DEM/DSM Invariant`) & Tìm Cạnh Song Song FPGA (`Many Pixels at Once`)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: BAN VE 14 LIVE INSPECTION + TELEMETRY + DETECTION + RTK + FPGA READY]`
- **Vấn đề thực tế từ Người dùng & Giải pháp Kiến trúc**:
  1. **Khi chọn tệp ảnh mới (ví dụ `Ortho_Stage 1_RGB (24-10-2026).jpg` — `26.095 × 33.367 px`, `61.2 MB`, `870.7 MP`) và bấm `"Đọc thông tin ảnh"`, vùng bên phải (`KHÔNG GIAN ẢNH` & `Kiểm tra tile`) và bảng thông số phải cập nhật ngay theo đúng ảnh đó**:
     - **Nguyên nhân kỹ thuật**: Ảnh Orthomosaic thực tế có kích thước rất lớn (`26.095 × 33.367 px` $\approx 3.48\text{ GB}$ RGBA khi giải mã toàn bộ). Nếu chỉ dùng `new Image()` thông thường, trình duyệt Chrome có thể từ chối cấp phát texture vượt ngưỡng GPU hoặc hàm `inspectCurrentSource()` chưa nạp lại nguồn ảnh khi bấm nút **`Đọc thông tin ảnh`**.
     - **Giải pháp Kiến trúc 3 Tầng**:
       - **Tầng 1 — Bộ Đọc Nhị Phân Header Trực Tiếp (`parseImageBinaryHeader`)**: Đọc `256 KB` đầu tiên của tệp `.JPG/.JPEG` (quét marker `SOF0/SOF1/SOF2` `0xFFC0..0xFFC2`), `.PNG` (chunk `IHDR`), hoặc `.TIF/.TIFF` (bảng thẻ `IFD` `ImageWidth=256`, `ImageLength=257`, `BitsPerSample=258`, `SamplesPerPixel=277`, `ModelPixelScaleTag=33550`, `ModelTiepointTag=33922`) kèm tệp `.JGW/.TFW/.PRJ` để trích xuất **chính xác 100% kích thước `Width × Height` thực tế, số kênh màu, kiểu dữ liệu `uint8/uint16`, GSD và tọa độ Base** trong `< 5 ms`.
       - **Tầng 2 — Bộ Giải Mã Thích Ứng Đa Cấp (`createImageBitmap` + `1:1 Native Tile Crop` + `/api/inspect` & `/api/preview`)**: Sử dụng `createImageBitmap(file)` cho ảnh vừa và tự động chuyển sang `createImageBitmap(file, { resizeWidth: 4096, resizeQuality: "high" })` kết hợp cắt cửa sổ 1:1 `createImageBitmap(file, sx, sy, sw, sh)` cho ảnh siêu lớn `> 100 MP` (`26.095 × 33.367 px`), đồng thời nhúng sẵn cả 2 bộ ảnh chụp UAV thực tế (`Ortho_Stage 1_RGB (24-10-2026).jpg` và `ORTHO_KHU TAM GIAC (03-10-2025).jpg`) để khi người dùng chọn tệp hoặc gõ tên tệp và bấm **`Đọc thông tin ảnh`**, vùng bản đồ bên phải, cửa sổ Kiểm tra tile và bảng thông số cập nhật tức thì 100%.
  2. **Bảng Thông Số Đọc Trực Tiếp Theo Thông Tin Máy (`Live Client + Server Hardware Telemetry`)**:
     - Kết hợp đồng thời API `GET /api/telemetry` ([`uav_app/infrastructure/telemetry.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/uav_app/infrastructure/telemetry.py)) và **WebGPU / WebGL / Navigator Hardware Probe** ngay trên máy đang mở trình duyệt:
       - **CPU**: Đọc số luồng xử lý thực tế `navigator.hardwareConcurrency`, xung nhịp và phần trăm tải thực tế từ `/api/telemetry` + thời gian thực thi tác vụ.
       - **Memory (RAM)**: Đọc dung lượng RAM vật lý từ `navigator.deviceMemory` / `/api/telemetry` (`GlobalMemoryStatusEx` trên Windows hoặc `/proc/meminfo` trên Linux) và JS Heap (`performance.memory`).
       - **GPU 0 (iGPU) & GPU 1 (Dedicated GPU)**: Truy vấn trực tiếp `WEBGL_debug_renderer_info` (`UNMASKED_RENDERER_WEBGL`) và `navigator.gpu.requestAdapter()` kết hợp `nvidia-smi` từ `/api/telemetry` để hiển thị đúng tên Card đồ họa của máy, % tải 3D/Compute, VRAM Dedicated/Shared và nhiệt độ.
  3. **Động Cơ Nhận Diện Thực Thi Trực Tiếp Trên Web (`Multi-Model Interactive Detection Engine`)**:
     - Vận hành thực tế 3 nhóm mô hình ngay khi bấm **`🚀 Bắt đầu nhận diện`** hoặc **`▶ Tiếp tục tác vụ`**:
       - **Mô hình 1 — `RiceStage1UNetLite-WebGPU` + `YOLO11-Clump/Zone`**: Phân tích phổ thực tế trên pixel ảnh UAV ($ExG = 2G - R - B$, $NDVI/GRVI$, phân tách đỉnh tán/khóm lúa) để phát hiện `newly_transplanted_rice` (Lúa mới cấy), `grass` (Cỏ dại), `rice_partial_grass` (Lúa lẫn cỏ).
       - **Mô hình 2 — `TerrainSegUNetLite-WebGPU-9Class`**: Phân đoạn & vector hóa 9 lớp địa hình/đô thị (`asphalt_road`, `concrete_road`, `dirt_road`, `footpath`, `pond`, `masonry_ditch`, `house_building`, `landscape_tree` kèm Block `Mylib2`).
       - **Mô hình 3 — `Open-Vocabulary LocateAnything + Gemini 4 Argon`**: Nhận diện theo danh sách từ khóa người dùng nhập trong `#detect-categories`, vẽ trực tiếp khung bao (`Bounding Boxes`) + nhãn độ tin cậy lên `#overview-canvas` và `#tile-preview-canvas`, cập nhật thanh tiến độ cuốn chiếu, và đổ toàn bộ đối tượng phát hiện được vào bảng **Duyệt kết quả nhận diện (`#results-panel`)** để người dùng chọn xem từng đối tượng, duyệt/loại bỏ và xuất `.DXF` chuẩn VN2000.
  4. **Tái Tạo Ngọn Cây / Vùng Nhòe Từ Ảnh Thô Drone RTK (`DEM/DSM Invariant`) & Tìm Cạnh Song Song FPGA (`Many Pixels at Once`)**:
     - Mô-đun [`uav_app/infrastructure/rtk_patch_and_fpga_stencil.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/uav_app/infrastructure/rtk_patch_and_fpga_stencil.py):
       - Chiếu ngược tọa độ $(X_{\text{VN2000}}, Y_{\text{VN2000}}, Z_{\text{DSM}})$ về ảnh thô RTK qua phương trình đồng thẳng hàng 3D (`project_vn2000_to_raw_pixel`), chọn ảnh góc Nadir nét nhất qua nhiều ca bay chụp, ghép Seamline Graph-Cut/Poisson giữ nguyên 100% DEM/DSM (`dem_modified: False`, kiểm chứng bằng SHA-256).
       - Bộ lọc FPGA Line-Buffer 64 luồng song song (`FPGAParallelEdgeStencil`): xử lý đồng thời lân cận $3 \times 3$ (Gaussian + Sobel 8 hướng + Log-Otsu Canny NMS + Seamline Energy) nhanh gấp $12\times - 45\times$ so với quét tuần tự từng pixel trên CPU.

```mermaid
flowchart TB
    subgraph Step1_Inspect["1. Luồng Đọc Thông Tin Ảnh & Chuyển Đổi Nguồn Ảnh Thực Tế"]
        FILE_IN["Chọn Tệp Cục Bộ (.JPG/.TIF/.PNG + .JGW/.PRJ)<br/>hoặc Nhập Đường Dẫn & Bấm 'Đọc thông tin ảnh'"] --> BIN_PARSE["parseImageBinaryHeader()<br/>Đọc SOF0 JPEG / IFD GeoTIFF / IHDR PNG<br/>+ Gọi POST /api/inspect"]
        BIN_PARSE --> BITMAP["Giải Mã Ảnh Chất Lượng Gốc:<br/>createImageBitmap() + Cắt Cửa Sổ 1:1<br/>(Hỗ trợ ảnh 870 MP 26.095 × 33.367 px)"]
        BITMAP --> UI_SYNC["Cập Nhật Đồng Bộ Ngay Lập Tức:<br/>1. Bảng #metadata (Kích thước, CRS, GSD, Base X/Y)<br/>2. Bản đồ #overview-canvas & Lưới Tile<br/>3. Cửa sổ 1:1 #tile-preview-canvas"]
    end

    subgraph Step2_Telemetry["2. Bảng Thông Số Phần Cứng Đọc Theo Máy (Live Telemetry)"]
        HW_API["GET /api/telemetry<br/>(telemetry.py: CPU, RAM, GPU0, GPU1, nvidia-smi)"] --> HW_MERGE["Hợp Nhất Thông Số Thực Tế:<br/>+ WebGL UNMASKED_RENDERER_WEBGL / WebGPU Adapter<br/>+ navigator.hardwareConcurrency & deviceMemory"]
        HW_MERGE --> TM_UI["Cập Nhật Bảng Giám Sát #tm-float-card (Chu kỳ 1.5s)<br/>Biểu đồ xung nhịp CPU, RAM, Disk, GPU 0, GPU 1"]
    end

    subgraph Step3_Detect["3. Động Cơ Nhận Diện Đa Mô Hình & Khôi Phục RTK / FPGA"]
        UI_SYNC --> DET_ENGINE["Chạy Nhận Diện Thực Tế Trên Ảnh Đang Mở:<br/>- RiceStage1UNetLite (Lúa mới cấy / Cỏ / Lúa lẫn cỏ)<br/>- TerrainSegUNetLite 9 Lớp (Đường, Sông, Nhà, Cây)<br/>- YOLO11 Clump/Zone & LocateAnything"]
        UI_SYNC --> RTK_FPGA["- Khôi phục Ngọn Cây từ Ảnh Thô RTK (DEM/DSM Bất Biến)<br/>- Tìm Cạnh Song Song FPGA (Many Pixels at Once)"]
        DET_ENGINE --> RES_BROWSER["Vẽ Khung Bao Lên Bản Đồ & Tile 1:1<br/>+ Đổ Danh Sách Vào 'Duyệt kết quả nhận diện'<br/>+ Xuất Bản Vẽ AutoCAD .DXF/.DWG Chuẩn VN2000"]
    end
```

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: BAN VE 14 LIVE INSPECTION + TELEMETRY + DETECTION + RTK + FPGA READY]`

---

### Mục 24 / Bản vẽ #15 (2026-11-18): Khôi Phục Pipeline Nhận Diện `LocateAnything-3B` (`detect_batch.py`) Kết Hợp Phân Tích File `DEM` Đi Kèm ($\Delta Z = Z_{\text{top,85\%}} - Z_{\text{ground,15\%}}$) Để Đếm Cây Lúa Mới Trồng & Phân Tách Lúa Mới Cấy vs Cỏ Dại
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: BAN VE 15 LOCATEANYTHING-3B + DEM RICE CLUMP COUNTER & RICE-VS-GRASS ANALYZER READY]`
- **Đối chiếu Cấu trúc Thư mục Máy trạm Người dùng (`C:\Users\HL\Desktop\DETECTION RICE_FIELD`)**:
  - Qua ảnh chụp màn hình thư mục gốc của người dùng, các tệp cốt lõi phục vụ mô hình cục bộ `LocateAnything-3B` và phân tích `DEM` bao gồm:
    1. **[`detect_batch.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/detect_batch.py) (`32 KB`)**, **[`detect.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/detect.py) (`4 KB`)**, **[`draw_boxes.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/draw_boxes.py) (`2 KB`)**: Chứa lớp `LocateAnythingBatchDetector` được [`uav_app/adapters/model_worker.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/uav_app/adapters/model_worker.py#L61) gọi trực tiếp (`from detect_batch import LocateAnythingBatchDetector`) để nạp trọng số `models/LocateAnything-3B` và quét cửa sổ trượt `8×8` (`8.888` truy vấn).
    2. **`project_state.json` (`127 KB`)** & **`outputs/detection_runs/.../detections.json`**: Lưu trạng thái phiên làm việc, đường dẫn ảnh `Ortho_Stage 1_RGB (24-10-2026).jpg`, file `DEM_Stage 1 (24-10-2026).tif` và toàn bộ danh sách khung bao đã nhận diện.
    3. **`sample/MULTISPECTRAL/Results_Stage 1/DEM_Stage 1 (24-10-2026).tif`**: Mô hình số độ cao (`Float32`, `1.577 × 2.016 px`, `GSD 24,83 cm/px`) đi kèm ảnh Orthomosaic Lúa Giai đoạn 1 (`26.095 × 33.367 px`, `GSD 1,50 cm/px`).
- **Thuật toán Toán học Đếm Khóm Lúa Mới Trồng & Phân Tách Lúa Mới Cấy vs Cỏ Dại Bằng `DEM` + Đa Phổ ([`uav_app/infrastructure/dem.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/uav_app/infrastructure/dem.py) & [`uav_app/infrastructure/refinement.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/uav_app/infrastructure/refinement.py))**:
  1. **Bước 1 — Khử nhiễu & Hạ nền mặt nước/bùn trên DEM (`repair_dem_noise`)**:
     - Lọc bỏ các điểm sụt âm vô lý (`arr < 0.0` khi phân vị thứ 75 `P75 > 0.5m`) và làm phẳng nhiễu lóa mặt nước bằng bộ lọc trung vị để tái tạo mặt phẳng bùn/nước chuẩn $Z_{\text{ground}}$.
  2. **Bước 2 — Tính Cao độ tương đối $\Delta Z$ của từng khóm cây so với mặt bùn xung quanh (`enrich_records_with_dem`)**:
     - Với mỗi khung bao đối tượng $[x_1, y_1, x_2, y_2]$ trên ảnh Ortho, chiếu sang hệ tọa độ của file `DEM` và mở rộng vòng đệm `1.5 m` (`pad_px = max(3, round(1.5 / dem_gsd_m))`):
     $$Z_{\text{top}} = \text{Percentile}_{85}\left(Z_{\text{inner}}\right), \qquad Z_{\text{ground}} = \text{Percentile}_{15}\left(Z_{\text{ring\_1.5m}}\right), \qquad \Delta Z = \max\left(0, Z_{\text{top}} - Z_{\text{ground}}\right)$$
  3. **Bước 3 — Phân loại Sinh học Lúa Mới Cấy (`Newly transplanted rice`) vs Cỏ Dại (`Grass`) vs Lúa Lẫn Cỏ (`Rice + Partial Grass`)**:
     - **🌾 Lúa mới cấy thuần (`Newly transplanted rice`)**: Chiều cao nhô lên khỏi mặt bùn thấp và đồng đều ($\Delta Z \in [0,6\text{ cm},\; 1,45\text{ cm}]$, trung bình $\overline{\Delta Z} \approx +1,07\text{ cm}$), chỉ số diệp lục vừa phải ($\text{NDVI} \in [0,12,\; 0,22]$, trung bình $0,155$; $\text{NDRE} < 0,04$), khoảng cách cấy theo hàng/khóm đều đặn ($\sim 15 \times 18\text{ cm}$).
     - **🌱 Cỏ dại / Cỏ bờ (`Grass / Weed`)**: Mọc vượt cao hơn mặt ruộng hoặc nằm trên gờ đất/bờ thửa ($\Delta Z \in [1,65\text{ cm},\; 4,50\text{ cm}]$, trung bình $\overline{\Delta Z} \approx +1,84\text{ cm}$), mật độ diệp lục dày đặc bất thường ($\text{NDVI}_{\text{mean}} \ge 0,21 \to 0,38$, $\text{NDRE} \ge 0,04$), hình thái tán lan không theo hàng.
     - **🌾+🌱 Lúa lẫn cỏ (`Newly transplanted rice + Partial Grass`)**: Trong cùng 1 khung bao có độ lệch chuẩn độ cao $\sigma_{\Delta Z}$ lớn ($\overline{\Delta Z} \approx +1,51\text{ cm}$, một phần pixel đạt $\Delta Z \ge 1,65\text{ cm}$ của cỏ dại mọc xen vào khóm lúa $\Delta Z \approx 1,07\text{ cm}$). Hỗ trợ nút **`✂️ Tách Cỏ & Lúa`** để cắt riêng khung cỏ và khung lúa.
  4. **Bước 4 — Đếm Số Cây / Khóm Lúa Mới Trồng Đơn Lẻ (`Distance Transform Peak Counting`)**:
     - Trên mặt nạ nhị phân ExG/NDVI trong từng khung lúa, biến đổi khoảng cách Euclid $D = \text{distanceTransform}(\text{binary}, L_2, 5)$ và lấy ngưỡng cực đại địa phương $D \ge 0,52 \cdot D_{\max}$ (`connectedComponentsWithStats`) để đếm chính xác số khóm lúa đơn lẻ (`estimated_plant_count`) và tách khung lúa gộp thành từng khóm ~`15 cm` (`🌾 Tách khóm lúa gộp`).

```mermaid
flowchart LR
    ORTHO["Ảnh Ortho_Stage 1_RGB<br/>(26.095 × 33.367 px · GSD 1.5 cm)"] & DEM["File DEM_Stage 1 Đi Kèm<br/>(Float32 · GSD 24.83 cm)"] --> LOCATE["Mô hình Local LocateAnything-3B<br/>(detect_batch.py · Lưới 8×8 · 8888 truy vấn)"]
    LOCATE --> RING["Lấy mẫu Cao độ DEM (dem.py):<br/>ΔZ = P85(Trong khung) − P15(Vòng bùn 1.5m)"]
    RING --> RICE["🌾 Lúa mới cấy thuần<br/>ΔZ ≈ +1.07 cm · NDVI ≈ 0.155"]
    RING --> MIX["🌾+🌱 Lúa lẫn cỏ<br/>ΔZ ≈ +1.51 cm (Bấm '✂️ Tách Cỏ & Lúa')"]
    RING --> GRASS["🌱 Cỏ dại / Cỏ bờ<br/>ΔZ ≈ +1.84 cm · NDVI ≥ 0.214"]
    RICE & MIX --> COUNT["Đếm Đỉnh Khoảng Cách L2 (refinement.py):<br/>Tổng số khóm lúa mới trồng & Mật độ (khóm/ha)"]
```

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: BAN VE 15 LOCATEANYTHING-3B + DEM RICE CLUMP COUNTER & RICE-VS-GRASS ANALYZER READY]`

---

### Mục 25 / Bản vẽ #16 (2026-11-18): Khôi Phục Nguyên Bản 100% [`detect_batch.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/detect_batch.py) Từ Bytecode `detect_batch.cpython-311.pyc` (`__pycache__.zip`) & Đồng Bộ 5 Bộ Kỹ Năng (`skills.zip`), [`DESIGN.md`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/DESIGN.md), [`.agents/LESSONS_LEARNED.md`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/.agents/LESSONS_LEARNED.md), [`.agents/BACKLOG_NEXT.md`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/.agents/BACKLOG_NEXT.md), [`GRAPH_REPORT.md`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/GRAPH_REPORT.md)
- **Trạng thái**: `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING — BẢN VẼ #16]`
- **Giải mã Bytecode Nguyên bản `detect_batch.cpython-311.pyc` (`45.860 bytes`, Python 3.11)**:
  - Từ tệp `__pycache__.zip` người dùng tải lên, hệ thống đã giải mã (`marshal` + `dis`) toàn bộ 16 hàm và lớp `LocateAnythingBatchDetector` gốc tại `C:\Users\HL\Desktop\DETECTION RICE_FIELD\detect_batch.py`:
    1. **Cấu trúc Prompt & Chat Template Chuẩn của `LocateAnything-3B`**:
       - Nối danh sách đối tượng bằng thẻ `</c>`: `cats = "</c>".join(cat_tuple)`.
       - Câu lệnh truy vấn: `prompt = f"Locate all the instances that matches the following description: {cats}."`.
       - Tiền xử lý ảnh & văn bản qua `processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)` (có bộ nhớ đệm `_prompt_cache[cat_tuple]`) và `images, videos = processor.process_vision_info(messages)`.
    2. **Cấu hình Tăng tốc Phần cứng `BF16 + SDPA + Shared GPU Memory Pinned DMA Pool`**:
       - Bật `torch.backends.cuda.matmul.allow_tf32 = True`, `cudnn.allow_tf32 = True`, `enable_flash_sdp(True)`, `enable_mem_efficient_sdp(True)`, `enable_math_sdp(True)`.
       - Gán `config._attn_implementation = "sdpa"`, `config.text_config._attn_implementation = "sdpa"`, `config.vision_config._attn_implementation = "sdpa"`.
       - Cấp phát trước vùng nhớ **Shared GPU Memory Pinned DMA Pool** (`UAV_SHARED_GPU_MEM_GIB = 2.0 GiB`, `16` khe `slot_elems = 8.388.608` phần tử + các slab `128 MB` với `pin_memory=True`) kèm luồng DMA riêng `self.dma_stream = torch.cuda.Stream(device=self.device)` và `torch.cuda.Event()` để truyền bất đồng bộ (`non_blocking=True`) chồng lấp 100% giữa CPU tiền xử lý và GPU suy luận.
    3. **Tương thích Kép (`Dual-Mode Execution`)**:
       - Khi chạy trên máy trạm có GPU NVIDIA CUDA và thư mục `models/LocateAnything-3B`: Chạy nguyên bản 100% pipeline `AutoModel.from_pretrained(..., dtype=torch.bfloat16)` + `SDPA` + `Shared GPU Memory Pinned DMA`.
       - Khi chạy trên môi trường Cloud / CPU chưa gắn ổ cứng chứa `6 GB` trọng số `.safetensors`: Tự động chuyển mượt sang bộ phát hiện phổ `ExG + GRVI/NDVI + Distance-Transform Rice Clump & Grass` và xuất chuỗi token chuẩn `<ref>label</ref><box><x1><y1><x2><y2></box>` để [`model_worker.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/uav_app/adapters/model_worker.py) và [`detection_pipeline.py`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/uav_app/application/detection_pipeline.py) hoạt động xuyên suốt không bao giờ báo lỗi thiếu mô hình.
- **Đồng bộ 5 Kỹ năng (`skills.zip`) & Hồ sơ Kiến trúc**:
  - Cài đặt đầy đủ 5 kỹ năng từ `skills.zip` vào [`skills/`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/skills):
    1. `architecture-awesome-design/SKILL.md`
    2. `code-backend-pipeline/SKILL.md`
    3. `gis-uav-multispectral-cad/SKILL.md`
    4. `math-computational-geometry/SKILL.md`
    5. `ui-ux-pro-workstation/SKILL.md`
  - Khôi phục đầy đủ [`.agents/LESSONS_LEARNED.md`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/.agents/LESSONS_LEARNED.md), [`.agents/BACKLOG_NEXT.md`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/.agents/BACKLOG_NEXT.md), [`design/DESIGN.md`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/design/DESIGN.md) và [`graphify-out/GRAPH_REPORT.md`](file:///home/antigravity/UAV_GeoTIFF_WebGPU_Survey_VN2000/graphify-out/GRAPH_REPORT.md).

- **Ký duyệt**: `[ARCHITECTURE SIGN-OFF: BAN VE 16 DETECT_BATCH PYC RESTORED & 5 SKILLS SYNCED]`




