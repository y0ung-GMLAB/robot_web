"""시간표 재생 · 스피커도 같은 시간표로 · 수정 목록 186 (2026-11-09)

「시간표 재생」 에서 로봇 PC 는 마스터 신호 없이 시간표 시각에 스스로 재생한다 · `start_at` 이 오지 않는다 ·
스피커도 마스터가 보내는 그룹 설정 묶음(`/motion_group/timetable`)을 받아 같은 시각에 음원을 튼다.

- 회차 k 시작 = 기준 시각 + (k − 첫 회차) × 주기 · 음원 = 마스터 재생 목록의 (k − 1) mod n 번째 애니메이션 것
- 기준 · 마스터 스케줄이 켜졌을 때 운영시간(마스터가 계산해 실은 `windows`) + 시작 여유 · 운영 중 설정 변경이면
  그 경계(`rebase_*`) · 사람이 누른 그룹 재생은 시간표가 아니라 신호 재생(`start_at`) · 사용자 2026-11-09
- 사람 정지 · 즉시 정지면 지금 소리도 끈다 · 회차 후 정지면 다음 회차를 안 튼다
- 받은 묶음은 파일에 둔다 · 마스터가 꺼져도 · 스피커가 다시 켜져도 마지막 시간표로

ROS 를 모른다 · 계산은 로봇 쪽 `motion_coordination.clock_grid` · `timetable.choose` 와 같다(스피커 PC 에는 그
꾸러미가 없다 · 고칠 때 둘 다).
"""

import json
import math
import os
import threading

MODE_CLOCK = "clock"
#: 시작 몇 초 전에 예약할까 · 예약은 타이머라 이르게 걸어도 된다
LOOKAHEAD_SEC = 2.0
STEP_SEC = 10.0
MARGIN_SEC = 2.0


def _float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def auto_period(period_sec, auto_sec):
    manual = _float(period_sec)
    auto = _float(auto_sec)
    if manual > 0.0 and (not auto or manual + 1e-6 >= auto):
        return manual
    return auto


def _merge(windows):
    merged = []
    pairs = []
    for pair in windows or ():
        try:
            pairs.append((float(pair[0]), float(pair[1])))
        except (TypeError, ValueError, IndexError):
            continue
    for start, end in sorted(pair for pair in pairs if pair[1] > pair[0]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def timeline(body, now):
    """(plan_id, anchor, period, end, first_cycle) 또는 None · 정지면 ('stopped', plan_id)"""
    if not isinstance(body, dict) or body.get("mode") != MODE_CLOCK:
        return None
    period = auto_period(body.get("period_sec"), body.get("auto_period_sec"))
    if period <= 0.0:
        return None
    stop = body.get("stop") if isinstance(body.get("stop"), dict) else {}
    if not body.get("schedule_enabled"):
        # 마스터를 수동으로 바꿈 · 따를 시간표는 없지만 즉시 정지는 도는 소리에 닿게
        return ("stopped", str(stop["plan_id"])) if stop.get("mode") == "now" and stop.get("plan_id") else None
    else:
        window = None
        merged = _merge(body.get("windows"))
        for start, end in merged:
            if start <= now < end:
                window = (start, end)
                break
        if window is None:
            upcoming = [pair for pair in merged if now < pair[0] <= now + 86400.0]
            window = tuple(upcoming[0]) if upcoming else None
        if window is None:
            return None
        anchor = window[0] + max(_float(body.get("start_lead_sec"), 60.0), 0.0)
        first = 1
        rebase = _float(body.get("rebase_unix"))
        if rebase and anchor <= rebase < window[1]:
            anchor, first = rebase, max(int(body.get("rebase_cycle") or 1), 1)
        if anchor >= window[1]:
            return None
        plan = ("tt-s%d" % int(round(window[0])), anchor, period, window[1], first)
    if stop.get("plan_id") == plan[0]:
        if stop.get("mode") == "now":
            return ("stopped", plan[0])
        if stop.get("mode") == "after_cycle":
            last = int(stop.get("last_cycle") or 0)
            if last < plan[4]:
                return ("stopped", plan[0])
            cut = plan[1] + (last + 1 - plan[4]) * plan[2] - 1e-3
            plan = (plan[0], plan[1], plan[2], min(plan[3], cut) if plan[3] else cut, plan[4])
    return plan


def next_cycle(plan, now):
    """(회차, 시작) · 지금 이후 첫 회차 · 없으면 None"""
    plan_id, anchor, period, end, first = plan
    steps = max(math.ceil((now - anchor) / period - 1e-9), 0)
    cycle = steps + first
    start = anchor + steps * period
    if end and start >= end:
        return None
    return cycle, start


class TimetableFollower:
    def __init__(self, path):
        self._path = path
        self._lock = threading.Lock()
        self._body = {}
        self._played = ("", 0)
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                self._body = loaded
        except (OSError, ValueError):
            pass

    def update(self, version, body_text, sender):
        """받은 묶음 · 높은 버전 · 같은 버전 내용이 다르면 이름이 앞인 마스터 · 바뀌면 True"""
        try:
            body = json.loads(body_text)
        except (TypeError, ValueError):
            return False
        if not isinstance(body, dict):
            return False
        with self._lock:
            current = int(self._body.get("version") or 0)
            version = int(version or body.get("version") or 0)
            if version < current or version == 0:
                return False
            if version == current:
                if body == self._body:
                    return False
                if not sender or sender >= str(self._body.get("issued_by") or "~"):
                    return False
            self._body = body
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(body, handle, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError:
            pass
        return True

    def snapshot(self):
        with self._lock:
            return dict(self._body)

    def clock(self):
        with self._lock:
            return self._body.get("mode") == MODE_CLOCK

    def active(self, now):
        """따르는 시간표가 있나 · 없으면(마스터 수동 · 운영시간 정보 없음) 신호 재생의 눈금 잇기(178)가 맡는다"""
        plan = timeline(self.snapshot(), now)
        return bool(plan) and plan[0] != "stopped"

    def stopped_plan(self, now):
        plan = timeline(self.snapshot(), now)
        return plan[1] if plan and plan[0] == "stopped" else ""

    def due(self, now):
        """지금 예약할 회차 · (plan_id, 회차, 시작, 애니메이션 이름) · 같은 회차는 한 번만"""
        body = self.snapshot()
        plan = timeline(body, now)
        if not plan or plan[0] == "stopped":
            return None
        found = next_cycle(plan, now)
        if found is None:
            return None
        cycle, start = found
        if start - now > LOOKAHEAD_SEC:
            return None
        with self._lock:
            if self._played == (plan[0], cycle):
                return None
            self._played = (plan[0], cycle)
        playlist = [str(name) for name in body.get("playlist") or [] if str(name).strip()]
        motion = playlist[(cycle - 1) % len(playlist)] if playlist else ""
        return plan[0], cycle, start, motion
