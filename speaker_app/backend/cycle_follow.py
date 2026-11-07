"""진행 PC 가 안 보여도 회차 눈금대로 소리를 잇는다 · 수정 목록 178 (2026-11-08)

로봇 PC 는 회차 맞춤 연속 재생에서 2회차부터 「앞 시작 + 주기」(10 s 올림)에 시작하고, 진행 PC 가 안
보이면 참가 PC 가 같은 눈금으로 스스로 잇는다 · 스피커도 같다 ·

- 진행 PC 의 `start_at` 두 개(이어진 회차)의 간격 = 주기
- 다음 시작 시각이 다가왔는데 진행 PC 하트비트가 끊겼고(3 s) · 같은 실행을 도는 다른 PC 가 보이면
  마지막 시작 + n × 주기 에 지난번과 같은 음원을 튼다
- 진행 PC 가 보이는 동안에는 기다린다(늦는 회차면 진행 PC 가 주기를 늘려 보낸다) · 도는 PC 가 하나도
  안 보이면(운영시간 끝 · 모두 섬) 그만둔다 · 정지 사건이 오면 잊는다

ROS 를 모른다 · 로봇 쪽 `motion_coordination.cycle_grid` 와 같은 계산(스피커 PC 에는 그 꾸러미가 없다).
"""

import math
import threading

#: 진행 PC 하트비트가 이만큼 없으면 「안 보임」 · 로봇 그룹 기본(peer_timeout 3 s)과 같다
MASTER_GONE_SEC = 3.0
#: 다음 시작 몇 초 전부터 볼까 · 진행 PC 의 `start_at` 은 보통 0.5~3 s 앞서 온다
LOOKAHEAD_SEC = 1.0


class CycleFollower:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = None

    def record(self, *, execution_id, coordinator_id, cycle, start, context, learn=True):
        """시작 하나 · 이어진 회차면 간격 = 주기 · `context` = 다시 틀 때 쓸 칸(음원 · 구간)"""
        if not execution_id:
            return
        with self._lock:
            state = self._state
            if state is None or state["execution_id"] != execution_id:
                state = self._state = {"execution_id": execution_id, "period": 0.0}
            if (
                learn
                and state.get("start") is not None
                and int(cycle) == int(state.get("cycle") or 0) + 1
                and float(start) > float(state["start"])
            ):
                state["period"] = float(start) - float(state["start"])
            state.update(coordinator_id=str(coordinator_id or ""), cycle=int(cycle),
                         start=float(start), context=dict(context or {}), due=None)

    def clear(self):
        with self._lock:
            self._state = None

    def snapshot(self):
        with self._lock:
            return dict(self._state) if self._state else None

    def due(self, *, now, coordinator_age, others_running):
        """지금 스스로 틀 회차 · (회차, 시작 시각, context) 또는 None

        `coordinator_age` = 진행 PC 하트비트 나이(초 · 모르면 None) · `others_running` = 같은 실행을 도는 다른 PC 가 보이나
        """
        with self._lock:
            state = self._state
            if not state or float(state.get("period") or 0.0) <= 0.0 or state.get("start") is None:
                return None
            period = float(state["period"])
            last = float(state["start"])
            if now < last + period - LOOKAHEAD_SEC:
                return None
            if coordinator_age is not None and coordinator_age < MASTER_GONE_SEC:
                return None
            if not others_running:
                self._state = None
                return None
            steps = max(int(math.ceil((now + 0.2 - last) / period - 1e-9)), 1)
            start = last + steps * period
            cycle = int(state.get("cycle") or 0) + 1
            return cycle, start, dict(state.get("context") or {})
