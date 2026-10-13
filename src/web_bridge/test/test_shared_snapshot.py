"""`/ws/status` 한 장을 탭 여럿이 나눠 쓴다 · 수정 목록 130"""

from motion_web_bridge.shared_snapshot import SharedSnapshot


def test_tabs_within_half_a_period_share_one_snapshot():
    now = [100.0]
    built = []

    def build():
        built.append(now[0])
        return f'snap-{len(built)}'

    snapshot = SharedSnapshot(build, max_age_sec=lambda: 0.05, clock=lambda: now[0])

    assert snapshot.text() == 'snap-1'
    now[0] += 0.01
    assert snapshot.text() == 'snap-1', '두 번째 탭은 같은 한 장'
    now[0] += 0.05
    assert snapshot.text() == 'snap-2', '반 박자가 지나면 새로'
    assert len(built) == 2


def test_one_tab_at_the_full_period_still_gets_a_fresh_snapshot_every_time():
    now = [0.0]
    built = []
    snapshot = SharedSnapshot(
        lambda: built.append(now[0]) or f'snap-{len(built)}',
        max_age_sec=lambda: 0.05, clock=lambda: now[0],
    )
    texts = []
    for _ in range(5):
        texts.append(snapshot.text())
        now[0] += 0.1   # 10 Hz
    assert texts == ['snap-1', 'snap-2', 'snap-3', 'snap-4', 'snap-5']
