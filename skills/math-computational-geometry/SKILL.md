---
name: math-computational-geometry
description: >-
  Use this skill when working on coordinate transformations, grid slicing,
  polygon intersection, IoU box fusion, or Otsu/spectral refinement math.
---

# Skill: Toán học & Hình học Tính toán (`math-geometry-expert`)

## 1. Phép biến đổi Tọa độ & Chia lưới Ảnh (`domain/geometry.py`)
- Chuyển đổi chính xác giữa tọa độ Pixel $(c, r)$, tọa độ chiếu CRS $(E, N)$ qua ma trận Affine 6 tham số, và tọa độ tương đối so với gốc Base:
  $$\Delta X = E - \text{Base}_X, \quad \Delta Y = N - \text{Base}_Y$$
- Tính bước nhảy lưới ($\text{stride}_x, \text{stride}_y$) và kiểm tra điều kiện bao phủ đối tượng lớn nhất:
  $$\text{Overlap}_{\text{thực tế (cm)}} \ge 2.5 \times D_{\max\text{ (cm)}}$$

## 2. Hình học Đa giác & Gộp khung Chồng lấn (`domain/detection.py`)
- Kiểm tra giao cắt giữa đa giác vùng chọn (`Polyline`) và khung hình chữ nhật của từng ảnh con bằng 3 điều kiện: đỉnh đa giác trong hình chữ nhật, tâm/góc hình chữ nhật trong đa giác (Ray-casting `_point_in_poly`), và giao cắt đoạn thẳng (`_segments_intersect` dùng hướng CCW).
- Khi quét cuốn chiếu (Streaming Detection):
  - Khi gộp khung mới từ ảnh vừa quét với danh sách đối tượng của các ảnh trước (`fuse_boxes` / `stitch_large_objects`), **phải ưu tiên giữ lại `id`, `review_status` và `sub_class`** của các khung mà người dùng đã duyệt hoặc đã gắn nhãn.

## 3. Tách nền & Co khung Sát tán (`infrastructure/refinement.py`)
- Kết hợp ngưỡng Otsu tự động trên phổ `NDVI` (khi có cam phổ) hoặc chỉ số xanh thực vật `ExG` + độ lệch màu LAB (khi chỉ có ảnh RGB) để tìm đường bao (`bounding box`) sát tán thực vật, loại bỏ bóng râm và nền bùn/nước.
