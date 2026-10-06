"""Tool giả lập và 9 kịch bản kiểm thử cho agent đặt vé."""
from __future__ import annotations

import copy
import functools
import json
import re
from dataclasses import dataclass, field

from langchain_core.tools import StructuredTool

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Scenario:
    id: str
    title: str
    request: str
    flights: list[dict]
    sold_out: set[str] = field(default_factory=set)        # chuyến hết chỗ
    price_change: dict[str, int] = field(default_factory=dict)  # giá mới khi check_seat
    search_timeouts: int = 0                                # số lần search bị timeout (99 = luôn lỗi)
    pending_polls: int = 0                                  # số lần get_booking trả pending
    expected: str = "DONE"                                  # DONE hoặc HANDOFF
    note: str = ""


def _f(fid, airline, depart, price, refundable=True, date="2026-10-07"):
    return {"flight_id": fid, "airline": airline, "origin": "SGN", "dest": "DAD",
            "date": date, "depart": depart, "price": price, "refundable": refundable, "seats": 9}


REQ = "Đặt giúp tôi 1 vé SGN → DAD ngày 2026-10-07, bay buổi sáng (trước 12:00), giá dưới 2 triệu."
REQ_DATE_VN = "Đặt giúp tôi 1 vé SGN → DAD ngày 07/10, bay buổi sáng (trước 12:00), giá dưới 2 triệu."

BASE = [_f("VJ610", "VietJet", "10:30", 1_320_000), _f("VN122", "Vietnam Airlines", "08:10", 1_450_000)]
CHEAP_AFTERNOON = _f("QH118", "Bamboo", "15:40", 1_190_000)

SCENARIOS: list[Scenario] = [
    Scenario("S1", "Đường đi chuẩn (có polling xác nhận)", REQ, BASE + [_f("VN134", "Vietnam Airlines", "11:00", 1_650_000)],
             pending_polls=1, note="get_booking trả pending 1 lần: polling hợp lệ, không phải lặp"),
    Scenario("S2", "Chuyến rẻ nhất vi phạm giờ bay", REQ, BASE + [CHEAP_AFTERNOON],
             note="QH118 rẻ nhất nhưng bay 15:40 → bẫy 'quên yêu cầu'"),
    Scenario("S3", "Chuyến được chọn hết chỗ", REQ, BASE, sold_out={"VJ610"},
             note="VJ610 sold_out tại check_seat → phải đổi chuyến"),
    Scenario("S4", "Giá thay đổi sau khi tìm kiếm", REQ, BASE, price_change={"VJ610": 2_310_000},
             note="VJ610 tăng lên 2.310.000đ tại check_seat → vượt ngân sách"),
    Scenario("S5", "Dịch vụ tìm chuyến lỗi tạm thời", REQ, BASE, search_timeouts=1,
             note="search_flights timeout 1 lần rồi chạy lại được"),
    Scenario("S6", "Dịch vụ tìm chuyến lỗi kéo dài", REQ, BASE, search_timeouts=99, expected="HANDOFF",
             note="timeout mãi → phải phát hiện lặp và bàn giao"),
    Scenario("S7", "Vé không hoàn → cần người duyệt", REQ,
             [_f("VJ602", "VietJet", "07:15", 1_150_000, refundable=False),
              _f("VN122", "Vietnam Airlines", "08:10", 1_850_000)], expected="HANDOFF",
             note="vé thỏa ràng buộc rẻ nhất là vé không hoàn → kiểm quyền chặn pay"),
    Scenario("S8", "Không chuyến nào thỏa ràng buộc", REQ,
             [CHEAP_AFTERNOON, _f("VN136", "Vietnam Airlines", "13:00", 1_700_000),
              _f("VN122", "Vietnam Airlines", "08:10", 2_250_000)], expected="HANDOFF",
             note="mọi chuyến vi phạm giờ hoặc giá → không được đặt bừa"),
    Scenario("S9", "Người dùng nhập ngày sai định dạng", REQ_DATE_VN, BASE,
             note="'07/10' → tool trả invalid_param kèm hint YYYY-MM-DD"),
]


