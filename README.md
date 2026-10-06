# BTVN#3 · Agent đặt vé máy bay bằng LangChain / LangGraph

Môn **SE373.R11 · Kỹ thuật xây dựng hệ thống Agentic AI** · Bài 03 *Agent fundamentals*

| | |
|---|---|
| **Sinh viên** | Đỗ Tấn Tường |
| **MSSV** | 23521749 |
| **Báo cáo nộp** | [`BTTH3_23521749_DoTanTuong.pdf`](BTTH3_23521749_DoTanTuong.pdf) |
| **Báo cáo chi tiết** | [`BAO_CAO.md`](BAO_CAO.md) |

Agent đặt 1 vé máy bay SGN → DAD ngày 2026-10-07, bay trước 12:00, giá không quá 2 triệu, theo công thức **agent = model + harness**. Bài làm gồm:

- **tool mockup** chạy trên một backend giả lập có cài sẵn 9 tình huống sự cố;
- một **lớp harness** bao quanh model, dùng chung cho mọi mẫu;
- **ba mẫu thiết kế** agent: ReAct, Plan-then-Execute và Lai;
- **script đánh giá** so sánh ba mẫu, kèm nhóm đối chứng không harness.

Không cần API key: mặc định code chạy với model giả lập, kết quả lặp lại được.

## Mục lục

