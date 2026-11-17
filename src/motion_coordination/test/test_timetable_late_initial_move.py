"""시간표 재생 · 초기 이동이 늦게 끝난 PC · 수정 목록 206 (2026-11-16)

사용자 결정 2026-11-16 · 시간표 재생에서 초기 이동이 회차 시작 뒤에 끝나도 잘못이 아니다
- 그 PC 만 끝나는 대로 바로 시작(회차를 쉬지 않음) · 늦음은 기록 · 다음 회차는 다시 시간표대로
- 다른 PC 는 기다리지 않는다 · 스피커는 늘 시간표 시각에 음원
- 너무 늦어 그 회차를 돌면 다음 회차 준비(초기 이동)를 먹을 때만 그 회차를 쉰다(이유 기록)

전에는 연동 노드가 초기 이동 끝을 본 뒤 시작 예약을 보냈다 · 시각을 넘긴 예약은 「트리거가 이미 지났습니다」 로 거절돼
그 회차를 쉬었다(실물 NY 2026-11-09 04:04 · 4대 중 3대).

시나리오 · PC 둘(A 제때 · B 의 2회차 초기 이동만 늦음) + 스피커(시간표 묶음만 봄) · 920 s 클립 · 초기 이동 10 s · 940 s
간격과 같은 남는 시간(8.5 s)으로 줄여 클립 80 s · 초기 이동 10 s · 간격 100 s.
"""

import json
import sys
from pathlib import Path

import pytest

from motion_common.timed_cycle import INITIAL_MOVE_SETTLE_SEC
from motion_coordination.clock_driver import ClockDriver
from motion_coordination.clock_grid import Timeline, auto_period
from motion_coordination.timetable import Choice

from test_clock_driver import Clock, FakeRuntime

SPEAKER_BACKEND = Path(__file__).resolve().parents[3] / 'speaker_app' / 'backend'

CLIP = 80.0
INIT = 10.0
WINDOW = (100_000.0, 100_600.0)
START_LEAD = 60.0


def _period() -> float:
    period = auto_period([CLIP + INIT])
    assert period == 100.0, '80 + 10 + 회차 끝 0.5 + 시작 여유 1 = 91.5 → 100 · 남는 8.5 s 가 늦은 시작 한도'
    return period


def _pc(late_cycle2: float):
    clock = Clock(WINDOW[0])
    runtime = FakeRuntime(clock, clip=CLIP, init=INIT, plan_init=INIT,
                          late={2: INITIAL_MOVE_SETTLE_SEC + late_cycle2} if late_cycle2 else None)
    notes = []
    driver = ClockDriver(runtime.control, info=notes.append, warn=notes.append, wall=clock.wall, mono=clock.mono,
                         finish=lambda plan, park, why: runtime.control({'command': 'group_cancel'}))
    return clock, runtime, driver, notes


def _speaker(tmp_path, period):
    sys.path.insert(0, str(SPEAKER_BACKEND))
    try:
        follow = pytest.importorskip('timetable_follow')
    finally:
        sys.path.remove(str(SPEAKER_BACKEND))
    follower = follow.TimetableFollower(str(tmp_path / 'timetable.local.json'))
    body = {
        'version': 1, 'issued_by': 'floating1', 'mode': 'clock', 'auto_period_sec': period,
        'start_lead_sec': START_LEAD, 'schedule_enabled': True, 'windows': [list(WINDOW)],
        'playlist': ['a.json'], 'stop': {},
    }
    assert follower.update(1, json.dumps(body), 'floating1')
    return follower


def _play(tmp_path, late_cycle2: float, seconds: float = 400.0):
    period = _period()
    timeline = Timeline('tt-s100000', anchor_unix=WINDOW[0] + START_LEAD, period_sec=period, end_unix=WINDOW[1])
    a = _pc(0.0)
    b = _pc(late_cycle2)
    speaker = _speaker(tmp_path, period)
    sounds = []
    for _ in range(int(seconds / 0.1)):
        for clock, runtime, driver, _notes in (a, b):
            clock.advance(0.1)
            runtime.step()
            driver.tick(Choice(timeline=timeline), {'status': runtime.status, 'init_sec': INIT})
        due = speaker.due(a[0].wall())
        if due is not None:
            sounds.append((due[1], due[2]))
    return timeline, a, b, sounds


