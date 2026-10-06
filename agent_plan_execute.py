"""Mẫu Plan-then-Execute: lập kế hoạch 1 lần, duyệt, rồi chạy từng bước.

Graph: planner -> review -> executor (lặp) -> finish. Bước nào lỗi thì dừng và bàn giao.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from harness import Harness
from model_gia import PLANNER_TAG
from tools_mock import TOOL_DOCS

PLANNER_SYSTEM = PLANNER_TAG + """ Bạn là bộ lập kế hoạch đặt vé máy bay. Trả về DUY NHẤT một JSON:
{{"status": "ok" | "no_option" | "done", "reasoning": "...", "pick_rule": "cheapest",
 "steps": [{{"tool": "<tên tool>", "args": {{...}}}}]}}
Tool có sẵn:
{tools}
Placeholder: "$pick" = flight_id chọn theo pick_rule từ kết quả search_flights gần nhất;
"$booking" = booking_code trả về từ book_seat.
Nếu có OBSERVATIONS_JSON (danh sách [tool, args, observation]) thì lập kế hoạch cho phần CÒN LẠI dựa trên đó;
không còn chuyến hợp lệ thì trả status "no_option".
{constraints}"""

MAX_RETRY = 2


class Step(BaseModel):
    tool: str
    args: dict


class Plan(BaseModel):
    status: Literal["ok", "no_option", "done"] = "ok"
    reasoning: str = ""
    pick_rule: str = "cheapest"
    steps: list[Step] = []


class PEState(TypedDict, total=False):
    plan: list[dict]
    pick_rule: str
    step: int
    retries: int
    history: list            # [tool, args, observation]
    refs: dict               # giá trị cho $booking
    replans: int
    status: str              # running | completed | failed | deviated | no_option | halted
    final: str


def _parse_plan(text: str) -> Plan:
    m = re.search(r"\{.*\}", text, re.S)       # bỏ ```json``` nếu có
    return Plan.model_validate_json(m.group(0) if m else text)


def _resolve(args: dict, st: PEState) -> dict | None:
    out = {}
    for k, v in args.items():
        if v == "$booking":
            v = st["refs"].get("booking")
        elif v == "$pick":
            flights = next((o["flights"] for t, _, o in reversed(st["history"])
                            if t == "search_flights" and o.get("status") == "ok"), [])
            if st.get("pick_rule", "cheapest") == "cheapest":
                flights = sorted(flights, key=lambda f: f["price"])
            v = flights[0]["flight_id"] if flights else None
        if v is None:
            return None
        out[k] = v
    return out


def build_graph(h: Harness, model, request: str,
                replan: Callable[[str, dict, Harness], bool] | None = None, max_replans: int = 4):
    """replan=None: Plan-then-Execute. Có replan: mẫu Lai."""
    system = PLANNER_SYSTEM.format(tools="\n".join(f"- {k}: {v}" for k, v in TOOL_DOCS.items()),
                                   constraints=h.c.as_prompt())

    def planner(st: PEState) -> PEState:
        if h.check_budget():
            return {"status": "halted"}
        msgs = [SystemMessage(system), HumanMessage(request)]
        if st.get("history"):
            msgs.append(HumanMessage("OBSERVATIONS_JSON: " + json.dumps(st["history"], ensure_ascii=False)))
        resp = model.invoke(msgs)
        h.count_model_call(msgs, resp.content)
        try:
            p = _parse_plan(str(resp.content))
        except (ValidationError, ValueError) as e:
            h._halt("INVALID_PLAN", f"kế hoạch không parse được theo schema Plan: {str(e)[:150]}")
            return {"status": "halted"}
        h.log("plan", status=p.status, steps=[f"{s.tool}({s.args})" for s in p.steps], reasoning=p.reasoning)
        return {"plan": [s.model_dump() for s in p.steps], "pick_rule": p.pick_rule, "step": 0, "retries": 0,
                "status": "running" if p.status == "ok" else p.status,
                "replans": st.get("replans", -1) + 1}

    def review(st: PEState) -> PEState:
        """Duyệt kế hoạch trước khi chạy."""
        if st["status"] != "running":
            return {}
        bad = [s["tool"] for s in st["plan"] if s["tool"] not in h.policy.allowed_tools]
        left = h.budget.max_tool_calls - h.tool_calls
        irreversible = [s["tool"] for s in st["plan"] if s["tool"] not in h.policy.read_only]
        h.log("plan_review", steps=len(st["plan"]), irreversible=irreversible, budget_left=left)
        if bad or len(st["plan"]) > left:
            h._halt("INVALID_PLAN", f"kế hoạch bị từ chối: tool lạ {bad}" if bad
                    else f"kế hoạch {len(st['plan'])} bước vượt ngân sách còn {left} lượt tool")
            return {"status": "halted"}
        return {}

    def executor(st: PEState) -> PEState:
        step = st["plan"][st["step"]]
        hist, refs = list(st.get("history", [])), dict(st.get("refs", {}))
        args = _resolve(step["args"], {**st, "history": hist, "refs": refs})
        if args is None:
            obs = {"status": "unresolved", "reason": f"không điền được placeholder trong {step['args']}"}
        else:
            obs = h.call_tool(step["tool"], args)
        hist.append([step["tool"], args or step["args"], obs])
        if step["tool"] == "book_seat" and obs.get("status") == "ok":
            refs["booking"] = obs["booking_code"]
        out: PEState = {"history": hist, "refs": refs}
        st_ = obs.get("status")
        if h.stop:
            return {**out, "status": "halted"}
        if st_ == "error" and st.get("retries", 0) < MAX_RETRY:            # thử lại khi timeout
            return {**out, "retries": st.get("retries", 0) + 1}
        if step["tool"] == "get_booking" and obs.get("state") == "pending":  # chờ xác nhận
            return out
        if st_ != "ok":
            return {**out, "status": "failed"}
        if replan and replan(step["tool"], obs, h):
            return {**out, "status": "deviated"}
        nxt = st["step"] + 1
        return {**out, "step": nxt, "retries": 0, "status": "completed" if nxt >= len(st["plan"]) else "running"}

    def finish(st: PEState) -> PEState:
        if not h.stop:
            status = st.get("status")
            if status in ("completed", "done"):
                b = next((o for t, _, o in reversed(st.get("history", [])) if t == "get_booking"), None)
                text = (f"Đã đặt thành công vé {b['flight_id']} ngày {b['depart_date']} lúc {b['depart_time']}, "
                        f"mã đặt chỗ {b['booking_code']}, giá {b['price']:,}đ.") if b else "Đã hoàn tất kế hoạch."
                h.finalize(text)
            elif status in ("failed", "deviated"):
                t, a, o = st["history"][-1]
                why = "đã hết lượt lập lại kế hoạch" if replan else "mẫu Plan-then-Execute không lập lại kế hoạch"
                h._halt("PLAN_FAILED", f"bước {st['step'] + 1}/{len(st['plan'])} {t}({a}) → "
                                       f"{o.get('status')} {o.get('reason', '')}; {why}")
            else:
                h.finalize("Không tìm thấy chuyến phù hợp với ràng buộc.")
        return {"final": h.stop.render() if h.stop else h.final_text}

    def after_exec(st: PEState) -> str:
        s = st["status"]
        if s == "running":
            return "executor"
        if s in ("failed", "deviated") and replan and st.get("replans", 0) < max_replans:
            return "planner"
        return "finish"

    g = StateGraph(PEState)
    for name, fn in (("planner", planner), ("review", review), ("executor", executor), ("finish", finish)):
        g.add_node(name, fn)
    g.add_edge(START, "planner")
    g.add_edge("planner", "review")
    g.add_conditional_edges("review", lambda s: "executor" if s["status"] == "running" else "finish",
                            ["executor", "finish"])
    g.add_conditional_edges("executor", after_exec, ["executor", "planner", "finish"])
    g.add_edge("finish", END)
    return g.compile()


def run(h: Harness, model, request: str, recursion_limit: int = 80) -> str:
    graph = build_graph(h, model, request)
    out = graph.invoke({"history": [], "refs": {}}, {"recursion_limit": recursion_limit})
    return out.get("final", "")
