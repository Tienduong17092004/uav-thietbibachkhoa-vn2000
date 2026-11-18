# Chính sách Phân Role & Quản trị Cấp Bậc Model (`MODEL_TIERS_POLICY.md`)
# Multi-Agent Role Assignment & Model Tier Governance Policy

Tài liệu này quy định chi tiết kiến trúc điều phối đa tác tử (Multi-Agent Governance) cho dự án **`UAV_GeoTIFF_WebGPU_Survey_VN2000`**, được thực thi tự động trong mã nguồn tại `uav_app/infrastructure/agent_governance.py` và cấu hình tại `config/agent_model_tiers.json`.

---

## 1. Tổng quan Quy tắc Điều phối (Core Governance Rules)

1. **Khảo sát Dự án Ban đầu (`Initial 5-Agent Hydrogen Survey`)**:
   - Khi bắt đầu đọc lại dự án, khởi chạy đồng thời **5 agent `Gemini 4 Hydrogen`** để khảo sát toàn bộ cấu trúc mã nguồn, kiến trúc, tài liệu và cấu hình.
2. **Lập Kế hoạch & Kiến trúc bởi `Model 4 Argon High` (`Phase 1 — Planning & Architecture`)**:
   - Khi người dùng giao việc, **`Model 4 Argon High`** (`argon_high`) lập kế hoạch cụ thể, chi tiết và thiết kế kiến trúc dự án.
   - **Cổng Duyệt Kiến trúc (`Architecture Approval Gate`)**: Bắt buộc phải duyệt kiến trúc xong (`approve_architecture`) mới được phép bắt đầu phân role (`assign_role`) cho các agent con.
3. **Phân Role & Chọn Mức Nỗ lực theo Độ khó (`Difficulty-Based Effort Scaling`)**:
   - Sau khi duyệt kiến trúc, từng agent con được gán role kèm mức nỗ lực (`effort`: `low`, `medium`, `high`, `max`) tương ứng với độ khó của tác vụ (`low`, `medium`, `high`, `critical`).
4. **Thực thi Kế hoạch Cụ thể & Vòng lặp Test bằng `Gemini 4 Hydrogen` (`Phase 2 — Execution & Test Loop`)**:
   - Các kế hoạch cụ thể và vòng lặp viết code / chạy kiểm thử (`code & test loop`) do **`Gemini 4 Hydrogen`** (`hydrogen`) đảm nhận.
   - Nhờ mức tiêu thụ token thấp, cho phép gọi cùng lúc lên đến **300 agent `Gemini 4 Hydrogen` đồng thời** (`MAX_CONCURRENT_HYDROGEN = 300`).
5. **Tự sửa Lỗi 2 Lần & Báo Task qua `Model 4 Carbon` (`2-Strike Self-Fix & Escalation Rule`)**:
   - Khi code hoặc test báo lỗi, agent `Gemini 4 Hydrogen` tự sửa lỗi (`SELF_FIX`).
   - Nếu **sau khi sửa 2 lần vẫn không được** (`MAX_HYDROGEN_SELF_FIX_ATTEMPTS = 2`), bắt buộc phải báo/chuyển task qua cho **`Model 4 Carbon`** giải quyết (`ESCALATE_TO_CARBON`).
6. **Tối ưu Hàm Chuyên sâu & Giới hạn Đồng thời `Model 4 Carbon` (`Phase 3 — Deep Optimization & Cap`)**:
   - Những vấn đề quá chuyên sâu cần tối ưu hàm/thuật toán phức tạp (`requires_deep_optimization = True`) hoặc task chuyển lên sau 2 lần lỗi được xử lý bởi **`Model 4 Carbon`** (`carbon`).
   - **Giới hạn nghiêm ngặt**: Không gọi đồng thời quá **10 agent `Model 4 Carbon`** (`MAX_CONCURRENT_CARBON = 10`).
7. **Sử dụng Linh hoạt `Model 4 Argon` (`Flexible Argon Usage`)**:
   - Nếu công việc cần dùng đến **`Model 4 Argon`** (`argon`), hệ thống có thể tùy ý sử dụng linh hoạt (`use_argon = True`) mà không bị khóa cứng hạn ngạch.

---

## 2. Bảng Định mức Cấp bậc Model (Model Tier Specification Table)

| Model Tier (`ModelTier`) | Mã Định danh | Vai trò Chính | Giới hạn Gọi Đồng thời (`max_concurrent`) | Quy tắc Tự sửa / Escalation |
| :--- | :--- | :--- | :---: | :--- |
| **Model 4 Argon High** | `argon_high` | Lập kế hoạch chi tiết, thiết kế & duyệt kiến trúc dự án trước khi phân role | Linh hoạt (`Unlimited / Flexible`) | Chốt cổng kiến trúc (`Architecture Gate`) |
| **Model 4 Argon** | `argon` | Tổng hợp kiến trúc, điều phối liên phân hệ, tùy ý sử dụng khi công việc cần | Linh hoạt (`Unlimited / Flexible`) | Sử dụng tùy ý theo nhu cầu công việc |
| **Gemini 4 Hydrogen** | `hydrogen` | Khảo sát nhanh (5 agents đầu), thực thi kế hoạch cụ thể, chạy test vòng lặp | **Tối đa 300 agents** (`<= 300`) | Tự sửa lỗi tối đa **2 lần** (`<= 2`); thất bại lần 3 chuyển sang `carbon` |
| **Model 4 Carbon** | `carbon` | Giải quyết task do Hydrogen báo lên sau 2 lần sửa lỗi thất bại; tối ưu hàm chuyên sâu | **Tối đa 10 agents** (`<= 10`) | Xử lý dứt điểm thuật toán & lỗi phức tạp |

