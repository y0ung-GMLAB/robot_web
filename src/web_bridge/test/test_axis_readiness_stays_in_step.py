"""축별 판정이 서버와 화면에서 갈리지 않는다 · §6-177

**같은 판정이 두 곳에 있다 · 없앨 수가 없다.**

    서버   `motor_readiness.readiness_error` · 명령을 받고 「실행해도 되나」
    화면   `motion_test.js` · 그리면서 「이 버튼을 켜도 되나」

화면 것을 없애고 서버 답을 받아쓰려 했지만 못 한다 · 사유를 계산하려면
**모터 종류**를 판단해야 하는데, 그 판단은 일부러 호출부마다 다르게 두었다.

    모터 종류 판정과 내부리밋 판정은 호출부가 한다 · 노드마다 판정 근거가
    다르고 (`_is_ac_servo` · `motor_config_rules.is_ac_servo_motor` ·
    매핑의 `motor_type`), 그것까지 여기로 끌어오면 이 모듈이 모터 모델을
    알아야 한다.                              — motor_readiness.py

브리지가 제 나름의 판단을 하나 더 만들면 **주인이 셋**이 된다 · 그게 더 나쁘다.

그래서 **없애는 대신 갈리지 않게 지킨다** · 둘은 같은 것을 같은 순서로 본다 ·
한쪽만 고치면 여기서 걸린다.

2026-09-18 에 문구는 한글로 통일했다 · 전에는 서버가 영어로 답해서, 조그를
거절당한 사람이 화면에서 `Axis 0 is not detected` 를 봤다.
"""

import re
from pathlib import Path

from motion_common import motor_readiness

WORKSPACE = Path(__file__).resolve().parents[3]


def _function(source: str, name: str) -> str:
    start = source.index(f'function {name}(')
    return source[start:source.index('\n}', start)]


def test_the_server_really_skips_servo_on_for_dynamixel():
    """화면만 보고 믿지 않는다 · 서버가 정말 건너뛰는지 돌려 본다."""
    motor = {'controller_index': 1, 'state': 'detected', 'fault': False}

    assert motor_readiness.readiness_error(
        motor, order=motor_readiness.MANUAL_ORDER, is_ac_servo=False,
    ) == ''
    assert '서보' in motor_readiness.readiness_error(
        motor, order=motor_readiness.MANUAL_ORDER, is_ac_servo=True,
    )


def test_both_sides_speak_korean():
    """서버가 영어로 답하면 사용자가 화면에서 영어를 본다 · 실제로 그랬다."""
    motor = {'controller_index': 0, 'state': 'missing'}
    server = motor_readiness.readiness_error(motor, order=motor_readiness.MANUAL_ORDER)

    assert '감지되지 않았습니다' in server
    assert not re.search(r'[A-Za-z]{4,}', server), (
        f'서버 문구에 영어가 남아 있습니다: {server!r}'
    )


