"""Model giả lập để chạy offline, kết quả lặp lại được.

Model chỉ đọc messages. Cố ý có 2 lỗi: chọn vé rẻ nhất mà quên giờ bay, và gặp timeout thì gọi lại y hệt.
Đổi sang LLM thật bằng biến môi trường SE373_MODEL, vd "anthropic:claude-sonnet-5-5".
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

PLANNER_TAG = "[PLANNER]"


def get_model(name: str | None = None) -> BaseChatModel:
    name = name or os.environ.get("SE373_MODEL", "gia")
    if name == "gia":
        return ModelGia()
    from langchain.chat_models import init_chat_model
    return init_chat_model(name, temperature=0)


# --- Đọc ngữ cảnh ---
def parse_request(text: str) -> dict:
    m = re.search(r"\b([A-Z]{3})\s*(?:→|->|-|đến)\s*([A-Z]{3})\b", text)
    d = re.search(r"\d{4}-\d{2}-\d{2}", text) or re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{4})?\b", text)
    return {"origin": m.group(1) if m else "SGN", "dest": m.group(2) if m else "DAD",
            "date": d.group(0) if d else ""}


def normalize_date(raw: str, year: int = 2026) -> str:
    p = raw.split("/")
    if len(p) >= 2:
        return f"{p[2] if len(p) == 3 else year}-{int(p[1]):02d}-{int(p[0]):02d}"
    return raw


def parse_constraints(sys_text: str) -> dict:
    m = re.search(r"CONSTRAINTS_JSON:\s*(\{.*?\})", sys_text)
    return json.loads(m.group(1)) if m else {}


def history_from_messages(messages) -> list[tuple[str, dict, dict]]:
    """Ghép tool call với kết quả của nó thành [(tool, args, obs)]."""
    calls, out = {}, []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                calls[tc["id"]] = tc
        elif isinstance(m, ToolMessage) and m.tool_call_id in calls:
            tc = calls[m.tool_call_id]
            try:
                obs = json.loads(m.content)
            except (TypeError, json.JSONDecodeError):
                obs = {"status": "unknown", "raw": str(m.content)}
            out.append((tc["name"], tc["args"], obs))
        elif isinstance(m, HumanMessage) and "OBSERVATIONS_JSON:" in str(m.content):
            out += [tuple(x) for x in json.loads(str(m.content).split("OBSERVATIONS_JSON:", 1)[1])]
    return out


@dataclass
class View:
    flights: dict = field(default_factory=dict)
    bad: dict = field(default_factory=dict)        # chuyến đã loại và lý do
    learned: set = field(default_factory=set)      # ràng buộc model học được sau khi bị từ chối
    checked: set = field(default_factory=set)
    booking: str | None = None
    paid: bool = False
    confirmed: dict | None = None
    last_search: tuple | None = None


def derive(history) -> View:
    v = View()
    for name, args, obs in history:
        st = obs.get("status")
        if name == "search_flights":
            v.last_search = (args, obs)
            if st == "ok":
                v.flights.update({f["flight_id"]: dict(f) for f in obs["flights"]})
        elif name == "check_seat":
            fid = args.get("flight_id")
            if st == "ok":
                v.flights.setdefault(fid, {}).update(price=obs["price"], depart=obs["depart"])
                v.checked.add(fid)
            else:
                v.bad[fid] = st
        elif name == "book_seat":
            if st == "ok":
                v.booking = obs["booking_code"]
            else:
                v.bad[args.get("flight_id")] = obs.get("reason", st)
                if "|" in str(obs.get("hint", "")):
                    v.learned |= set(obs["hint"].split("|", 1)[1].split(","))
        elif name == "pay" and st == "ok":
            v.paid = True
        elif name == "get_booking" and st == "ok" and obs.get("state") == "confirmed":
            v.confirmed = obs
    return v


def candidates(v: View, c: dict) -> list[dict]:
    def ok(f):
        if "depart" in v.learned and c and f["depart"] >= c["depart_before"]:
            return False
        if "price" in v.learned and c and f["price"] > c["max_price"]:
            return False
        return True
    return sorted((f for fid, f in v.flights.items() if fid not in v.bad and ok(f)), key=lambda f: f["price"])


def _call(name, args, i):
    return {"name": name, "args": args, "id": f"call_{i}", "type": "tool_call"}


# --- ReAct: mỗi lần gọi chọn 1 bước ---
def react_step(messages) -> AIMessage:
    sys_text = next((str(m.content) for m in messages if isinstance(m, SystemMessage)), "")
    req = parse_request(next(str(m.content) for m in messages if isinstance(m, HumanMessage)))
    c = parse_constraints(sys_text)
    v = derive(history_from_messages(messages))
    i = sum(isinstance(m, AIMessage) for m in messages) + 1

    def act(thought, name, args):
        return AIMessage(content=f"Suy luận: {thought}", tool_calls=[_call(name, args, i)])

    if v.confirmed:
        b = v.confirmed
        return AIMessage(content=f"Đã đặt thành công vé {b['flight_id']} ngày {b['depart_date']} "
                                 f"lúc {b['depart_time']}, mã đặt chỗ {b['booking_code']}, giá {b['price']:,}đ.")
    if v.paid:
        return act("đã thanh toán, đọc lại trạng thái booking", "get_booking", {"booking_code": v.booking})
    if v.booking:
        return act("đã giữ chỗ, tiến hành thanh toán", "pay", {"booking_code": v.booking})
    if not v.flights:
        if v.last_search is None:
            return act("cần danh sách chuyến", "search_flights",
                       {"origin": req["origin"], "dest": req["dest"], "date": req["date"]})
        args, obs = v.last_search
        if obs.get("status") in ("invalid_param", "denied"):
            return act("tham số ngày sai định dạng, sửa theo hint", "search_flights",
                       {**args, "date": normalize_date(args["date"])})
        if obs.get("status") == "error":
            return act("dịch vụ lỗi, thử lại", "search_flights", dict(args))
        return AIMessage(content="Không có chuyến bay nào cho hành trình này.")
    cand = candidates(v, c)
    if not cand:
        return AIMessage(content="Không tìm thấy chuyến nào phù hợp. Đã loại: "
                                 + ", ".join(f"{k} ({r})" for k, r in v.bad.items()))
    f = cand[0]
    if f["flight_id"] in v.checked:
        return act(f"{f['flight_id']} còn ghế, giữ chỗ", "book_seat", {"flight_id": f["flight_id"]})
    return act(f"chọn chuyến rẻ nhất {f['flight_id']} ({f['price']:,}đ), kiểm tra ghế",
               "check_seat", {"flight_id": f["flight_id"]})


# --- Planner: sinh cả kế hoạch ---
def plan(messages) -> dict:
    sys_text = next((str(m.content) for m in messages if isinstance(m, SystemMessage)), "")
    req = parse_request(next(str(m.content) for m in messages if isinstance(m, HumanMessage)))
    c = parse_constraints(sys_text)
    hist = history_from_messages(messages)
    tail = [{"tool": "pay", "args": {"booking_code": "$booking"}},
            {"tool": "get_booking", "args": {"booking_code": "$booking"}}]
    if not hist:   # kế hoạch đầu: chọn chuyến rẻ nhất
        return {"status": "ok", "pick_rule": "cheapest", "reasoning": "tìm → chọn rẻ nhất → kiểm ghế → giữ → trả → xác nhận",
                "steps": [{"tool": "search_flights", "args": dict(req)},
                          {"tool": "check_seat", "args": {"flight_id": "$pick"}},
                          {"tool": "book_seat", "args": {"flight_id": "$pick"}}] + tail}
    v = derive(hist)    # lập lại kế hoạch từ kết quả đã có
    if v.confirmed:
        return {"status": "done", "steps": []}
    if v.paid:
        return {"status": "ok", "steps": tail[1:]}
    if v.booking:
        return {"status": "ok", "steps": tail}
    if not v.flights:
        args, obs = v.last_search
        if obs.get("status") in ("invalid_param", "denied"):
            args = {**args, "date": normalize_date(args["date"])}
        return {"status": "ok", "pick_rule": "cheapest", "reasoning": "tìm lại chuyến",
                "steps": [{"tool": "search_flights", "args": args},
                          {"tool": "check_seat", "args": {"flight_id": "$pick"}},
                          {"tool": "book_seat", "args": {"flight_id": "$pick"}}] + tail}
    cand = candidates(v, c)
    if not cand:
        return {"status": "no_option", "steps": [], "reasoning": f"đã loại {sorted(v.bad)}"}
    fid = cand[0]["flight_id"]
    steps = [] if fid in v.checked else [{"tool": "check_seat", "args": {"flight_id": fid}}]
    return {"status": "ok", "reasoning": f"đổi sang {fid}, loại {sorted(v.bad)}",
            "steps": steps + [{"tool": "book_seat", "args": {"flight_id": fid}}] + tail}


class ModelGia(BaseChatModel):
    """Chat model giả lập, dùng được trong create_agent."""

    @property
    def _llm_type(self) -> str:
        return "model-gia"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        sys_text = next((str(m.content) for m in messages if isinstance(m, SystemMessage)), "")
        if PLANNER_TAG in sys_text:
            msg = AIMessage(content=json.dumps(plan(messages), ensure_ascii=False))
        else:
            msg = react_step(messages)
        return ChatResult(generations=[ChatGeneration(message=msg)])