---

## 3. Hợp đồng Giao diện Phần mềm (`uav_app.infrastructure.agent_governance`)

```python
from uav_app.infrastructure.agent_governance import (
    AgentGovernancePolicy,
    ModelTier,
    TaskDifficulty,
)

policy = AgentGovernancePolicy()

# Bước 1: Model 4 Argon High lập và duyệt kiến trúc
policy.create_architecture_plan("plan-vn2000", "Kiến trúc WebGPU + Domain + TPU Offload")
policy.approve_architecture("plan-vn2000", approved_by=ModelTier.ARGON_HIGH.value)

# Bước 2: Phân role theo độ khó sau khi kiến trúc đã duyệt
role_std = policy.assign_role("task-web-server", difficulty="medium")
# -> assigned_tier="hydrogen", effort="medium"

role_opt = policy.assign_role("task-spline-opt", difficulty="critical", requires_deep_optimization=True)
# -> assigned_tier="carbon", effort="max"

# Bước 3: Kiểm soát số lượng sub-agent đồng thời (Hydrogen <= 300, Carbon <= 10)
policy.acquire_agent_slot("hydrogen", count=5)
policy.acquire_agent_slot("carbon", count=2)

# Bước 4: Vòng lặp test & tự sửa 2 lần trước khi báo qua Model 4 Carbon
r1 = policy.record_test_failure("task-web-server", "AssertionError: port mismatch")
# -> attempt=1, action="SELF_FIX", assigned_tier="hydrogen", escalated=False
r2 = policy.record_test_failure("task-web-server", "AssertionError: header missing")
# -> attempt=2, action="SELF_FIX", assigned_tier="hydrogen", escalated=False
r3 = policy.record_test_failure("task-web-server", "AssertionError: persistent bug")
# -> attempt=3, action="ESCALATE_TO_CARBON", assigned_tier="carbon", escalated=True

# Bước 5: Tự động spam số lượng agent và chia task theo file rule
# (// tự động spam số lượng agent và chia task theo file rule\)
auto_summary = policy.auto_divide_and_spawn_tasks()
# -> survey_agents_count=5, architecture_sign_off="[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING]", rule_compliance=True
```

---

## 4. Tự Động Chia Task Theo File Rule, Đẩy TPU `>15 Phút` & Quản Lý Key 7 Cột Google Sheet

1. **Tự động Spam Agent & Chia Task (`// tự động spam số lượng agent và chia task theo file rule\`)**:
   - Hàm `auto_divide_and_spawn_tasks()` tự động khởi chạy 5 agent `Gemini 4 Hydrogen` (`flash_lite`) khảo sát, duyệt kiến trúc bởi `Model 4 Argon High` (`[ARCHITECTURE SIGN-OFF: APPROVED FOR CODING]`), và chia 6 nhóm tác vụ cốt lõi theo độ khó (`low`, `medium`, `high`, `critical`) kèm cấp phát slot (`MAX_CONCURRENT_HYDROGEN = 300`, `MAX_CONCURRENT_CARBON = 10`).
2. **Tự động Đẩy Tác Vụ `> 15 Phút` (`> 900s`) Lên Google TPU & Phân Quyền Key**:
   - Khi upload ảnh nhận diện hoặc cập nhật mô hình YOLO nhận diện vật thể mới, nếu thời gian ước tính `> 15 phút` (`> 900 giây`) thì tự động đẩy lên Google TPU.
   - Chỉ key **Admin** (`role = "admin"`) hoặc key khách được Admin cấp quyền `allow_tpu = True` mới được phép sử dụng tính năng TPU `> 15 phút` (key khách không có quyền sẽ bị từ chối với `403 Forbidden`).
3. **Quản Lý Key 7 Cột Google Sheet & Lưu Trữ Google Drive (`1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN`)**:
   - Quản lý key theo bảng 7 cột Google Sheet (`Người nhận,SĐT người nhận,Key,Mục đích,Thời gian cấp,Thời gian hết hạn,Tình trạng`): báo đỏ (`status_color = "red"`) khi thời gian còn lại `<= 1/3`, tô màu xanh (`status_color = "green"`) khi `> 1/3`. Chỉ key Admin mới xem/tạo/xóa được key trên web; key khách bị ẩn hoàn toàn (`403 Forbidden`).
   - Dữ liệu xử lý được lưu tại thư mục Google Drive: `https://drive.google.com/drive/u/3/folders/1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN` (`1Q9P-T98xdXxd-4NIijdI_AomEaHiTSDN`).

