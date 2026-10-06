"""Lớp harness bao quanh model.

Thứ tự kiểm mỗi lần gọi tool: kiểm quyền -> phát hiện lặp -> chạy tool -> bế tắc -> ngân sách.
Khi model báo xong: kiểm tiêu chí hoàn thành bằng code. Dừng bất thường thì tạo gói bàn giao.
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable

from tools_mock import DATE_RE, TOOL_NAMES, FlightWorld


# --- Ràng buộc là dữ liệu ---
@dataclass(frozen=True)
class Constraints:
    """Yêu cầu của người dùng."""
    origin: str = "SGN"
    dest: str = "DAD"
    date: str = "2026-10-07"
    depart_before: str = "12:00"
    max_price: int = 2_000_000

    def violations(self, f: dict) -> list[dict]:
        """Danh sách vi phạm, rỗng là hợp lệ."""
        date = f.get("date") or f.get("depart_date")
        depart = f.get("depart") or f.get("depart_time")
        out = []
        if date is not None and date != self.date:
            out.append({"field": "date", "detail": f"ngày {date} khác {self.date}"})
        if depart is not None and depart >= self.depart_before:
            out.append({"field": "depart", "detail": f"giờ bay {depart} không trước {self.depart_before}"})
        if f.get("price") is not None and f["price"] > self.max_price:
            out.append({"field": "price", "detail": f"giá {f['price']:,}đ vượt {self.max_price:,}đ"})
        return out

    def as_prompt(self) -> str:
        return ("RÀNG BUỘC (bắt buộc, harness sẽ kiểm bằng code):\n"
                f"CONSTRAINTS_JSON: {json.dumps(asdict(self), ensure_ascii=False)}")


@dataclass(frozen=True)
class Policy:
    """Quyền hạn của agent."""
    allowed_tools: frozenset = frozenset(TOOL_NAMES)
    read_only: frozenset = frozenset({"search_flights", "check_seat", "get_booking"})
    auto_pay_limit: int = 1_500_000          # trên mức này cần người duyệt
    auto_pay_requires_refundable: bool = True  # vé không hoàn cần người duyệt
    max_active_bookings: int = 1
    required_args: dict = field(default_factory=lambda: {
        "search_flights": ("origin", "dest", "date"), "check_seat": ("flight_id",),
        "book_seat": ("flight_id",), "pay": ("booking_code",), "get_booking": ("booking_code",)})


@dataclass(frozen=True)
class Budget:
    max_model_calls: int = 12
    max_tool_calls: int = 16
    max_tokens: int = 40_000
    max_seconds: float = 60.0


# --- Phát hiện lặp và bế tắc ---
class LoopDetector:
    def __init__(self, window=6, repeat_k=3, stall_n=5, polling_ok=("get_booking",)):
        self.recent = deque(maxlen=window)       # chỉ xét vài lần gọi gần nhất
        self.k, self.n, self.polling_ok = repeat_k, stall_n, set(polling_ok)
        self.last, self.stall = None, 0

    def check_action(self, tool: str, args: dict) -> str | None:
        """Báo LOOP khi cùng (tool, args) lặp lại. Bỏ qua get_booking vì đó là polling."""
        if tool in self.polling_ok:
            return None
        fp = (tool, repr(sorted(args.items())))
        if self.recent.count(fp) + 1 >= self.k:
            return f"LOOP · '{tool}' gọi {self.k} lần với cùng tham số trong {self.recent.maxlen} vòng gần nhất"
        self.recent.append(fp)
        return None

    def check_progress(self, progress) -> str | None:
        self.stall = self.stall + 1 if progress == self.last else 0
        self.last = progress
        if self.stall >= self.n:
            return f"STALL · {self.n} lần gọi tool liên tiếp mà tiến độ vẫn ở mức '{STAGES[progress]}'"
        return None


STAGES = ["chưa có dữ liệu", "đã có danh sách chuyến", "đã kiểm ghế", "đã giữ chỗ", "đã thanh toán", "đã xác nhận"]


# --- Bàn giao ---
@dataclass
class Handoff:
    kind: str                     # loại dừng
    stop_reason: str              # lý do dừng
    trang_thai: dict              # đã làm tới đâu
    da_thu: list[str]             # đã thử những gì
    cau_hoi_cho_nguoi: str        # câu hỏi cho người

    def is_complete(self) -> bool:
        return all([self.stop_reason, self.trang_thai, self.da_thu, self.cau_hoi_cho_nguoi])

    def render(self) -> str:
        tt = "; ".join(f"{k}: {v}" for k, v in self.trang_thai.items())
        thu = "\n".join(f"   - {x}" for x in self.da_thu[-10:])
        return (f"DỪNG [{self.kind}]\n"
                f"  Lý do     : {self.stop_reason}\n  Trạng thái: {tt}\n"
                f"  Đã thử    :\n{thu}\n  Hỏi người : {self.cau_hoi_cho_nguoi}")


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ASK_HUMAN = "ASK_HUMAN"


def approx_tokens(obj: Any) -> int:
    """Ước lượng token (~4 ký tự/token)."""
    return max(1, len(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)) // 4)


# --- Harness ---
class Harness:
    def __init__(self, world: FlightWorld, constraints=Constraints(), policy=Policy(), budget=Budget(),
                 approver: Callable[[dict], bool] | None = None, enabled: bool = True, verbose: bool = False):
        self.world, self.c, self.policy, self.budget = world, constraints, policy, budget
        self.approver, self.enabled, self.verbose = approver, enabled, verbose
        self.loop = LoopDetector()
        self.t0 = time.perf_counter()
        self.model_calls = self.tool_calls = self.tokens = 0
        self.interventions: list[str] = []   # các lần harness chặn
        self.trace: list[dict] = []          # nhật ký
        self.seen: dict[str, dict] = {}      # thông tin chuyến lấy từ tool
        self.my_bookings: dict[str, dict] = {}
        self.stage = 0
        self.stop: Handoff | None = None
        self.final_text = ""
        self.done = False
        self.error: str | None = None        # lỗi framework

    # --- Nhật ký ---
    def log(self, event: str, **data):
        ev = {"t_ms": round((time.perf_counter() - self.t0) * 1000, 1), "event": event, **data}
        self.trace.append(ev)
        if self.verbose:
            print(f"  [{event}] " + json.dumps(data, ensure_ascii=False, default=str)[:220])

    def count_model_call(self, messages: list, output: Any = None):
        self.model_calls += 1
        n = approx_tokens([getattr(m, "content", m) for m in messages] +
                          [getattr(m, "tool_calls", None) for m in messages]) + approx_tokens(output or "")
        self.tokens += n
        self.log("model_call", n=self.model_calls, tokens=n)

    # --- Kiểm quyền ---
    def authorize(self, name: str, args: dict) -> tuple[Decision, str, str]:
        """Trả (quyết định, lý do, gợi ý) trước khi chạy tool."""
        p = self.policy
        if name not in p.allowed_tools:
            return Decision.DENY, f"tool '{name}' không nằm trong danh sách cho phép", f"Chỉ dùng: {sorted(p.allowed_tools)}"
        missing = [a for a in p.required_args.get(name, ()) if not args.get(a)]
        if missing:
            return Decision.DENY, f"thiếu tham số {missing}", f"Cần đủ {p.required_args[name]}"
        if name == "search_flights" and not DATE_RE.match(str(args["date"])):
            return Decision.DENY, f"date '{args['date']}' sai định dạng", "Dùng YYYY-MM-DD, ví dụ 2026-10-07"
        if name in p.read_only:
            return Decision.ALLOW, "read-only", ""

        if name == "book_seat":
            fid = args["flight_id"]
            info = self.seen.get(fid)
            if not info:
                return Decision.DENY, f"chuyến {fid} chưa xuất hiện trong kết quả tool nào", "Gọi search_flights/check_seat trước"
            active = [b for b in self.my_bookings.values() if not b.get("released")]
            if len(active) >= p.max_active_bookings:
                return Decision.DENY, f"đã giữ chỗ {active[0]['booking_code']}", "Thanh toán hoặc bàn giao booking đang giữ"
            v = self.c.violations(info)
            if v:
                return (Decision.DENY, "vi phạm ràng buộc: " + "; ".join(x["detail"] for x in v),
                        "Chọn chuyến khác thỏa CONSTRAINTS_JSON|" + ",".join(x["field"] for x in v))
            return Decision.ALLOW, "thỏa ràng buộc", ""

        if name == "pay":
            b = self.my_bookings.get(args["booking_code"])
            if not b:
                return Decision.DENY, "booking không do agent tạo trong phiên này", "Chỉ thanh toán booking từ book_seat"
            reasons = []
            if b["price"] > p.auto_pay_limit:
                reasons.append(f"số tiền {b['price']:,}đ vượt hạn mức tự duyệt {p.auto_pay_limit:,}đ")
            if p.auto_pay_requires_refundable and not b["refundable"]:
                reasons.append("vé không hoàn")
            if reasons:
                req = {"booking": b, "reasons": reasons}
                if self.approver and self.approver(req):
                    self.log("human_approved", **req)
                    return Decision.ALLOW, "người duyệt đồng ý: " + "; ".join(reasons), ""
                return Decision.ASK_HUMAN, " và ".join(reasons), ""
            return Decision.ALLOW, "trong hạn mức tự duyệt", ""
        return Decision.DENY, "không có quy tắc cho tool này", ""

    # --- Gọi tool ---
    def call_tool(self, name: str, args: dict, run: Callable[[], dict] | None = None) -> dict:
        """Cửa duy nhất để gọi tool, dùng chung cho cả 3 mẫu."""
        args = dict(args or {})
        run = run or (lambda: getattr(self.world, name)(**args))
        if self.stop:
            return {"status": "halted", "reason": self.stop.stop_reason}
        if not self.enabled:                       # chế độ không harness
            obs = self._execute(name, args, run)
            self.tool_calls += 1
            self.log("tool", name=name, args=args, obs=obs)
            return obs

        dec, reason, hint = self.authorize(name, args)                 # kiểm quyền
        if dec is Decision.ASK_HUMAN:
            self.interventions.append(f"ASK_HUMAN {name}{args}: {reason}")
            self.log("permission", name=name, args=args, decision=dec.value, reason=reason)
            self._halt("NEED_HUMAN", f"{name}({args}) cần phê duyệt: {reason}")
            return {"status": "need_approval", "reason": reason}

        loop = self.loop.check_action(name, args)                     # phát hiện lặp
        if loop:
            self._halt("LOOP", loop)
            return {"status": "halted", "reason": loop}

        if dec is Decision.DENY:
            self.interventions.append(f"DENY {name}{args}: {reason}")
            obs = {"status": "denied", "reason": reason, "hint": hint}
            self.log("permission", name=name, args=args, decision=dec.value, reason=reason)
        else:
            obs = self._execute(name, args, run)
        self.tool_calls += 1
        self._record(name, args, obs)
        self.log("tool", name=name, args=args, obs=obs)

        stall = self.loop.check_progress(self.stage)                  # bế tắc
        if stall:
            self._halt("STALL", stall)
        else:
            self.check_budget()                                       # ngân sách, kiểm cuối
        return obs

    @staticmethod
    def _execute(name, args, run) -> dict:
        try:
            return run()
        except TypeError as e:          # sai tên tham số
            return {"status": "invalid_param", "error": str(e), "hint": "Kiểm tra lại tên tham số theo schema"}

    def _record(self, name: str, args: dict, obs: dict):
        """Cập nhật thông tin chuyến, booking và tiến độ."""
        st = obs.get("status")
        if name == "search_flights" and st == "ok":
            for f in obs["flights"]:
                self.seen[f["flight_id"]] = dict(f)
            self.stage = max(self.stage, 1)
        elif name == "check_seat" and st == "ok":
            f = self.seen.setdefault(obs["flight_id"], {"flight_id": obs["flight_id"]})
            f.update(price=obs["price"], depart=obs["depart"], date=obs["date"],
                     refundable=obs["refundable"], checked_price=obs["price"])
            self.stage = max(self.stage, 2)
        elif name == "book_seat" and st == "ok":
            f = self.seen.get(args["flight_id"], {})
            self.my_bookings[obs["booking_code"]] = {**obs, "flight_id": args["flight_id"],
                                                     "seen_price": f.get("checked_price", f.get("price"))}
            self.stage = max(self.stage, 3)
        elif name == "pay" and st == "ok":
            self.my_bookings[args["booking_code"]]["paid"] = True
            self.stage = max(self.stage, 4)
        elif name == "get_booking" and st == "ok" and obs.get("state") == "confirmed":
            self.stage = max(self.stage, 5)

    def check_budget(self) -> bool:
        b, secs = self.budget, time.perf_counter() - self.t0
        over = [n for n, used, cap in (("model_calls", self.model_calls, b.max_model_calls),
                                        ("tool_calls", self.tool_calls, b.max_tool_calls),
                                        ("tokens", self.tokens, b.max_tokens),
                                        ("seconds", secs, b.max_seconds)) if used >= cap]
        if over and self.enabled and not self.stop:
            self._halt("BUDGET", f"chạm trần ngân sách: {', '.join(over)}")
        return bool(over)

    # --- Tiêu chí hoàn thành ---
    def verify_completion(self) -> tuple[bool, list[str], dict | None]:
        """Đọc lại backend: vé phải confirmed, đã trả tiền, đúng ràng buộc, đúng giá."""
        if not self.my_bookings:
            return False, ["chưa có booking nào do agent tạo"], None
        code = list(self.my_bookings)[-1]
        b = self.world.get_booking(code)       # đọc thẳng backend
        fails = []
        if b.get("state") != "confirmed":
            fails.append(f"state={b.get('state')} ≠ confirmed")
        if not b.get("paid"):
            fails.append("paid=False")
        fails += [v["detail"] for v in self.c.violations(b)]
        seen = self.my_bookings[code].get("seen_price")
        if seen is not None and seen != b.get("price"):
            fails.append(f"giá booking {b.get('price'):,} ≠ giá đã thấy {seen:,}")
        return not fails, fails, b

    def verify_answer(self, text: str) -> list[str]:
        """Mã chuyến, mã booking, số tiền trong câu trả lời phải có trong kết quả tool."""
        corpus = json.dumps([e.get("obs") for e in self.trace if e["event"] == "tool"] + [asdict(self.c)],
                            ensure_ascii=False)
        bad = [tok for tok in re.findall(r"\b[A-Z]{2}\d{3}\b|\bBK\d+\b", text) if tok not in corpus]
        for num in re.findall(r"\d{1,3}(?:[.,]\d{3})+", text):
            if num not in corpus and num.replace(".", "").replace(",", "") not in corpus:
                bad.append(num)
        return [f"'{t}' không có nguồn trong observation" for t in bad]

    def finalize(self, answer: str) -> bool:
        """Kiểm khi model báo xong. True nếu đạt thật."""
        self.final_text = answer
        if self.stop:
            return False
        if not self.enabled:
            self.done = "đặt thành công" in answer.lower()   # không harness: tin lời model
            return self.done
        ok, fails, _ = self.verify_completion()
        ungrounded = self.verify_answer(answer)
        self.log("verify", ok=ok, fails=fails, ungrounded=ungrounded)
        if ok and not ungrounded:
            self.done = True
            return True
        self._halt("NOT_DONE", "tiêu chí hoàn thành chưa đạt: " + "; ".join(fails + ungrounded)
                   + (f" | model nói: “{answer[:120]}”" if answer else ""))
        return False

    # --- Bàn giao ---
    def _halt(self, kind: str, reason: str):
        if self.stop:
            return
        self.stop = self.make_handoff(kind, reason)
        self.log("halt", kind=kind, reason=reason)

    def make_handoff(self, kind: str, reason: str) -> Handoff:
        side = [f"{c}: {'ĐÃ THANH TOÁN' if b.get('paid') else 'đang GIỮ CHỖ'} {b['flight_id']} "
                f"{b['price']:,}đ" for c, b in self.my_bookings.items()]
        trang_thai = {"tiến độ": STAGES[self.stage], "model_calls": self.model_calls,
                      "tool_calls": self.tool_calls, "tác dụng phụ": side or "không có"}
        da_thu = []
        for e in self.trace:
            if e["event"] == "tool":
                o = e["obs"]
                why = o.get("reason") or o.get("error") or o.get("state") or o.get("hint") or ""
                da_thu.append(f"{e['name']}({', '.join(map(str, e['args'].values()))}) → {o.get('status')}"
                              + (f" ({why})" if why and o.get("status") != "ok" else ""))
        if not da_thu:
            da_thu = ["chưa gọi tool nào"]
        valid = [f for f in self.seen.values() if not self.c.violations(f)]
        if kind == "NEED_HUMAN":
            b = list(self.my_bookings.values())[-1]
            q = (f"Duyệt thanh toán {b['booking_code']} ({b['flight_id']}, {b['price']:,}đ, "
                 f"{'hoàn được' if b['refundable'] else 'KHÔNG hoàn'})? Đồng ý → pay; Từ chối → huỷ giữ chỗ.")
        elif kind == "LOOP":
            q = "Dịch vụ liên tục lỗi. Thử lại sau 15 phút hay chuyển nhân viên đặt thủ công?"
        elif kind == "BUDGET":
            q = "Đã hết ngân sách chạy. Cấp thêm ngân sách hay dừng tại đây?"
        elif not valid and self.seen:
            q = (f"Không chuyến nào thỏa toàn bộ ràng buộc ({len(self.seen)} chuyến đã xét). "
                 f"Nới giờ bay (sau {self.c.depart_before}) hay ngân sách (> {self.c.max_price:,}đ)?")
        else:
            q = "Kế hoạch hiện tại không hoàn thành được. Cho phép agent lập lại kế hoạch hay chuyển nhân viên?"
        return Handoff(kind, reason, trang_thai, da_thu, q)

    def metrics(self) -> dict:
        return {"model_calls": self.model_calls, "tool_calls": self.tool_calls, "tokens": self.tokens,
                "latency_ms": round((time.perf_counter() - self.t0) * 1000, 1),
                "interventions": len(self.interventions)}
