"""반복은 늘 초기 위치를 거친다 · 서버도 · 수정 목록 112 라 (사용자 결정 2026-10-13)

「바로 다음 회차」(direct) · 「대기 후 다음 회차」(dwell) 은 끝값에서 시작값으로 바로 잇는다 ·
새 화면에서 뺐고(2026-10-12), 이제 서버도 새로 들어오면 거절하고 저장된 값은 초기 위치 방식으로 읽는다.
"""

from motion_common import repeat_policy as rp


def test_saved_old_modes_are_read_as_the_reinitialize_modes():
    assert rp.normalize_repeat_mode('direct') == rp.REINITIALIZE
    assert rp.normalize_repeat_mode('dwell') == rp.DWELL_REINITIALIZE
    assert rp.normalize_repeat_mode('reinitialize') == rp.REINITIALIZE
    assert rp.normalize_repeat_mode('dwell_reinitialize') == rp.DWELL_REINITIALIZE
    assert rp.normalize_repeat_mode('') == rp.REINITIALIZE
    assert rp.normalize_repeat_mode('immediate') == rp.REINITIALIZE


def test_new_requests_with_old_or_unknown_modes_are_refused_before_accepting():
    assert rp.request_repeat_mode_error('direct') == rp.UNSAFE_MODE_MESSAGE
    assert rp.request_repeat_mode_error('DWELL') == rp.UNSAFE_MODE_MESSAGE
    assert '지원하지 않는 반복 방식' in rp.request_repeat_mode_error('immediate')   # 112 라 · H-53


def test_allowed_or_empty_requests_pass():
    for value in ('', None, 'reinitialize', 'dwell_reinitialize'):
        assert rp.request_repeat_mode_error(value) == ''
