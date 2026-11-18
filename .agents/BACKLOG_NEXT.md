# Danh Mục Công Việc Kế Tiếp (`BACKLOG_NEXT.md`)

Tài liệu theo dõi lộ trình phát triển và tối ưu hóa **UAV GeoTIFF Studio & WebGPU Survey Portal (`VN2000`)**.

---

## 1. Hạng Mục Đã Hoàn Tất (`Completed & Verified`)
- [x] **Khôi phục `detect_batch.py` nguyên bản từ `detect_batch.cpython-311.pyc` (`__pycache__.zip`)**:
  - Khôi phục đầy đủ `LocateAnythingBatchDetector` (`BF16`, `SDPA`, `Shared GPU Memory Pinned DMA Pool 2.0 GiB`, `prepare_inputs_pinned`, `predict_from_prepared`, `parse_detections`, `annotate_image`, `process_batch`).
- [x] **Khôi phục Giao diện & Thuật toán Đếm Cây Lúa Mới Trồng + Phân Tích Lúa vs Cỏ bằng `DEM` ($\Delta Z$)**:
  - Nạp trực tiếp file `DEM_Stage 1 (24-10-2026).tif` và `project_state.json` / `detections.json` ngay trên giao diện Web.
  - Tính $\Delta Z = Z_{\text{top,P85}} - Z_{\text{ground,P15}}$, đếm tổng số khóm lúa đơn lẻ bằng biến đổi khoảng cách $L_2$ (`distanceTransform`), hỗ trợ 4 công cụ: `⛰️ Hạ / Khử nhiễu nền DEM`, `📡 Phân tích DEM ΔZ (Lúa vs Cỏ)`, `🌾 Tách & Đếm khóm lúa (~15cm)`, `✂️ Tách Cỏ & Lúa khung lẫn`.
- [x] **Đồng bộ 5 Bộ Kỹ Năng Chuyên Gia (`skills.zip`)**:
  - `architecture-awesome-design`, `code-backend-pipeline`, `gis-uav-multispectral-cad`, `math-computational-geometry`, `ui-ux-pro-workstation`.
- [x] **Khôi phục Ngọn Cây từ Ảnh Thô RTK (`DEM/DSM Bất Biến`) & Tìm Cạnh Song Song FPGA (`Many Pixels at Once`)**.

## 2. Hạng Mục Sẵn Sàng Mở Rộng Tiếp Theo (`Next Up`)
- [ ] **Nạp trực tiếp `project_state.json` (`127 KB`) & `DEM_Stage 1 (24-10-2026).tif` từ máy người dùng**:
  - Khi người dùng upload thêm `project_state.json` hoặc `DEM_Stage 1 (24-10-2026).tif`, tự động đồng bộ vào thư mục `sample/MULTISPECTRAL/Results_Stage 1/` và cập nhật sẵn vào bộ mẫu mặc định.
- [ ] **Xuất báo cáo nông học `.CSV` / `.DXF` phân lớp Lúa mới cấy (`KS_LUA_MOI_CAY`), Cỏ dại (`KS_CO_DAI`), Lúa lẫn cỏ (`KS_LUA_LAN_CO`)** kèm tọa độ VN2000 và cao độ $\Delta Z$ của từng khóm.
