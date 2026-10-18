"""조인트 최대 속도·가속도 검사 · 재생 계획과 녹화 저장이 같은 잣대 · 수정 목록 5-2 · 156

재생 계획(`plan_builder`)이 쓰던 것을 옮겼다 · X-Touch 녹화(브리지)가 저장 전에 같은 검사를
해서 「저장은 됐는데 재생 거절」 이 없게 한다.

    axes     [{motion_id, row}]  · row = 조인트 매핑 줄(상한 칸)
    samples  [{time_sec, motion_values: {motion_id: 조인트 rad}}]
"""

from __future__ import annotations

from . import joint_mapping, units

_deg = units.rad_to_deg


def rate_limit_error(axes, samples, period_sec: float) -> str:
    """조인트 최대 속도·가속도를 넘는 애니메이션이면 거부 사유 · 수정 목록 5-2 (2026-10-06)

    전에는 어느 계층도 속도·가속도를 보지 않았다 · 너무 빠른 애니메이션은 모터가
    못 따라가 「도달 실패」 로 끝나거나 기구에 무리가 갔다. 조인트 매핑에 축별
    상한을 적으면(비우면 검사 안 함) 재생 계획(20 ms 재샘플 · 매핑 범위로 자른 값)
    의 차분으로 잰다 · 재생과 같은 값을 보므로 「검사는 통과했는데 실제로는 넘는다」 가 없다.
    """
    if len(samples) < 2 or period_sec <= 0:
        return ''
    problems = []
    for axis in axes:
        row = axis.get('row') or {}
        # 상한·재는 값 모두 rad · 글에만 deg · 수정 목록 6
        max_velocity = joint_mapping.rate(row, 'max_velocity', units.RAD)
        max_acceleration = joint_mapping.rate(row, 'max_acceleration', units.RAD)
        if not max_velocity and not max_acceleration:
            continue
        motion_id = str(axis['motion_id'])
        values = [float(sample['motion_values'][motion_id]) for sample in samples]
        times = [float(sample['time_sec']) for sample in samples]
        velocities = []
        for index in range(1, len(values)):
            dt = times[index] - times[index - 1]
            if dt <= 1e-9:
                continue
            velocities.append(((values[index] - values[index - 1]) / dt, times[index]))
        if max_velocity:
            worst = max(velocities, key=lambda item: abs(item[0]), default=None)
            if worst and abs(worst[0]) > max_velocity * (1 + 1e-6):
                problems.append(
                    f'{motion_id} 속도 {_deg(abs(worst[0])):.1f} deg/s > 상한 {round(_deg(max_velocity), 6):g} ({worst[1]:.2f} s)'
                )
        if max_acceleration and len(velocities) > 1:
            accelerations = [
                ((velocities[i][0] - velocities[i - 1][0]) / max(velocities[i][1] - velocities[i - 1][1], 1e-9),
                 velocities[i][1])
                for i in range(1, len(velocities))
            ]
            worst = max(accelerations, key=lambda item: abs(item[0]), default=None)
            if worst and abs(worst[0]) > max_acceleration * (1 + 1e-6):
                problems.append(
                    f'{motion_id} 가속도 {_deg(abs(worst[0])):.0f} deg/s² > 상한 {round(_deg(max_acceleration), 6):g} ({worst[1]:.2f} s)'
                )
    if not problems:
        return ''
    return '애니메이션이 조인트 매핑의 속도·가속도 상한을 넘습니다 · ' + ' · '.join(problems[:4])
