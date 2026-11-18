---
name: architecture-awesome-design
description: Quy trình Bắt buộc Trước Khi Code (Architecture-First Gatekeeper & Awesome Design System). Bắt buộc kích hoạt trước mọi lần viết hoặc sửa code để đọc Graphify, vẽ bổ sung sơ đồ kiến trúc vào ARCHITECTURE.md + DESIGN.md, kiểm tra chốt kiến trúc trơn tru (0 xung đột, 0 vòng lặp phụ thuộc), rồi mới cho phép các Agent thi công bắt đầu code.
---

# Architecture-First & Awesome Design Gatekeeper (`architecture-design-lead`)

Kỹ năng này quy định **Bước 0 Bắt buộc (`Pre-Code Architecture Sign-Off`)** trước mọi lần thêm tính năng, thay đổi thuật toán hoặc cập nhật giao diện trong dự án **UAV GeoTIFF Studio & WebGPU Survey Portal**.

---

## 1. Quy tắc Bất di bất dịch ("Chốt Kiến trúc Trơn tru Rồi Mới Code")

> [!IMPORTANT]
> **TUYỆT ĐỐI KHÔNG CODE NGAY LẬP TỨC**:
> Trước mỗi lần code, **Agent Điều phối** hoặc Sub-Agent **`architecture-design-lead`** bắt buộc phải thực hiện đủ 4 bước dưới đây. Chỉ khi kiến trúc đã được vẽ bổ sung vào [`uav_geotiff/ARCHITECTURE.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ARCHITECTURE.md) và chốt trơn tru thì các Agent thi công (`code-architect`, `ui-ux-specialist`, `math-geometry-expert`, `gis-uav-specialist`) mới được phép chạm vào code.

---

## 2. Quy trình 4 Bước của Agent `architecture-design-lead` Trước Khi Code

### Bước 1: Đọc Đồ thị Tri thức `Graphify` & Kiến trúc Hiện tại
1. Đọc [`uav_geotiff/graphify-out/GRAPH_REPORT.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/graphify-out/GRAPH_REPORT.md) để nắm các **God Nodes** (`ProjectService`, `createAdvanced()`, `createViewport()`, `run_detection()`, `run_terrain_segmentation_and_export_dxf()`, `handle_automation_get/post()`).
2. Đọc [`uav_geotiff/ARCHITECTURE.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ARCHITECTURE.md) và [`uav_geotiff/DESIGN.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/DESIGN.md).

### Bước 2: Vẽ Bổ sung Kiến trúc & Đặc tả Awesome Design vào `ARCHITECTURE.md`
Cập nhật vào **Phần IV (Nhật ký Bản vẽ Kiến trúc)** và các sơ đồ liên quan trong [`uav_geotiff/ARCHITECTURE.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ARCHITECTURE.md):
1. **Sơ đồ Mermaid (`flowchart`, `sequenceDiagram`, hoặc `stateDiagram-v2`)**: Thể hiện rõ luồng gọi hàm, tên tệp, API route (`GET`/`POST`), và định dạng dữ liệu truyền qua lại.
2. **Hợp đồng Kỹ thuật (`Data & API Contracts`)**: Ghi rõ tên hàm, tham số đầu vào, kiểu dữ liệu trả về và cơ chế xử lý lỗi/fallback.
3. **Đặc tả Giao diện Awesome Design (`DESIGN.md`)**: Nếu có thay đổi UI, chỉ định rõ mã màu (`Hex`), kiểu chữ (`Inter` / `SFMono-Regular tabular-nums`), vị trí gắn vào DOM và trạng thái nút bấm theo chuẩn [`uav_geotiff/DESIGN.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/DESIGN.md).

### Bước 3: Rà soát Chốt Kiến trúc Trơn tru (`Smoothness & Safety Gate`)
Kiểm tra 5 tiêu chí bắt buộc trước khi duyệt:
- [ ] **0 Import Cycles**: Tầng `domain/` không import `infrastructure/` hay `adapters/`.
- [ ] **Tách biệt Tiến trình GPU**: Tiến trình HTTP Server không import trực tiếp `torch` nếu không cần thiết; huấn luyện/suy luận nặng chạy qua worker hoặc luồng nền an toàn.
- [ ] **Bảo toàn Trạng thái Đang Chạy**: Không làm gián đoạn lượt quét ảnh đang chạy hoặc cổng Auto-Host `8765`.
- [ ] **Chuẩn Thuật ngữ & UI**: Dùng từ `ảnh` thay cho `tile`, không chứa ký tự emoji bị cấm.
- [ ] **Phân rã Độc lập cho Sub-Agents**: Mỗi Sub-Agent thi công được giao danh sách tệp riêng biệt, không ghi đè lên nhau.

### Bước 4: Ký Duyệt `[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING]`
Sau khi lưu [`uav_geotiff/ARCHITECTURE.md`](file:///C:/Users/HL/Desktop/DETECTION%20RICE_FIELD/uav_geotiff/ARCHITECTURE.md), xuất bản tóm tắt phân công rõ ràng cho từng Agent thi công bắt đầu viết code, kiểm thử `pytest`, và chạy `graphify update .` sau khi hoàn tất.
