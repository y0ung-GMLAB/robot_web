"""회차 단위 실패 표지 · 수정 목록 67"""


from motion_common import cycle_failure


def test_tag_round_trip():
    text = cycle_failure.tagged('모션 최종 위치 도달 확인 실패: 2번 모터')
    assert cycle_failure.is_cycle_failure(f'그룹 모션 실행 실패: {text}')
    assert not cycle_failure.is_cycle_failure('통신이 끊긴 모터가 있어 재생을 멈춥니다')
    assert not cycle_failure.is_cycle_failure(None)


def test_all_three_reach_checks_are_tagged_in_the_player():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / 'motion_runtime/motion_runtime/motion_player.py').read_text(encoding='utf-8')
    for what in ('초기 위치 도달 확인 실패', '첫 프레임 도달 확인 실패', '모션 최종 위치 도달 확인 실패'):
        assert f"cycle_failure.tagged(f'{what}:" in source, what