class FlightWorld:
    """Backend giả lập, tạo mới cho mỗi lần chạy."""

    def __init__(self, sc: Scenario):
        self.sc = sc
        self.flights = {f["flight_id"]: copy.deepcopy(f) for f in sc.flights}
        self.timeouts_left = sc.search_timeouts
        self.polls_left = sc.pending_polls
        self.bookings: dict[str, dict] = {}
        self.side_effects: list[str] = []   # các hành động có tác dụng phụ

    # --- Chỉ đọc ---
    def search_flights(self, origin: str, dest: str, date: str) -> dict:
        if not DATE_RE.match(str(date)):
            return {"status": "invalid_param", "param": "date", "got": date,
                    "hint": "Dùng định dạng YYYY-MM-DD, ví dụ 2026-10-07"}
        if self.timeouts_left > 0:
            self.timeouts_left -= 1
            return {"status": "error", "error": "timeout",
                    "hint": "Dịch vụ tìm chuyến lỗi tạm thời, có thể thử lại sau"}
        rows = [{k: f[k] for k in ("flight_id", "airline", "date", "depart", "price", "refundable")}
                for f in self.flights.values()
                if f["origin"] == origin.upper() and f["dest"] == dest.upper() and f["date"] == date]
        return {"status": "ok", "count": len(rows), "flights": sorted(rows, key=lambda r: r["depart"])}

    def check_seat(self, flight_id: str) -> dict:
        f = self.flights.get(flight_id)
        if not f:
            return {"status": "not_found", "flight_id": flight_id,
                    "hint": "flight_id phải lấy từ kết quả search_flights"}
        if flight_id in self.sc.sold_out:
            return {"status": "sold_out", "flight_id": flight_id, "hint": "Chọn chuyến khác"}
        f["price"] = self.sc.price_change.get(flight_id, f["price"])
        return {"status": "ok", "flight_id": flight_id, "date": f["date"], "depart": f["depart"],
                "seats_left": f["seats"], "price": f["price"], "refundable": f["refundable"]}

    def get_booking(self, booking_code: str) -> dict:
        b = self.bookings.get(booking_code)
        if not b:
            return {"status": "not_found", "booking_code": booking_code,
                    "hint": "booking_code phải lấy từ kết quả book_seat"}
        if b["paid"] and b["state"] == "pending":
            if self.polls_left > 0:
                self.polls_left -= 1
            else:
                b["state"] = "confirmed"
        return {"status": "ok", **copy.deepcopy(b)}

    # --- Có tác dụng phụ ---
    def book_seat(self, flight_id: str) -> dict:
        f = self.flights.get(flight_id)
        if not f:
            return {"status": "not_found", "flight_id": flight_id,
                    "hint": "flight_id phải lấy từ kết quả search_flights"}
        if flight_id in self.sc.sold_out:
            return {"status": "sold_out", "flight_id": flight_id, "hint": "Chọn chuyến khác"}
        f["price"] = self.sc.price_change.get(flight_id, f["price"])
        code = f"BK{101 + len(self.bookings)}"
        self.bookings[code] = {"booking_code": code, "flight_id": flight_id, "depart_date": f["date"],
                               "depart_time": f["depart"], "price": f["price"],
                               "refundable": f["refundable"], "state": "held", "paid": False}
        self.side_effects.append(f"book_seat({flight_id}) → {code}")
        return {"status": "ok", "booking_code": code, "state": "held", "price": f["price"],
                "refundable": f["refundable"]}

    def pay(self, booking_code: str) -> dict:
        b = self.bookings.get(booking_code)
        if not b:
            return {"status": "not_found", "booking_code": booking_code,
                    "hint": "booking_code phải lấy từ kết quả book_seat"}
        b["paid"], b["state"] = True, "pending"
        self.side_effects.append(f"pay({booking_code}) {b['price']:,}đ")
        return {"status": "ok", "booking_code": booking_code, "paid": True, "amount": b["price"]}


TOOL_DOCS = {
    "search_flights": "Tìm chuyến bay. Tham số: origin (mã IATA, vd SGN), dest (vd DAD), date (YYYY-MM-DD).",
    "check_seat": "Kiểm tra còn ghế và giá hiện tại của một chuyến. Tham số: flight_id lấy từ search_flights.",
    "book_seat": "Giữ chỗ (tạo booking trạng thái held). CÓ TÁC DỤNG PHỤ. Tham số: flight_id.",
    "pay": "Thanh toán booking. KHÔNG HOÀN TÁC ĐƯỢC. Tham số: booking_code lấy từ book_seat.",
    "get_booking": "Đọc trạng thái booking (held/pending/confirmed). Tham số: booking_code.",
}
TOOL_NAMES = tuple(TOOL_DOCS)


def make_tools(world: FlightWorld) -> list[StructuredTool]:
    """Bọc các hàm của world thành LangChain tool, kết quả trả JSON."""
    def as_json(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return json.dumps(fn(*args, **kwargs), ensure_ascii=False)
        return wrapper
    return [StructuredTool.from_function(as_json(getattr(world, n)), name=n, description=TOOL_DOCS[n])
            for n in TOOL_NAMES]
