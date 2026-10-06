# BTVN#3 · Agent đặt vé máy bay bằng LangChain / LangGraph

Môn SE373 · Kỹ thuật xây dựng hệ thống Agentic AI · Bài 03 Agent fundamentals.

Agent đặt vé SGN → DAD theo công thức **agent = model + harness**. Code gồm ba phần:

- tool mockup chạy trên một backend giả lập có cài sẵn sự cố;
- một lớp harness bao quanh model;
- ba mẫu thiết kế agent dùng chung harness đó, kèm script đánh giá so sánh ba mẫu.

## Yêu cầu đề bài và phần code tương ứng

| Yêu cầu | Cài đặt |
|---|---|
| 1. Đủ các lớp harness | `harness.py`: ràng buộc là dữ liệu (`Constraints`, `Policy`, `Budget`), tiêu chí hoàn thành kiểm bằng code (`verify_completion`, `verify_answer`), kiểm quyền (`authorize`), bàn giao (`Handoff`). Thêm phát hiện lặp, phát hiện bế tắc, ngân sách và trace |
| 2. Ba mẫu thiết kế | `agent_react.py` (ReAct), `agent_plan_execute.py` (Plan-then-Execute), `agent_hybrid.py` (Lai) |
| 3. Đánh giá hiệu quả | `danh_gia.py`: 9 kịch bản × 3 mẫu, thêm nhóm đối chứng ReAct không harness |

## Cấu trúc thư mục

```
FlightBookingAgent/
├── tools_mock.py          Backend giả lập FlightWorld, 9 kịch bản S1–S9, bọc thành LangChain tool
├── harness.py             Lớp harness dùng chung cho cả 3 mẫu
├── model_gia.py           Model giả lập (ModelGia) và get_model() để đổi sang LLM thật
├── agent_react.py         Mẫu 1 · ReAct: create_agent + HarnessMiddleware
├── agent_plan_execute.py  Mẫu 2 · Plan-then-Execute: StateGraph planner → review → executor → finish
├── agent_hybrid.py        Mẫu 3 · Lai: thêm cạnh executor → planner khi observation đổi đáng kể
├── danh_gia.py            Chạy toàn bộ đánh giá, ghi kết quả vào ket_qua/
├── main.py                Chạy một mẫu trên một kịch bản và in trace từng vòng
├── requirements.txt
├── BAO_CAO.md             Báo cáo chi tiết (harness, 3 mẫu, đánh giá)
└── ket_qua/               Sinh ra khi chạy danh_gia.py
    ├── ket_qua_danh_gia.md
    ├── ket_qua_danh_gia.json
    └── traces/            Trace JSON của từng lần chạy
```

## Cài đặt

Cần Python 3.10 trở lên. Không cần API key: mặc định code dùng model giả lập.