@pytest.mark.parametrize('late', [0.3, 3.0])
def test_a_pc_whose_initial_move_ends_late_starts_late_without_skipping_and_others_do_not_wait(tmp_path, late):
    timeline, a, b, sounds = _play(tmp_path, late)
    on_time = [(k, timeline.start_of(k)) for k in (1, 2, 3, 4)]
    assert a[1].starts == on_time, 'A 는 B 를 기다리지 않는다'
    assert b[1].starts == [(1, on_time[0][1]), (2, round(on_time[1][1] + late, 3)), on_time[2], on_time[3]], \
        'B 는 2회차를 늦은 만큼 늦게 · 쉬지 않음 · 3회차부터 다시 시간표 시각'
    assert not b[1].skips
    late_lines = [note for note in b[3] if '늦게 시작' in note]
    assert late_lines == [f'시간표 재생 · 2회차 {late:.1f} s 늦게 시작 · 초기 이동이 늦게 끝남 · 생략 아님 · 다음 회차는 다시 시간표 시각']
    assert not any('회차 생략' in note for note in b[3]), b[3]
    assert sounds[:4] == on_time, '스피커는 늘 시간표 시각에 음원 · 헤드 늦음과 상관없음'


def test_an_extremely_late_initial_move_skips_only_that_cycle_with_the_reason(tmp_path):
    timeline, a, b, sounds = _play(tmp_path, 20.0)
    on_time = [(k, timeline.start_of(k)) for k in (1, 2, 3, 4)]
    assert a[1].starts == on_time
    assert [cycle for cycle, _ in b[1].starts] == [1, 3, 4], 'B 는 2회차만 쉼'
    assert b[1].starts[1:] == on_time[2:], '쉰 뒤 다음 회차는 시간표 시각'
    skipped = [note for note in b[3] if '회차 생략' in note]
    assert skipped == ['시간표 재생 · 2회차 생략: 초기 이동이 20.0초 지연 종료, 재생 시 3회차 준비 시각 초과'], b[3]
    assert b[1].calls.count('group_prepare') == 1 and 'group_join' not in b[1].calls, '실행은 놓지 않고 이어서'
    assert sounds[:4] == on_time


def test_a_restarted_coordination_node_takes_over_a_cycle_the_runtime_is_still_moving_into(tmp_path):
    """연동 노드가 초기 이동 중에 다시 떴다 · 재생 관리자는 회차 명령을 쥐고 스스로 시작한다 · 이어받아 회차를 잇는다

    고치기 전에는 초기 이동 · 시작 대기 단계는 「준비 단계」 라 놓고(`group_cancel`) 그 PC 만 다음 경계까지 쉬었다.
    """
    period = _period()
    timeline = Timeline('tt-s100000', anchor_unix=WINDOW[0] + START_LEAD, period_sec=period, end_unix=WINDOW[1])
    clock, runtime, driver, notes = _pc(0.0)
    view = lambda: {'status': runtime.status, 'init_sec': INIT}   # noqa: E731
    for _ in range(int(150.0 / 0.1)):                              # 2회차(100160) 초기 이동 중 · 100149 부터
        clock.advance(0.1)
        runtime.step()
        driver.tick(Choice(timeline=timeline), view())
    assert runtime.status['phase'] == 'initializing' and runtime.status.get('timed_cycle') == 2
    calls = len(runtime.calls)
    fresh = ClockDriver(runtime.control, info=notes.append, warn=notes.append, wall=clock.wall, mono=clock.mono)
    for _ in range(int(250.0 / 0.1)):
        clock.advance(0.1)
        runtime.step()
        fresh.tick(Choice(timeline=timeline), view())
    assert 'group_cancel' not in runtime.calls[calls:], runtime.calls[calls:]
    assert runtime.starts == [(k, timeline.start_of(k)) for k in (1, 2, 3, 4)]
