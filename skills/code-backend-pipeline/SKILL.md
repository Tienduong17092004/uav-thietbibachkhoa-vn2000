---
name: code-backend-pipeline
description: >-
  Use this skill when modifying the Python backend, HTTP server, project state,
  or streaming detection pipeline in UAV GeoTIFF Studio.
---

# Skill: Code Architect & Streaming Pipeline (`code-architect`)

## 1. Quy tắc An toàn Hệ thống & Trạng thái
- Trước khi sửa code, luôn đọc [`.agents/LESSONS_LEARNED.md`](../../LESSONS_LEARNED.md).
- Trong [`ProjectService.__init__`](../../../uav_geotiff/uav_app/application/service.py), mọi tham chiếu `last_detection_job` hoặc `last_job` đọc từ `project_state.json` phải kiểm tra tệp thực tế trên đĩa (`detections.json`). Nếu tệp không tồn tại, phải reset về `None` để không gây lỗi 400 khi khởi động.
- Trong [`uav_app/__main__.py`](../../../uav_geotiff/uav_app/__main__.py), luôn dùng `_pick_available_port()` để tránh lỗi `WinError 10048`.

## 2. Kiến trúc Quét cuốn chiếu, Gắn nhãn tức thì & Tạm dừng / Tiếp tục (Streaming + Pause/Resume)
Khi nâng cấp [`run_detection` trong `detection_pipeline.py`](../../../uav_geotiff/uav_app/application/detection_pipeline.py) và [`ProjectService` trong `service.py`](../../../uav_geotiff/uav_app/application/service.py):
1. **Xử lý cuốn chiếu từng ảnh (Incremental Image Processing)**:
   - Ngay sau khi quét xong 1 cửa sổ ảnh (`window`), thực hiện gộp khung cục bộ (`fuse_boxes`), cắt ảnh đối tượng (`annotate_object`), tính chỉ số phổ (`NDVI`/`NDRE` hoặc fallback `ExG` trên RGB) + đọc cao độ `DEM` (`enrich_records_with_dem`), và tính `confidence_score` (`estimate_confidence`).
   - Tự động gắn nhãn phân lớp (`sub_class`) và tự duyệt (`accepted_candidate` / `accepted_raw`) cho các khung có độ tin cậy cao.
2. **Ghi `detections.json` & `checkpoint.json` tức thì sau mỗi ảnh**:
   - Bảo toàn các quyết định duyệt (`review_status`, `sub_class`) mà người dùng đã thao tác trên các ảnh trước đó.
   - Ghi `checkpoint.json` lưu tập `completed_keys` (`f"{win_uid}::{category}"`), `scanned_windows`, `completed_regions`, `completed_queries`.
3. **Tạm dừng Giải phóng GPU & Tiếp tục Nội suy (`Pause & Resume`)**:
   - Khi người dùng bấm **`⏸ Tạm dừng (Nhả GPU)`** (`/api/pause` hoặc `/api/cancel`) hoặc tắt ứng dụng đột ngột:
     - Đóng ngay tiến trình `ModelClient` (`client.close()`) để giải phóng 100% VRAM của Card đồ họa cho công việc khác.
     - Giữ nguyên toàn bộ kết quả đã quét trong `detections.json` và đánh dấu trạng thái `paused` (hoặc `cancelled`/`interrupted` đều cho phép Resume).
   - Khi người dùng bấm **`▶ Tiếp tục quét`** (`/api/resume-detection`):
     - Mở lại đúng thư mục `output_dir` của phiên đang dở (`resume=True`), nạp lại `raw_boxes.jsonl`, `detections.json` và `checkpoint.json`.
     - Bỏ qua toàn bộ các cặp `(win_uid, category)` đã có trong `completed_keys`, nạp lại mô hình lên GPU và tiếp tục quét từ ảnh kế tiếp cho đến khi đạt 100%.

## 3. Kiểm thử Bắt buộc
Sau mọi thay đổi ở Backend, chạy lệnh kiểm thử:
```powershell
Set-Location "C:\Users\HL\Desktop\DETECTION RICE_FIELD\uav_geotiff"
& ".venv\Scripts\python.exe" -m pytest -q
```
Đảm bảo 100% bài test vượt qua trước khi bàn giao.