```powershell
cd FlightBookingAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Nếu PowerShell báo "running scripts is disabled", chạy lệnh dưới một lần rồi kích hoạt lại môi trường:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Trên macOS/Linux, kích hoạt môi trường bằng `source .venv/bin/activate`.

## Cách chạy

### 1. Chạy toàn bộ đánh giá

```powershell
python danh_gia.py
```

Lệnh này chạy 9 kịch bản trên 4 cấu hình (ReAct, Plan-then-Execute, Lai, ReAct không harness). Sau mỗi lần chạy, script đọc lại trạng thái backend để kiểm kết quả, không dựa vào lời agent tự báo.

- Terminal in ra bảng tổng hợp theo mẫu và bảng kết quả từng kịch bản.
- Bảng đầy đủ được ghi vào `ket_qua/ket_qua_danh_gia.md`.
- Dữ liệu thô ở `ket_qua/ket_qua_danh_gia.json`; trace từng lần chạy ở `ket_qua/traces/`.

### 2. Chạy cả 9 kịch bản với một mẫu, xem trace từng kịch bản

`danh_gia.py` chỉ in bảng tổng hợp. Muốn xem trace chi tiết của cả 9 kịch bản cho một mẫu, chạy vòng lặp gọi `main.py`:

```powershell
# PowerShell: đổi react thành plan hoặc hybrid để chạy mẫu khác
foreach ($s in 1..9) { python main.py --pattern react --scenario "S$s"; "" }
```

```bash
# macOS/Linux
for s in 1 2 3 4 5 6 7 8 9; do python main.py --pattern react --scenario S$s; echo; done
```

Muốn lưu toàn bộ trace ra file để đọc lại, thêm `> trace_react.txt` vào cuối lệnh PowerShell (sau dấu `}`).

### 3. Chạy từng kịch bản

Mỗi lệnh dưới đây chạy một kịch bản với một mẫu. Đổi `--pattern` thành `react`, `plan` hoặc `hybrid` để so sánh ba mẫu trên cùng kịch bản.

```powershell
python main.py --pattern react --scenario S1   # đường đi chuẩn, có chờ xác nhận
python main.py --pattern react --scenario S2   # chuyến rẻ nhất bay sai giờ
python main.py --pattern react --scenario S3   # chuyến được chọn hết chỗ
python main.py --pattern react --scenario S4   # giá tăng sau khi tìm
python main.py --pattern react --scenario S5   # tìm chuyến bị timeout 1 lần
python main.py --pattern react --scenario S6   # tìm chuyến bị timeout liên tục
python main.py --pattern react --scenario S7   # vé không hoàn, cần người duyệt
python main.py --pattern react --scenario S8   # không có chuyến hợp lệ
python main.py --pattern react --scenario S9   # ngày nhập sai định dạng
```

Với S6, S7, S8, dòng `Đạt tiêu chí hoàn thành (kiểm bằng code): False` là kết quả đúng: kỳ vọng ở các kịch bản này là agent dừng và bàn giao cho người, không đặt vé.

Ví dụ so sánh ba mẫu trên kịch bản S3:

```powershell
python main.py --pattern react  --scenario S3
python main.py --pattern plan   --scenario S3
python main.py --pattern hybrid --scenario S3
```

### 4. Tham số của main.py

```powershell
python main.py --pattern react --scenario S2
```

Cú pháp: `python main.py --pattern <mẫu> --scenario <kịch bản> [--approve] [--no-harness] [--model <tên>]`.
Thay phần trong `< >` bằng giá trị cụ thể. Phần trong `[ ]` có thể bỏ.

| Tham số | Giá trị | Ý nghĩa |
|---|---|---|
| `--pattern` | `react`, `plan`, `hybrid` | Mẫu thiết kế. Mặc định `react` |
| `--scenario` | `S1` … `S9` | Kịch bản (xem bảng bên dưới). Mặc định `S2` |
| `--approve` | | Giả lập người duyệt đồng ý khi harness yêu cầu phê duyệt |
| `--no-harness` | | Tắt harness để đối chứng |
| `--model` | vd `anthropic:claude-sonnet-5-5` | Dùng LLM thật thay cho model giả lập |

Trace in theo từng vòng:

| Nhãn | Nội dung |
|---|---|
| `[model_call]` | Một lượt gọi model và số token ước lượng |
| `[tool]` | Lời gọi tool và observation |
| `[permission]` | Quyết định kiểm quyền (DENY / ASK_HUMAN) |
| `[plan]`, `[plan_review]` | Kế hoạch và bước duyệt kế hoạch (mẫu Plan-then-Execute, Lai) |
| `[verify]` | Kết quả kiểm tiêu chí hoàn thành bằng code |
| `[halt]` | Lý do dừng bất thường |

Cuối trace có câu trả lời của agent, kết quả kiểm tiêu chí hoàn thành, các chỉ số đo được và các tác dụng phụ trên backend.

### 5. Các lệnh nên thử

| Lệnh | Kiểm chứng điều gì | Kết quả mong đợi |
|---|---|---|
| `python main.py --pattern react --scenario S2` | Ràng buộc là dữ liệu và kiểm quyền chống "quên yêu cầu" | Harness từ chối QH118 (bay 15:40), agent đổi sang VJ610 |
| `python main.py --pattern react --scenario S2 --no-harness` | Đối chứng khi bỏ harness | Đặt và trả tiền QH118 sai giờ nhưng vẫn báo thành công |
| `python main.py --pattern plan --scenario S3` | Plan-then-Execute không thích nghi | Hết chỗ → dừng PLAN_FAILED, có gói bàn giao |
| `python main.py --pattern hybrid --scenario S3` | Mẫu Lai lập lại kế hoạch | Lập lại kế hoạch, đặt được VN122 |
| `python main.py --pattern hybrid --scenario S4` | Lập lại kế hoạch khi giá đổi | Đổi chuyến trước khi giữ chỗ |
| `python main.py --pattern react --scenario S6` | Phát hiện lặp và bàn giao | Dừng ở lần gọi trùng thứ 3 (LOOP) |
| `python main.py --pattern react --scenario S6 --no-harness` | Đối chứng: chỉ còn trần cứng của LangGraph | Lặp tới `GraphRecursionError` |
| `python main.py --pattern hybrid --scenario S7` | Kiểm quyền với vé không hoàn | Dừng chờ duyệt (NEED_HUMAN), booking đang giữ chỗ |
| `python main.py --pattern hybrid --scenario S7 --approve` | Luồng sau khi người duyệt đồng ý | Thanh toán và xác nhận vé |
| `python main.py --pattern react --scenario S8` | Không đặt bừa khi không có chuyến hợp lệ | Dừng, hỏi nới giờ bay hay ngân sách |
| `python main.py --pattern plan --scenario S9` | Kiểm tham số trước khi gọi tool | Ngày `07/10` bị chặn ngay bước 1 |

### 6. Chạy với LLM thật (tuỳ chọn)

```powershell
pip install langchain-anthropic
$env:ANTHROPIC_API_KEY = "sk-..."
$env:SE373_MODEL = "anthropic:claude-sonnet-5-5"
python danh_gia.py --repeat 3
```

Với OpenAI: cài `langchain-openai`, đặt `OPENAI_API_KEY` và `SE373_MODEL = "openai:gpt-4.1-mini"`.
Để quay lại model giả lập, chạy `Remove-Item Env:SE373_MODEL`.
Với LLM thật nên chạy `--repeat 3` trở lên, vì mỗi lần chạy có thể cho kết quả khác nhau.

## Kịch bản kiểm thử

Ràng buộc chung: SGN → DAD, ngày 2026-10-07, cất cánh trước 12:00, giá không quá 2.000.000đ.
Harness chỉ tự thanh toán vé hoàn được và không quá 1.500.000đ; ngoài mức đó phải có người duyệt.

| KB | Tình huống | Kỳ vọng |
|---|---|---|
| S1 | Đường đi chuẩn; `get_booking` trả `pending` một lần trước khi `confirmed` | DONE |
| S2 | Chuyến rẻ nhất (QH118) bay 15:40 | DONE |
| S3 | Chuyến được chọn hết chỗ | DONE |
| S4 | Giá tăng lên 2.310.000đ sau khi tìm | DONE |
| S5 | `search_flights` timeout một lần | DONE |
| S6 | `search_flights` timeout liên tục | HANDOFF |
| S7 | Vé hợp lệ rẻ nhất là vé không hoàn | HANDOFF |
| S8 | Không chuyến nào thỏa giờ bay và giá | HANDOFF |
| S9 | Người dùng nhập ngày `07/10` | DONE |

DONE nghĩa là phải có vé đã thanh toán, đã xác nhận và thỏa mọi ràng buộc.
HANDOFF nghĩa là agent phải dừng có kiểm soát, kèm gói bàn giao đủ 4 trường, và không có khoản thanh toán nào.

## Kết quả (model giả lập)

| Mẫu | Thành công | Lượt model TB | Token TB | Vi phạm an toàn |
|---|--:|--:|--:|--:|
| ReAct | 100% | 6.2 | 2755 | 0 |
| Plan-then-Execute | 56% | 1.0 | 444 | 0 |
| Lai | 100% | 1.8 | 929 | 0 |
| ReAct không harness | 56% | 7.3 | 3498 | 3 |

- **ReAct** thích nghi tốt nhất nhưng tốn nhiều lượt model nhất. Mỗi lượt gửi lại toàn bộ lịch sử, nên token tăng nhanh theo số vòng.
- **Plan-then-Execute** rẻ nhất (1 lượt model) và có thể duyệt kế hoạch trước khi chạy. Mẫu này thất bại khi tình huống lệch khỏi kế hoạch: S2, S3, S4, S9.
- **Lai** thành công như ReAct, với khoảng 1/3 chi phí token, vì model chỉ được gọi lại khi có biến cố.
- **Bỏ harness**: agent đặt sai giờ bay, tự thanh toán vé không hoàn và lặp tới khi LangGraph báo lỗi.

## Lưu ý

- Kết quả trên dùng model giả lập (`model_gia.py`), tương tự `ModelGia` trong demo 2. Model này cố ý mắc hai lỗi hay gặp ở LLM: xếp chuyến theo giá mà quên giờ bay, và gặp timeout thì gọi lại y hệt. Cả ba mẫu dùng cùng model này, nên khác biệt giữa các mẫu đến từ kiến trúc và harness. Số liệu với LLM thật có thể khác.
- Token là số ước lượng (khoảng 4 ký tự mỗi token). Thời gian chạy của model giả lập không phản ánh độ trễ thực tế.
