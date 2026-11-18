---
name: ui-ux-pro-workstation
description: >-
  Use this skill when designing or updating HTML, CSS, or JavaScript UI/UX
  in UAV GeoTIFF Studio to ensure a professional GIS/CAD workstation interface.
---

# Skill: UI/UX Professional Workstation (`ui-ux-specialist`)

## 1. Tiêu chuẩn Giao diện Phần mềm Kỹ thuật Chuyên nghiệp
- **Không giải thích rườm rà**:
  - Lược bỏ hoàn toàn các câu văn mô tả dài dòng dưới tiêu đề chính (`#step-description`), các phụ đề `<small>` trên thanh điều hướng bước (`01–04`), và các đoạn `.field-help` / `.overview-note` / `.inspector-note` mang tính giải thích lý thuyết.
  - Chỉ giữ lại nhãn chức năng ngắn gọn, sắc nét như các phần mềm kỹ thuật chuyên nghiệp (QGIS, AutoCAD, Pix4D).
- **Đổi toàn bộ chữ `tile` thành `ảnh`**:
  - Trên mọi nhãn HTML và chuỗi JS hiển thị cho người dùng:
    - `Chia lưới tile` → **`Chia lưới ảnh`**
    - `Kiểm tra tile` → **`Kiểm tra ảnh`**
    - `Tile đang xem` → **`Ảnh đang xem`**
    - `tile_000082` → hiển thị là **`Ảnh 000082`** (vẫn giữ `option.value = tile.id` ở tầng dữ liệu để tương thích API).
    - `Biên tile` → **`Biên ảnh`**
    - `Xuất tile GeoTIFF` → **`Xuất ảnh GeoTIFF`**
    - `tile dự kiến` → **`ảnh dự kiến`**

## 2. Chế độ Sáng / Tối & Bố cục Màn hình 24 inch
- **Mặc định Chế độ Sáng (`data-theme="light"`)**, có công tắc `☀️ Sáng` / `🌙 Tối` trên thanh Header.
- Bắt buộc có `[hidden] { display: none !important; }` ở đầu `ui/styles.css`.
- Bố cục Full-bleed (`width: 100%`, không để lề trống hai bên), tận dụng tối đa màn hình 24 inch (`1920×1080`).
- Khi đang quét cuốn chiếu: cho phép người dùng mở bảng **Kiểm duyệt kết quả** và bấm duyệt / đổi nhãn đối tượng của các ảnh đã quét xong ngay trong lúc tiến trình quét vẫn đang chạy.
