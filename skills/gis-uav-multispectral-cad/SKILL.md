---
name: gis-uav-multispectral-cad
description: >-
  Use this skill when processing UAV GeoTIFF rasters, Multispectral bands
  (NIR/RedEdge/NDVI), RGB fallback indices, DEM elevation cleaning, or AutoCAD DXF/DWG export.
---

# Skill: Chuyên gia GIS, Viễn thám UAV & CAD (`gis-uav-specialist`)

## 1. Xử lý Đa phổ & Tự động Fallback sang RGB (`infrastructure/multispectral.py`)
- **Khi có Camera Đa phổ (`Green`, `Red`, `RedEdge`, `NIR`)**:
  - Tính các chỉ số chuẩn hóa:
    $$\text{NDVI} = \frac{\text{NIR} - \text{Red}}{\text{NIR} + \text{Red}}, \quad \text{NDRE} = \frac{\text{NIR} - \text{RedEdge}}{\text{NIR} + \text{RedEdge}}, \quad \text{NDWI} = \frac{\text{Green} - \text{NIR}}{\text{Green} + \text{NIR}}$$
  - Tự động phân nhãn thực vật: `Lúa khỏe / Tán dày`, `Lúa trung bình / Cỏ dại`, `Thực vật thưa / Suy yếu`, `Mặt nước / Ruộng ngập`, `Đất trống / Bờ ruộng`.
- **Khi KHÔNG có Camera Đa phổ (chỉ có ảnh RGB thường)**:
  - Hệ thống tự động phát hiện `multispectral.available == False` và chuyển mượt sang luồng RGB thuần:
    - Tính chỉ số xanh thực vật từ RGB: $\text{ExG} = 2G - R - B$ chuẩn hóa trên $[0, 1]$.
    - Kết hợp với chiều cao tương đối $\Delta Z$ từ tệp `DEM` (nếu có) để tự động gắn nhãn phân tầng mà không cần người dùng bật/tắt thủ công.

## 2. Làm sạch DEM & Phân tầng Cao độ (`infrastructure/dem.py`)
- Tính cao độ tương đối $\Delta Z = Z_{\text{đỉnh trong khung}} - Z_{\text{mặt đất nền xung quanh}}$.
- Phân tầng tự động:
  - $\Delta Z < 0.25\text{ m}$: `Lúa / Cỏ thấp / Mặt ruộng`
  - $0.25\text{ m} \le \Delta Z < 1.2\text{ m}$: `Bụi cây / Cây hoa màu`
  - $\Delta Z \ge 1.2\text{ m}$: `Cây thân gỗ / Cây ăn quả`
- Khi khử nhiễu tệp `DEM` gốc (`repair_dem_anomalies`), luôn giãn nhẹ mặt nạ vùng nhiễu và nội suy theo cao độ mặt ruộng liền kề kèm làm mượt Gaussian ở viền để không để lại dấu vết.

## 3. Xuất Bình đồ Khảo sát AutoCAD (`infrastructure/survey_cad.py`)
- Bảo toàn hệ tọa độ tương đối với `Base X`, `Base Y`.
- Hỗ trợ chèn Block (`INSERT`), vẽ đường đôi song song (`DOUBLE_LINE`) kèm tim đường (`CENTERLINE`) cho mương/đường giao thông, và Polyline khép kín cho công trình.