1. [Yêu cầu đề bài và phần code tương ứng](#1-yêu-cầu-đề-bài-và-phần-code-tương-ứng)
2. [Bắt đầu nhanh](#2-bắt-đầu-nhanh)
3. [Cấu trúc thư mục](#3-cấu-trúc-thư-mục)
4. [Kiến trúc tổng thể](#4-kiến-trúc-tổng-thể)
5. [Tool mockup](#5-tool-mockup)
6. [Lớp harness](#6-lớp-harness)
7. [Ba mẫu thiết kế agent](#7-ba-mẫu-thiết-kế-agent)
8. [Cài đặt](#8-cài-đặt) · [Các file không có sẵn trong repo](#81-các-file-không-có-sẵn-trong-repo)
9. [Hướng dẫn chạy](#9-hướng-dẫn-chạy)
10. [Kịch bản kiểm thử](#10-kịch-bản-kiểm-thử)
11. [Phương pháp đánh giá](#11-phương-pháp-đánh-giá)
12. [Kết quả](#12-kết-quả)
13. [Xử lý lỗi thường gặp](#13-xử-lý-lỗi-thường-gặp)
14. [Hạn chế và hướng phát triển](#14-hạn-chế-và-hướng-phát-triển)
15. [Tài liệu tham khảo](#15-tài-liệu-tham-khảo)

## 1. Yêu cầu đề bài và phần code tương ứng

| Yêu cầu | Cài đặt | Xem thêm |
|---|---|---|
| Tìm hiểu LangChain, LangGraph | ReAct dùng `create_agent` + `AgentMiddleware` của LangChain; Plan-then-Execute và Lai dựng bằng `StateGraph` của LangGraph | [Mục 7](#7-ba-mẫu-thiết-kế-agent) |
| Tạo tool mockup | `tools_mock.py`: 5 tool trên backend giả lập `FlightWorld`, 9 kịch bản | [Mục 5](#5-tool-mockup) |
| 1. Đủ các lớp harness | `harness.py`: ràng buộc là dữ liệu (`Constraints`, `Policy`, `Budget`), tiêu chí hoàn thành kiểm bằng code (`verify_completion`, `verify_answer`), kiểm quyền (`authorize`), bàn giao (`Handoff`). Thêm phát hiện lặp, phát hiện bế tắc, ngân sách và trace | [Mục 6](#6-lớp-harness) |
| 2. Ba mẫu thiết kế | `agent_react.py` (ReAct), `agent_plan_execute.py` (Plan-then-Execute), `agent_hybrid.py` (Lai) | [Mục 7](#7-ba-mẫu-thiết-kế-agent) |
| 3. Đánh giá hiệu quả | `danh_gia.py`: 9 kịch bản × 3 mẫu, thêm nhóm đối chứng ReAct không harness, kết quả kiểm trực tiếp từ backend | [Mục 11](#11-phương-pháp-đánh-giá), [Mục 12](#12-kết-quả) |

## 2. Bắt đầu nhanh

```powershell
git clone https://github.com/Tuong1308/23521749-DoTanTuong-SE373.R11-BTTH3.git
cd 23521749-DoTanTuong-SE373.R11-BTTH3
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python danh_gia.py                                   # toàn bộ đánh giá, in bảng kết quả
python main.py --pattern react --scenario S2         # xem trace một kịch bản
```

Chi tiết cài đặt và các file cần tự tạo (bị `.gitignore` bỏ qua) ở [Mục 8](#8-cài-đặt), các cách chạy ở [Mục 9](#9-hướng-dẫn-chạy).

## 3. Cấu trúc thư mục

```
├── tools_mock.py          Tầng tool: backend giả lập FlightWorld, 5 tool, 9 kịch bản S1–S9, bọc thành LangChain tool
├── harness.py             Lớp harness dùng chung cho cả 3 mẫu (ràng buộc, kiểm quyền, kiểm hoàn thành, bàn giao)
├── model_gia.py           Model giả lập (ModelGia) và get_model() để đổi sang LLM thật
├── agent_react.py         Mẫu 1 · ReAct: create_agent + HarnessMiddleware
├── agent_plan_execute.py  Mẫu 2 · Plan-then-Execute: StateGraph planner → review → executor → finish
├── agent_hybrid.py        Mẫu 3 · Lai: dùng lại graph mẫu 2, thêm cạnh executor → planner khi kết quả lệch đáng kể
├── main.py                Chạy một mẫu trên một kịch bản và in trace từng vòng
├── danh_gia.py            Chạy toàn bộ đánh giá (9 kịch bản × 4 cấu hình), audit backend, ghi kết quả vào ket_qua/
├── requirements.txt       Thư viện cần cài
├── README.md              File này
├── BAO_CAO.md             Báo cáo chi tiết dạng Markdown
├── BTTH3_23521749_DoTanTuong.pdf   Báo cáo nộp (có ảnh chạy kịch bản)
├── .gitignore             Danh sách file không đưa lên git (xem Mục 8.1)
└── ket_qua/               Sinh ra khi chạy danh_gia.py (chạy lại sẽ ghi đè)
    ├── ket_qua_danh_gia.md    Bảng kết quả: hiệu quả, chi phí, từng kịch bản, vi phạm
    ├── ket_qua_danh_gia.json  Dữ liệu thô của từng lần chạy
    └── traces/                Trace JSON từng cặp (kịch bản, mẫu), vd S2_ReAct.json, S6_ReAct_noharness.json
```

Thứ tự nên đọc code: `tools_mock.py` → `harness.py` → `agent_react.py` → `agent_plan_execute.py` → `agent_hybrid.py` → `danh_gia.py`. `model_gia.py` chỉ cần đọc nếu muốn biết model giả lập ra quyết định thế nào.

## 4. Kiến trúc tổng thể

```
                 main.py / danh_gia.py
                          │  chọn kịch bản (tools_mock.SCENARIOS) và mẫu
                          ▼
   agent_react.py   agent_plan_execute.py   agent_hybrid.py      ← 3 mẫu, cùng chữ ký run(h, model, request)
          │                  │                     │
          └──────── model_gia.get_model() ─────────┘              ← cùng một model
                             │ model đề xuất gọi tool
                             ▼
                  harness.Harness.call_tool()                     ← cửa duy nhất để gọi tool
        kiểm quyền → phát hiện lặp → chạy tool → bế tắc → ngân sách
                             │
                             ▼
                  tools_mock.FlightWorld                          ← backend giả lập (nguồn sự thật)
```

- Mỗi lần chạy tạo mới một `FlightWorld(scenario)` và một `Harness(world)`, nên các lần chạy không ảnh hưởng nhau.
- Cả 3 mẫu đều gọi tool qua `Harness.call_tool()`. Vì vậy harness không phụ thuộc mẫu thiết kế, và khác biệt đo được giữa các mẫu chỉ đến từ kiến trúc vòng lặp.
- Khi agent báo xong, `Harness.finalize()` đọc lại backend để kiểm tiêu chí hoàn thành. Nếu không đạt, hoặc khi harness dừng giữa chừng, `Harness.make_handoff()` tạo gói bàn giao 4 trường.
- `danh_gia.py` còn tự audit backend sau mỗi lần chạy, độc lập với harness, để tính tỷ lệ thành công và số vi phạm.

## 5. Tool mockup

Mọi tool trả về JSON có trường `status` (`ok`, `sold_out`, `invalid_param`, `error`, `not_found`, …). Khi `status` khác `ok`, kết quả kèm `hint` gợi ý bước tiếp theo, để model đổi hướng thay vì gọi lại y hệt.

| Tool | Tham số | Chức năng | Tác dụng phụ |
|---|---|---|---|
| `search_flights` | `origin`, `dest`, `date` (YYYY-MM-DD) | Tìm chuyến bay | Không |
| `check_seat` | `flight_id` | Kiểm còn ghế và giá hiện tại | Không |
| `book_seat` | `flight_id` | Giữ chỗ, tạo booking trạng thái `held` | **Có** |
| `pay` | `booking_code` | Thanh toán, không hoàn tác được | **Có** |
| `get_booking` | `booking_code` | Đọc trạng thái `held` / `pending` / `confirmed` | Không |

Mỗi kịch bản (xem [Mục 10](#10-kịch-bản-kiểm-thử)) cấu hình backend khác nhau: chuyến hết chỗ, giá đổi, dịch vụ timeout, vé không hoàn…

## 6. Lớp harness

Mỗi lần model muốn gọi tool, `Harness.call_tool()` kiểm theo thứ tự:

1. **Kiểm quyền** (`authorize`) trước khi chạy tool.
2. **Phát hiện lặp**: cùng tool, cùng tham số 3 lần trong 6 vòng gần nhất → dừng `LOOP`. `get_booking` được miễn vì chờ xác nhận là polling hợp lệ.
3. **Chạy tool** và ghi kết quả vào trace.
4. **Phát hiện bế tắc**: tiến độ (chưa có dữ liệu → … → đã xác nhận) đứng yên 5 lượt tool liên tiếp → dừng `STALL`.
5. **Ngân sách**: vượt trần lượt model, lượt tool, token hoặc thời gian → dừng `BUDGET`. Kiểm cuối cùng để không che mất lỗi gốc.

### 6.1 Các thành phần chính

| Thành phần | Lớp harness | Vai trò |
|---|---|---|
| `Constraints` | Ràng buộc là dữ liệu | Yêu cầu người dùng (tuyến, ngày, giờ bay trước 12:00, giá ≤ 2.000.000đ) và hàm `violations()`. Dùng ở 3 chỗ: đưa vào prompt, chặn `book_seat`, kiểm lại khi hoàn thành |
| `Policy` | Ràng buộc là dữ liệu | Quyền của agent: tool cho phép, tool chỉ đọc, hạn mức tự thanh toán 1.500.000đ, vé không hoàn cần duyệt, tối đa 1 booking đang giữ |
| `Budget` | Ràng buộc là dữ liệu | Trần 12 lượt model, 16 lượt tool, 40.000 token, 60 giây |
| `verify_completion()` | Tiêu chí hoàn thành | Đọc lại backend: vé phải `confirmed`, đã thanh toán, thỏa ràng buộc, giá khớp giá đã thấy |
| `verify_answer()` | Tiêu chí hoàn thành | Mã chuyến, mã booking, số tiền trong câu trả lời phải có trong kết quả tool (chống bịa) |
| `authorize()` | Kiểm quyền | Trả `ALLOW` / `DENY` / `ASK_HUMAN` cho từng lời gọi tool |
| `Handoff`, `make_handoff()` | Bàn giao | Gói 4 trường khi dừng bất thường |
| `LoopDetector` | Bổ trợ | Phát hiện `LOOP` và `STALL` |

### 6.2 Kiểm quyền

| Quyết định | Khi nào | Harness làm gì |
|---|---|---|
| `ALLOW` | Tool chỉ đọc hợp lệ; `book_seat` chuyến thỏa ràng buộc; `pay` trong hạn mức | Chạy tool |
| `DENY` | Tool lạ, thiếu tham số, ngày sai định dạng; `book_seat` chuyến chưa thấy trong kết quả tool hoặc vi phạm ràng buộc; đã giữ booking khác; `pay` booking không do agent tạo | Không chạy tool, trả `{"status": "denied", "reason", "hint"}` để model đổi hướng |
| `ASK_HUMAN` | `pay` vượt 1.500.000đ hoặc vé không hoàn | Dừng và bàn giao cho người duyệt; với `--approve` thì người duyệt đồng ý và chạy tiếp |

### 6.3 Bàn giao

Mọi kiểu dừng bất thường (`NEED_HUMAN`, `LOOP`, `STALL`, `BUDGET`, `NOT_DONE`, `PLAN_FAILED`, `INVALID_PLAN`) đều in gói bàn giao 4 trường. Ví dụ kịch bản S7:

```
DỪNG [NEED_HUMAN]
  Lý do     : pay({'booking_code': 'BK101'}) cần phê duyệt: vé không hoàn
  Trạng thái: tiến độ: đã giữ chỗ; model_calls: 4; tool_calls: 3; tác dụng phụ: ['BK101: đang GIỮ CHỖ VJ602 1,150,000đ']
  Đã thử    :
   - search_flights(SGN, DAD, 2026-10-07) → ok
   - check_seat(VJ602) → ok
   - book_seat(VJ602) → ok
  Hỏi người : Duyệt thanh toán BK101 (VJ602, 1,150,000đ, KHÔNG hoàn)? Đồng ý → pay; Từ chối → huỷ giữ chỗ.
```

## 7. Ba mẫu thiết kế agent

Cả ba mẫu có cùng hàm `run(h, model, request)`, dùng chung harness và model.

### 7.1 ReAct (`agent_react.py`)

```
START → model ⇄ tools → END        (create_agent của LangChain)
```

Mỗi vòng, model đọc toàn bộ lịch sử, chọn 1 tool, nhận kết quả rồi suy luận tiếp. Harness gắn vào qua `HarnessMiddleware`:

| Hook | Việc |
|---|---|
| `wrap_tool_call` | Chuyển mọi lời gọi tool qua `Harness.call_tool()` |
| `wrap_model_call` | Đếm lượt model và token |
| `before_model` | Harness đã ra lệnh dừng → kết thúc kèm gói bàn giao |
| `after_model` | Model thôi gọi tool → `finalize()` kiểm tiêu chí hoàn thành |

**Ưu:** thích nghi từng bước. **Nhược:** mỗi bước một lượt model, token tăng dần theo số vòng.

### 7.2 Plan-then-Execute (`agent_plan_execute.py`)

```
START → planner → review → executor ⟲ → finish → END        (StateGraph của LangGraph)
```

- **planner**: gọi model 1 lần để lấy kế hoạch JSON, validate bằng Pydantic (`Plan`, `Step`).
- **review**: duyệt kế hoạch trước khi chạy: tool hợp lệ, không vượt ngân sách, liệt kê bước có tác dụng phụ.
- **executor**: chạy từng bước, không gọi model. `$pick` (chuyến rẻ nhất trong kết quả tìm kiếm) và `$booking` (mã từ `book_seat`) được điền từ kết quả bước trước. Có thử lại khi timeout và polling khi `pending`.
- Bước nào lệch là dừng `PLAN_FAILED` và bàn giao; mẫu này không lập lại kế hoạch.

**Ưu:** rẻ (1 lượt model), duyệt được kế hoạch. **Nhược:** gãy khi thế giới lệch khỏi giả định lúc lập kế hoạch.

### 7.3 Lai (`agent_hybrid.py`)

```
START → planner → review → executor ⟲ → finish → END
            ▲                    │
            └── lệch đáng kể ────┘   (tối đa 4 lần lập lại kế hoạch)
```

Dùng lại graph của Plan-then-Execute, thêm cạnh `executor → planner`. Planner được gọi lại khi một bước trả `status` khác `ok`, hoặc khi `significant_change()` thấy kết quả lệch đáng kể (giá vượt ngân sách, tìm không ra chuyến). Planner nhận toàn bộ kết quả đã có để lập kế hoạch cho phần còn lại.

**Ưu:** ca êm rẻ như Plan-then-Execute, gặp biến cố vẫn xử lý được như ReAct. **Nhược:** luồng 2 tầng, khó debug hơn.

## 8. Cài đặt

Yêu cầu: **Python 3.10 trở lên** (đã chạy thử với Python 3.13, `langchain` 1.4, `langgraph` 1.2).

**Windows (PowerShell):**

```powershell
cd 23521749-DoTanTuong-SE373.R11-BTTH3
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Nếu PowerShell báo "running scripts is disabled", chạy lệnh dưới một lần rồi kích hoạt lại môi trường:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 8.1 Các file không có sẵn trong repo

Một số file và thư mục bị `.gitignore` bỏ qua nên **không có khi clone về**. Người chạy tự tạo những thứ cần thiết theo bảng dưới:

| File / thư mục | Vì sao không đưa lên | Cách tạo lại |
|---|---|---|
| `.venv/` | Môi trường ảo nặng và phụ thuộc máy, hệ điều hành | Tạo bằng `python -m venv .venv` rồi `pip install -r requirements.txt` (phần trên) |
| `__pycache__/`, `*.pyc` | Bytecode Python sinh tự động | Không cần làm gì, Python tự tạo khi chạy |
| `.env` | Có thể chứa API key, không được đưa lên git | **Chỉ cần khi chạy với LLM thật.** Code không tự đọc file `.env`; đặt biến môi trường trực tiếp trong terminal như [Mục 9.5](#95-chạy-với-llm-thật-tuỳ-chọn). Không bao giờ commit API key |
| `.vscode/`, `.idea/`, `Thumbs.db`, `.DS_Store` | Cấu hình riêng của IDE / hệ điều hành | Không cần |
| `anh_minh_chung/`, `ket_qua/tong_quan.html`, `~$*.docx` | File nháp cá nhân khi làm báo cáo | Không cần cho việc chạy code |

Thư mục `ket_qua/` **có sẵn** trong repo (kết quả lần chạy của tác giả). Chạy lại `python danh_gia.py` sẽ ghi đè các file trong đó bằng kết quả trên máy bạn; với model giả lập, số liệu phải giống hệt bảng ở [Mục 12](#12-kết-quả).

Kiểm tra nhanh sau khi cài đặt:

```powershell
python -c "import langchain, langgraph; print('langchain', langchain.__version__)"
python main.py --pattern react --scenario S1
```

Nếu cuối output có dòng `Đạt tiêu chí hoàn thành (kiểm bằng code): True` là môi trường đã sẵn sàng.

## 9. Hướng dẫn chạy

### 9.1 Chạy toàn bộ đánh giá

```powershell
python danh_gia.py
```

Chạy 9 kịch bản trên 4 cấu hình (ReAct, Plan-then-Execute, Lai, ReAct không harness), mất vài giây. Sau mỗi lần chạy, script đọc lại trạng thái backend để kiểm kết quả, không dựa vào lời agent tự báo.

- Terminal in bảng tổng hợp theo mẫu và bảng kết quả từng kịch bản.
- Bảng đầy đủ ghi vào `ket_qua/ket_qua_danh_gia.md`; dữ liệu thô ở `ket_qua/ket_qua_danh_gia.json`; trace từng lần chạy ở `ket_qua/traces/`.

### 9.2 Chạy một kịch bản và xem trace

```powershell
python main.py --pattern react --scenario S2
```

Cú pháp: `python main.py --pattern <mẫu> --scenario <kịch bản> [--approve] [--no-harness] [--model <tên>]`.
Thay phần trong `< >` bằng giá trị cụ thể. Phần trong `[ ]` có thể bỏ.

| Tham số | Giá trị | Ý nghĩa |
|---|---|---|
| `--pattern` | `react`, `plan`, `hybrid` | Mẫu thiết kế. Mặc định `react` |
| `--scenario` | `S1` … `S9` | Kịch bản ([Mục 10](#10-kịch-bản-kiểm-thử)). Mặc định `S2` |
| `--approve` | | Giả lập người duyệt đồng ý khi harness yêu cầu phê duyệt |
| `--no-harness` | | Tắt harness để đối chứng |
| `--model` | vd `anthropic:claude-sonnet-5-5` | Dùng LLM thật thay cho model giả lập |

### 9.3 Đọc trace

| Nhãn | Nội dung |
|---|---|
| `[model_call]` | Một lượt gọi model và số token ước lượng |
| `[tool]` | Lời gọi tool và kết quả trả về |
| `[permission]` | Quyết định kiểm quyền (`DENY` / `ASK_HUMAN`) |
| `[plan]`, `[plan_review]` | Kế hoạch và bước duyệt kế hoạch (Plan-then-Execute, Lai) |
| `[người duyệt]`, `[human_approved]` | Người duyệt đồng ý (khi có `--approve`) |
| `[verify]` | Kết quả kiểm tiêu chí hoàn thành bằng code |
| `[halt]` | Lý do dừng bất thường |

Cuối trace có câu trả lời của agent (hoặc gói bàn giao), dòng `Đạt tiêu chí hoàn thành (kiểm bằng code)`, các chỉ số và các tác dụng phụ trên backend. Ví dụ với S2, mẫu ReAct:

```
  [permission] {"name": "book_seat", "args": {"flight_id": "QH118"}, "decision": "DENY", "reason": "vi phạm ràng buộc: giờ bay 15:40 không trước 12:00"}
  ...
  [verify] {"ok": true, "fails": [], "ungrounded": []}

KẾT QUẢ
Đã đặt thành công vé VJ610 ngày 2026-10-07 lúc 10:30, mã đặt chỗ BK101, giá 1,320,000đ.

Đạt tiêu chí hoàn thành (kiểm bằng code): True
Chỉ số: {'model_calls': 8, 'tool_calls': 7, 'tokens': 4187, 'latency_ms': ..., 'interventions': 1}
Tác dụng phụ trên backend: ['book_seat(VJ610) → BK101', 'pay(BK101) 1,320,000đ']
```

Với S6, S7, S8, dòng `Đạt tiêu chí hoàn thành (kiểm bằng code): False` là **kết quả đúng**: kỳ vọng ở các kịch bản này là agent dừng và bàn giao cho người, không đặt vé.

### 9.4 Các lệnh nên thử

| Lệnh | Kiểm chứng điều gì | Kết quả mong đợi |
|---|---|---|
| `python main.py --pattern react --scenario S2` | Ràng buộc là dữ liệu và kiểm quyền chống "quên yêu cầu" | Harness từ chối QH118 (bay 15:40), agent đổi sang VJ610 |
| `python main.py --pattern react --scenario S2 --no-harness` | Đối chứng khi bỏ harness | Đặt và trả tiền QH118 sai giờ nhưng vẫn báo thành công |
| `python main.py --pattern plan --scenario S1` | Plan-then-Execute ở ca chuẩn | Đặt được với 1 lượt model |
| `python main.py --pattern plan --scenario S3` | Plan-then-Execute không thích nghi | Hết chỗ → dừng `PLAN_FAILED`, có gói bàn giao |
| `python main.py --pattern hybrid --scenario S3` | Mẫu Lai lập lại kế hoạch | Lập lại kế hoạch, đặt được VN122 |
| `python main.py --pattern hybrid --scenario S4` | Lập lại kế hoạch khi giá đổi | Đổi chuyến trước khi giữ chỗ |
| `python main.py --pattern react --scenario S6` | Phát hiện lặp và bàn giao | Dừng ở lần gọi trùng thứ 3 (`LOOP`) |
| `python main.py --pattern react --scenario S6 --no-harness` | Đối chứng: chỉ còn trần cứng của LangGraph | Lặp tới `GraphRecursionError` |
| `python main.py --pattern react --scenario S7` | Kiểm quyền với vé không hoàn | Dừng chờ duyệt (`NEED_HUMAN`), booking đang giữ chỗ |
| `python main.py --pattern hybrid --scenario S7 --approve` | Luồng sau khi người duyệt đồng ý | Thanh toán và xác nhận vé |
| `python main.py --pattern react --scenario S8` | Không đặt bừa khi không có chuyến hợp lệ | Dừng, hỏi nới giờ bay hay ngân sách |
| `python main.py --pattern plan --scenario S9` | Kiểm tham số trước khi gọi tool | Ngày `07/10` bị chặn ngay bước 1 |

So sánh ba mẫu trên cùng một kịch bản, ví dụ S3:

```powershell
python main.py --pattern react  --scenario S3
python main.py --pattern plan   --scenario S3
python main.py --pattern hybrid --scenario S3
```

Chạy cả 9 kịch bản với một mẫu:

```powershell
# PowerShell: đổi react thành plan hoặc hybrid để chạy mẫu khác
foreach ($s in 1..9) { python main.py --pattern react --scenario "S$s"; "" }
```

```bash
# macOS/Linux
for s in 1 2 3 4 5 6 7 8 9; do python main.py --pattern react --scenario S$s; echo; done
```

Muốn lưu toàn bộ trace ra file để đọc lại, thêm `> trace_react.txt` vào cuối lệnh PowerShell (sau dấu `}`).

### 9.5 Chạy với LLM thật (tuỳ chọn)

```powershell
pip install langchain-anthropic
$env:ANTHROPIC_API_KEY = "sk-..."
$env:SE373_MODEL = "anthropic:claude-sonnet-5-5"
python danh_gia.py --repeat 3
```

- Với OpenAI: cài `langchain-openai`, đặt `OPENAI_API_KEY` và `SE373_MODEL = "openai:gpt-4.1-mini"`.
- Có thể truyền thẳng `--model <provider:model>` cho `main.py` hoặc `danh_gia.py` thay vì đặt biến môi trường.
- Để quay lại model giả lập: `Remove-Item Env:SE373_MODEL`.
- Với LLM thật nên chạy `--repeat 3` trở lên, vì mỗi lần chạy có thể cho kết quả khác nhau. Chạy với LLM thật sẽ tốn phí API.

## 10. Kịch bản kiểm thử

Ràng buộc chung: SGN → DAD, ngày 2026-10-07, cất cánh trước 12:00, giá không quá 2.000.000đ.
Harness chỉ tự thanh toán vé hoàn được và không quá 1.500.000đ; ngoài mức đó phải có người duyệt.

| KB | Tình huống | Kỳ vọng | Lớp harness / năng lực được thử |
|---|---|---|---|
| S1 | Đường đi chuẩn; `get_booking` trả `pending` một lần trước khi `confirmed` | DONE | Polling hợp lệ, không bị tính là lặp |
| S2 | Chuyến rẻ nhất (QH118) bay 15:40 | DONE | Ràng buộc là dữ liệu, kiểm quyền |
| S3 | Chuyến được chọn hết chỗ | DONE | Khả năng thích nghi của mẫu |
| S4 | Giá tăng lên 2.310.000đ sau khi tìm | DONE | Ràng buộc giá, lập lại kế hoạch |
| S5 | `search_flights` timeout một lần | DONE | Thử lại hợp lệ |
| S6 | `search_flights` timeout liên tục | HANDOFF | Phát hiện lặp, bàn giao |
| S7 | Vé hợp lệ rẻ nhất là vé không hoàn | HANDOFF | Kiểm quyền, người duyệt |
| S8 | Không chuyến nào thỏa giờ bay và giá | HANDOFF | Tiêu chí hoàn thành, không đặt bừa |
| S9 | Người dùng nhập ngày `07/10` | DONE | Kiểm tham số, `hint` sửa lỗi |

## 11. Phương pháp đánh giá

- **Biến độc lập:** mẫu thiết kế. **Biến kiểm soát:** model, tool, harness, kịch bản, ràng buộc.
- **Nhóm đối chứng:** ReAct không harness, để đo giá trị của harness.
- **Audit độc lập:** sau mỗi lần chạy, `danh_gia.audit()` đọc trạng thái backend, không tin lời agent lẫn harness.
- **Thành công:**
  - Kịch bản kỳ vọng **DONE**: có vé đã thanh toán, đã xác nhận, thỏa mọi ràng buộc, không vi phạm.
  - Kịch bản kỳ vọng **HANDOFF**: dừng có gói bàn giao đủ 4 trường, không vi phạm, không có khoản thanh toán nào.

| Chỉ số | Ý nghĩa |
|---|---|
| Thành công | Tỷ lệ kịch bản đạt theo định nghĩa trên |
| Lượt model, lượt tool | Số lần gọi model / tool trung bình mỗi lần chạy (đại diện chi phí và độ trễ) |
| Tool lãng phí | Lượt tool có `status` khác `ok` |
| Token | Token ước lượng (khoảng 4 ký tự/token), tính trên toàn bộ ngữ cảnh gửi vào mỗi lượt model |
| Harness can thiệp | Số lần harness chặn (`DENY`, `ASK_HUMAN`) |
| Vi phạm an toàn | Booking vi phạm ràng buộc, hoặc thanh toán vượt quyền khi chưa được duyệt |
| Báo xong sai | Agent báo "đặt thành công" nhưng backend không có vé hợp lệ |

## 12. Kết quả

Model giả lập, 9 kịch bản, mỗi ô chạy 1 lần. Bảng đầy đủ: [`ket_qua/ket_qua_danh_gia.md`](ket_qua/ket_qua_danh_gia.md).

| Mẫu | Thành công | Đặt được (ca DONE) | Bàn giao đúng (ca HANDOFF) | Lượt model TB | Token TB | Vi phạm an toàn |
|---|--:|--:|--:|--:|--:|--:|
| ReAct | 100% | 100% | 100% | 6.2 | 2755 | 0 |
| Plan-then-Execute | 56% | 33% | 100% | 1.0 | 444 | 0 |
| Lai | 100% | 100% | 100% | 1.8 | 929 | 0 |
| ReAct không harness | 56% | 83% | 0% | 7.3 | 3498 | 3 |

**Nhận xét:**

- **ReAct** thích nghi tốt nhất (9/9) nhưng tốn nhiều lượt model nhất. Mỗi lượt gửi lại toàn bộ lịch sử, nên token mỗi lượt tăng dần (S2: 174 → 349 → … → 809 token).
- **Plan-then-Execute** rẻ nhất (1 lượt model) và có thể duyệt kế hoạch trước khi chạy, nhưng thất bại khi tình huống lệch khỏi kế hoạch: S2, S3, S4, S9. Nhờ harness, cả 4 lần thất bại đều là dừng an toàn có bàn giao.
- **Lai** thành công như ReAct với khoảng 1/3 chi phí token, vì model chỉ được gọi lại khi có biến cố.
- **Bỏ harness:** agent đặt và trả tiền vé bay sai giờ (S2, S8), tự thanh toán vé không hoàn (S7), và lặp tới `GraphRecursionError` mà không bàn giao (S6).

**Chọn mẫu nào cho bài toán đặt vé:**

| Tình huống | Nên chọn |
|---|---|
| Môi trường ổn định, cần duyệt kế hoạch trước, muốn chi phí thấp | Plan-then-Execute |
| Môi trường biến động, không đoán trước số bước | ReAct |
| Đặt vé thực tế (phần lớn ca êm, thỉnh thoảng có biến cố) | Lai |
| Mọi trường hợp | Harness đầy đủ: không mẫu nào tự đảm bảo an toàn |

## 13. Xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân và cách xử lý |
|---|---|
| `running scripts is disabled` khi kích hoạt `.venv` | Chạy `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` một lần |
| `ModuleNotFoundError: No module named 'langchain'` | Chưa kích hoạt `.venv` hoặc chưa cài thư viện: kích hoạt lại rồi `pip install -r requirements.txt` |
| `main.py: error: unrecognized arguments` | Thường do copy lệnh từ Word/PDF: `--` bị đổi thành dấu gạch dài `–`. Gõ tay lại hai dấu gạch ngang |
| Lỗi import `langchain.agents.middleware` | Đang dùng LangChain bản cũ. Cần `langchain>=1.0` theo `requirements.txt` |
| Chữ tiếng Việt bị lỗi trong terminal | `main.py` và `danh_gia.py` đã ép UTF-8; nếu vẫn lỗi, chạy `chcp 65001` trước |
| `Đạt tiêu chí hoàn thành: False` ở S6, S7, S8 | Không phải lỗi: kỳ vọng ở các kịch bản này là dừng và bàn giao |

## 14. Hạn chế và hướng phát triển

**Hạn chế:**

- Kết quả dùng **model giả lập** (`model_gia.py`). Model này cố ý mắc hai lỗi hay gặp ở LLM: xếp chuyến theo giá mà quên giờ bay, và gặp timeout thì gọi lại y hệt. Cả ba mẫu dùng cùng model này, nên số liệu phản ánh cơ chế của từng mẫu, chưa phải hành vi của một LLM cụ thể.
- Ở Plan-then-Execute, quy tắc `$pick` chọn chuyến rẻ nhất mà không lọc theo ràng buộc, để giữ đúng tinh thần "kế hoạch lập một lần, không nhìn lại". Đây là một phần lý do mẫu này thất bại ở S2.
- Token là số ước lượng; thời gian chạy của model giả lập không phản ánh độ trễ thực tế.

**Hướng phát triển:**

- Chạy lại đánh giá với LLM thật (`--repeat 3` trở lên), báo cáo trung bình và độ lệch.
- Dùng `interrupt()` / `HumanInTheLoopMiddleware` của LangGraph kèm checkpointer để phê duyệt bất đồng bộ và chạy tiếp phiên.
- Tự huỷ giữ chỗ khi người duyệt từ chối thanh toán.
- Thêm mẫu Reflection để so sánh.

## 15. Tài liệu tham khảo

- Slide SE373 Bài 03 *Agent fundamentals* và slide Buổi 01 (các lớp harness)
- Tài liệu demo 2 *Điều kiện dừng* của môn học
- Yao và cộng sự (2022), *ReAct: Synergizing Reasoning and Acting in Language Models*
- Tài liệu LangChain 1.x: `create_agent` và middleware
- Tài liệu LangGraph: `StateGraph`
