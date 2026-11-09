"""시간표 재생 · 그룹 설정 묶음 · 버전 · 저장 · 충돌 규칙 · 어느 시간표를 따를지 · 수정 목록 186 (2026-11-09)

사용자 결정(설계 7장) · 입력은 마스터 한 곳(재생 방식 · 회차 간격 · 운영시간) · 나머지 PC 는 받아서 디스크에
저장(재부팅 뒤에도 유지) · 애니메이션 파일은 지금처럼 PC 마다 · 끊긴 PC 는 옛 버전으로 계속 · 다시 붙으면 받아
다음 회차 경계부터 · 운영 중 설정 변경은 다음 회차 경계부터(Q7) · 끊긴 PC 의 정지는 다시 붙으면(Q8).

시간표는 스케줄(운영시간)에만 · 사람이 누른 그룹 재생은 재생 방식과 상관없이 신호 재생(사용자 2026-11-09 · Q9 변경).

- 버전 · 마스터가 바꿀 때마다 +1 · 높은 버전이 이긴다 · 같은 버전에 내용이 다르면(마스터 둘) 이름이 앞인
  마스터 것(`_accept_execution_claim` 의 min 규칙과 같음)
- 사람 정지(즉시 정지 · 회차 후 정지)도 이 묶음의 한 칸 · 끊긴 PC 는 다시 붙어 새 버전을 받는
  순간 따른다(따로 다시 보내기 없음)
- 운영시간 · 마스터 스케줄 항목을 그대로 싣는다 · 각 PC 가 `schedule_engine` 과 같은 규칙으로 구간을 계산 ·
  시각은 그 PC 의 시간대로 읽는다(모든 PC 시간대가 같아야 한다 · 다르면 표시)

ROS 를 모른다 · 계산 · 파일만.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from motion_common import store as common_store

from . import clock_grid
from .clock_grid import Timeline

#: 재생 방식 · 코드 이름 · 화면 이름은 웹(「신호 재생」 · 「시간표 재생」)
MODE_SIGNAL = 'lockstep'
MODE_CLOCK = 'clock'
MODES = (MODE_SIGNAL, MODE_CLOCK)

#: 설정 파일 · 모든 PC · 워크스페이스 `config/` 아래
FILE_NAME = 'group_timetable.json'
#: 묶음 형식 번호 · 칸을 바꾸면 올린다
FORMAT = 1

STOP_NOW = 'now'
STOP_AFTER_CYCLE = 'after_cycle'

#: 운전 모드 · `schedule_store` 와 같은 글자
SCHEDULE_MODE = 'schedule'
MANUAL_MODE = 'manual'
OFF_MODE = 'off'


@dataclass(frozen=True)
class TimetableConfig:
    """그룹 설정 묶음 · 마스터가 정하고 모든 PC 가 같은 것을 갖는다"""

    version: int = 0
    issued_by: str = ''
    issued_at_unix: float = 0.0
    mode: str = MODE_SIGNAL
    #: 사람이 넣은 회차 간격 · 0 = 자동
    period_sec: float = 0.0
    #: 자동 회차 간격 · 마스터가 PC 보고(가장 긴 클립 + 초기 이동)로 계산
    auto_period_sec: float = 0.0
    start_lead_sec: float = clock_grid.DEFAULT_START_LEAD_SEC
    #: 마스터 운전 모드가 스케줄인가 · 아니면 아무 PC 도 스케줄 시간표를 따르지 않는다
    schedule_enabled: bool = False
    #: 마스터 스케줄 항목(`ScheduleItem.to_dict`) · 운영시간 계산용
    schedules: Tuple[Mapping[str, Any], ...] = ()
    #: 마스터 시간대 · 판정에는 안 쓴다 · PC 시간대가 다르면 표시
    timezone: str = ''
    #: 마스터가 계산한 운영시간(어제 · 오늘 · 내일 · 유닉스 초) · 스피커는 스케줄 계산 꾸러미가 없어 이것을 쓴다 ·
    #: 로봇 PC 는 `schedules` 로 직접 계산(오래 끊겨도 날짜가 넘어가게)
    windows: Tuple[Tuple[float, float], ...] = ()
    #: 운영 중 설정 변경 · 그 경계(유닉스 초) · 그 경계의 회차 번호 · 0 = 없음
    rebase_unix: float = 0.0
    rebase_cycle: int = 0
    #: 사람 정지 · plan_id · mode(now · after_cycle) · last_cycle · 빈 것 = 없음
    stop: Mapping[str, Any] = field(default_factory=dict)
    #: 마스터 재생 목록(파일 이름) · 스피커 음원 고르기 · 표시
    playlist: Tuple[str, ...] = ()
    #: 초기 위치 이동 시간 · 0 = PC 마다 조인트 매핑 값
    initial_move_time_sec: float = 0.0

    @property
    def clock(self) -> bool:
        return self.mode == MODE_CLOCK

    def period(self) -> float:
        return clock_grid.effective_period(self.period_sec, self.auto_period_sec)


# --------------------------------------------------------------------------- #
# 직렬화 · 저장
# --------------------------------------------------------------------------- #

def to_body(config: TimetableConfig) -> Dict[str, Any]:
    body = asdict(config)
    body['format'] = FORMAT
    body['schedules'] = [dict(item) for item in config.schedules]
    body['stop'] = dict(config.stop)
    body['playlist'] = list(config.playlist)
    body['windows'] = [list(pair) for pair in config.windows]
    return body


def from_body(body: Any) -> TimetableConfig:
    """받은 묶음 · 모르는 칸은 버림 · 틀린 값은 기본값 · 읽을 수 없으면 ValueError"""
    if isinstance(body, (str, bytes)):
        try:
            body = json.loads(body)
        except ValueError as exc:
            raise ValueError(f'시간표 설정을 읽을 수 없습니다: {exc}') from exc
    if not isinstance(body, Mapping):
        raise ValueError('시간표 설정은 객체여야 합니다')
    mode = str(body.get('mode') or MODE_SIGNAL)
    schedules = body.get('schedules') or ()
    stop = body.get('stop') or {}
    playlist = body.get('playlist') or ()
    windows = []
    for pair in body.get('windows') or ():
        try:
            starts_at, ends_at = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if ends_at > starts_at:
            windows.append((starts_at, ends_at))
    return TimetableConfig(
        version=max(_int(body.get('version')), 0),
        issued_by=str(body.get('issued_by') or ''),
        issued_at_unix=_float(body.get('issued_at_unix')),
        mode=mode if mode in MODES else MODE_SIGNAL,
        period_sec=max(_float(body.get('period_sec')), 0.0),
        auto_period_sec=max(_float(body.get('auto_period_sec')), 0.0),
        start_lead_sec=max(_float(body.get('start_lead_sec'), clock_grid.DEFAULT_START_LEAD_SEC), 0.0),
        schedule_enabled=bool(body.get('schedule_enabled')),
        schedules=tuple(dict(item) for item in schedules if isinstance(item, Mapping)),
        timezone=str(body.get('timezone') or ''),
        windows=tuple(windows),
        rebase_unix=max(_float(body.get('rebase_unix')), 0.0),
        rebase_cycle=max(_int(body.get('rebase_cycle')), 0),
        stop=dict(stop) if isinstance(stop, Mapping) else {},
        playlist=tuple(str(name) for name in playlist if str(name).strip()) if isinstance(playlist, (list, tuple)) else (),
        initial_move_time_sec=max(_float(body.get('initial_move_time_sec')), 0.0),
    )


def body_text(config: TimetableConfig) -> str:
    return json.dumps(to_body(config), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def content_key(config: TimetableConfig) -> str:
    """버전 · 보낸 PC · 보낸 시각을 뺀 내용 · 같은 버전 충돌을 가른다"""
    body = to_body(config)
    for key in ('version', 'issued_by', 'issued_at_unix'):
        body.pop(key, None)
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def default_path(workspace: Path) -> Path:
    return Path(workspace) / 'config' / FILE_NAME


def load(path: Path) -> TimetableConfig:
    """디스크의 마지막 묶음 · 없거나 깨졌으면 기본(신호 재생 · 버전 0)"""
    try:
        return from_body(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return TimetableConfig()


def save(path: Path, config: TimetableConfig) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    common_store.atomic_write_json(path, to_body(config))


def accept(current: TimetableConfig, incoming: TimetableConfig) -> bool:
    """받은 묶음을 쓸까 · 높은 버전 · 같은 버전 내용이 다르면 이름이 앞인 마스터 것"""
    if incoming.version > current.version:
        return True
    if incoming.version < current.version or incoming.version == 0:
        return False
    if content_key(incoming) == content_key(current):
        return False
    return bool(incoming.issued_by) and (not current.issued_by or incoming.issued_by < current.issued_by)


# --------------------------------------------------------------------------- #
# 운영시간
# --------------------------------------------------------------------------- #

def schedule_windows(schedules, now_unix: float) -> List[Tuple[float, float]]:
    """스케줄 항목 → 어제 · 오늘 · 내일 시작하는 운영시간들(유닉스 초) · 이 PC 시간대로 읽는다

    규칙은 `motion_common.schedule_window`(스케줄 노드 `schedule_engine` 과 같은 곳) · 스케줄 노드와 같은 답.
    """
    from motion_common.schedule_models import ScheduleItem
    from motion_common.schedule_window import day_matches as _day_matches, window_of

    now = datetime.fromtimestamp(float(now_unix))
    windows: List[Tuple[float, float]] = []
    for raw in schedules or ():
        try:
            item = ScheduleItem.from_dict(dict(raw))
        except (TypeError, ValueError):
            continue
        if not item.enabled:
            continue
        for day in (now - timedelta(days=1), now, now + timedelta(days=1)):
            if not _day_matches(item, day):
                continue
            window = window_of(item, day)
            if window is not None:
                windows.append((window[0].timestamp(), window[1].timestamp()))
    return windows


# --------------------------------------------------------------------------- #
# 어느 시간표를 따르나
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Choice:
    """이 PC 가 지금 따를 시간표 · 없으면 이유"""

    timeline: Optional[Timeline] = None
    reason: str = ''
    #: 사람이 「즉시 정지」 한 시간표 · 이 PC 가 그 실행을 쥐고 있으면 바로 세운다
    stopped_plan_id: str = ''
    #: 사람이 「회차 후 정지」 한 시간표 · 끝이 운영시간 끝이 아니라 정지라서 주차하지 않는다
    stop_after: bool = False


def choose(config: TimetableConfig, now_unix: float, *, operation_mode: str) -> Choice:
    """지금 따를 시간표 · 마스터 스케줄의 운영시간 · 사람이 누른 그룹 재생은 신호 재생이라 여기 없다

    - 오프 · 수동 모드 PC · 아무것도 안 따른다
    - 스케줄 시간표 · 마스터 운전 모드가 스케줄이고 이 PC 도 스케줄 모드일 때만
    - 따를 시간표가 없어도 즉시 정지는 알린다 · 마스터를 수동으로 바꾼 뒤 아직 회차를 마치는 PC 를 세우게
    """
    if not config.clock:
        return Choice(reason='신호 재생')
    stop = dict(config.stop or {})
    halted = str(stop.get('plan_id') or '') if stop.get('mode') == STOP_NOW else ''
    mode = str(operation_mode or SCHEDULE_MODE)
    if mode == OFF_MODE:
        return Choice(reason='오프 모드', stopped_plan_id=halted)
    period = config.period()
    if period <= 0.0:
        return Choice(reason='회차 간격 모름', stopped_plan_id=halted)
    if not config.schedule_enabled:
        return Choice(reason='마스터 스케줄 꺼짐', stopped_plan_id=halted)
    if mode != SCHEDULE_MODE:
        return Choice(reason='수동 모드', stopped_plan_id=halted)
    window = clock_grid.pick_window(schedule_windows(config.schedules, now_unix), now_unix)
    if window is None:
        return Choice(reason='운영시간 아님', stopped_plan_id=halted)
    rebase = (config.rebase_unix, config.rebase_cycle) if config.rebase_unix else None
    timeline = clock_grid.window_timeline(
        window, period, start_lead_sec=config.start_lead_sec, rebase=rebase,
    )
    if timeline is None:
        return Choice(reason='운영시간 아님', stopped_plan_id=halted)
    if stop.get('plan_id') and str(stop['plan_id']) == timeline.plan_id:
        if stop.get('mode') == STOP_NOW:
            return Choice(reason='정지됨', stopped_plan_id=timeline.plan_id)
        if stop.get('mode') == STOP_AFTER_CYCLE:
            last = _int(stop.get('last_cycle'))
            if last < timeline.first_cycle:
                return Choice(reason='정지됨', stopped_plan_id=timeline.plan_id)
            # 그 회차 다음 경계부터 시작 없음 · 도는 회차는 끝까지
            cut = timeline.start_of(last + 1) - 1e-3
            timeline = replace(timeline, end_unix=min(timeline.end_unix, cut) if timeline.end_unix else cut)
            return Choice(timeline=timeline, stop_after=True)
    return Choice(timeline=timeline)


# --------------------------------------------------------------------------- #
# 마스터 · 새 버전 만들기
# --------------------------------------------------------------------------- #

def issue(current: TimetableConfig, *, issuer: str, now_unix: Optional[float] = None, **changes: Any) -> TimetableConfig:
    """마스터 · 바꾼 칸으로 새 버전 · 운영 중에 회차 시각이 바뀌면 다음 경계부터(Q7)

    회차 시각이 바뀌는 칸 = 재생 방식 · 회차 간격(사람 · 자동) · 시작 여유 · 스케줄 · 스케줄 켬.
    지금 따르는 스케줄 시간표의 다음 경계를 새 기준 시각으로 적어 둔다 · 회차 번호는 이어서.
    """
    now = time.time() if now_unix is None else float(now_unix)
    updated = replace(current, **changes)
    if content_key(updated) == content_key(current):
        return current
    timing_fields = ('mode', 'period_sec', 'auto_period_sec', 'start_lead_sec', 'schedules', 'schedule_enabled')
    if current.clock and updated.clock and any(getattr(updated, name) != getattr(current, name) for name in timing_fields):
        before = choose(current, now, operation_mode=SCHEDULE_MODE).timeline
        if before is not None:
            point, cycle = clock_grid.rebase_point(before, now)
            if point:
                updated = replace(updated, rebase_unix=point, rebase_cycle=cycle)
    return replace(updated, version=current.version + 1, issued_by=str(issuer), issued_at_unix=now)


def stop_plan(
    current: TimetableConfig, *, issuer: str, after_cycle: bool, now_unix: Optional[float] = None,
    held_plan_id: str = '',
) -> Tuple[TimetableConfig, str]:
    """사람 정지 · 지금 시간표에 정지를 적는다 · (새 묶음, 그 시간표 이름) · 따르는 시간표가 없으면 그대로

    회차 후 정지 = 지금 도는 회차(시간표상)까지 · 즉시 정지 = 바로.
    `held_plan_id` · 따를 시간표는 없는데(마스터를 수동으로 바꿈) 아직 그 회차를 도는 PC 가 있다 · 즉시 정지만
    적는다(회차 후 정지는 할 일 없음 · 그 PC 들은 회차를 마치고 스스로 놓는다).
    """
    now = time.time() if now_unix is None else float(now_unix)
    choice = choose(current, now, operation_mode=SCHEDULE_MODE)
    timeline = choice.timeline
    if timeline is None:
        if held_plan_id and not after_cycle:
            stop = {'plan_id': str(held_plan_id), 'mode': STOP_NOW}
            return issue(current, issuer=issuer, now_unix=now, stop=stop), str(held_plan_id)
        return current, ''
    if after_cycle:
        last = clock_grid.running_cycle(timeline, now)
        stop = {'plan_id': timeline.plan_id, 'mode': STOP_AFTER_CYCLE, 'last_cycle': last or (timeline.first_cycle - 1)}
    else:
        stop = {'plan_id': timeline.plan_id, 'mode': STOP_NOW}
    return issue(current, issuer=issuer, now_unix=now, stop=stop), timeline.plan_id


def resume_schedule(current: TimetableConfig, *, issuer: str, now_unix: Optional[float] = None) -> TimetableConfig:
    """스케줄이 다시 시작을 원한다 · 스케줄 시간표의 정지를 지운다 · 다음 경계부터"""
    stop = dict(current.stop or {})
    if not str(stop.get('plan_id') or '').startswith('tt-s'):
        return current
    return issue(current, issuer=issuer, now_unix=now_unix, stop={})


# --------------------------------------------------------------------------- #

def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    return number if number == number and abs(number) != float('inf') else float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)
