"""Mẫu Lai: như Plan-then-Execute nhưng lập lại kế hoạch khi kết quả tool lệch đáng kể."""
from __future__ import annotations

from agent_plan_execute import build_graph
from harness import Harness


def significant_change(tool: str, obs: dict, h: Harness) -> bool:
    """True nếu kết quả tool làm kế hoạch hiện tại không còn đúng."""
    if tool == "check_seat" and obs.get("price", 0) > h.c.max_price:
        return True        # giá mới vượt ngân sách
    if tool == "search_flights" and obs.get("count", 1) == 0:
        return True
    return False


def run(h: Harness, model, request: str, recursion_limit: int = 80) -> str:
    graph = build_graph(h, model, request, replan=significant_change, max_replans=4)
    out = graph.invoke({"history": [], "refs": {}}, {"recursion_limit": recursion_limit})
    return out.get("final", "")
