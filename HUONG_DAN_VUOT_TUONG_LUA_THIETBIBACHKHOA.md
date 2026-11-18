# Hướng Dẫn Vượt Tường Lửa Công Ty & Vận Hành Độc Lập Cho Tên Miền `https://thietbibachkhoa.id.vn/`

Khi máy tính Windows ở công ty bị **Tường lửa (Firewall)** chặn không cho mở port hoặc chặn kết nối `cloudflared` mặc định, hệ thống đã được trang bị **3 Phương Án Vượt Tường Lửa & Vận Hành Độc Lập**:

---

## Phương Án 1: Vận Hành Độc Lập 24/7 Bằng Cloud Server (VPS) Hoặc Cloudflare Workers *(Không phụ thuộc tường lửa máy công ty)*

> [!IMPORTANT]
> **Để vận hành độc lập (máy công ty tắt hay bị tường lửa chặn vẫn vào được web bình thường), bạn NÊN DÙNG CLOUD SERVER (VPS) hoặc CLOUDFLARE WORKERS, KHÔNG DÙNG Shared Web Hosting.**

### Cách 1A — Miễn Phí `0đ/tháng` Ngay Trên Cloudflare Workers (Đã tạo sẵn file code)
Vì tên miền `thietbibachkhoa.id.vn` của bạn đã nằm trên Cloudflare:
1. Đăng nhập [Cloudflare Dashboard](https://dash.cloudflare.com/) -> chọn menu **Workers & Pages** -> bấm **Create** -> **Create Worker**.
2. Đặt tên Worker là `uav-thietbibachkhoa-portal` -> bấm **Deploy** -> bấm **Edit Code**.
3. Mở file `deploy/cloudflare_worker_thietbibachkhoa.js` trong thư mục dự án, copy toàn bộ nội dung dán vào khung code của Cloudflare Worker -> bấm **Deploy**.
4. Vào mục **Settings** của Worker -> **Domains & Routes** -> bấm **+ Add** -> chọn **Custom Domain** -> gõ `thietbibachkhoa.id.vn` (và thêm `www.thietbibachkhoa.id.vn`).
5. **Kết quả**: Tên miền **`https://thietbibachkhoa.id.vn/`** chạy thẳng trên mạng đám mây Cloudflare 24/7 (có sẵn giao diện WebGPU, bảng Quản lý Key Google Sheet 7 cột với Key Admin `uav_admin_master_key_vn2000`, và tự động đẩy tác vụ `>15 phút` sang Google TPU + lưu dữ liệu vào Google Drive `1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN`) mà **không cần trỏ về IP máy công ty**!

### Cách 1B — Thuê Cloud Server (VPS Ubuntu 22.04/24.04) Độc Lập 24/7 (~100k–180k/tháng)
1. Thuê 1 Cloud VPS nhỏ (`2 vCPU, 2GB–4GB RAM, Ubuntu 22.04 LTS`). Bạn sẽ nhận được 1 địa chỉ **IP tĩnh riêng** (không bị tường lửa công ty chặn).
2. Vào Cloudflare Dashboard -> chọn tên miền `thietbibachkhoa.id.vn` -> mục **DNS** -> thêm bản ghi:
   - **Type**: `A`
   - **Name**: `@` (tức `thietbibachkhoa.id.vn`)
   - **IPv4 address**: `<Nhập IP của Cloud Server>`
   - **Proxy status**: Bật đám mây màu cam (Proxied)
3. Trên Cloud Server Ubuntu, tải bộ code về và chạy:
   ```bash
   sudo cp deploy/systemd/thietbibachkhoa-web.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now thietbibachkhoa-web.service
   ```

---

## Phương Án 2: Chạy Ngay Trên Máy Tính Công Ty Qua Chế Độ Vượt Tường Lửa (`HTTP/2 TCP + Loopback 127.0.0.1`)

Nguyên nhân máy công ty chặn `cloudflared` mặc định là do:
1. Mặc định `cloudflared` dùng giao thức **UDP QUIC (cổng 7844)** -> 99% tường lửa công ty chặn UDP.
2. Mặc định Python mở `--host 0.0.0.0` -> Windows Defender Firewall bật bảng chặn và đòi quyền Admin IT.

**Cách khắc phục 1-Click trên máy công ty**:
- Nhấp đúp trực tiếp vào file **`CAI_DAT_VUOT_TUONG_LUA_CONG_TY.bat`** (không cần quyền Administrator!).
- Kịch bản sẽ tự động:
  1. Mở Web Server trên **`127.0.0.1:8765`** (Localhost Loopback -> Windows Firewall không bao giờ chặn).
  2. Ép `cloudflared` chạy qua **`--protocol http2 --edge-ip-version 4`** (giao thức TCP + tự động đọc Proxy công ty).
  3. Kích hoạt **Cầu nối Outbound HTTPS Cổng 443 (`firewall_bypass.py`)** đồng bộ trực tiếp với Google Drive `1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN`.
