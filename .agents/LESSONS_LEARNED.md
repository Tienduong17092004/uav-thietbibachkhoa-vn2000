# Bài Học Kinh Nghiệm Kỹ Thuật (`LESSONS_LEARNED.md`)

Tài liệu này lưu trữ các bài học xương máu trong quá trình vận hành **UAV GeoTIFF Studio & WebGPU Survey Portal (`VN2000`)** kết hợp **`LocateAnything-3B`** (`detect_batch.py`) + **`DEM_Stage 1`**. Mọi Sub-Agent bắt buộc đọc trước khi sửa code.

---

## 1. Quản lý Trạng thái `project_state.json` & Khởi động Dịch vụ (`ProjectService.__init__`)
- **Bài học #01**: Mọi tham chiếu `last_detection_job` hoặc `last_job` đọc từ `project_state.json` phải kiểm tra tệp thực tế trên đĩa (`detections.json`). Nếu tệp không tồn tại, phải reset về `None` để không gây lỗi `HTTP 400` khi khởi động.
- **Bài học #02**: Trong `uav_app/__main__.py`, luôn dùng `_pick_available_port()` để tránh lỗi `WinError 10048` khi cổng `8765` / `8766` đang được giữ bởi tiến trình chạy nền.

## 2. Quét Cuốn Chiếu `LocateAnything-3B` & Tạm Dừng Giải Phóng GPU (`Streaming + Pause/Resume`)
- **Bài học #03 (`detect_batch.py` + `model_worker.py`)**:
  - `LocateAnythingBatchDetector` sử dụng **Shared GPU Memory Pinned DMA Pool** (`UAV_SHARED_GPU_MEM_GIB=2.0`, `pin_memory=True`) và luồng `self.dma_stream = torch.cuda.Stream()` riêng biệt để truyền tensor bất đồng bộ (`non_blocking=True`) trong lúc GPU đang chạy `model.generate(...)` ở chế độ `BF16 + SDPA`.
  - Khi người dùng bấm **`⏸ Tạm dừng (Nhả GPU)`**, phải đóng ngay `ModelClient` (`client.close()`) để giải phóng 100% VRAM và ghi `checkpoint.json` lưu tập `completed_keys` (`f"{win_uid}::{category}"`).
- **Bài học #04 (Bảo toàn quyết định duyệt của người dùng)**:
  - Khi gộp khung chồng lấn (`fuse_boxes` / `stitch_large_objects`) trong lúc quét cuốn chiếu, **bắt buộc ưu tiên giữ lại `id`, `review_status` và `sub_class`** của các khung mà người dùng đã duyệt hoặc đã gán nhãn thủ công.

## 3. Đếm Cây Lúa Mới Trồng & Phân Tách Lúa Mới Cấy vs Cỏ Dại Bằng `DEM` ($\Delta Z$)
- **Bài học #05 (`dem.py` & `refinement.py`)**:
  - Tuyệt đối không dùng cao độ tuyệt đối $Z$ của DEM để phân loại vì mặt ruộng có độ nghiêng tự nhiên. Phải lấy **cao độ tương đối cục bộ**:
    $$\Delta Z = \text{Percentile}_{85}(Z_{\text{trong khung}}) - \text{Percentile}_{15}(Z_{\text{vòng đệm bùn 1.5m}})$$
  - Ngưỡng thực nghiệm trên `Ortho_Stage 1_RGB (24-10-2026)` + `DEM_Stage 1 (24-10-2026).tif`:
    - **🌾 Lúa mới cấy thuần (`Newly transplanted rice`)**: $\Delta Z \approx +1,07\text{ cm}$ (`0.8 -> 1.38 cm`), $\text{NDVI} \approx 0,155$, $\text{NDRE} < 0,04$.
    - **🌱 Cỏ dại / Cỏ bờ (`Grass`)**: $\Delta Z \approx +1,84\text{ cm}$ (`>= 1.65 cm`), $\text{NDVI} \ge 0,214$.
    - **🌾+🌱 Lúa lẫn cỏ (`Rice + Partial Grass`)**: $\Delta Z \approx +1,51\text{ cm}$, hỗ trợ tách đôi bằng nút **`✂️ Tách Cỏ & Lúa`**.

## 4. Giải Mã Ảnh Orthomosaic Siêu Lớn (`870 MP` — `26.095 × 33.367 px`) Trên Trình Duyệt
- **Bài học #06**:
  - Không dùng `new Image()` đơn thuần cho ảnh `.JPG`/`.TIF` nặng `> 100 MP` vì giới hạn cấp phát texture của trình duyệt. Phải đọc trực tiếp binary header (`SOF0` JPEG / `IFD` GeoTIFF) để lấy đúng `Width × Height` gốc 100% kết hợp `createImageBitmap` và cắt cửa sổ 1:1.
