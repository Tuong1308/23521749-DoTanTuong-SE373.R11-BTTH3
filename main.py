"""Chạy một mẫu trên một kịch bản và in trace.

    python main.py --pattern react --scenario S2
    python main.py --pattern hybrid --scenario S7 --approve
    python main.py --pattern react --scenario S6 --no-harness
"""
from __future__ import annotations

import argparse
import sys

import agent_hybrid
import agent_plan_execute
import agent_react
from harness import Harness
from model_gia import get_model
from tools_mock import SCENARIOS, FlightWorld

RUNNERS = {"react": agent_react.run, "plan": agent_plan_execute.run, "hybrid": agent_hybrid.run}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", choices=RUNNERS, default="react")
    ap.add_argument("--scenario", choices=[s.id for s in SCENARIOS], default="S2")
    ap.add_argument("--model", default=None, help='vd "anthropic:claude-sonnet-5-5"; mặc định model giả lập')
    ap.add_argument("--approve", action="store_true", help="giả lập người duyệt đồng ý mọi yêu cầu phê duyệt")
    ap.add_argument("--no-harness", action="store_true")
    a = ap.parse_args()

    sc = next(s for s in SCENARIOS if s.id == a.scenario)
    print(f"Kịch bản {sc.id}: {sc.title}\n  {sc.note}\n  Yêu cầu: {sc.request}\n  Mẫu: {a.pattern}\n")
    approver = (lambda req: print(f"  [người duyệt] {req['reasons']} -> đồng ý") or True) \
        if a.approve else None
    h = Harness(FlightWorld(sc), approver=approver, enabled=not a.no_harness, verbose=True)
    final = RUNNERS[a.pattern](h, get_model(a.model), sc.request)
    print("\nKẾT QUẢ")
    print(final or f"(không có câu trả lời: {h.error})")
    print("\nĐạt tiêu chí hoàn thành (kiểm bằng code):", h.done)
    print("Chỉ số:", h.metrics())
    print("Tác dụng phụ trên backend:", h.world.side_effects or "không có")


if __name__ == "__main__":
    main()
