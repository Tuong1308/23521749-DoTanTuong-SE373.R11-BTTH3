"""Mẫu ReAct: create_agent + middleware gắn harness."""
from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from harness import Harness
from tools_mock import make_tools

SYSTEM = """Bạn là agent đặt vé máy bay. Chỉ dùng tool để lấy thông tin; không tự bịa mã chuyến, giá hay mã đặt chỗ.
Quy trình gợi ý: search_flights → check_seat → book_seat → pay → get_booking (tới khi state = confirmed).
Nếu tool trả status khác "ok", đọc "hint" để đổi hướng thay vì gọi lại y hệt.
Khi xong, trả lời ngắn gọn: mã chuyến, ngày giờ bay, mã đặt chỗ, giá.
{constraints}"""


class HarnessMiddleware(AgentMiddleware):
    def __init__(self, h: Harness):
        super().__init__()
        self.h = h

    def _end(self):
        return {"jump_to": "end", "messages": [AIMessage(content=self.h.stop.render())]}

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        if self.h.stop or (self.h.enabled and self.h.check_budget()):
            return self._end()
        return None

    def wrap_model_call(self, request, handler):
        resp = handler(request)
        out = getattr(resp, "result", [resp])
        msgs = ([request.system_message] if request.system_message else []) + list(request.messages)
        self.h.count_model_call(msgs, [getattr(m, "content", "") for m in out])
        return resp

    def wrap_tool_call(self, request, handler):
        tc = request.tool_call

        def run():
            content = handler(request).content
            try:
                return json.loads(content)
            except (TypeError, json.JSONDecodeError):
                return {"status": "error", "error": str(content)[:200]}

        obs = self.h.call_tool(tc["name"], tc["args"], run)
        return ToolMessage(content=json.dumps(obs, ensure_ascii=False), tool_call_id=tc["id"], name=tc["name"])

    @hook_config(can_jump_to=["end"])
    def after_model(self, state, runtime):
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return None
        if self.h.finalize(str(last.content)) or not self.h.enabled:
            return None
        return self._end()


def run(h: Harness, model, request: str, recursion_limit: int = 50) -> str:
    agent = create_agent(model=model, tools=make_tools(h.world),
                         system_prompt=SYSTEM.format(constraints=h.c.as_prompt()),
                         middleware=[HarnessMiddleware(h)])
    try:
        out = agent.invoke({"messages": [{"role": "user", "content": request}]},
                           {"recursion_limit": recursion_limit})          # trần cứng của LangGraph
        return str(out["messages"][-1].content)
    except GraphRecursionError:
        h.error = f"GraphRecursionError (recursion_limit={recursion_limit})"
        h.log("error", error=h.error)
        return ""
